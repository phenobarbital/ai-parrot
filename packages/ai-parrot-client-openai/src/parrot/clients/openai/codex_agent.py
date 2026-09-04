from __future__ import annotations

import asyncio
import contextlib
import json
import os
import subprocess
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, AsyncIterator, Literal, Optional

from pydantic import BaseModel

from parrot.clients.base import AbstractClient, MessageResponse
from parrot.clients.openai.models import OpenAIModel
from parrot.exceptions import InvokeError
from parrot.models import AIMessage, StructuredOutputConfig
from parrot.models.basic import CompletionUsage, ToolCall
from parrot.models.responses import InvokeResult

if TYPE_CHECKING:  # pragma: no cover - typing only
    from parrot.clients.openai.codex_tool_bridge import CodexToolBridge


Backend = Literal["auto", "sdk", "cli"]

#: Placeholder cached by ``AbstractClient`` when the CLI backend is active.
#: The CLI path owns its own lifecycle, so no SDK object is ever needed —
#: see :meth:`OpenAICodexClient.get_client`.
_CLI_BACKEND_HANDLE = object()
SandboxMode = Literal["read-only", "workspace-write", "danger-full-access"]
ApprovalPolicy = Literal["untrusted", "on-request", "never"]


@dataclass(slots=True)
class CodexAgentRunOptions:
    """Per-run options for :class:`OpenAICodexClient`."""

    backend: Backend = "auto"
    model: Optional[str] = None
    cwd: Optional[str] = None
    codex_bin: str = "codex"
    sandbox: SandboxMode = "read-only"
    approval_policy: ApprovalPolicy = "never"
    expose_parrot_tools: bool = True
    tool_bridge_name: str = "ai_parrot"
    tool_bridge_max_tools: Optional[int] = None
    tool_bridge_tool_names: Optional[list[str]] = None
    ephemeral: bool = False
    ignore_user_config: bool = False
    ignore_rules: bool = False
    extra_args: list[str] = field(default_factory=list)
    extra_config: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class _CodexRunResult:
    output: str
    model: str
    usage: CompletionUsage
    raw_events: list[dict[str, Any]]
    session_id: Optional[str] = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: Optional[str] = None


