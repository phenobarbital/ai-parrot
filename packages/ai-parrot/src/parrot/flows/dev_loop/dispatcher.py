"""ClaudeCodeDispatcher — orchestration glue between AgentsFlow and Claude Code.

The dispatcher is the heart of FEAT-129. It is intentionally a *thin*
class: it owns the global concurrency cap, the Redis stream plumbing,
and the profile → run-options resolver, but delegates all SDK work to
:class:`parrot.clients.claude_agent.ClaudeAgentClient` (FEAT-124) via
:class:`parrot.clients.factory.LLMFactory`.

Responsibilities (per spec §3 Module 2):

1. Resolve a :class:`ClaudeCodeDispatchProfile` into a populated
   :class:`ClaudeAgentRunOptions`, including programmatic ``agents=`` and
   the ``extra_args={"output-format":"json","json-schema":<path>}``
   structured-output flags.
2. Acquire a global :class:`asyncio.Semaphore` sized by
   ``CLAUDE_CODE_MAX_CONCURRENT_DISPATCHES``.
3. Iterate ``client.ask_stream(...)``, wrap each event in a
   :class:`DispatchEvent`, and ``XADD`` to
   ``flow:{run_id}:dispatch:{node_id}`` with an ``MAXLEN`` derived from
   ``stream_ttl_seconds``.
4. On final ``ResultMessage``, parse the concatenated assistant text as
   JSON and validate against ``output_model``. Raises
   :class:`DispatchOutputValidationError` on failure (carrying the raw
   payload for the audit log).
5. Defense-in-depth: refuse dispatch when ``cwd`` is not under
   ``WORKTREE_BASE_PATH`` (spec §7 R4).
"""

from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import os
import shlex
import shutil
import tempfile
import time
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Protocol,
    Sequence,
    TYPE_CHECKING,
    Type,
    TypeVar,
)

from pydantic import BaseModel, ValidationError

from parrot import conf
from parrot.clients.claude_agent import ClaudeAgentRunOptions
from parrot.clients.factory import LLMFactory
from parrot.flows.dev_loop._subagent_defs import load_subagent_definition
from parrot.flows.dev_loop.models import (
    ClaudeCodeDispatchProfile,
    CodexCodeDispatchProfile,
    GeminiCodeDispatchProfile,
    DispatchEvent,
    LLMCodeDispatchProfile,
    GrokCodeDispatchProfile,
    MoonshotCodeDispatchProfile,
    ZaiCodeDispatchProfile,
)
from parrot.flows.dev_loop.session_state import SessionHost, action_from_dispatch_event
from parrot.clients.moonshot import _thinking_ctx as _moonshot_thinking_ctx
from parrot.models.moonshot import ALWAYS_THINKING_MODELS, K_SERIES_MODELS
from parrot.models.zai import THINKING_CAPABLE_ZAI_MODELS

if TYPE_CHECKING:  # pragma: no cover - typing only
    from claude_agent_sdk.types import AgentDefinition  # noqa: F401

T = TypeVar("T", bound=BaseModel)

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Dual-publish shim (FEAT-322 TASK-1852) — fold DispatchEvents into the run's
# SessionHost alongside the legacy XADD, with zero call-site fan-out.
#
# ``dispatch()`` gains an explicit ``session_host: Optional[SessionHost] =
# None`` kwarg (the per-dispatch value the spec requires — never dispatcher-
# instance state, since one dispatcher instance is shared across concurrent
# runs). Internally, threading that value positionally through every one of
# the ~40 ``self._publish_event(...)``/``_publish_*_event(...)`` call sites
# spread across 4 dispatcher classes' streaming helpers would be a large,
# error-prone rewrite of this hot, actively-churning file (FEAT-270/Moonshot
# work landed here in the last weeks — see spec §7 "Known Risks"). Instead,
# ``dispatch()`` binds the value into a ``ContextVar`` for the duration of
# its own call; ``_publish_event`` (the ONE choke point every dispatch kind
# already funnels through) reads it back. ``ContextVar`` values are copied
# per ``asyncio.Task`` at task-creation time, so concurrent dispatches on the
# SAME shared dispatcher instance (separate Tasks) never observe each
# other's host — the identical safety property explicit per-call-site
# threading would have given, with a 3-line touch per dispatch() method
# instead of a rewrite of every internal helper.
# ---------------------------------------------------------------------------

_SESSION_HOST_CTX: "contextvars.ContextVar[Optional[SessionHost]]" = contextvars.ContextVar(
    "dev_loop_session_host", default=None
)


def _apply_to_session_host(event: DispatchEvent) -> None:
    """Fold one dispatch event into the current dispatch's SessionHost, if any.

    Reads the per-dispatch host from :data:`_SESSION_HOST_CTX` (bound by the
    active ``dispatch()`` call). No-op when no host is bound (legacy
    callers). Every failure is swallowed and logged at DEBUG — the shim must
    never affect the legacy publish path or the dispatch itself.
    """
    host = _SESSION_HOST_CTX.get()
    if host is None:
        return
    try:
        action = action_from_dispatch_event(
            event.kind, event.node_id, event.ts, event.payload
        )
        if action is not None:
            host.apply(action)
    except Exception:  # noqa: BLE001 - shim must never break a dispatch
        _logger.debug(
            "dev-loop session-state shim failed for dispatch event %s (node=%s)",
            event.kind, event.node_id, exc_info=True,
        )

# Edit/Write tools that let a dispatched session mutate the filesystem through
# the SDK's own tool surface. A dispatch whose profile excludes ALL of these
# AND runs in ``permission_mode="plan"`` cannot make changes, so the
# WORKTREE_BASE_PATH confinement (which exists to stop a write-capable agent
# escaping the worktree) does not apply to it. ``Bash`` is intentionally NOT
# here: plan mode gates command execution to read-only behaviour, and the
# read-only QA/code-review gates legitimately need a shell.
_WRITE_CAPABLE_TOOLS = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit"})


def _claude_profile_is_read_only(profile: ClaudeCodeDispatchProfile) -> bool:
    """True when a Claude Code profile cannot mutate the filesystem.

    Read-only means ``permission_mode="plan"`` (plan mode forbids edits) AND no
    Edit/Write tool in ``allowed_tools``. Such a dispatch (e.g. the additive
    ``sdd-codereview`` gate) is safe to run against a path outside
    ``WORKTREE_BASE_PATH`` — an already-checked-out repo or the demo's own
    checkout — because the confinement only matters for write-capable sessions.
    """
    if profile.permission_mode != "plan":
        return False
    return not (set(profile.allowed_tools) & _WRITE_CAPABLE_TOOLS)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class DispatchExecutionError(Exception):
    """Raised when the Claude Code session fails before producing a result.

    Wraps any exception raised by ``ClaudeAgentClient.ask_stream`` plus
    misconfiguration errors caught before SDK invocation (e.g.
    ``cwd`` outside ``WORKTREE_BASE_PATH``).
    """


class DispatchOutputValidationError(Exception):
    """Raised when the final ResultMessage payload fails to validate.

    Attributes:
        raw_payload: The concatenated assistant text that failed
            ``output_model.model_validate_json``. Surfaced so the
            audit log / failure handler can capture it verbatim.
    """

    def __init__(self, message: str, *, raw_payload: str = "") -> None:
        super().__init__(message)
        self.raw_payload = raw_payload


class DevLoopCodeDispatcher(Protocol):
    """Shared dispatch contract consumed by dev-loop code-agent nodes."""

    async def dispatch(
        self,
        *,
        brief: BaseModel,
        profile: BaseModel,
        output_model: Type[T],
        run_id: str,
        node_id: str,
        cwd: str,
        session_host: Optional[SessionHost] = None,
    ) -> T:
        """Dispatch a code-agent run and return validated structured output."""


# ---------------------------------------------------------------------------
# ClaudeCodeDispatcher
# ---------------------------------------------------------------------------


