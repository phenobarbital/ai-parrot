"""GeminiCodeDispatcher — orchestration glue between AgentsFlow and Gemini CLI.

Mirrors the public ``dispatch`` contract of :class:`ClaudeCodeDispatcher`
and :class:`CodexCodeDispatcher` so Development can choose the Google
Gemini Agent (headless CLI, ``--output-format stream-json``) as a
coding-agent backend without changing the dev-loop graph.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import time
from typing import Any, Dict, List, Optional, Sequence, Type

from pydantic import BaseModel, ValidationError

from parrot import conf
from parrot.flows.dev_loop._subagent_defs import load_subagent_definition
from parrot.flows.dev_loop.dispatchers._shared import (
    T,
    _SESSION_HOST_CTX,
    _apply_to_session_host,
    DispatchExecutionError,
    DispatchOutputValidationError,
)
from parrot.flows.dev_loop.models import (
    ClaudeCodeDispatchProfile,
    DispatchEvent,
    GeminiCodeDispatchProfile,
)
from parrot.flows.dev_loop.session_state import SessionHost


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
            limit=8 * 1024 * 1024,
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

