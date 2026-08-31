"""LLMCodeDispatcher — local coding-agent loop for OpenAI-compatible clients.

CLI-backed dispatchers (Claude, Codex, Gemini) delegate filesystem and
command execution to their external runtime. This dispatcher keeps that
runtime in-process: the model drives a local tool loop (read/write/edit/
run_command) against ``cwd`` via any OpenAI-compatible ``AbstractClient``
resolved through :class:`parrot.clients.factory.LLMFactory`. Backend-
specific dispatchers (Grok, Z.ai, Moonshot) subclass this to reuse the
loop, Redis event streaming, cwd-safety guard, and output validation.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shlex
import time
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Sequence, Type

from pydantic import BaseModel, ValidationError

from parrot import conf
from parrot.clients.factory import LLMFactory
from parrot.flows.dev_loop._subagent_defs import load_subagent_definition
from parrot.flows.dev_loop.dispatchers._shared import (
    T,
    _SESSION_HOST_CTX,
    _apply_to_session_host,
    DispatchExecutionError,
    DispatchOutputValidationError,
)
from parrot.flows.dev_loop.dispatchers.claude import ClaudeCodeDispatcher
from parrot.flows.dev_loop.models import DispatchEvent, LLMCodeDispatchProfile
from parrot.flows.dev_loop.session_state import SessionHost
from parrot.models.basic import CompletionUsage
from parrot.observability.context import usage_attribution

if TYPE_CHECKING:
    from parrot.core.events.lifecycle import EventRegistry


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
        # FEAT-479 M5: resolves run_id -> the run's per-run EventRegistry, so
        # constructed clients emit on it (exactness) instead of degrading to
        # fire-and-forget on a lazily self-created registry. None (default)
        # when no owner (e.g. DevLoopRunner) has wired one in — see
        # set_event_registry_resolver.
        self._event_registry_resolver: Optional[
            Callable[[str], Optional["EventRegistry"]]
        ] = None

    def set_event_registry_resolver(
        self, resolver: Callable[[str], Optional["EventRegistry"]]
    ) -> None:
        """Wire a ``run_id -> EventRegistry`` lookup (FEAT-479 M5).

        Called once by the owning :class:`DevLoopRunner` so
        :meth:`_create_client` can inject the run's per-run registry into
        every client it builds for that run, instead of letting the client
        lazily self-create an isolated one (which would degrade delivery to
        fire-and-forget — see spec §2 Exactness).

        Args:
            resolver: A callable returning the live :class:`EventRegistry`
                for a given ``run_id``, or ``None`` if that run has no
                tracked registry (e.g. never wired, or already closed).
        """
        self._event_registry_resolver = resolver

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
        # FEAT-479 M5: bind run/seat attribution for the whole dispatch —
        # UsageRecordingSubscriber._on_client_after reads these ContextVars
        # when the per-run registry's emit() invokes it synchronously.
        # `node_id` IS the seat here: DevAgentPool already passes
        # "development.w1"-style worker ids as `node_id` (agent_pool.py).
        with usage_attribution(run_id, node_id):
            client = self._create_client(profile, run_id=run_id)
            await self._ensure_client_ready(client)
            model = self._resolve_model(profile, client)
            messages = self._initial_messages(profile, brief, output_model)
            tools = self._tool_schemas(output_model)
            args = self._completion_args(profile, tools)

            # FEAT-405 Module 6: drive the same FEAT-397 emitter trio every
            # client's own ask() loop uses. This loop never calls ask(), so
            # without this, per-round usage/telemetry never reaches the
            # dev-loop dispatch path for ANY backend (nvidia/zai/moonshot/grok/
            # nova all report None tokens otherwise). Underscore-private
            # methods — a deliberate, documented choice at the same level of
            # intimacy this loop already has with client._chat_completion
            # below. Per-round events are still one-per-round and are NOT
            # summed for that purpose. FEAT-479 additionally accumulates a
            # per-call total here (via ``CompletionUsage.__add__``) solely to
            # populate the awaited ``AfterClientCallEvent`` — see
            # sdd/specs/devflow-telemetry-accounting.spec.md §3 Module 3 for
            # why FEAT-405 R4 is deliberately overridden on this path.
            tc = self._safe_emit_before_call(client, model=model, has_tools=bool(tools))
            loop_t0 = time.perf_counter()
            accumulated: Optional[CompletionUsage] = None  # LOCAL, never self.*
            try:
                for turn_index in range(profile.max_turns):
                    round_t0 = time.perf_counter()
                    response = await self._chat_completion(
                        client=client,
                        model=model,
                        messages=messages,
                        args=args,
                    )
                    round_duration_ms = (time.perf_counter() - round_t0) * 1000
                    message = self._response_message(response)
                    content = self._message_content(message)
                    tool_calls = self._message_tool_calls(message)
                    usage, raw_usage = self._extract_usage(response)
                    if usage is not None:
                        accumulated = usage if accumulated is None else accumulated + usage
                    self._safe_emit_round_event(
                        client,
                        tc,
                        model=model,
                        round_number=turn_index + 1,
                        usage=usage,
                        raw_usage=raw_usage,
                        tool_calls=[self._tool_call_name(call) for call in tool_calls],
                        duration_ms=round_duration_ms,
                    )

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
            finally:
                await self._safe_emit_after_call(
                    client,
                    tc,
                    model=model,
                    duration_ms=(time.perf_counter() - loop_t0) * 1000,
                    input_tokens=accumulated.prompt_tokens if accumulated else None,
                    output_tokens=accumulated.completion_tokens if accumulated else None,
                )

    def _create_client(
        self, profile: LLMCodeDispatchProfile, *, run_id: Optional[str] = None
    ) -> Any:
        model_args = {
            "temperature": profile.temperature,
            "max_tokens": profile.max_tokens,
        }
        client = self._client_factory(profile.llm, model_args=model_args)
        # FEAT-479 M5: thread the run's per-run EventRegistry into the
        # constructed client so its `await self.events.emit(...)` calls
        # (clients/base.py:630) reach the run's ledger subscriber
        # synchronously (exactness) instead of the client lazily
        # self-creating its own isolated registry (mixin.py:113), which
        # would degrade delivery to fire-and-forget. §8 open question,
        # resolved: LLMFactory.create / _client_factory does NOT propagate
        # any registry — verified by reading factory.py's signature and
        # AbstractClient.__init__ (clients/base.py:372), which
        # unconditionally calls `self._init_events(forward_to_global=False)`,
        # always constructing a fresh, isolated registry. Threading it
        # explicitly here, post-construction, is therefore required.
        if run_id is not None and self._event_registry_resolver is not None:
            registry = self._event_registry_resolver(run_id)
            if registry is not None and hasattr(client, "_events_registry"):
                client._events_registry = registry  # the documented injection point
        return client

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

    # ------------------------------------------------------------------
    # FEAT-405 Module 6: per-round telemetry — the FEAT-397 emitter trio,
    # driven from this loop instead of a client's ask(). Every "_safe_"
    # method here tolerates a client that lacks the emitter methods (a
    # test double, a non-AbstractClient) — dispatch must keep working
    # either way, in the same spirit as the `_chat_completion` guard
    # above. NO accumulation anywhere in this file — one event per round.
    # ------------------------------------------------------------------

    @staticmethod
    def _client_display_name(client: Any) -> str:
        """Best-effort provider identifier for the emitted events."""
        return str(getattr(client, "client_name", None) or getattr(client, "client_type", None) or "unknown")

    def _safe_emit_before_call(self, client: Any, *, model: str, has_tools: bool) -> Any:
        """Call ``client._emit_before_call`` if the client exposes it.

        Returns the ``TraceContext`` it returns, or ``None`` when the
        client has no emitter methods — every other ``_safe_emit_*``
        method below treats ``None`` as "nothing to do".
        """
        method = getattr(client, "_emit_before_call", None)
        if not callable(method):
            return None
        return method(
            client_name=self._client_display_name(client),
            model=model,
            has_tools=has_tools,
        )

    def _safe_emit_round_event(
        self,
        client: Any,
        tc: Any,
        *,
        model: str,
        round_number: int,
        usage: Optional[CompletionUsage],
        raw_usage: Optional[Dict[str, Any]],
        tool_calls: List[str],
        duration_ms: float,
    ) -> None:
        """Call ``client._emit_round_event`` for one turn of the loop.

        ``round_number`` is 1-indexed. ``usage``/``raw_usage`` may be
        ``None`` — legal per the trio's own contract. No-op when ``tc`` is
        ``None`` (client had no emitter methods) or the client lacks
        ``_emit_round_event`` specifically.
        """
        if tc is None:
            return
        method = getattr(client, "_emit_round_event", None)
        if not callable(method):
            return
        method(
            tc,
            client_name=self._client_display_name(client),
            model=model,
            round_number=round_number,
            usage=usage,
            raw_usage=raw_usage,
            tool_calls=tool_calls,
            duration_ms=duration_ms,
        )

    async def _safe_emit_after_call(
        self,
        client: Any,
        tc: Any,
        *,
        model: str,
        duration_ms: float,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
    ) -> None:
        """Call ``client._emit_after_call`` once, at the end of the dispatch.

        ``input_tokens``/``output_tokens`` (FEAT-479) carry the per-call
        total accumulated across the turn loop via
        ``CompletionUsage.__add__`` — see the accumulation comment at the
        top of :meth:`_dispatch_loop`. ``None`` means no round reported
        usage; never fabricate ``0``.
        """
        if tc is None:
            return
        method = getattr(client, "_emit_after_call", None)
        if not callable(method):
            return
        await method(
            tc,
            client_name=self._client_display_name(client),
            model=model,
            duration_ms=duration_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    @staticmethod
    def _extract_usage(response: Any) -> tuple[Optional[CompletionUsage], Optional[Dict[str, Any]]]:
        """Extract this turn's usage from an OpenAI-shaped completion response.

        Defensive: providers differ in whether/how they report usage on
        each turn. Returns ``(None, None)`` when absent — legal per
        ``_emit_round_event``'s contract, never raises.
        """
        usage_obj = getattr(response, "usage", None)
        if usage_obj is None:
            return None, None
        if hasattr(usage_obj, "model_dump"):
            raw_usage: Dict[str, Any] = usage_obj.model_dump()
        elif isinstance(usage_obj, dict):
            raw_usage = dict(usage_obj)
        else:
            raw_usage = {
                "prompt_tokens": getattr(usage_obj, "prompt_tokens", None),
                "completion_tokens": getattr(usage_obj, "completion_tokens", None),
                "total_tokens": getattr(usage_obj, "total_tokens", None),
            }
        try:
            usage = CompletionUsage.from_openai(usage_obj)
        except Exception:  # noqa: BLE001 - usage extraction must never break dispatch
            usage = None
        return usage, raw_usage

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
                limit=8 * 1024 * 1024,
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