class ClaudeCodeDispatcher:
    """Thin orchestration class over :class:`ClaudeAgentClient`.

    A single dispatcher instance is meant to be shared by every node in a
    flow: it owns the global concurrency cap and the Redis connection.
    """

    def __init__(
        self,
        *,
        max_concurrent: int,
        redis_url: str,
        stream_ttl_seconds: int,
    ) -> None:
        """Initialise the dispatcher.

        Args:
            max_concurrent: Cap on simultaneous in-flight dispatches.
                Sourced from
                ``conf.CLAUDE_CODE_MAX_CONCURRENT_DISPATCHES`` by the
                caller.
            redis_url: Redis URL used for stream publication
                (``redis.asyncio.from_url``).
            stream_ttl_seconds: Stream retention. Approximated as
                ``MAXLEN ~ floor(ttl_seconds / 60)`` so a 7-day TTL caps
                each stream around 10 080 entries.
        """
        if max_concurrent < 1:
            raise ValueError("max_concurrent must be >= 1")
        self.logger = logging.getLogger(__name__)
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._redis_url = redis_url
        self.stream_ttl_seconds = stream_ttl_seconds
        self._redis: Any = None  # lazy aioredis.Redis

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def dispatch(
        self,
        *,
        brief: BaseModel,
        profile: ClaudeCodeDispatchProfile,
        output_model: Type[T],
        run_id: str,
        node_id: str,
        cwd: str,
        session_host: Optional[SessionHost] = None,
    ) -> T:
        """Dispatch a single Claude Code session and return its parsed output.

        Args:
            brief: A Pydantic model instance carrying the per-node input
                (e.g. ``BugBrief``, ``ResearchOutput``, ``QABrief``).
                Serialized to JSON in the prompt body.
            profile: Declarative dispatch profile (subagent, allowed
                tools, permission mode, etc.).
            output_model: Pydantic model the final ResultMessage payload
                must validate against. Returned as a typed instance.
            run_id: The flow run id, used for the Redis stream key.
            node_id: The flow node id, used for the Redis stream key.
            cwd: Working directory for the Claude Code session. MUST be
                under ``conf.WORKTREE_BASE_PATH`` (defense in depth).

        Returns:
            An instance of ``output_model`` validated from the assistant's
            final JSON payload.

        Raises:
            DispatchExecutionError: SDK failure or cwd safety violation.
            DispatchOutputValidationError: Final payload did not validate.
        """
        stream_key = f"flow:{run_id}:dispatch:{node_id}"
        json_schema_path: Optional[str] = None
        # FEAT-322 TASK-1852: bind the per-dispatch host for _publish_event
        # to read (see module-level _SESSION_HOST_CTX docstring). The main
        # finally: below resets it on every path THAT reaches the semaphore
        # block; this try/except covers the narrow pre-semaphore window
        # (cwd validation, the "queued" publish) so an early raise there
        # still resets the var instead of leaking it forward.
        _host_token = _SESSION_HOST_CTX.set(session_host)
        try:
            # Spec §7 R4 — defense in depth. Waived for read-only (plan-mode,
            # no-edit) dispatches such as the sdd-codereview gate, which may
            # run against a checkout outside the worktree base.
            self._enforce_cwd_under_worktree_base(cwd, profile)

            await self._publish_event(
                stream_key,
                kind="dispatch.queued",
                run_id=run_id,
                node_id=node_id,
                payload={"profile": profile.model_dump(mode="json")},
            )
        except Exception:
            _SESSION_HOST_CTX.reset(_host_token)
            raise

        async with self._semaphore:
            try:
                # ``json_schema_path`` is intentionally not generated:
                # the SDK's subprocess transport pins
                # ``--output-format stream-json`` / ``--input-format
                # stream-json`` itself, so passing
                # ``extra_args={"output-format": "json", ...}`` causes a
                # CLI-level conflict. Output validation falls back to
                # best-effort JSON parsing of the final assistant text
                # (spec §7 R2).
                run_options = self._resolve_run_options(profile, cwd, json_schema_path=None)

                client = LLMFactory.create(f"claude-agent:{profile.model}")

                await self._publish_event(
                    stream_key,
                    kind="dispatch.started",
                    run_id=run_id,
                    node_id=node_id,
                    payload={"cwd": cwd, "subagent": profile.subagent},
                )

                prompt = self._build_prompt(brief, output_model)
                messages: List[Any] = []
                try:
                    # Wall-clock cap for the whole stream — spec §2 Data
                    # Models declares ``ClaudeCodeDispatchProfile.timeout_seconds``
                    # (default 1800, ge=60, le=7200). asyncio.timeout (Py 3.11+)
                    # raises TimeoutError on expiry, which we surface as
                    # ``dispatch.failed`` and re-raise as DispatchExecutionError.
                    async with asyncio.timeout(profile.timeout_seconds):
                        async for msg in client.stream_messages(prompt, run_options=run_options):
                            messages.append(msg)
                            await self._publish_message_event(stream_key, msg, run_id, node_id)
                except TimeoutError as exc:
                    await self._publish_event(
                        stream_key,
                        kind="dispatch.failed",
                        run_id=run_id,
                        node_id=node_id,
                        payload={
                            "error_class": "TimeoutError",
                            "error_message": (f"dispatch exceeded " f"{profile.timeout_seconds}s wall-clock cap"),
                        },
                    )
                    self.logger.warning(
                        "Dispatch timeout for run=%s node=%s after %ss",
                        run_id,
                        node_id,
                        profile.timeout_seconds,
                    )
                    raise DispatchExecutionError(
                        f"Dispatch exceeded {profile.timeout_seconds}s " f"wall-clock cap"
                    ) from exc
                except Exception as exc:  # session failure
                    # The SDK collapses an erroring ``ResultMessage`` into an
                    # opaque ``ProcessError`` ("Claude Code returned an error
                    # result: success") because the CLI exits non-zero after
                    # emitting the result. The actionable detail —
                    # ``api_error_status`` (e.g. 401/429/529) and the human
                    # ``result`` text ("Invalid API key · Fix external API
                    # key") — lives on the ResultMessage we already buffered.
                    # Recover it so the failure is diagnosable instead of
                    # mysterious.
                    err_detail = self._extract_result_error(messages)
                    failure_payload: Dict[str, Any] = {
                        "error_class": type(exc).__name__,
                        "error_message": str(exc),
                    }
                    if err_detail:
                        failure_payload.update(err_detail)
                    await self._publish_event(
                        stream_key,
                        kind="dispatch.failed",
                        run_id=run_id,
                        node_id=node_id,
                        payload=failure_payload,
                    )
                    self.logger.error(
                        "Dispatch session failure for run=%s node=%s: %s",
                        run_id,
                        node_id,
                        self._format_result_error(err_detail) or str(exc),
                    )
                    raise DispatchExecutionError(self._compose_session_error(exc, err_detail)) from exc

                # Even when the SDK does NOT raise (some CLI versions emit
                # the erroring result and close the stream cleanly), an
                # ``is_error`` ResultMessage must fail the dispatch — never
                # fall through to JSON validation on a half-finished turn.
                err_detail = self._extract_result_error(messages)
                if err_detail:
                    await self._publish_event(
                        stream_key,
                        kind="dispatch.failed",
                        run_id=run_id,
                        node_id=node_id,
                        payload={
                            "error_class": "ResultError",
                            "error_message": self._format_result_error(err_detail),
                            **err_detail,
                        },
                    )
                    self.logger.error(
                        "Dispatch returned an error result for run=%s " "node=%s: %s",
                        run_id,
                        node_id,
                        self._format_result_error(err_detail),
                    )
                    raise DispatchExecutionError(self._format_result_error(err_detail))

                try:
                    result = self._validate_output(messages, output_model)
                except DispatchOutputValidationError as exc:
                    await self._publish_event(
                        stream_key,
                        kind="dispatch.output_invalid",
                        run_id=run_id,
                        node_id=node_id,
                        payload={
                            "raw_payload": exc.raw_payload[:8000],
                            "error_message": str(exc),
                        },
                    )
                    raise

                await self._publish_event(
                    stream_key,
                    kind="dispatch.completed",
                    run_id=run_id,
                    node_id=node_id,
                    payload={"output_model": output_model.__name__},
                )
                return result
            finally:
                _SESSION_HOST_CTX.reset(_host_token)
                if json_schema_path is not None:
                    try:
                        os.unlink(json_schema_path)
                    except OSError:  # pragma: no cover - best effort
                        pass

    # ------------------------------------------------------------------
    # Internal helpers (underscored — but accessible to unit tests)
    # ------------------------------------------------------------------

    def _enforce_cwd_under_worktree_base(
        self,
        cwd: str,
        profile: Optional[ClaudeCodeDispatchProfile] = None,
    ) -> None:
        """Spec §7 R4: refuse dispatch when ``cwd`` is not in worktree base.

        The confinement protects against a *write-capable* session escaping its
        worktree. A read-only dispatch (plan mode, no Edit/Write tools) cannot
        write anywhere, so when *profile* is read-only the check is waived —
        this lets the additive ``sdd-codereview`` gate review a checkout that
        legitimately lives outside ``WORKTREE_BASE_PATH``.

        Raises:
            DispatchExecutionError: when the path check fails.
        """
        if profile is not None and _claude_profile_is_read_only(profile):
            return
        base = os.path.abspath(conf.WORKTREE_BASE_PATH)
        target = os.path.abspath(cwd)
        try:
            common = os.path.commonpath([base, target])
        except ValueError:
            common = ""
        if common != base:
            raise DispatchExecutionError(f"cwd {cwd!r} is not under WORKTREE_BASE_PATH={base!r}")

    def _resolve_run_options(
        self,
        profile: ClaudeCodeDispatchProfile,
        cwd: str,
        *,
        json_schema_path: Optional[str] = None,
    ) -> ClaudeAgentRunOptions:
        """Translate a dispatch profile into a run-options instance.

        See spec §3 Module 2 and the unit tests in
        ``test_dispatch_profile_to_run_options`` /
        ``test_dispatch_profile_generic_session_fallback``.

        Note: ``dispatch()`` calls :meth:`_enforce_cwd_under_worktree_base`
        BEFORE the semaphore acquire (and before publishing
        ``dispatch.queued``) so a misconfigured ``cwd`` fails fast
        without consuming a slot or polluting the audit log. This method
        does NOT re-validate ``cwd`` — callers exercising it in
        isolation are expected to validate the path themselves.
        """
        agents_dict: Optional[Dict[str, Any]] = None
        system_prompt: Optional[str] = None

        if profile.subagent is not None:
            # Lazy SDK import — keeps `import parrot.flows.dev_loop`
            # working without the [claude-agent] extra installed.
            try:
                from claude_agent_sdk.types import AgentDefinition
            except ImportError:  # pragma: no cover - exercised in live env
                AgentDefinition = None  # type: ignore[assignment]

            body = load_subagent_definition(profile.subagent)
            if AgentDefinition is None:
                # Fall back to a plain dict shape; the SDK accepts this
                # at runtime and rejects it loudly if not.
                agents_dict = {
                    profile.subagent: {
                        "description": f"SDD {profile.subagent} subagent",
                        "prompt": body,
                        "tools": list(profile.allowed_tools) or None,
                        "model": profile.model,
                    }
                }
            else:
                agents_dict = {
                    profile.subagent: AgentDefinition(
                        description=f"SDD {profile.subagent} subagent",
                        prompt=body,
                        tools=list(profile.allowed_tools) or None,
                        model=profile.model,
                    )
                }
        else:
            system_prompt = profile.system_prompt_override

        # NOTE: spec §7 R2 floated using
        # ``extra_args={"output-format":"json","json-schema":<path>}`` as
        # a v1 enhancement, but the SDK's subprocess transport always
        # adds ``--output-format stream-json`` / ``--input-format
        # stream-json`` itself; overriding via ``extra_args`` produces
        # ``--input-format=stream-json requires output-format=stream-json``
        # at runtime. We therefore stick with the documented best-effort
        # JSON parsing of the final ``ResultMessage`` payload — see
        # ``_validate_output`` — and leave ``extra_args`` unset.
        extra_args: Optional[Dict[str, Optional[str]]] = None

        return ClaudeAgentRunOptions(
            cwd=cwd,
            permission_mode=profile.permission_mode,
            allowed_tools=list(profile.allowed_tools) or None,
            agents=agents_dict,
            setting_sources=list(profile.setting_sources) if profile.setting_sources else None,
            strict_mcp_config=profile.strict_mcp_config,
            env=self._resolve_dispatch_env() or None,
            extra_args=extra_args,
            system_prompt=system_prompt,
            model=profile.model,
        )

    def _resolve_dispatch_env(self) -> Dict[str, str]:
        """Compute env overrides that steer the subprocess auth method.

        Claude Code prefers ``ANTHROPIC_API_KEY`` over the interactive
        claude.ai subscription whenever the key is present in the
        environment, silently switching billing to API credits (and
        failing outright when that account is keyless / out of credit:
        ``401 Invalid API key`` or ``400 Credit balance is too low``).

        Policy is set by ``conf.CLAUDE_CODE_DISPATCH_AUTH``:

        * ``"prefer-subscription"`` (default) — blank ``ANTHROPIC_API_KEY``
          for the subprocess when a subscription login is detected so the
          CLI uses it; otherwise inherit the key (API-key fallback).
        * ``"subscription"`` — always blank the key (force subscription).
        * ``"api-key"`` — inherit the key unchanged (API billing).

        Returns a dict suitable for ``ClaudeAgentRunOptions.env``; empty
        means "inherit the parent environment unchanged".
        """
        mode = (getattr(conf, "CLAUDE_CODE_DISPATCH_AUTH", "") or "").strip()
        if mode == "api-key":
            chosen = "api-key (inherited ANTHROPIC_API_KEY)"
            env: Dict[str, str] = {}
        elif mode == "subscription":
            chosen = "subscription (forced)"
            env = {"ANTHROPIC_API_KEY": ""}
        else:  # prefer-subscription (default / unknown values)
            if self._subscription_available():
                chosen = "subscription (detected claude.ai login)"
                # Blank the key only for the subprocess; the parent process
                # keeps it for the AnthropicClient summarizer / plan LLM.
                env = {"ANTHROPIC_API_KEY": ""}
            else:
                chosen = "api-key (no subscription login detected)"
                env = {}
        self.logger.debug("Dispatch auth resolved: %s", chosen)
        return env

    @staticmethod
    def _subscription_available() -> bool:
        """Return True when a claude.ai subscription login is on disk.

        Reads ``$CLAUDE_CONFIG_DIR/.credentials.json`` (default
        ``~/.claude``) and looks for a ``claudeAiOauth.accessToken``. The
        presence of a refresh token means the CLI renews an expired access
        token itself, so expiry is intentionally NOT checked here. Any
        error (missing file, unreadable, macOS keychain storage) returns
        False so the policy degrades to the API-key path rather than
        blanking a key that is the only working credential.
        """
        config_dir = os.environ.get("CLAUDE_CONFIG_DIR", os.path.expanduser("~/.claude"))
        cred_path = os.path.join(config_dir, ".credentials.json")
        try:
            with open(cred_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return False
        oauth = data.get("claudeAiOauth") if isinstance(data, dict) else None
        return bool(isinstance(oauth, dict) and oauth.get("accessToken"))

    def _materialize_json_schema(self, output_model: Type[BaseModel]) -> str:
        """Write ``output_model.model_json_schema()`` to a tempfile.

        The path is passed to the CLI via ``extra_args={"json-schema": ...}``
        when the SDK supports it. The dispatcher unlinks the file in a
        ``finally:`` block.
        """
        schema = output_model.model_json_schema()
        fd, path = tempfile.mkstemp(prefix="dev_loop_schema_", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(schema, fh)
        except Exception:
            os.close(fd)
            try:
                os.unlink(path)
            except OSError:
                pass
            raise
        return path

    def _build_prompt(self, brief: BaseModel, output_model: Type[BaseModel]) -> str:
        """Compose the prompt body for a dispatch.

        Embeds:

        * The JSON-encoded brief.
        * A compact field-list extracted from
          ``output_model.model_json_schema()`` so the subagent sees
          the canonical field names + types + descriptions (subagents
          drift on field names when given only a class name —
          ``jira_key`` instead of ``jira_issue_key`` was the trigger).
        * A required-field allowlist so the subagent knows what cannot
          be omitted.
        * A no-prose / no-markdown-fence instruction so
          :func:`_validate_output`'s best-effort JSON extractor finds
          a clean object.
        """
        brief_json = brief.model_dump_json()
        schema = output_model.model_json_schema()
        properties = schema.get("properties", {}) or {}
        required = schema.get("required", []) or []
        field_lines: List[str] = []
        for fname, fmeta in properties.items():
            ftype = fmeta.get("type") or fmeta.get("$ref", "").rsplit("/", 1)[-1] or "any"
            fdesc = (fmeta.get("description") or "").strip()
            mandatory = " (required)" if fname in required else ""
            line = f"  - {fname}: {ftype}{mandatory}"
            if fdesc:
                line += f" — {fdesc}"
            field_lines.append(line)
        fields_block = "\n".join(field_lines) or "  (no fields)"
        required_block = ", ".join(required) if required else "(none)"

        return (
            f"Input brief:\n{brief_json}\n\n"
            f"Respond with a single JSON object that matches the "
            f"`{output_model.__name__}` schema. Use these EXACT field "
            f"names — do not invent shorter aliases:\n"
            f"{fields_block}\n\n"
            f"Required fields (must be present and non-empty): "
            f"{required_block}.\n\n"
            f"Output rules:\n"
            f"  1. Emit ONE JSON object — no surrounding prose.\n"
            f"  2. No markdown fences around the JSON.\n"
            f"  3. All required fields above must appear under their "
            f"exact names."
        )

    def _validate_output(self, messages: List[Any], output_model: Type[T]) -> T:
        """Best-effort JSON parse + Pydantic validate against ``output_model``.

        Concatenates the text of every ``AssistantMessage``'s
        ``TextBlock``s in stream order, locates the last balanced
        JSON object, and validates it. Raises
        :class:`DispatchOutputValidationError` (with raw payload) on
        any failure.
        """
        concatenated = self._concatenate_assistant_text(messages)
        if not concatenated.strip():
            raise DispatchOutputValidationError(
                "No assistant text found in dispatch result.",
                raw_payload="",
            )
        json_text = self._extract_last_json_object(concatenated)
        if json_text is None:
            raise DispatchOutputValidationError(
                "Could not locate a JSON object in the assistant output.",
                raw_payload=concatenated,
            )
        try:
            return output_model.model_validate_json(json_text)
        except ValidationError as exc:
            raise DispatchOutputValidationError(
                f"Output failed {output_model.__name__} validation: {exc}",
                raw_payload=json_text,
            ) from exc

    @staticmethod
    def _extract_result_error(messages: List[Any]) -> Optional[Dict[str, Any]]:
        """Return error details from an ``is_error`` ResultMessage, if any.

        The Claude Agent SDK's terminal ``ResultMessage`` carries the only
        actionable diagnosis when a dispatch fails:

        * ``is_error`` — True when the CLI's underlying API call failed.
        * ``api_error_status`` — the HTTP status of that call (e.g. 401
          auth, 429 rate-limit, 529 overloaded). Set by the CLI when
          ``is_error`` is True while ``subtype`` stays ``"success"``.
        * ``result`` — the human-readable CLI message (e.g.
          ``"Invalid API key · Fix external API key"``).
        * ``permission_denials`` — tools the run was refused.

        Duck-typed (no eager SDK import) on the ``is_error`` attribute —
        only the terminal ``ResultMessage`` carries it, so this also
        identifies the result without importing the SDK class. Scans in
        reverse so the terminal result wins. Returns ``None`` when no
        erroring result is present.
        """
        for msg in reversed(messages):
            if not hasattr(msg, "is_error"):
                continue
            if not getattr(msg, "is_error", False):
                return None
            detail: Dict[str, Any] = {
                "api_error_status": getattr(msg, "api_error_status", None),
                "subtype": getattr(msg, "subtype", None),
                "result_text": getattr(msg, "result", None),
                "num_turns": getattr(msg, "num_turns", None),
            }
            denials = getattr(msg, "permission_denials", None)
            if denials:
                detail["permission_denials"] = [str(d) for d in denials]
            return detail
        return None

    @staticmethod
    def _format_result_error(detail: Optional[Dict[str, Any]]) -> str:
        """Render :meth:`_extract_result_error` output as a one-line message."""
        if not detail:
            return ""
        status = detail.get("api_error_status")
        text = (detail.get("result_text") or "").strip()
        parts: List[str] = ["Claude Code dispatch failed"]
        if status is not None:
            parts.append(f"with API error {status}")
        if text:
            parts.append(f"— {text}")
        elif detail.get("subtype"):
            parts.append(f"(subtype={detail['subtype']})")
        msg = " ".join(parts)
        if detail.get("permission_denials"):
            msg += f" [permission_denials={detail['permission_denials']}]"
        return msg

    def _compose_session_error(self, exc: Exception, detail: Optional[Dict[str, Any]]) -> str:
        """Build the DispatchExecutionError message for a session failure.

        Prefers the structured ResultMessage diagnosis when present;
        otherwise falls back to the raw SDK exception text.
        """
        formatted = self._format_result_error(detail)
        if formatted:
            return formatted
        return f"ClaudeAgentClient.ask_stream raised: {exc}"

    @staticmethod
    def _concatenate_assistant_text(messages: List[Any]) -> str:
        """Concatenate ``TextBlock.text`` from every AssistantMessage."""
        chunks: List[str] = []
        for msg in messages:
            # Duck-type — we don't import the SDK eagerly. Production SDK
            # objects expose ``content`` as a list of blocks each with a
            # ``text`` attribute on TextBlock.
            content = getattr(msg, "content", None)
            if not isinstance(content, list):
                continue
            for block in content:
                text = getattr(block, "text", None)
                if isinstance(text, str):
                    chunks.append(text)
        return "".join(chunks)

    @staticmethod
    def _extract_last_json_object(text: str) -> Optional[str]:
        """Return the last balanced ``{...}`` substring of ``text``.

        Uses a brace-balance scanner (NOT regex) so embedded braces in
        strings inside the JSON body do not confuse the parser. Quotes
        and escapes are tracked. Returns ``None`` if no balanced object
        is found.
        """
        last_obj: Optional[str] = None
        depth = 0
        start = -1
        in_string = False
        escape = False
        for idx, ch in enumerate(text):
            if escape:
                escape = False
                continue
            if ch == "\\" and in_string:
                escape = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "{":
                if depth == 0:
                    start = idx
                depth += 1
            elif ch == "}":
                if depth > 0:
                    depth -= 1
                    if depth == 0 and start >= 0:
                        last_obj = text[start : idx + 1]
                        start = -1
        return last_obj

    # ------------------------------------------------------------------
    # Redis publication
    # ------------------------------------------------------------------

    async def _ensure_redis(self) -> Any:
        """Lazily connect to Redis on first publish."""
        if self._redis is not None:
            return self._redis
        # Lazy import — keeps the model layer importable even when the
        # ``redis`` package is missing in some odd environment.
        import redis.asyncio as aioredis

        self._redis = aioredis.from_url(self._redis_url)
        return self._redis

    async def _publish_event(
        self,
        stream_key: str,
        *,
        kind: str,
        run_id: str,
        node_id: str,
        payload: Dict[str, Any],
    ) -> None:
        """Wrap the event in a :class:`DispatchEvent` and ``XADD`` it."""
        event = DispatchEvent(
            kind=kind,  # type: ignore[arg-type]
            ts=time.time(),
            run_id=run_id,
            node_id=node_id,
            payload=payload,
        )
        # FEAT-322 TASK-1852: dual-publish — fold into the run's SessionHost
        # (if any) independent of legacy Redis availability, mirroring
        # flow.py's FlowEventPublisher pattern (two independent failure
        # domains; neither publish path affects the other).
        _apply_to_session_host(event)
        try:
            redis_client = await self._ensure_redis()
        except Exception as exc:  # pragma: no cover - dev-mode fallback
            self.logger.warning(
                "Redis unavailable (%s); dropping event %s for %s",
                exc,
                kind,
                stream_key,
            )
            return
        maxlen = max(1, self.stream_ttl_seconds // 60)
        fields = {"event": event.model_dump_json()}
        try:
            await redis_client.xadd(stream_key, fields, maxlen=maxlen, approximate=True)
        except Exception as exc:  # pragma: no cover - best-effort publish
            self.logger.warning("Failed to XADD %s to %s: %s", kind, stream_key, exc)

    async def _publish_message_event(
        self,
        stream_key: str,
        message: Any,
        run_id: str,
        node_id: str,
    ) -> None:
        """Inspect an SDK message and publish the right event kind.

        AssistantMessages with TextBlocks → ``dispatch.message``.
        Messages with ToolUseBlocks → ``dispatch.tool_use``.
        Messages with ToolResultBlocks → ``dispatch.tool_result``.
        ResultMessage / SystemMessage / UserMessage → ``dispatch.message``
        (catch-all).
        """
        kind = "dispatch.message"
        content = getattr(message, "content", None)
        if isinstance(content, list):
            for block in content:
                cls_name = type(block).__name__
                if cls_name == "ToolUseBlock":
                    kind = "dispatch.tool_use"
                    break
                if cls_name == "ToolResultBlock":
                    kind = "dispatch.tool_result"
                    break
        payload: Dict[str, Any] = {
            "message_class": type(message).__name__,
        }
        # Surface terminal-result error metadata inline so the live stream
        # shows *why* a dispatch died, not just that a ResultMessage arrived.
        if getattr(message, "is_error", False):
            payload["is_error"] = True
            payload["api_error_status"] = getattr(message, "api_error_status", None)
            payload["result_text"] = getattr(message, "result", None)
        await self._publish_event(
            stream_key,
            kind=kind,
            run_id=run_id,
            node_id=node_id,
            payload=payload,
        )


class CodexCodeDispatcher:
    """Thin orchestration class over ``codex exec --json``.

    The class mirrors the public ``dispatch`` contract of
    :class:`ClaudeCodeDispatcher` so Development can choose a coding-agent
    backend without changing the dev-loop graph.
    """

    _TOOL_ITEM_TYPES = {
        "command_execution",
        "file_change",
        "mcp_tool_call",
        "web_search",
    }

    def __init__(
        self,
        *,
        max_concurrent: int,
        redis_url: str,
        stream_ttl_seconds: int,
        codex_bin: str = "codex",
    ) -> None:
        if max_concurrent < 1:
            raise ValueError("max_concurrent must be >= 1")
        self.logger = logging.getLogger(__name__)
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._redis_url = redis_url
        self.stream_ttl_seconds = stream_ttl_seconds
        self.codex_bin = codex_bin
        self._redis: Any = None

    async def dispatch(
        self,
        *,
        brief: BaseModel,
        profile: CodexCodeDispatchProfile,
        output_model: Type[T],
        run_id: str,
        node_id: str,
        cwd: str,
        session_host: Optional[SessionHost] = None,
    ) -> T:
        """Dispatch a single Codex CLI session and return parsed output."""
        stream_key = f"flow:{run_id}:dispatch:{node_id}"
        schema_path: Optional[str] = None
        output_path: Optional[str] = None
        process: Any = None
        # FEAT-322 TASK-1852: see module-level _SESSION_HOST_CTX docstring.
        # try/except covers the narrow pre-semaphore window so an early
        # raise here still resets the var (the main finally: below only
        # covers the semaphore block).
        _host_token = _SESSION_HOST_CTX.set(session_host)
        try:
            self._enforce_cwd_under_worktree_base(cwd)

            await self._publish_event(
                stream_key,
                kind="dispatch.queued",
                run_id=run_id,
                node_id=node_id,
                payload={"profile": profile.model_dump(mode="json")},
            )
        except Exception:
            _SESSION_HOST_CTX.reset(_host_token)
            raise

        async with self._semaphore:
            try:
                schema_path = self._materialize_json_schema(output_model)
                output_path = self._reserve_output_path()
                prompt = self._build_codex_prompt(profile, brief, output_model)
                command = self._build_command(
                    profile=profile,
                    cwd=cwd,
                    schema_path=schema_path,
                    output_path=output_path,
                    prompt=prompt,
                )

                await self._publish_event(
                    stream_key,
                    kind="dispatch.started",
                    run_id=run_id,
                    node_id=node_id,
                    payload={
                        "cwd": cwd,
                        "subagent": profile.subagent,
                        "model": profile.model,
                        "sandbox": profile.sandbox,
                    },
                )

                try:
                    async with asyncio.timeout(profile.timeout_seconds):
                        process = await self._create_process(command)
                        stderr_task = asyncio.create_task(self._read_stream(process.stderr))
                        await self._stream_stdout_events(
                            process.stdout,
                            stream_key=stream_key,
                            run_id=run_id,
                            node_id=node_id,
                        )
                        return_code = await process.wait()
                        stderr = await stderr_task
                except FileNotFoundError as exc:
                    await self._publish_event(
                        stream_key,
                        kind="dispatch.failed",
                        run_id=run_id,
                        node_id=node_id,
                        payload={
                            "error_class": "FileNotFoundError",
                            "error_message": (f"Codex CLI executable {self.codex_bin!r} " "was not found on PATH"),
                        },
                    )
                    raise DispatchExecutionError(f"Codex CLI executable {self.codex_bin!r} was not found") from exc
                except TimeoutError as exc:
                    if process is not None:
                        process.kill()
                        await process.wait()
                    await self._publish_event(
                        stream_key,
                        kind="dispatch.failed",
                        run_id=run_id,
                        node_id=node_id,
                        payload={
                            "error_class": "TimeoutError",
                            "error_message": (f"dispatch exceeded " f"{profile.timeout_seconds}s wall-clock cap"),
                        },
                    )
                    raise DispatchExecutionError(
                        f"Dispatch exceeded {profile.timeout_seconds}s " f"wall-clock cap"
                    ) from exc

                if return_code != 0:
                    await self._publish_event(
                        stream_key,
                        kind="dispatch.failed",
                        run_id=run_id,
                        node_id=node_id,
                        payload={
                            "exit_code": return_code,
                            "stderr_tail": stderr[-4000:],
                        },
                    )
                    raise DispatchExecutionError(
                        "Codex CLI dispatch failed with exit code " f"{return_code}: {stderr[-1000:]}"
                    )

                try:
                    result = self._validate_output_file(output_path, output_model)
                except DispatchOutputValidationError as exc:
                    await self._publish_event(
                        stream_key,
                        kind="dispatch.output_invalid",
                        run_id=run_id,
                        node_id=node_id,
                        payload={
                            "raw_payload": exc.raw_payload[:8000],
                            "error_message": str(exc),
                        },
                    )
                    raise

                await self._publish_event(
                    stream_key,
                    kind="dispatch.completed",
                    run_id=run_id,
                    node_id=node_id,
                    payload={"output_model": output_model.__name__},
                )
                return result
            finally:
                _SESSION_HOST_CTX.reset(_host_token)
                for path in (schema_path, output_path):
                    if path is None:
                        continue
                    try:
                        os.unlink(path)
                    except OSError:
                        pass

    def _build_command(
        self,
        *,
        profile: CodexCodeDispatchProfile,
        cwd: str,
        schema_path: str,
        output_path: str,
        prompt: str,
    ) -> List[str]:
        """Build the ``codex exec`` command line."""
        cmd = [
            self.codex_bin,
            "exec",
            "--json",
            "--cd",
            cwd,
            "--model",
            profile.model,
            "--sandbox",
            profile.sandbox,
            "--ask-for-approval",
            profile.approval_policy,
            "--output-schema",
            schema_path,
            "-o",
            output_path,
        ]
        if profile.ignore_user_config:
            cmd.append("--ignore-user-config")
        if profile.ignore_rules:
            cmd.append("--ignore-rules")
        cmd.append(prompt)
        return cmd

    def _build_codex_prompt(
        self,
        profile: CodexCodeDispatchProfile,
        brief: BaseModel,
        output_model: Type[BaseModel],
    ) -> str:
        body = load_subagent_definition(profile.subagent)
        output_prompt = self._build_prompt(brief, output_model)
        return (
            f"You are the `{profile.subagent}` dev-loop subagent.\n\n"
            f"Subagent instructions:\n{body}\n\n"
            f"{output_prompt}"
        )

    async def _create_process(self, command: Sequence[str]) -> Any:
        """Spawn the Codex CLI subprocess."""
        return await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

    async def _stream_stdout_events(
        self,
        stdout: Any,
        *,
        stream_key: str,
        run_id: str,
        node_id: str,
    ) -> None:
        if stdout is None:
            return
        while True:
            raw = await stdout.readline()
            if not raw:
                return
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except ValueError:
                await self._publish_event(
                    stream_key,
                    kind="dispatch.message",
                    run_id=run_id,
                    node_id=node_id,
                    payload={"raw_line": line},
                )
                continue
            await self._publish_codex_event(stream_key, event, run_id, node_id)

    async def _publish_codex_event(
        self,
        stream_key: str,
        event: Dict[str, Any],
        run_id: str,
        node_id: str,
    ) -> None:
        await self._publish_event(
            stream_key,
            kind=self._codex_event_kind(event),
            run_id=run_id,
            node_id=node_id,
            payload={"codex_event": event},
        )

    def _codex_event_kind(self, event: Dict[str, Any]) -> str:
        event_type = event.get("type")
        item = event.get("item")
        item_type = item.get("type") if isinstance(item, dict) else None
        if event_type == "item.started" and item_type in self._TOOL_ITEM_TYPES:
            return "dispatch.tool_use"
        if event_type == "item.completed" and item_type in self._TOOL_ITEM_TYPES:
            return "dispatch.tool_result"
        return "dispatch.message"

    async def _read_stream(self, stream: Any) -> str:
        if stream is None:
            return ""
        data = await stream.read()
        if isinstance(data, bytes):
            return data.decode("utf-8", errors="replace")
        return str(data or "")

    def _validate_output_file(
        self,
        output_path: str,
        output_model: Type[T],
    ) -> T:
        try:
            with open(output_path, "r", encoding="utf-8") as fh:
                raw_payload = fh.read()
        except OSError as exc:
            raise DispatchOutputValidationError(
                "Codex did not write a structured output file.",
                raw_payload="",
            ) from exc
        if not raw_payload.strip():
            raise DispatchOutputValidationError(
                "Codex structured output file was empty.",
                raw_payload="",
            )
        try:
            return output_model.model_validate_json(raw_payload)
        except ValidationError as exc:
            raise DispatchOutputValidationError(
                f"Output failed {output_model.__name__} validation: {exc}",
                raw_payload=raw_payload,
            ) from exc

    def _enforce_cwd_under_worktree_base(self, cwd: str) -> None:
        base = os.path.abspath(conf.WORKTREE_BASE_PATH)
        target = os.path.abspath(cwd)
        try:
            common = os.path.commonpath([base, target])
        except ValueError:
            common = ""
        if common != base:
            raise DispatchExecutionError(f"cwd {cwd!r} is not under WORKTREE_BASE_PATH={base!r}")

    def _materialize_json_schema(self, output_model: Type[BaseModel]) -> str:
        schema = output_model.model_json_schema()
        fd, path = tempfile.mkstemp(prefix="dev_loop_codex_schema_", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(schema, fh)
        except Exception:
            os.close(fd)
            try:
                os.unlink(path)
            except OSError:
                pass
            raise
        return path

    @staticmethod
    def _reserve_output_path() -> str:
        fd, path = tempfile.mkstemp(prefix="dev_loop_codex_output_", suffix=".json")
        os.close(fd)
        return path

    def _build_prompt(self, brief: BaseModel, output_model: Type[BaseModel]) -> str:
        brief_json = brief.model_dump_json()
        schema = output_model.model_json_schema()
        properties = schema.get("properties", {}) or {}
        required = schema.get("required", []) or []
        field_lines: List[str] = []
        for fname, fmeta in properties.items():
            ftype = fmeta.get("type") or fmeta.get("$ref", "").rsplit("/", 1)[-1] or "any"
            fdesc = (fmeta.get("description") or "").strip()
            mandatory = " (required)" if fname in required else ""
            line = f"  - {fname}: {ftype}{mandatory}"
            if fdesc:
                line += f" — {fdesc}"
            field_lines.append(line)
        fields_block = "\n".join(field_lines) or "  (no fields)"
        required_block = ", ".join(required) if required else "(none)"
        return (
            f"Input brief:\n{brief_json}\n\n"
            f"Respond with a single JSON object that matches the "
            f"`{output_model.__name__}` schema. Use these EXACT field "
            f"names — do not invent shorter aliases:\n"
            f"{fields_block}\n\n"
            f"Required fields (must be present and non-empty): "
            f"{required_block}.\n\n"
            f"Output rules:\n"
            f"  1. Emit ONE JSON object — no surrounding prose.\n"
            f"  2. No markdown fences around the JSON.\n"
            f"  3. All required fields above must appear under their "
            f"exact names."
        )

    async def _ensure_redis(self) -> Any:
        if self._redis is not None:
            return self._redis
        import redis.asyncio as aioredis

        self._redis = aioredis.from_url(self._redis_url)
        return self._redis

    async def _publish_event(
        self,
        stream_key: str,
        *,
        kind: str,
        run_id: str,
        node_id: str,
        payload: Dict[str, Any],
    ) -> None:
        event = DispatchEvent(
            kind=kind,  # type: ignore[arg-type]
            ts=time.time(),
            run_id=run_id,
            node_id=node_id,
            payload=payload,
        )
        # FEAT-322 TASK-1852: dual-publish shim (see module-level docstring).
        _apply_to_session_host(event)
        try:
            redis_client = await self._ensure_redis()
        except Exception as exc:  # pragma: no cover - dev-mode fallback
            self.logger.warning(
                "Redis unavailable (%s); dropping event %s for %s",
                exc,
                kind,
                stream_key,
            )
            return
        maxlen = max(1, self.stream_ttl_seconds // 60)
        fields = {"event": event.model_dump_json()}
        try:
            await redis_client.xadd(stream_key, fields, maxlen=maxlen, approximate=True)
        except Exception as exc:  # pragma: no cover - best-effort publish
            self.logger.warning("Failed to XADD %s to %s: %s", kind, stream_key, exc)


class GeminiCodeDispatcher:
    """Thin orchestration class over ``gemini --output-format stream-json``.

    The class mirrors the public ``dispatch`` contract of
    :class:`ClaudeCodeDispatcher` and :class:`CodexCodeDispatcher` so
    Development can choose a coding-agent backend without changing the
    dev-loop graph.
    """

    def __init__(
        self,
        *,
        max_concurrent: int,
        redis_url: str,
        stream_ttl_seconds: int,
        gemini_bin: str = "gemini",
    ) -> None:
        if max_concurrent < 1:
            raise ValueError("max_concurrent must be >= 1")
        self.logger = logging.getLogger(__name__)
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._redis_url = redis_url
        self.stream_ttl_seconds = stream_ttl_seconds
        self.gemini_bin = gemini_bin
        self._redis: Any = None

        # Resolve binary path
        resolved = shutil.which(self.gemini_bin) or shutil.which("gemini-cli") or shutil.which("gemini")
        if not resolved:
            # check common local path as fallback
            local_fallback = "/home/jesuslara/.nvm/versions/node/v23.0.0/bin/gemini"
            if os.path.exists(local_fallback):
                resolved = local_fallback
            else:
                resolved = self.gemini_bin
        self.resolved_bin = resolved

    async def dispatch(
        self,
        *,
        brief: BaseModel,
        profile: Any,
        output_model: Type[T],
        run_id: str,
        node_id: str,
        cwd: str,
        session_host: Optional[SessionHost] = None,
    ) -> T:
        """Dispatch a single Gemini CLI session and return its parsed output."""
        stream_key = f"flow:{run_id}:dispatch:{node_id}"
        process: Any = None
        # FEAT-322 TASK-1852: see module-level _SESSION_HOST_CTX docstring.
        # try/except covers the narrow pre-semaphore window so an early
        # raise here still resets the var (the main finally: below only
        # covers the semaphore block).
        _host_token = _SESSION_HOST_CTX.set(session_host)
        try:
            self._enforce_cwd_under_worktree_base(cwd)

            # Handle transparent profile conversion
            if isinstance(profile, ClaudeCodeDispatchProfile):
                approval_mode = "auto_edit"
                if profile.permission_mode == "acceptEdits":
                    approval_mode = "auto_edit"
                elif profile.permission_mode == "bypassPermissions" or profile.permission_mode == "default":
                    approval_mode = "yolo"
                elif profile.permission_mode == "plan":
                    approval_mode = "plan"

                profile = GeminiCodeDispatchProfile(
                    subagent=profile.subagent or "sdd-worker",
                    model="auto",
                    sandbox=True,
                    approval_mode=approval_mode,
                    timeout_seconds=profile.timeout_seconds,
                )

            await self._publish_event(
                stream_key,
                kind="dispatch.queued",
                run_id=run_id,
                node_id=node_id,
                payload={"profile": profile.model_dump(mode="json")},
            )
        except Exception:
            _SESSION_HOST_CTX.reset(_host_token)
            raise

        async with self._semaphore:
            try:
                prompt = self._build_gemini_prompt(profile, brief, output_model)
                command = self._build_command(
                    profile=profile,
                    prompt=prompt,
                )

                await self._publish_event(
                    stream_key,
                    kind="dispatch.started",
                    run_id=run_id,
                    node_id=node_id,
                    payload={
                        "cwd": cwd,
                        "subagent": profile.subagent,
                        "model": profile.model,
                    },
                )

                try:
                    async with asyncio.timeout(profile.timeout_seconds):
                        process = await self._create_process(command, cwd=cwd)
                        stderr_task = asyncio.create_task(self._read_stream(process.stderr))
                        assistant_text = await self._stream_stdout_events(
                            process.stdout,
                            stream_key=stream_key,
                            run_id=run_id,
                            node_id=node_id,
                        )
                        return_code = await process.wait()
                        stderr = await stderr_task
                except FileNotFoundError as exc:
                    await self._publish_event(
                        stream_key,
                        kind="dispatch.failed",
                        run_id=run_id,
                        node_id=node_id,
                        payload={
                            "error_class": "FileNotFoundError",
                            "error_message": (f"Gemini CLI executable {self.resolved_bin!r} " "was not found on PATH"),
                        },
                    )
                    raise DispatchExecutionError(f"Gemini CLI executable {self.resolved_bin!r} was not found") from exc
                except TimeoutError as exc:
                    if process is not None:
                        process.kill()
                        await process.wait()
                    await self._publish_event(
                        stream_key,
                        kind="dispatch.failed",
                        run_id=run_id,
                        node_id=node_id,
                        payload={
                            "error_class": "TimeoutError",
                            "error_message": (f"dispatch exceeded " f"{profile.timeout_seconds}s wall-clock cap"),
                        },
                    )
                    raise DispatchExecutionError(
                        f"Dispatch exceeded {profile.timeout_seconds}s " f"wall-clock cap"
                    ) from exc

                if return_code != 0:
                    await self._publish_event(
                        stream_key,
                        kind="dispatch.failed",
                        run_id=run_id,
                        node_id=node_id,
                        payload={
                            "exit_code": return_code,
                            "stderr_tail": stderr[-4000:],
                        },
                    )
                    raise DispatchExecutionError(
                        "Gemini CLI dispatch failed with exit code " f"{return_code}: {stderr[-1000:]}"
                    )

                try:
                    result = self._validate_output(assistant_text, output_model)
                except DispatchOutputValidationError as exc:
                    await self._publish_event(
                        stream_key,
                        kind="dispatch.output_invalid",
                        run_id=run_id,
                        node_id=node_id,
                        payload={
                            "raw_payload": exc.raw_payload[:8000],
                            "error_message": str(exc),
                        },
                    )
                    raise

                await self._publish_event(
                    stream_key,
                    kind="dispatch.completed",
                    run_id=run_id,
                    node_id=node_id,
                    payload={"output_model": output_model.__name__},
                )
                return result
            finally:
                _SESSION_HOST_CTX.reset(_host_token)

    def _build_command(
        self,
        *,
        profile: GeminiCodeDispatchProfile,
        prompt: str,
    ) -> List[str]:
        """Build the ``gemini`` command line."""
        cmd = [
            self.resolved_bin,
            "--skip-trust",
            "--output-format",
            "stream-json",
            "--approval-mode",
            profile.approval_mode,
        ]
        if profile.model and profile.model != "auto":
            cmd.extend(["--model", profile.model])
        if profile.sandbox:
            cmd.append("--sandbox")

        cmd.extend(["--prompt", prompt])
        return cmd

    def _build_gemini_prompt(
        self,
        profile: GeminiCodeDispatchProfile,
        brief: BaseModel,
        output_model: Type[BaseModel],
    ) -> str:
        body = load_subagent_definition(profile.subagent)
        output_prompt = self._build_prompt(brief, output_model)
        return (
            f"You are the `{profile.subagent}` dev-loop subagent.\n\n"
            f"Subagent instructions:\n{body}\n\n"
            f"{output_prompt}"
        )

    async def _create_process(self, command: Sequence[str], cwd: str) -> Any:
        """Spawn the Gemini CLI subprocess."""
        return await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )

    async def _stream_stdout_events(
        self,
        stdout: Any,
        *,
        stream_key: str,
        run_id: str,
        node_id: str,
    ) -> str:
        if stdout is None:
            return ""
        assistant_chunks: List[str] = []
        while True:
            raw = await stdout.readline()
            if not raw:
                break
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except ValueError:
                await self._publish_event(
                    stream_key,
                    kind="dispatch.message",
                    run_id=run_id,
                    node_id=node_id,
                    payload={"raw_line": line},
                )
                continue

            if isinstance(event, dict):
                event_type = event.get("type")
                if event_type == "message" and event.get("role") == "assistant":
                    content = event.get("content", "")
                    if content:
                        assistant_chunks.append(content)

                await self._publish_gemini_event(stream_key, event, run_id, node_id)

        return "".join(assistant_chunks)

    async def _publish_gemini_event(
        self,
        stream_key: str,
        event: Dict[str, Any],
        run_id: str,
        node_id: str,
    ) -> None:
        await self._publish_event(
            stream_key,
            kind=self._gemini_event_kind(event),
            run_id=run_id,
            node_id=node_id,
            payload={"gemini_event": event},
        )

    def _gemini_event_kind(self, event: Dict[str, Any]) -> str:
        event_type = event.get("type")
        if event_type == "tool_call":
            return "dispatch.tool_use"
        if event_type == "tool_response":
            return "dispatch.tool_result"
        return "dispatch.message"

    async def _read_stream(self, stream: Any) -> str:
        if stream is None:
            return ""
        data = await stream.read()
        if isinstance(data, bytes):
            return data.decode("utf-8", errors="replace")
        return str(data or "")

    def _validate_output(self, concatenated: str, output_model: Type[T]) -> T:
        """Best-effort JSON parse + Pydantic validate against ``output_model``.

        Locates the last balanced JSON object in the concatenated assistant text,
        and validates it. Raises :class:`DispatchOutputValidationError` (with raw payload) on
        any failure.
        """
        if not concatenated.strip():
            raise DispatchOutputValidationError(
                "No assistant text found in dispatch result.",
                raw_payload="",
            )
        json_text = self._extract_last_json_object(concatenated)
        if json_text is None:
            raise DispatchOutputValidationError(
                "Could not locate a JSON object in the assistant output.",
                raw_payload=concatenated,
            )
        try:
            return output_model.model_validate_json(json_text)
        except ValidationError as exc:
            raise DispatchOutputValidationError(
                f"Output failed {output_model.__name__} validation: {exc}",
                raw_payload=json_text,
            ) from exc

    def _enforce_cwd_under_worktree_base(self, cwd: str) -> None:
        base = os.path.abspath(conf.WORKTREE_BASE_PATH)
        target = os.path.abspath(cwd)
        try:
            common = os.path.commonpath([base, target])
        except ValueError:
            common = ""
        if common != base:
            raise DispatchExecutionError(f"cwd {cwd!r} is not under WORKTREE_BASE_PATH={base!r}")

    @staticmethod
    def _extract_last_json_object(text: str) -> Optional[str]:
        """Return the last balanced ``{...}`` substring of ``text``."""
        last_obj: Optional[str] = None
        depth = 0
        start = -1
        in_string = False
        escape = False
        for idx, ch in enumerate(text):
            if escape:
                escape = False
                continue
            if ch == "\\" and in_string:
                escape = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "{":
                if depth == 0:
                    start = idx
                depth += 1
            elif ch == "}":
                if depth > 0:
                    depth -= 1
                    if depth == 0 and start != -1:
                        last_obj = text[start : idx + 1]
        return last_obj

    def _build_prompt(self, brief: BaseModel, output_model: Type[BaseModel]) -> str:
        brief_json = brief.model_dump_json()
        schema = output_model.model_json_schema()
        properties = schema.get("properties", {}) or {}
        required = schema.get("required", []) or []
        field_lines: List[str] = []
        for fname, fmeta in properties.items():
            ftype = fmeta.get("type") or fmeta.get("$ref", "").rsplit("/", 1)[-1] or "any"
            fdesc = (fmeta.get("description") or "").strip()
            mandatory = " (required)" if fname in required else ""
            line = f"  - {fname}: {ftype}{mandatory}"
            if fdesc:
                line += f" — {fdesc}"
            field_lines.append(line)
        fields_block = "\n".join(field_lines) or "  (no fields)"
        required_block = ", ".join(required) if required else "(none)"
        return (
            f"Input brief:\n{brief_json}\n\n"
            f"Respond with a single JSON object that matches the "
            f"`{output_model.__name__}` schema. Use these EXACT field "
            f"names — do not invent shorter aliases:\n"
            f"{fields_block}\n\n"
            f"Required fields (must be present and non-empty): "
            f"{required_block}.\n\n"
            f"Output rules:\n"
            f"  1. Emit ONE JSON object — no surrounding prose.\n"
            f"  2. No markdown fences around the JSON.\n"
            f"  3. All required fields above must appear under their "
            f"exact names."
        )

    async def _ensure_redis(self) -> Any:
        if self._redis is not None:
            return self._redis
        import redis.asyncio as aioredis

        self._redis = aioredis.from_url(self._redis_url)
        return self._redis

    async def _publish_event(
        self,
        stream_key: str,
        *,
        kind: str,
        run_id: str,
        node_id: str,
        payload: Dict[str, Any],
    ) -> None:
        event = DispatchEvent(
            kind=kind,  # type: ignore[arg-type]
            ts=time.time(),
            run_id=run_id,
            node_id=node_id,
            payload=payload,
        )
        # FEAT-322 TASK-1852: dual-publish shim (see module-level docstring).
        _apply_to_session_host(event)
        try:
            redis_client = await self._ensure_redis()
        except Exception as exc:  # pragma: no cover - dev-mode fallback
            self.logger.warning(
                "Redis unavailable (%s); dropping event %s for %s",
                exc,
                kind,
                stream_key,
            )
            return
        maxlen = max(1, self.stream_ttl_seconds // 60)
        fields = {"event": event.model_dump_json()}
        try:
            await redis_client.xadd(stream_key, fields, maxlen=maxlen, approximate=True)
        except Exception as exc:  # pragma: no cover - best-effort publish
            self.logger.warning("Failed to XADD %s to %s: %s", kind, stream_key, exc)


class LLMCodeDispatcher:
    """Local coding-agent loop for OpenAI-compatible LLM clients.

    CLI-backed dispatchers delegate filesystem and command execution to their
    external runtime. This dispatcher keeps that runtime in-process: the model
    receives a small OpenAI-style tool surface, every tool is cwd-confined, and
    the final payload is validated against the requested Pydantic model.
    """

    def __init__(
        self,
        *,
        max_concurrent: int,
        redis_url: str,
        stream_ttl_seconds: int,
        client_factory: Callable[..., Any] = LLMFactory.create,
    ) -> None:
        if max_concurrent < 1:
            raise ValueError("max_concurrent must be >= 1")
        self.logger = logging.getLogger(__name__)
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._redis_url = redis_url
        self.stream_ttl_seconds = stream_ttl_seconds
        self._client_factory = client_factory
        self._redis: Any = None

    async def dispatch(
        self,
        *,
        brief: BaseModel,
        profile: LLMCodeDispatchProfile,
        output_model: Type[T],
        run_id: str,
        node_id: str,
        cwd: str,
        session_host: Optional[SessionHost] = None,
    ) -> T:
        stream_key = f"flow:{run_id}:dispatch:{node_id}"
        # FEAT-322 TASK-1852: see module-level _SESSION_HOST_CTX docstring —
        # the try/except below covers the narrow pre-semaphore window (an
        # early raise here still resets the var); the try/except/finally
        # inside the semaphore block below resets it on every OTHER exit
        # path (the success return or one of the re-raising excepts).
        _host_token = _SESSION_HOST_CTX.set(session_host)
        try:
            self._enforce_cwd_under_worktree_base(cwd)

            await self._publish_event(
                stream_key,
                kind="dispatch.queued",
                run_id=run_id,
                node_id=node_id,
                payload={"profile": profile.model_dump(mode="json")},
            )
        except Exception:
            _SESSION_HOST_CTX.reset(_host_token)
            raise

        async with self._semaphore:
            await self._publish_event(
                stream_key,
                kind="dispatch.started",
                run_id=run_id,
                node_id=node_id,
                payload={
                    "cwd": cwd,
                    "subagent": profile.subagent,
                    "llm": profile.llm,
                    "sandbox": profile.sandbox,
                },
            )
            try:
                async with asyncio.timeout(profile.timeout_seconds):
                    return await self._dispatch_loop(
                        brief=brief,
                        profile=profile,
                        output_model=output_model,
                        run_id=run_id,
                        node_id=node_id,
                        stream_key=stream_key,
                        cwd=cwd,
                    )
            except TimeoutError as exc:
                await self._publish_event(
                    stream_key,
                    kind="dispatch.failed",
                    run_id=run_id,
                    node_id=node_id,
                    payload={
                        "error_class": "TimeoutError",
                        "error_message": (f"dispatch exceeded {profile.timeout_seconds}s " "wall-clock cap"),
                    },
                )
                raise DispatchExecutionError(f"Dispatch exceeded {profile.timeout_seconds}s wall-clock cap") from exc
            except DispatchOutputValidationError as exc:
                await self._publish_event(
                    stream_key,
                    kind="dispatch.output_invalid",
                    run_id=run_id,
                    node_id=node_id,
                    payload={
                        "raw_payload": exc.raw_payload[:8000],
                        "error_message": str(exc),
                    },
                )
                raise
            except DispatchExecutionError as exc:
                await self._publish_event(
                    stream_key,
                    kind="dispatch.failed",
                    run_id=run_id,
                    node_id=node_id,
                    payload={
                        "error_class": type(exc).__name__,
                        "error_message": str(exc),
                    },
                )
                raise
            except Exception as exc:
                await self._publish_event(
                    stream_key,
                    kind="dispatch.failed",
                    run_id=run_id,
                    node_id=node_id,
                    payload={
                        "error_class": type(exc).__name__,
                        "error_message": str(exc),
                    },
                )
                raise DispatchExecutionError(f"LLM code dispatch failed: {exc}") from exc
            finally:
                _SESSION_HOST_CTX.reset(_host_token)

    async def _dispatch_loop(
        self,
        *,
        brief: BaseModel,
        profile: LLMCodeDispatchProfile,
        output_model: Type[T],
        run_id: str,
        node_id: str,
        stream_key: str,
        cwd: str,
    ) -> T:
        client = self._create_client(profile)
        await self._ensure_client_ready(client)
        model = self._resolve_model(profile, client)
        messages = self._initial_messages(profile, brief, output_model)
        tools = self._tool_schemas(output_model)
        args = self._completion_args(profile, tools)

        for turn_index in range(profile.max_turns):
            response = await self._chat_completion(
                client=client,
                model=model,
                messages=messages,
                args=args,
            )
            message = self._response_message(response)
            content = self._message_content(message)
            tool_calls = self._message_tool_calls(message)

            if content:
                await self._publish_event(
                    stream_key,
                    kind="dispatch.message",
                    run_id=run_id,
                    node_id=node_id,
                    payload={"turn": turn_index, "text": content[:4000]},
                )

            if not tool_calls:
                result = self._validate_text_output(content, output_model)
                await self._publish_event(
                    stream_key,
                    kind="dispatch.completed",
                    run_id=run_id,
                    node_id=node_id,
                    payload={"output_model": output_model.__name__},
                )
                return result

            messages.append(
                {
                    "role": "assistant",
                    "content": content,
                    "tool_calls": [self._tool_call_to_openai_dict(call) for call in tool_calls],
                }
            )

            for call in tool_calls:
                tool_call_id = self._tool_call_id(call)
                tool_name = self._tool_call_name(call)
                tool_args = self._tool_call_arguments(call)
                await self._publish_event(
                    stream_key,
                    kind="dispatch.tool_use",
                    run_id=run_id,
                    node_id=node_id,
                    payload={
                        "tool_call_id": tool_call_id,
                        "tool_name": tool_name,
                        "arguments": tool_args,
                    },
                )

                if tool_name == "final_output":
                    result = self._validate_final_tool(tool_args, output_model)
                    await self._publish_event(
                        stream_key,
                        kind="dispatch.tool_result",
                        run_id=run_id,
                        node_id=node_id,
                        payload={
                            "tool_call_id": tool_call_id,
                            "tool_name": tool_name,
                            "result": {"ok": True},
                        },
                    )
                    await self._publish_event(
                        stream_key,
                        kind="dispatch.completed",
                        run_id=run_id,
                        node_id=node_id,
                        payload={"output_model": output_model.__name__},
                    )
                    return result

                tool_result = await self._run_tool(
                    tool_name=tool_name,
                    tool_args=tool_args,
                    cwd=cwd,
                    profile=profile,
                )
                await self._publish_event(
                    stream_key,
                    kind="dispatch.tool_result",
                    run_id=run_id,
                    node_id=node_id,
                    payload={
                        "tool_call_id": tool_call_id,
                        "tool_name": tool_name,
                        "result": tool_result,
                    },
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "name": tool_name,
                        "content": json.dumps(tool_result, ensure_ascii=False),
                    }
                )

        raise DispatchExecutionError(f"LLM code dispatch exceeded max_turns={profile.max_turns}")

    def _create_client(self, profile: LLMCodeDispatchProfile) -> Any:
        model_args = {
            "temperature": profile.temperature,
            "max_tokens": profile.max_tokens,
        }
        return self._client_factory(profile.llm, model_args=model_args)

    @staticmethod
    async def _ensure_client_ready(client: Any) -> None:
        if getattr(client, "client", None) is not None:
            return
        ensure = getattr(client, "_ensure_client", None)
        if callable(ensure):
            await ensure()

    @staticmethod
    def _resolve_model(profile: LLMCodeDispatchProfile, client: Any) -> str:
        _provider, model = LLMFactory.parse_llm_string(profile.llm)
        resolved = (
            model
            or getattr(client, "model", None)
            or getattr(client, "default_model", None)
            or getattr(client, "_default_model", None)
        )
        if resolved is None:
            raise DispatchExecutionError(f"Could not resolve a model from llm={profile.llm!r}")
        return str(resolved)

    def _initial_messages(
        self,
        profile: LLMCodeDispatchProfile,
        brief: BaseModel,
        output_model: Type[BaseModel],
    ) -> List[Dict[str, Any]]:
        body = load_subagent_definition(profile.subagent)
        return [
            {
                "role": "system",
                "content": (
                    f"You are the `{profile.subagent}` dev-loop coding "
                    "subagent. Use the provided tools to inspect and update "
                    "only the current repository. Finish by calling "
                    "`final_output` with the exact structured result.\n\n"
                    f"Subagent instructions:\n{body}"
                ),
            },
            {
                "role": "user",
                "content": self._build_prompt(brief, output_model),
            },
        ]

    def _completion_args(
        self,
        profile: LLMCodeDispatchProfile,
        tools: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        args: Dict[str, Any] = {
            "tools": tools,
            "tool_choice": "auto",
            "parallel_tool_calls": False,
            "max_tokens": profile.max_tokens,
        }
        if profile.temperature is not None:
            args["temperature"] = profile.temperature
        if profile.enable_thinking:
            args["extra_body"] = {
                "chat_template_kwargs": {
                    "enable_thinking": True,
                    "clear_thinking": profile.clear_thinking,
                }
            }
        return args

    async def _chat_completion(
        self,
        *,
        client: Any,
        model: str,
        messages: List[Dict[str, Any]],
        args: Dict[str, Any],
    ) -> Any:
        method = getattr(client, "_chat_completion", None)
        if not callable(method):
            raise DispatchExecutionError(f"Client {type(client).__name__} does not expose chat completion")
        return await method(
            model=model,
            messages=messages,
            use_tools=True,
            **args,
        )

    def _tool_schemas(self, output_model: Type[BaseModel]) -> List[Dict[str, Any]]:
        return [
            self._function_tool(
                "read_file",
                "Read a UTF-8 text file under the current repository.",
                {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "start_line": {"type": "integer", "minimum": 1},
                        "max_lines": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 1000,
                            "default": 200,
                        },
                    },
                    "required": ["path"],
                    "additionalProperties": False,
                },
            ),
            self._function_tool(
                "list_files",
                "List files under a repository directory.",
                {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "default": "."},
                        "max_results": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 500,
                            "default": 100,
                        },
                    },
                    "additionalProperties": False,
                },
            ),
            self._function_tool(
                "search_files",
                "Search repository text files for a literal string.",
                {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "path": {"type": "string", "default": "."},
                        "file_glob": {"type": "string"},
                        "max_results": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 200,
                            "default": 50,
                        },
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
            ),
            self._function_tool(
                "apply_patch",
                "Apply a git unified diff inside the current repository.",
                {
                    "type": "object",
                    "properties": {"patch": {"type": "string"}},
                    "required": ["patch"],
                    "additionalProperties": False,
                },
            ),
            self._function_tool(
                "run_command",
                "Run an allow-listed argv command in the repository.",
                {
                    "type": "object",
                    "properties": {
                        "argv": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 1,
                        },
                        "timeout_seconds": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 3600,
                        },
                    },
                    "required": ["argv"],
                    "additionalProperties": False,
                },
            ),
            self._function_tool(
                "final_output",
                "Return the final structured DevelopmentOutput payload.",
                output_model.model_json_schema(),
            ),
        ]

    @staticmethod
    def _function_tool(
        name: str,
        description: str,
        parameters: Dict[str, Any],
    ) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": parameters,
            },
        }

    async def _run_tool(
        self,
        *,
        tool_name: str,
        tool_args: Dict[str, Any],
        cwd: str,
        profile: LLMCodeDispatchProfile,
    ) -> Dict[str, Any]:
        try:
            if tool_name == "read_file":
                return self._tool_read_file(cwd, tool_args)
            if tool_name == "list_files":
                return self._tool_list_files(cwd, tool_args)
            if tool_name == "search_files":
                return await self._tool_search_files(cwd, tool_args)
            if tool_name == "apply_patch":
                return await self._tool_apply_patch(cwd, tool_args, profile)
            if tool_name == "run_command":
                return await self._tool_run_command(cwd, tool_args, profile)
            return {"ok": False, "error": f"unknown tool {tool_name!r}"}
        except Exception as exc:  # tool failures are returned to the model
            return {
                "ok": False,
                "error_class": type(exc).__name__,
                "error": str(exc),
            }

    def _tool_read_file(self, cwd: str, args: Dict[str, Any]) -> Dict[str, Any]:
        path = self._resolve_repo_path(cwd, str(args["path"]))
        start_line = int(args.get("start_line") or 1)
        max_lines = min(int(args.get("max_lines") or 200), 1000)
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
        selected = lines[start_line - 1 : start_line - 1 + max_lines]
        return {
            "ok": True,
            "path": os.path.relpath(path, cwd),
            "start_line": start_line,
            "line_count": len(selected),
            "content": "".join(selected)[:20000],
        }

    def _tool_list_files(self, cwd: str, args: Dict[str, Any]) -> Dict[str, Any]:
        root = self._resolve_repo_path(cwd, str(args.get("path") or "."))
        max_results = min(int(args.get("max_results") or 100), 500)
        if not os.path.isdir(root):
            raise ValueError(f"{args.get('path')!r} is not a directory")
        results: List[str] = []
        for current_root, dirnames, filenames in os.walk(root):
            dirnames[:] = [name for name in sorted(dirnames) if name not in {".git", ".venv", "__pycache__"}]
            for filename in sorted(filenames):
                results.append(os.path.relpath(os.path.join(current_root, filename), cwd))
                if len(results) >= max_results:
                    return {"ok": True, "files": results, "truncated": True}
        return {"ok": True, "files": results, "truncated": False}

    async def _tool_search_files(
        self,
        cwd: str,
        args: Dict[str, Any],
    ) -> Dict[str, Any]:
        query = str(args["query"])
        if not query:
            raise ValueError("query must not be empty")
        path = self._resolve_repo_path(cwd, str(args.get("path") or "."))
        max_results = min(int(args.get("max_results") or 50), 200)
        command = [
            "rg",
            "--line-number",
            "--no-heading",
            "--color",
            "never",
            "--fixed-strings",
        ]
        file_glob = args.get("file_glob")
        if file_glob:
            command.extend(["--glob", str(file_glob)])
        command.extend([query, os.path.relpath(path, cwd)])
        result = await self._run_argv(command, cwd=cwd, timeout=30)
        lines = result["stdout"].splitlines()[:max_results]
        if result["exit_code"] not in {0, 1}:
            return {**result, "ok": False}
        return {
            "ok": True,
            "matches": lines,
            "truncated": len(result["stdout"].splitlines()) > max_results,
        }

    async def _tool_apply_patch(
        self,
        cwd: str,
        args: Dict[str, Any],
        profile: LLMCodeDispatchProfile,
    ) -> Dict[str, Any]:
        if profile.sandbox != "workspace-write":
            raise ValueError("apply_patch requires workspace-write sandbox")
        patch = str(args["patch"])
        self._validate_patch_paths(cwd, patch)
        check = await self._run_argv(
            ["git", "apply", "--check", "-"],
            cwd=cwd,
            timeout=profile.command_timeout_seconds,
            stdin=patch,
        )
        if check["exit_code"] != 0:
            return {**check, "ok": False}
        applied = await self._run_argv(
            ["git", "apply", "-"],
            cwd=cwd,
            timeout=profile.command_timeout_seconds,
            stdin=patch,
        )
        return {**applied, "ok": applied["exit_code"] == 0}

    async def _tool_run_command(
        self,
        cwd: str,
        args: Dict[str, Any],
        profile: LLMCodeDispatchProfile,
    ) -> Dict[str, Any]:
        argv = args.get("argv")
        if not isinstance(argv, list) or not argv or not all(isinstance(v, str) for v in argv):
            raise ValueError("argv must be a non-empty list of strings")
        command = os.path.basename(argv[0])
        if command not in set(profile.allowed_commands):
            return {
                "ok": False,
                "exit_code": None,
                "stdout": "",
                "stderr": f"command {command!r} is not allow-listed",
            }
        timeout = min(
            int(args.get("timeout_seconds") or profile.command_timeout_seconds),
            profile.command_timeout_seconds,
        )
        result = await self._run_argv(argv, cwd=cwd, timeout=timeout)
        return {**result, "ok": result["exit_code"] == 0}

    async def _run_argv(
        self,
        argv: Sequence[str],
        *,
        cwd: str,
        timeout: int,
        stdin: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not argv:
            raise ValueError("argv must not be empty")
        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                cwd=cwd,
                stdin=asyncio.subprocess.PIPE if stdin is not None else None,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            return {
                "exit_code": 127,
                "stdout": "",
                "stderr": str(exc),
            }
        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                process.communicate(stdin.encode("utf-8") if stdin is not None else None),
                timeout=timeout,
            )
        except TimeoutError:
            process.kill()
            await process.wait()
            return {
                "exit_code": None,
                "stdout": "",
                "stderr": f"command timed out after {timeout}s",
            }
        stdout = stdout_b.decode("utf-8", errors="replace")[-20000:]
        stderr = stderr_b.decode("utf-8", errors="replace")[-20000:]
        return {
            "exit_code": process.returncode,
            "stdout": stdout,
            "stderr": stderr,
        }

    def _validate_patch_paths(self, cwd: str, patch: str) -> None:
        for raw in patch.splitlines():
            path: Optional[str] = None
            if raw.startswith("diff --git "):
                parts = shlex.split(raw)
                for token in parts[2:4]:
                    if token.startswith(("a/", "b/")):
                        path = token[2:]
                        self._resolve_repo_path(cwd, path)
            elif raw.startswith(("--- ", "+++ ")):
                token = raw[4:].strip().split("\t", 1)[0]
                if token == "/dev/null":
                    continue
                if token.startswith(("a/", "b/")):
                    path = token[2:]
                else:
                    path = token
                self._resolve_repo_path(cwd, path)

    def _resolve_repo_path(self, cwd: str, path: str) -> str:
        if os.path.isabs(path):
            target = os.path.abspath(path)
        else:
            target = os.path.abspath(os.path.join(cwd, path))
        base = os.path.abspath(cwd)
        try:
            common = os.path.commonpath([base, target])
        except ValueError:
            common = ""
        if common != base:
            raise ValueError(f"path {path!r} escapes cwd={base!r}")
        return target

    def _validate_final_tool(
        self,
        payload: Dict[str, Any],
        output_model: Type[T],
    ) -> T:
        try:
            return output_model.model_validate(payload)
        except ValidationError as exc:
            raise DispatchOutputValidationError(
                f"Output failed {output_model.__name__} validation: {exc}",
                raw_payload=json.dumps(payload, default=str),
            ) from exc

    def _validate_text_output(self, text: str, output_model: Type[T]) -> T:
        if not text.strip():
            raise DispatchOutputValidationError(
                "No assistant text found in dispatch result.",
                raw_payload="",
            )
        json_text = ClaudeCodeDispatcher._extract_last_json_object(text)
        if json_text is None:
            raise DispatchOutputValidationError(
                "Could not locate a JSON object in the assistant output.",
                raw_payload=text,
            )
        try:
            return output_model.model_validate_json(json_text)
        except ValidationError as exc:
            raise DispatchOutputValidationError(
                f"Output failed {output_model.__name__} validation: {exc}",
                raw_payload=json_text,
            ) from exc

    def _enforce_cwd_under_worktree_base(self, cwd: str) -> None:
        base = os.path.abspath(conf.WORKTREE_BASE_PATH)
        target = os.path.abspath(cwd)
        try:
            common = os.path.commonpath([base, target])
        except ValueError:
            common = ""
        if common != base:
            raise DispatchExecutionError(f"cwd {cwd!r} is not under WORKTREE_BASE_PATH={base!r}")

    @staticmethod
    def _response_message(response: Any) -> Any:
        choices = getattr(response, "choices", None)
        if not choices:
            raise DispatchExecutionError("LLM response did not include choices")
        return choices[0].message

    @staticmethod
    def _message_content(message: Any) -> str:
        content = getattr(message, "content", "")
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        return json.dumps(content, default=str)

    @staticmethod
    def _message_tool_calls(message: Any) -> List[Any]:
        return list(getattr(message, "tool_calls", None) or [])

    @staticmethod
    def _tool_call_id(call: Any) -> str:
        return str(getattr(call, "id", "") or "")

    @staticmethod
    def _tool_call_name(call: Any) -> str:
        function = getattr(call, "function", None)
        if isinstance(call, dict):
            function = call.get("function")
        if isinstance(function, dict):
            return str(function.get("name") or "")
        return str(getattr(function, "name", "") or "")

    @staticmethod
    def _tool_call_arguments(call: Any) -> Dict[str, Any]:
        function = getattr(call, "function", None)
        if isinstance(call, dict):
            function = call.get("function")
        raw_args: Any
        if isinstance(function, dict):
            raw_args = function.get("arguments") or "{}"
        else:
            raw_args = getattr(function, "arguments", "{}")
        if isinstance(raw_args, dict):
            return raw_args
        if not isinstance(raw_args, str):
            raise DispatchExecutionError(f"Tool arguments must be JSON object, got {type(raw_args).__name__}")
        try:
            parsed = json.loads(raw_args)
        except ValueError as exc:
            raise DispatchExecutionError(f"Could not parse tool arguments as JSON: {raw_args[:200]}") from exc
        if not isinstance(parsed, dict):
            raise DispatchExecutionError("Tool arguments JSON must be an object")
        return parsed

    def _tool_call_to_openai_dict(self, call: Any) -> Dict[str, Any]:
        return {
            "id": self._tool_call_id(call),
            "type": "function",
            "function": {
                "name": self._tool_call_name(call),
                "arguments": json.dumps(
                    self._tool_call_arguments(call),
                    ensure_ascii=False,
                ),
            },
        }

    def _build_prompt(
        self,
        brief: BaseModel,
        output_model: Type[BaseModel],
    ) -> str:
        brief_json = brief.model_dump_json()
        schema = output_model.model_json_schema()
        properties = schema.get("properties", {}) or {}
        required = schema.get("required", []) or []
        field_lines: List[str] = []
        for fname, fmeta in properties.items():
            ftype = fmeta.get("type") or fmeta.get("$ref", "").rsplit("/", 1)[-1] or "any"
            fdesc = (fmeta.get("description") or "").strip()
            mandatory = " (required)" if fname in required else ""
            line = f"  - {fname}: {ftype}{mandatory}"
            if fdesc:
                line += f" — {fdesc}"
            field_lines.append(line)
        fields_block = "\n".join(field_lines) or "  (no fields)"
        required_block = ", ".join(required) if required else "(none)"
        return (
            f"Input brief:\n{brief_json}\n\n"
            f"Use tools to inspect and edit files as needed. When the work is "
            f"complete, call `final_output` with a JSON object matching the "
            f"`{output_model.__name__}` schema. Use these EXACT field names:\n"
            f"{fields_block}\n\n"
            f"Required fields: {required_block}."
        )

    async def _ensure_redis(self) -> Any:
        if self._redis is not None:
            return self._redis
        import redis.asyncio as aioredis

        self._redis = aioredis.from_url(self._redis_url)
        return self._redis

    async def _publish_event(
        self,
        stream_key: str,
        *,
        kind: str,
        run_id: str,
        node_id: str,
        payload: Dict[str, Any],
    ) -> None:
        event = DispatchEvent(
            kind=kind,  # type: ignore[arg-type]
            ts=time.time(),
            run_id=run_id,
            node_id=node_id,
            payload=payload,
        )
        # FEAT-322 TASK-1852: dual-publish shim (see module-level docstring).
        _apply_to_session_host(event)
        try:
            redis_client = await self._ensure_redis()
        except Exception as exc:  # pragma: no cover - dev-mode fallback
            self.logger.warning(
                "Redis unavailable (%s); dropping event %s for %s",
                exc,
                kind,
                stream_key,
            )
            return
        maxlen = max(1, self.stream_ttl_seconds // 60)
        fields = {"event": event.model_dump_json()}
        try:
            await redis_client.xadd(stream_key, fields, maxlen=maxlen, approximate=True)
        except Exception as exc:  # pragma: no cover - best-effort publish
            self.logger.warning("Failed to XADD %s to %s: %s", kind, stream_key, exc)


class GrokCodeDispatcher(LLMCodeDispatcher):
    """Local coding-agent loop tailored for Grok client and Grok Build model.

    Extends LLMCodeDispatcher to leverage the local OpenAI-compatible tool loop
    while binding to the custom `GrokClient` via LLMFactory and xAI SDK.
    """

    def __init__(
        self,
        *,
        max_concurrent: int,
        redis_url: str,
        stream_ttl_seconds: int,
    ) -> None:
        super().__init__(
            max_concurrent=max_concurrent,
            redis_url=redis_url,
            stream_ttl_seconds=stream_ttl_seconds,
            client_factory=lambda model, **kw: LLMFactory.create(model, **kw),
        )

    async def _chat_completion(
        self,
        *,
        client: Any,
        model: str,
        messages: List[Dict[str, Any]],
        args: Dict[str, Any],
    ) -> Any:
        await client._ensure_client()
        return await client.client.chat.completions.create(
            model=model,
            messages=messages,
            **args,
        )

    async def dispatch(
        self,
        *,
        brief: BaseModel,
        profile: GrokCodeDispatchProfile,
        output_model: Type[T],
        run_id: str,
        node_id: str,
        cwd: str,
        session_host: Optional[SessionHost] = None,
    ) -> T:
        llm_profile = LLMCodeDispatchProfile(
            subagent=profile.subagent,
            llm=f"grok:{profile.model}",
            sandbox=profile.sandbox,
            approval_policy=profile.approval_policy,
            timeout_seconds=profile.timeout_seconds,
            max_turns=profile.max_turns,
            max_tokens=profile.max_tokens,
            temperature=profile.temperature,
            command_timeout_seconds=profile.command_timeout_seconds,
            allowed_commands=profile.allowed_commands,
        )
        return await super().dispatch(
            brief=brief,
            profile=llm_profile,
            output_model=output_model,
            run_id=run_id,
            node_id=node_id,
            cwd=cwd,
            session_host=session_host,
        )


class ZaiCodeDispatcher(LLMCodeDispatcher):
    """Local coding-agent loop bound to ``ZaiClient`` / GLM-5.2.

    Extends ``LLMCodeDispatcher`` to reuse the inherited local tool loop,
    Redis event streaming, cwd-safety guard, and output validation, while
    overriding the completion-args and chat-completion hooks so requests
    carry Z.ai-native ``thinking``/``reasoning_effort`` parameters instead
    of the Nvidia-style ``extra_body.chat_template_kwargs`` block emitted
    by the base class.
    """

    def __init__(
        self,
        *,
        max_concurrent: int,
        redis_url: str,
        stream_ttl_seconds: int,
    ) -> None:
        super().__init__(
            max_concurrent=max_concurrent,
            redis_url=redis_url,
            stream_ttl_seconds=stream_ttl_seconds,
            client_factory=lambda model, **kw: LLMFactory.create(model, **kw),
        )

    def _completion_args(
        self,
        profile: ZaiCodeDispatchProfile,
        tools: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Build Z.ai-native completion args.

        Emits ``thinking={"type": "enabled"|"disabled"}`` and
        ``reasoning_effort`` per ``profile``. Never emits ``extra_body`` /
        ``chat_template_kwargs`` (Nvidia-only concept, not understood by
        Z.ai). Logs a warning (but still dispatches) when thinking is
        requested for a model outside ``THINKING_CAPABLE_ZAI_MODELS``.
        """
        args: Dict[str, Any] = {
            "tools": tools,
            "tool_choice": "auto",
            "parallel_tool_calls": False,
            "max_tokens": profile.max_tokens,
        }
        if profile.temperature is not None:
            args["temperature"] = profile.temperature

        _provider, model = LLMFactory.parse_llm_string(profile.llm)
        if profile.enable_thinking and model not in THINKING_CAPABLE_ZAI_MODELS:
            self.logger.warning(
                "Z.ai thinking requested for model %s, which is not in the "
                "known thinking-capable set.",
                model,
            )
        args["thinking"] = {
            "type": "enabled" if profile.enable_thinking else "disabled"
        }
        args["reasoning_effort"] = profile.reasoning_effort
        return args

    async def _chat_completion(
        self,
        *,
        client: Any,
        model: str,
        messages: List[Dict[str, Any]],
        args: Dict[str, Any],
    ) -> Any:
        sdk = await client._ensure_client()
        return await asyncio.to_thread(
            sdk.chat.completions.create,
            model=model,
            messages=messages,
            **args,
        )

    async def dispatch(
        self,
        *,
        brief: BaseModel,
        profile: ZaiCodeDispatchProfile,
        output_model: Type[T],
        run_id: str,
        node_id: str,
        cwd: str,
        session_host: Optional[SessionHost] = None,
    ) -> T:
        return await super().dispatch(
            brief=brief,
            profile=profile,
            output_model=output_model,
            run_id=run_id,
            node_id=node_id,
            cwd=cwd,
            session_host=session_host,
        )


class MoonshotCodeDispatcher(LLMCodeDispatcher):
    """Local coding-agent loop bound to ``MoonshotClient`` / kimi-k3.

    Extends ``LLMCodeDispatcher`` to reuse the inherited local tool loop,
    Redis event streaming, cwd-safety guard, and output validation, while
    overriding the completion-args and chat-completion hooks so requests
    route through ``MoonshotClient._chat_completion`` — which strips the
    fixed sampling parameters K-series models reject, translates
    ``max_tokens`` to ``max_completion_tokens``, and injects the
    thinking-mode ``extra_body`` (``reasoning_effort`` for kimi-k3,
    ``thinking`` dict for kimi-k2.6) — instead of emitting the
    Nvidia-style ``extra_body.chat_template_kwargs`` block used by the
    base class.
    """

    def __init__(
        self,
        *,
        max_concurrent: int,
        redis_url: str,
        stream_ttl_seconds: int,
    ) -> None:
        super().__init__(
            max_concurrent=max_concurrent,
            redis_url=redis_url,
            stream_ttl_seconds=stream_ttl_seconds,
            client_factory=lambda model, **kw: LLMFactory.create(model, **kw),
        )

    def _completion_args(
        self,
        profile: MoonshotCodeDispatchProfile,
        tools: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Build Moonshot-native completion args.

        Omits ``temperature`` for K-series models (fixed sampling
        parameters — the API rejects a non-null value) and never emits
        ``extra_body`` / ``chat_template_kwargs`` (Nvidia-only concept).
        The ``thinking`` / ``reasoning_effort`` markers are consumed by
        :meth:`_chat_completion`, which forwards them to
        ``MoonshotClient._chat_completion`` via the client's thinking
        context variable so the model-family-specific ``extra_body``
        injection happens in one place.
        """
        args: Dict[str, Any] = {
            "tools": tools,
            "tool_choice": "auto",
            "parallel_tool_calls": False,
            "max_tokens": profile.max_tokens,
        }
        _provider, model = LLMFactory.parse_llm_string(profile.llm)
        if profile.temperature is not None and model not in K_SERIES_MODELS:
            args["temperature"] = profile.temperature
        if not profile.enable_thinking and model in ALWAYS_THINKING_MODELS:
            self.logger.warning(
                "Moonshot model %s reasons unconditionally; "
                "enable_thinking=False has no effect.",
                model,
            )
        args["thinking"] = profile.enable_thinking
        args["reasoning_effort"] = profile.reasoning_effort
        return args

    async def _chat_completion(
        self,
        *,
        client: Any,
        model: str,
        messages: List[Dict[str, Any]],
        args: Dict[str, Any],
    ) -> Any:
        args = dict(args)
        thinking_flags = {
            "thinking": args.pop("thinking", None),
            "reasoning_effort": args.pop("reasoning_effort", None),
        }
        method = getattr(client, "_chat_completion", None)
        if not callable(method):
            raise DispatchExecutionError(f"Client {type(client).__name__} does not expose chat completion")
        token = _moonshot_thinking_ctx.set(thinking_flags)
        try:
            return await method(
                model=model,
                messages=messages,
                use_tools=True,
                **args,
            )
        finally:
            _moonshot_thinking_ctx.reset(token)

    async def dispatch(
        self,
        *,
        brief: BaseModel,
        profile: MoonshotCodeDispatchProfile,
        output_model: Type[T],
        run_id: str,
        node_id: str,
        cwd: str,
        session_host: Optional[SessionHost] = None,
    ) -> T:
        return await super().dispatch(
            brief=brief,
            profile=profile,
            output_model=output_model,
            run_id=run_id,
            node_id=node_id,
            cwd=cwd,
            session_host=session_host,
        )


__all__ = [
    "ClaudeCodeDispatcher",
    "CodexCodeDispatcher",
    "GeminiCodeDispatcher",
    "LLMCodeDispatcher",
    "GrokCodeDispatcher",
    "MoonshotCodeDispatcher",
    "ZaiCodeDispatcher",
    "DevLoopCodeDispatcher",
    "DispatchExecutionError",
    "DispatchOutputValidationError",
]
