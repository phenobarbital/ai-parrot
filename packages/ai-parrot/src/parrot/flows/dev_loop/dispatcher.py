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
import tempfile
import time
from typing import (
    Any,
    Dict,
    List,
    Optional,
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
    DispatchEvent,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from claude_agent_sdk.types import AgentDefinition  # noqa: F401

T = TypeVar("T", bound=BaseModel)


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

        # Spec §7 R4 — defense in depth.
        self._enforce_cwd_under_worktree_base(cwd)

        await self._publish_event(
            stream_key,
            kind="dispatch.queued",
            run_id=run_id,
            node_id=node_id,
            payload={"profile": profile.model_dump(mode="json")},
        )

        async with self._semaphore:
            try:
                # Materialize the JSON schema for the structured-output flag.
                json_schema_path = self._materialize_json_schema(output_model)
                run_options = self._resolve_run_options(
                    profile, cwd, json_schema_path=json_schema_path
                )

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
                    async for msg in client.ask_stream(
                        prompt, options=run_options
                    ):
                        messages.append(msg)
                        await self._publish_message_event(
                            stream_key, msg, run_id, node_id
                        )
                except Exception as exc:  # session failure
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
                    self.logger.exception(
                        "Dispatch session failure for run=%s node=%s",
                        run_id,
                        node_id,
                    )
                    raise DispatchExecutionError(
                        f"ClaudeAgentClient.ask_stream raised: {exc}"
                    ) from exc

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
                if json_schema_path is not None:
                    try:
                        os.unlink(json_schema_path)
                    except OSError:  # pragma: no cover - best effort
                        pass

    # ------------------------------------------------------------------
    # Internal helpers (underscored — but accessible to unit tests)
    # ------------------------------------------------------------------

    def _enforce_cwd_under_worktree_base(self, cwd: str) -> None:
        """Spec §7 R4: refuse dispatch when ``cwd`` is not in worktree base.

        Raises:
            DispatchExecutionError: when the path check fails.
        """
        base = os.path.abspath(conf.WORKTREE_BASE_PATH)
        target = os.path.abspath(cwd)
        try:
            common = os.path.commonpath([base, target])
        except ValueError:
            common = ""
        if common != base:
            raise DispatchExecutionError(
                f"cwd {cwd!r} is not under WORKTREE_BASE_PATH={base!r}"
            )

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
        """
        self._enforce_cwd_under_worktree_base(cwd)

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

        extra_args: Optional[Dict[str, Optional[str]]] = None
        if json_schema_path is not None:
            extra_args = {
                "output-format": "json",
                "json-schema": json_schema_path,
            }

        return ClaudeAgentRunOptions(
            cwd=cwd,
            permission_mode=profile.permission_mode,
            allowed_tools=list(profile.allowed_tools) or None,
            agents=agents_dict,
            setting_sources=list(profile.setting_sources)
            if profile.setting_sources
            else None,
            extra_args=extra_args,
            system_prompt=system_prompt,
            model=profile.model,
        )

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

    def _build_prompt(
        self, brief: BaseModel, output_model: Type[BaseModel]
    ) -> str:
        """Compose the prompt body for a dispatch.

        The brief is JSON-encoded so the subagent gets a structured input;
        an explicit instruction line tells the subagent to respond with a
        JSON object matching ``output_model``.
        """
        brief_json = brief.model_dump_json()
        return (
            f"Input brief:\n{brief_json}\n\n"
            f"Respond with a single JSON object matching the "
            f"`{output_model.__name__}` schema. Do not wrap the JSON in "
            f"markdown fences and do not add prose around it."
        )

    def _validate_output(
        self, messages: List[Any], output_model: Type[T]
    ) -> T:
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
            await redis_client.xadd(
                stream_key, fields, maxlen=maxlen, approximate=True
            )
        except Exception as exc:  # pragma: no cover - best-effort publish
            self.logger.warning(
                "Failed to XADD %s to %s: %s", kind, stream_key, exc
            )

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
        payload = {
            "message_class": type(message).__name__,
        }
        await self._publish_event(
            stream_key,
            kind=kind,
            run_id=run_id,
            node_id=node_id,
            payload=payload,
        )


__all__ = [
    "ClaudeCodeDispatcher",
    "DispatchExecutionError",
    "DispatchOutputValidationError",
]