class OpenAICodexClient(AbstractClient):
    """ai-parrot LLM client backed by OpenAI Codex credentials/runtime.

    The preferred path uses the optional ``openai-codex`` SDK when installed.
    A verified ``codex exec`` backend is kept as a fallback so existing Codex
    CLI credentials can be reused without reading credential files directly.
    """

    client_type = "openai_codex"
    client_name = "openai-codex"
    default_model = "gpt-5.1-codex"
    use_session = False

    # FEAT-523 folder-convention attributes (read by LLMFactory).
    provider_keys: tuple[str, ...] = ("codex-agent", "openai-codex", "codex-code")
    models: type[Enum] = OpenAIModel

    def __init__(
        self,
        *,
        model: Optional[str] = None,
        run_options: Optional[CodexAgentRunOptions | dict[str, Any]] = None,
        backend: Backend = "auto",
        codex_bin: str = "codex",
        **kwargs: Any,
    ) -> None:
        super().__init__(model=model or self.default_model, **kwargs)
        self.run_options = self._coerce_run_options(run_options)
        self.run_options.backend = backend
        self.run_options.codex_bin = codex_bin

    async def get_client(self) -> Any:
        """Return the SDK client, or an inert handle for the CLI backend.

        With ``backend="cli"`` there is no SDK client to build: ``ask()``
        drives the ``codex`` binary itself and never touches the cached
        handle (``AbstractClient`` only stores it per event loop). Importing
        the SDK here would make the CLI backend depend on the very package
        it exists to avoid — which is what happened to every caller that
        goes through ``async with client`` instead of ``complete()``, e.g.
        an agent turn via ``execute_llm_call()``.

        Returns:
            The ``AsyncCodex`` SDK client, or ``_CLI_BACKEND_HANDLE`` when
            running the CLI backend.
        """
        if self.run_options.backend == "cli":
            return _CLI_BACKEND_HANDLE
        sdk = self._import_sdk()
        return sdk.AsyncCodex()

    async def ask(
        self,
        prompt: str,
        model: Optional[str] = None,
        *,
        run_options: Optional[CodexAgentRunOptions | dict[str, Any]] = None,
        use_tools: Optional[bool] = None,
        system_prompt: Optional[str] = None,
        parent_trace: Optional[Any] = None,
        **kwargs: Any,
    ) -> AIMessage:
        del kwargs
        effective = self._effective_run_options(run_options, model=model)
        if use_tools is not None:
            effective.expose_parrot_tools = use_tools
        full_prompt = self._compose_prompt(prompt, system_prompt)
        started = time.perf_counter()
        trace = self._emit_before_call(
            client_name=self.client_name,
            model=effective.model or self.model,
            system_prompt=system_prompt,
            has_tools=effective.expose_parrot_tools,
            parent_trace=parent_trace,
        )
        try:
            result = await self._run_codex(full_prompt, effective)
        except Exception as exc:
            await self._emit_failed_call(
                trace,
                client_name=self.client_name,
                model=effective.model or self.model,
                duration_ms=(time.perf_counter() - started) * 1000,
                exc=exc,
            )
            raise

        duration = time.perf_counter() - started
        await self._emit_after_call(
            trace,
            client_name=self.client_name,
            model=result.model,
            duration_ms=duration * 1000,
            input_tokens=result.usage.prompt_tokens,
            output_tokens=result.usage.completion_tokens,
            finish_reason=result.finish_reason,
        )
        return self._to_ai_message(prompt, result, duration)

    async def ask_stream(
        self,
        prompt: str,
        **kwargs: Any,
    ) -> AsyncIterator[str | AIMessage]:
        message = await self.ask(prompt, **kwargs)
        if message.response:
            yield message.response
        yield message

    async def complete(
        self,
        prompt: str,
        *,
        model: Optional[str] = None,
        system_prompt: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> str:
        """Return a plain-text Codex reply without forcing SDK initialization.

        The base ``AbstractClient.complete()`` enters the SDK client before
        calling ``ask()``. That is useful for HTTP SDK clients, but it defeats
        this client's CLI fallback because ``__aenter__`` would import
        ``openai-codex`` even when ``backend="cli"``. ``ask()`` already owns
        the backend-specific lifecycle, so this wrapper delegates directly.
        """
        response = await self.ask(
            prompt=prompt,
            model=model,
            system_prompt=system_prompt,
            max_tokens=max_tokens or 4096,
            temperature=temperature if temperature is not None else 0.7,
        )
        text = self._extract_text(response)
        if not text:
            raise RuntimeError(
                f"LLM returned no extractable text "
                f"(response type: {type(response).__name__})"
            )
        return text

    async def resume(
        self,
        session_id: str,
        user_input: str,
        state: dict[str, Any],
    ) -> MessageResponse:
        del state
        effective = self._effective_run_options(None, model=None)
        result = await self._run_codex(user_input, effective, session_id=session_id)
        return {
            "id": result.session_id or session_id,
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": result.output}],
            "model": result.model,
            "stop_reason": result.finish_reason,
            "stop_sequence": None,
            "usage": result.usage.model_dump(),
        }

    async def invoke(
        self,
        prompt: str,
        *,
        output_type: Optional[type] = None,
        structured_output: Optional[StructuredOutputConfig] = None,
        model: Optional[str] = None,
        system_prompt: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: float = 0.0,
        use_tools: bool = False,
        tools: Optional[list[Any]] = None,
    ) -> InvokeResult:
        # Codex runs through `codex exec`, which has no max_tokens knob — the
        # argument is accepted for AbstractClient parity and deliberately
        # dropped here, so there is no budget to resolve.
        del max_tokens, temperature, tools
        resolved_model = self._resolve_invoke_model(model)
        structured_config = self._build_invoke_structured_config(
            output_type,
            structured_output,
        )
        full_prompt = self._compose_prompt(
            prompt,
            self._resolve_invoke_system_prompt(system_prompt),
        )
        effective = self._effective_run_options(
            None,
            model=resolved_model,
        )
        effective.expose_parrot_tools = use_tools

        schema_path: Optional[str] = None
        try:
            if structured_config is not None and structured_config.output_type is not None:
                schema_path = self._write_output_schema(structured_config.output_type)
            result = await self._run_codex(
                full_prompt,
                effective,
                output_schema_path=schema_path,
            )
            parsed: Any = result.output
            if structured_config is not None:
                parsed = await self._parse_structured_output(
                    result.output,
                    structured_config,
                    finish_reason=result.finish_reason,
                    model=resolved_model,
                )
            return InvokeResult(
                output=parsed,
                output_type=output_type,
                model=result.model,
                usage=result.usage,
                raw_response=result.raw_events,
            )
        except Exception as exc:  # noqa: BLE001
            if isinstance(exc, InvokeError):
                raise
            raise InvokeError(
                f"OpenAICodexClient.invoke failed: {exc}",
                original=exc,
            ) from exc
        finally:
            if schema_path:
                with contextlib.suppress(FileNotFoundError):
                    os.unlink(schema_path)

    async def batch_ask(self, requests: list[Any], **kwargs: Any) -> list[Any]:
        del requests, kwargs
        raise NotImplementedError("OpenAICodexClient does not support batch processing.")

    async def _run_codex(
        self,
        prompt: str,
        options: CodexAgentRunOptions,
        *,
        output_schema_path: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> _CodexRunResult:
        if options.backend in {"auto", "sdk"}:
            try:
                return await self._run_with_sdk(
                    prompt,
                    options,
                    output_schema_path=output_schema_path,
                    session_id=session_id,
                )
            except ImportError:
                if options.backend == "sdk":
                    raise
        return await self._run_with_cli(
            prompt,
            options,
            output_schema_path=output_schema_path,
            session_id=session_id,
        )

    async def _run_with_sdk(
        self,
        prompt: str,
        options: CodexAgentRunOptions,
        *,
        output_schema_path: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> _CodexRunResult:
        if output_schema_path is not None:
            raise NotImplementedError(
                "Structured Codex invoke currently uses the codex exec backend."
            )
        if session_id is not None:
            raise NotImplementedError(
                "OpenAI Codex SDK resume support is not wired in ai-parrot yet."
            )
        sdk = self._import_sdk()
        bridge = self._new_tool_bridge(options)
        async with self._maybe_started_bridge(bridge):
            async with sdk.AsyncCodex() as codex:
                thread = await codex.thread_start(model=options.model or self.model)
                result = await thread.run(prompt)
        text = self._get_attr(result, "final_response", "finalResponse", default="")
        return _CodexRunResult(
            output=str(text or ""),
            model=options.model or self.model,
            usage=self._usage_from_obj(self._get_attr(result, "usage", default=None)),
            raw_events=[self._json_safe(result)],
            session_id=str(self._get_attr(thread, "id", "thread_id", default="") or ""),
            finish_reason=str(self._get_attr(result, "finish_reason", default="stop")),
        )

    async def _run_with_cli(
        self,
        prompt: str,
        options: CodexAgentRunOptions,
        *,
        output_schema_path: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> _CodexRunResult:
        output_path = self._temp_path(".txt")
        bridge = self._new_tool_bridge(options)
        try:
            async with self._maybe_started_bridge(bridge) as active_bridge:
                command = self._build_cli_command(
                    prompt=prompt,
                    options=options,
                    output_path=output_path,
                    output_schema_path=output_schema_path,
                    session_id=session_id,
                    bridge_config=active_bridge.config if active_bridge else None,
                )
                stdout, stderr, return_code = await self._run_cli_command(
                    command,
                    prompt,
                )
            if return_code != 0:
                error_detail = stderr.strip() or "\n".join(
                    stdout.strip().splitlines()[-5:]
                )
                raise RuntimeError(
                    f"codex exec failed with exit code {return_code}: {error_detail}"
                )
            output = Path(output_path).read_text(encoding="utf-8").strip()
            return self._parse_cli_result(
                output=output,
                stdout=stdout,
                model=options.model or self.model,
            )
        finally:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(output_path)

    def _build_cli_command(
        self,
        *,
        prompt: str,
        options: CodexAgentRunOptions,
        output_path: str,
        output_schema_path: Optional[str] = None,
        session_id: Optional[str] = None,
        bridge_config: Optional[Any] = None,
    ) -> list[str]:
        command = [options.codex_bin, "exec", "--json"]
        if session_id:
            command.extend(["resume", session_id])
        cwd = options.cwd or os.getcwd()
        command.extend(["--cd", cwd])
        if options.model:
            command.extend(["--model", options.model])
        command.extend(["--sandbox", options.sandbox])
        command.extend(["-c", f"approval_policy={json.dumps(options.approval_policy)}"])
        if options.ephemeral:
            command.append("--ephemeral")
        if options.ignore_user_config:
            command.append("--ignore-user-config")
        if options.ignore_rules:
            command.append("--ignore-rules")
        if output_schema_path is not None:
            command.extend(["--output-schema", output_schema_path])
        command.extend(["-o", output_path])
        for key, value in options.extra_config.items():
            command.extend(["-c", f"{key}={json.dumps(value)}"])
        if bridge_config is not None:
            command.extend(bridge_config.to_codex_config_args())
        command.extend(options.extra_args)
        command.append("-")
        return command

    async def _run_cli_command(
        self,
        command: list[str],
        input_text: Optional[str] = None,
    ) -> tuple[str, str, int]:
        stdin = asyncio.subprocess.PIPE if input_text is not None else subprocess.DEVNULL
        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=stdin,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        input_bytes = input_text.encode("utf-8") if input_text is not None else None
        stdout_bytes, stderr_bytes = await process.communicate(input_bytes)
        return (
            stdout_bytes.decode("utf-8", errors="replace"),
            stderr_bytes.decode("utf-8", errors="replace"),
            int(process.returncode or 0),
        )

    def _parse_cli_result(
        self,
        *,
        output: str,
        stdout: str,
        model: str,
    ) -> _CodexRunResult:
        events = self._parse_jsonl(stdout)
        usage = CompletionUsage()
        session_id: Optional[str] = None
        finish_reason: Optional[str] = None
        tool_calls: list[ToolCall] = []
        fallback_output = output

        for event in events:
            event_type = event.get("type") or event.get("event")
            payload = event.get("item") or event
            if event_type in {"thread.started", "session.started"}:
                session_id = str(
                    event.get("thread_id")
                    or event.get("session_id")
                    or event.get("id")
                    or ""
                ) or session_id
            usage = self._usage_from_event(event) or usage
            if event_type in {"turn.completed", "response.completed"}:
                finish_reason = str(
                    event.get("finish_reason")
                    or event.get("stop_reason")
                    or "stop"
                )
            item_type = payload.get("type")
            if item_type == "agent_message":
                text = payload.get("text") or payload.get("message") or payload.get("content")
                if text:
                    fallback_output = str(text)
            if item_type in {"mcp_tool_call", "function_call"}:
                tool_calls.append(self._tool_call_from_event(payload))

        return _CodexRunResult(
            output=output or fallback_output,
            model=model,
            usage=usage,
            raw_events=events,
            session_id=session_id,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
        )

    def _to_ai_message(
        self,
        prompt: str,
        result: _CodexRunResult,
        duration: float,
    ) -> AIMessage:
        return AIMessage(
            input=prompt,
            output=result.output,
            response=result.output,
            model=result.model,
            provider=self.client_name,
            usage=result.usage,
            tool_calls=result.tool_calls,
            response_time=duration,
            session_id=result.session_id,
            finish_reason=result.finish_reason,
            raw_response={"events": result.raw_events},
        )

    def _new_tool_bridge(
        self,
        options: CodexAgentRunOptions,
    ) -> Optional["CodexToolBridge"]:
        if not options.expose_parrot_tools or self.tool_manager.tool_count() == 0:
            return None
        from parrot.clients.openai.codex_tool_bridge import CodexToolBridge

        return CodexToolBridge(
            self.tool_manager,
            permission_context=getattr(self, "_permission_context", None),
            name=options.tool_bridge_name,
            max_tools=options.tool_bridge_max_tools,
            tool_names=options.tool_bridge_tool_names,
        )

    @contextlib.asynccontextmanager
    async def _maybe_started_bridge(
        self,
        bridge: Optional["CodexToolBridge"],
    ) -> AsyncIterator[Optional["CodexToolBridge"]]:
        if bridge is None:
            yield None
            return
        async with bridge:
            yield bridge

    def _effective_run_options(
        self,
        run_options: Optional[CodexAgentRunOptions | dict[str, Any]],
        *,
        model: Optional[str],
    ) -> CodexAgentRunOptions:
        effective = self._coerce_run_options(self.run_options)
        override = self._coerce_run_options(run_options)
        for field_name in override.__dataclass_fields__:
            value = getattr(override, field_name)
            if value != getattr(CodexAgentRunOptions(), field_name):
                setattr(effective, field_name, value)
        if model is not None:
            effective.model = model
        elif effective.model is None:
            effective.model = self.model
        return effective

    @staticmethod
    def _coerce_run_options(
        run_options: Optional[CodexAgentRunOptions | dict[str, Any]],
    ) -> CodexAgentRunOptions:
        if run_options is None:
            return CodexAgentRunOptions()
        if isinstance(run_options, CodexAgentRunOptions):
            return CodexAgentRunOptions(**asdict(run_options))
        return CodexAgentRunOptions(**run_options)

    @staticmethod
    def _compose_prompt(prompt: str, system_prompt: Optional[str]) -> str:
        if not system_prompt:
            return prompt
        return f"{system_prompt.strip()}\n\n{prompt}"

    @staticmethod
    def _parse_jsonl(stdout: str) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for line in stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                events.append(event)
        return events

    @staticmethod
    def _tool_call_from_event(event: dict[str, Any]) -> ToolCall:
        arguments = event.get("arguments") or event.get("input") or {}
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {"raw": arguments}
        return ToolCall(
            id=str(event.get("id") or uuid.uuid4()),
            name=str(event.get("name") or event.get("tool_name") or "unknown_tool"),
            arguments=arguments,
            result=event.get("result"),
            error=event.get("error"),
        )

    @staticmethod
    def _usage_from_event(event: dict[str, Any]) -> Optional[CompletionUsage]:
        usage = event.get("usage")
        if not isinstance(usage, dict):
            payload = event.get("item")
            usage = payload.get("usage") if isinstance(payload, dict) else None
        if not isinstance(usage, dict):
            return None
        prompt_tokens = int(
            usage.get("prompt_tokens")
            or usage.get("input_tokens")
            or usage.get("tokens_in")
            or 0
        )
        completion_tokens = int(
            usage.get("completion_tokens")
            or usage.get("output_tokens")
            or usage.get("tokens_out")
            or 0
        )
        total_tokens = int(
            usage.get("total_tokens")
            or usage.get("tokens_total")
            or prompt_tokens + completion_tokens
        )
        return CompletionUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            extra_usage={"raw": usage},
        )

    def _usage_from_obj(self, usage: Any) -> CompletionUsage:
        if usage is None:
            return CompletionUsage()
        if isinstance(usage, dict):
            return self._usage_from_event({"usage": usage}) or CompletionUsage()
        return CompletionUsage(
            prompt_tokens=int(self._get_attr(usage, "prompt_tokens", "input_tokens", default=0) or 0),
            completion_tokens=int(
                self._get_attr(usage, "completion_tokens", "output_tokens", default=0) or 0
            ),
            total_tokens=int(self._get_attr(usage, "total_tokens", default=0) or 0),
            extra_usage={"raw": self._json_safe(usage)},
        )

    @staticmethod
    def _write_output_schema(output_type: type) -> str:
        if isinstance(output_type, type) and issubclass(output_type, BaseModel):
            schema = output_type.model_json_schema()
        elif hasattr(output_type, "model_json_schema"):
            schema = output_type.model_json_schema()
        else:
            schema = {
                "type": "object",
                "properties": getattr(output_type, "__annotations__", {}),
            }
        path = OpenAICodexClient._temp_path(".schema.json")
        Path(path).write_text(json.dumps(schema), encoding="utf-8")
        return path

    @staticmethod
    def _temp_path(suffix: str) -> str:
        fd, path = tempfile.mkstemp(prefix="parrot-codex-", suffix=suffix)
        os.close(fd)
        return path

    @staticmethod
    def _import_sdk() -> Any:
        try:
            import openai_codex  # type: ignore[import-not-found]
        except ImportError as exc:
            raise ImportError(
                "OpenAICodexClient SDK backend requires openai-codex. "
                "Install with: pip install ai-parrot[codex-agent]"
            ) from exc
        return openai_codex

    @staticmethod
    def _get_attr(obj: Any, *names: str, default: Any = None) -> Any:
        for name in names:
            if isinstance(obj, dict) and name in obj:
                return obj[name]
            if hasattr(obj, name):
                return getattr(obj, name)
        return default

    @staticmethod
    def _json_safe(obj: Any) -> Any:
        if isinstance(obj, (str, int, float, bool)) or obj is None:
            return obj
        if isinstance(obj, dict):
            return obj
        if hasattr(obj, "model_dump"):
            return obj.model_dump()
        if hasattr(obj, "__dict__"):
            return obj.__dict__
        return repr(obj)
