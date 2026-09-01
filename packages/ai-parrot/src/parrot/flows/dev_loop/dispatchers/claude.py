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
import json
import logging
import os
import time
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Type

from pydantic import BaseModel, ValidationError

from parrot import conf
from parrot.clients.claude_agent import ClaudeAgentRunOptions
from parrot.clients.factory import LLMFactory
from parrot.core.events.lifecycle import TraceContext
from parrot.core.events.lifecycle.events.client import (
    AfterClientCallEvent,
    ClientCallFailedEvent,
)
from parrot.flows.dev_loop._subagent_defs import load_subagent_definition
from parrot.flows.dev_loop.dispatchers._shared import (
    _SESSION_HOST_CTX,
    DispatchExecutionError,
    DispatchOutputValidationError,
    T,
    _apply_to_session_host,
)
from parrot.flows.dev_loop.models import ClaudeCodeDispatchProfile, DispatchEvent
from parrot.flows.dev_loop.session_state import SessionHost
from parrot.observability.context import usage_attribution

if TYPE_CHECKING:  # pragma: no cover - typing only
    from claude_agent_sdk.types import AgentDefinition  # noqa: F401

    from parrot.core.events.lifecycle import EventRegistry

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
        self._cached_dispatch_env: Optional[Dict[str, str]] = None
        self._client_cache: Dict[str, Any] = {}  # model -> ClaudeAgentClient
        # FEAT-479 M6: resolves run_id -> the run's per-run EventRegistry, so
        # this out-of-process dispatcher's harvested usage can be emitted as
        # an AfterClientCallEvent on the exact registry the ledger listens
        # on. None (default) when no owner (e.g. DevLoopRunner) has wired
        # one in — see set_event_registry_resolver. Same shape as
        # LLMCodeDispatcher's resolver (dispatchers/llm.py) so DevLoopRunner
        # wires both identically via one hasattr-guarded call.
        self._event_registry_resolver: Optional[Callable[[str], Optional[EventRegistry]]] = None

    def set_event_registry_resolver(self, resolver: Callable[[str], Optional[EventRegistry]]) -> None:
        """Wire a ``run_id -> EventRegistry`` lookup (FEAT-479 M6).

        Called once by the owning :class:`DevLoopRunner` so harvested usage
        can be emitted on the run's per-run registry (§2 Exactness).

        Args:
            resolver: A callable returning the live :class:`EventRegistry`
                for a given ``run_id``, or ``None`` if that run has no
                tracked registry.
        """
        self._event_registry_resolver = resolver

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
                # A JSON-schema path is intentionally never generated for
                # this dispatcher: the SDK's subprocess transport pins
                # ``--output-format stream-json`` / ``--input-format
                # stream-json`` itself, so passing
                # ``extra_args={"output-format": "json", ...}`` causes a
                # CLI-level conflict. Output validation falls back to
                # best-effort JSON parsing of the final assistant text
                # (spec §7 R2).
                run_options = self._resolve_run_options(profile, cwd)

                cache_key = profile.model or ""
                client = self._client_cache.get(cache_key)
                if client is None:
                    client = LLMFactory.create(f"claude-agent:{profile.model}")
                    self._client_cache[cache_key] = client

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
                    # FEAT-479 M6: every failure branch, not only the
                    # success path, must reach the ledger — with the
                    # error and whatever tokens were burned before it.
                    await self._emit_failure_event(
                        messages,
                        run_id=run_id,
                        node_id=node_id,
                        profile=profile,
                        error_type="TimeoutError",
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
                    await self._emit_failure_event(
                        messages,
                        run_id=run_id,
                        node_id=node_id,
                        profile=profile,
                        error_type=type(exc).__name__,
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
                    await self._emit_failure_event(
                        messages,
                        run_id=run_id,
                        node_id=node_id,
                        profile=profile,
                        error_type="ResultError",
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
                    await self._emit_failure_event(
                        messages,
                        run_id=run_id,
                        node_id=node_id,
                        profile=profile,
                        error_type=type(exc).__name__,
                    )
                    raise

                completed_payload: Dict[str, Any] = {
                    "output_model": output_model.__name__,
                }
                usage_detail = self._extract_result_usage(messages)
                if usage_detail:
                    completed_payload["usage"] = usage_detail
                await self._publish_event(
                    stream_key,
                    kind="dispatch.completed",
                    run_id=run_id,
                    node_id=node_id,
                    payload=completed_payload,
                )
                # FEAT-479 M6: route out-of-process usage through the same
                # accounting path as in-process AbstractClient calls. seat=
                # node_id, which is "development.w1" for a pool worker — a
                # free string, so no NodeId widening is needed (Finding 3).
                # No harvest -> no event: "—" in the report is honest, a
                # fabricated 0 is not.
                await self._emit_usage_event(
                    usage_detail,
                    run_id=run_id,
                    node_id=node_id,
                    profile=profile,
                )
                return result
            finally:
                _SESSION_HOST_CTX.reset(_host_token)

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

        A second, narrower waiver: a profile with
        ``allow_project_root_cwd=True`` may run at EXACTLY
        ``conf.PROJECT_ROOT``. That is the base checkout, which is the
        legitimate workspace for a dispatch that authors and commits on the
        base branch before any feature worktree exists (``IdeationNode``).

        Raises:
            DispatchExecutionError: when the path check fails.
        """
        if profile is not None and _claude_profile_is_read_only(profile):
            return
        target = os.path.abspath(cwd)
        if (
            profile is not None
            and getattr(profile, "allow_project_root_cwd", False)
            and target == os.path.abspath(str(conf.PROJECT_ROOT))
        ):
            return
        base = os.path.abspath(conf.WORKTREE_BASE_PATH)
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
            # FEAT-482 Module 6: explicit MCP servers (e.g. the read-only
            # wikitoolkit graph-search server for the ideation dispatch).
            # None (default) => ClaudeAgentRunOptions.mcp_servers is None,
            # byte-identical to pre-Module-6 behavior.
            mcp_servers=profile.mcp_servers,
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

        The result is cached on the instance: the auth policy and the
        credentials file are both stable for the lifetime of the server
        process, so re-reading the file on every dispatch is pure waste
        (and noisy — the DEBUG log fires once per dispatch).

        Returns a dict suitable for ``ClaudeAgentRunOptions.env``; empty
        means "inherit the parent environment unchanged".
        """
        if self._cached_dispatch_env is not None:
            return self._cached_dispatch_env

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
                env = {"ANTHROPIC_API_KEY": ""}
            else:
                chosen = "api-key (no subscription login detected)"
                env = {}
        self.logger.debug("Dispatch auth resolved: %s", chosen)
        self._cached_dispatch_env = env
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
    def _extract_result_usage(messages: List[Any]) -> Optional[Dict[str, Any]]:
        """Return telemetry (tokens/cost/turns/duration) from the terminal
        ``ResultMessage``, if any.

        Spec §3 Module 8 (v0.2 amendment): the dispatcher already mines the
        terminal ``ResultMessage`` for error diagnosis
        (:meth:`_extract_result_error`) but discards its telemetry on the
        success path. This helper duck-types the same reverse-scan pattern
        to also surface ``usage`` (tokens), ``total_cost_usd``, ``num_turns``
        and ``duration_ms`` for the run bundle (TASK-1928/1929).

        ``usage`` may arrive as a dict (the Claude Agent SDK's
        ``ResultMessage.usage`` shape) or as an object with attributes —
        both are supported. Never raises: a malformed/absent usage payload
        must not fail a dispatch that otherwise succeeded.

        Returns:
            A dict with any of ``input_tokens``, ``output_tokens``,
            ``cache_creation_input_tokens``, ``cache_read_input_tokens``,
            ``total_cost_usd``, ``num_turns``, ``duration_ms`` present
            (only non-``None`` keys are included), or ``None`` when no
            terminal ``ResultMessage`` is found or nothing could be
            extracted.
        """
        for msg in reversed(messages):
            if not hasattr(msg, "is_error"):
                continue
            try:
                usage = getattr(msg, "usage", None)

                def _usage_get(key: str) -> Any:
                    if usage is None:
                        return None
                    if isinstance(usage, dict):
                        return usage.get(key)
                    return getattr(usage, key, None)

                detail: Dict[str, Any] = {
                    "input_tokens": _usage_get("input_tokens"),
                    "output_tokens": _usage_get("output_tokens"),
                    "cache_creation_input_tokens": _usage_get("cache_creation_input_tokens"),
                    "cache_read_input_tokens": _usage_get("cache_read_input_tokens"),
                    "total_cost_usd": getattr(msg, "total_cost_usd", None),
                    "num_turns": getattr(msg, "num_turns", None),
                    "duration_ms": getattr(msg, "duration_ms", None),
                }
            except Exception:  # noqa: BLE001 — telemetry must never break dispatch
                return None
            detail = {k: v for k, v in detail.items() if v is not None}
            return detail or None
        return None

    async def _emit_usage_event(
        self,
        usage_detail: Optional[Dict[str, Any]],
        *,
        run_id: str,
        node_id: str,
        profile: ClaudeCodeDispatchProfile,
    ) -> None:
        """Emit an ``AfterClientCallEvent`` from harvested terminal usage.

        FEAT-479 Module 6. This dispatcher runs out of process — there is
        no ``AbstractClient`` and none of ``clients/base.py``'s lifecycle
        emission happens. Routes the harvested
        :meth:`_extract_result_usage` payload through the same accounting
        path in-process clients use, so pool-worker seats
        (``node_id="development.w1"``) and this backend's real model reach
        the per-run ledger instead of being silently dropped (spec
        Findings 3 and 4's model gap).

        No-ops when there is nothing to report (no harvest, or no
        registry resolver wired) — never fabricates zeros, and never lets
        a telemetry failure break the dispatch.

        Forwards to the global registry explicitly after the awaited
        per-run emit, mirroring ``AbstractClient._emit_after_call``
        (``clients/base.py:634``) — this run's per-run registry is
        constructed with ``forward_to_global=False`` (matching a client's
        own default), so global OTel/usage-recorder visibility for this
        out-of-process backend depends entirely on this explicit call.
        """
        if not usage_detail or self._event_registry_resolver is None:
            return
        registry = self._event_registry_resolver(run_id)
        if registry is None:
            return
        try:
            with usage_attribution(run_id, seat=node_id):
                event = AfterClientCallEvent(
                    trace_context=TraceContext.new_root(),
                    client_name="claude-code",
                    model=profile.model or "",
                    duration_ms=float(usage_detail.get("duration_ms") or 0.0),
                    input_tokens=usage_detail.get("input_tokens"),
                    output_tokens=usage_detail.get("output_tokens"),
                    source_type="dispatcher",
                    source_name="claude-code",
                )
                await registry.emit(event)
                registry.forward_to_global(event)
        except Exception:  # telemetry must never break dispatch
            self.logger.warning(
                "Failed to emit AfterClientCallEvent for run=%s node=%s",
                run_id,
                node_id,
                exc_info=True,
            )

    async def _emit_failure_event(
        self,
        messages: List[Any],
        *,
        run_id: str,
        node_id: str,
        profile: ClaudeCodeDispatchProfile,
        error_type: str,
    ) -> None:
        """Route a failed dispatch through the same accounting path as a
        successful one (FEAT-479 M6 extension — every failure branch of
        this dispatcher's ``dispatch()`` calls this, not only the
        success path).

        First harvests whatever usage the buffered ``messages`` report
        (often partial or none for a true timeout — a dispatch that
        raised before receiving any terminal ``ResultMessage``) via
        :meth:`_emit_usage_event`, then emits a ``ClientCallFailedEvent``
        for the failure itself. Two ledger records rather than one:
        ``ClientCallFailedEvent`` structurally carries no token fields
        (spec's privacy contract — only ``error_type``, the exception
        class name, never a message), so "tokens burned before failing"
        is represented by the harvested cycle, and "what failed" by this
        one. Never lets a telemetry failure break the dispatch.
        """
        usage_detail = self._extract_result_usage(messages)
        await self._emit_usage_event(
            usage_detail,
            run_id=run_id,
            node_id=node_id,
            profile=profile,
        )
        if self._event_registry_resolver is None:
            return
        registry = self._event_registry_resolver(run_id)
        if registry is None:
            return
        try:
            with usage_attribution(run_id, seat=node_id):
                event = ClientCallFailedEvent(
                    trace_context=TraceContext.new_root(),
                    client_name="claude-code",
                    model=profile.model or "",
                    error_type=error_type,
                )
                await registry.emit(event)
                registry.forward_to_global(event)
        except Exception:  # telemetry must never break dispatch
            self.logger.warning(
                "Failed to emit ClientCallFailedEvent for run=%s node=%s",
                run_id,
                node_id,
                exc_info=True,
            )

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

        Each event carries structured metadata so the live stream shows
        *what* happened (tool name, text snippet), not just the message
        class.
        """
        kind = "dispatch.message"
        payload: Dict[str, Any] = {
            "message_class": type(message).__name__,
        }
        content = getattr(message, "content", None)
        if isinstance(content, list):
            tool_names: List[str] = []
            text_snippet = ""
            for block in content:
                cls_name = type(block).__name__
                if cls_name == "ToolUseBlock":
                    kind = "dispatch.tool_use"
                    name = getattr(block, "name", None)
                    if name:
                        tool_names.append(name)
                elif cls_name == "ToolResultBlock":
                    kind = "dispatch.tool_result"
                    name = getattr(block, "tool_use_id", None) or getattr(block, "name", None)
                    if name:
                        tool_names.append(name)
                elif cls_name == "TextBlock" and not text_snippet:
                    raw = getattr(block, "text", "") or ""
                    if raw:
                        text_snippet = raw[:200]
            if tool_names:
                payload["tools"] = tool_names
            if text_snippet:
                payload["text"] = text_snippet
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
