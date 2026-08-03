"""GoogleCodingDispatcher — orchestration glue between AgentsFlow and the
Google Antigravity CLI console (``agy``) in headless mode.

Mirrors the public ``dispatch`` contract of :class:`ClaudeCodeDispatcher`,
:class:`CodexCodeDispatcher`, and :class:`GeminiCodeDispatcher` so
Development can choose Antigravity as a coding-agent backend without
changing the dev-loop graph.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import tempfile
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple, Type

from pydantic import BaseModel, ValidationError

from parrot import conf
from parrot.flows.dev_loop._subagent_defs import load_subagent_definition
from parrot.flows.dev_loop.dispatchers._shared import (
    T,
    _SESSION_HOST_CTX,
    DispatchExecutionError,
    DispatchOutputValidationError,
)
from parrot.flows.dev_loop.dispatchers.gemini import GeminiCodeDispatcher
from parrot.flows.dev_loop.models import (
    ClaudeCodeDispatchProfile,
    CodexCodeDispatchProfile,
    GeminiCodeDispatchProfile,
    GoogleCodingDispatchProfile,
)
from parrot.flows.dev_loop.session_state import SessionHost


class GoogleCodingDispatcher:
    """Thin orchestration class over ``agy --print ... --output-format stream-json``.

    The class mirrors the public ``dispatch`` contract of
    :class:`ClaudeCodeDispatcher`, :class:`CodexCodeDispatcher`, and
    :class:`GeminiCodeDispatcher` so Development can choose a Google
    Antigravity CLI console in headless mode as a coding-agent backend
    without changing the dev-loop graph.
    """

    def __init__(
        self,
        *,
        max_concurrent: int,
        redis_url: str,
        stream_ttl_seconds: int,
        agy_bin: str = "agy",
    ) -> None:
        if max_concurrent < 1:
            raise ValueError("max_concurrent must be >= 1")
        self.logger = logging.getLogger(__name__)
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._redis_url = redis_url
        self.stream_ttl_seconds = stream_ttl_seconds
        self.agy_bin = agy_bin
        self._redis: Any = None

        resolved = shutil.which(self.agy_bin) or shutil.which("agy")
        self.resolved_bin = resolved or self.agy_bin

    async def _get_redis(self) -> Any:
        if self._redis is None:
            import redis.asyncio as aioredis
            self._redis = aioredis.from_url(self._redis_url, decode_responses=True)
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
        try:
            r = await self._get_redis()
            data = {
                "kind": kind,
                "run_id": run_id,
                "node_id": node_id,
                "timestamp": str(time.time()),
                "payload": json.dumps(payload),
            }
            await r.xadd(stream_key, data)
            await r.expire(stream_key, self.stream_ttl_seconds)
        except Exception as exc:
            self.logger.warning("Failed to publish dispatch event to Redis: %s", exc)

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
        """Dispatch a single agy CLI session and return its parsed output."""
        stream_key = f"flow:{run_id}:dispatch:{node_id}"
        schema_path: Optional[str] = None
        process: Any = None
        _host_token = _SESSION_HOST_CTX.set(session_host)
        try:
            self._enforce_cwd_under_worktree_base(cwd)

            if isinstance(
                profile,
                (ClaudeCodeDispatchProfile, CodexCodeDispatchProfile, GeminiCodeDispatchProfile),
            ):
                profile = GoogleCodingDispatchProfile(
                    subagent=getattr(profile, "subagent", "sdd-worker"),
                    model=getattr(profile, "model", "auto"),
                    timeout_seconds=getattr(profile, "timeout_seconds", 1800),
                )
            if not isinstance(profile, GoogleCodingDispatchProfile):
                raise ValueError(f"Expected GoogleCodingDispatchProfile, got {type(profile).__name__}")

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
                prompt = self._build_agy_prompt(profile, brief, output_model)
                command = self._build_command(
                    profile=profile,
                    schema_path=schema_path,
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
                        result_data, assistant_text = await self._stream_stdout_events(
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
                            "error_message": f"agy CLI executable {self.resolved_bin!r} was not found on PATH",
                        },
                    )
                    raise DispatchExecutionError(
                        f"agy CLI executable {self.resolved_bin!r} was not found"
                    ) from exc
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
                            "error_message": f"dispatch exceeded {profile.timeout_seconds}s wall-clock cap",
                        },
                    )
                    raise DispatchExecutionError(
                        f"Dispatch exceeded {profile.timeout_seconds}s wall-clock cap"
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
                        f"agy CLI dispatch failed with exit code {return_code}: {stderr[-1000:]}"
                    )

                result = self._parse_and_validate_result(result_data, assistant_text, output_model)

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
                if schema_path:
                    try:
                        os.unlink(schema_path)
                    except OSError:
                        pass

    def _build_command(
        self,
        *,
        profile: GoogleCodingDispatchProfile,
        schema_path: str,
        prompt: str,
    ) -> List[str]:
        """Build the ``agy --print ...`` command line."""
        cmd = [
            self.resolved_bin,
            "--print",
            prompt,
            "--output-format",
            "stream-json",
            "--json-schema",
            schema_path,
        ]
        if profile.dangerously_skip_permissions:
            cmd.append("--dangerously-skip-permissions")
        if profile.sandbox:
            cmd.append("--sandbox")
        if profile.mode:
            cmd.extend(["--mode", profile.mode])
        if profile.model and profile.model != "auto":
            cmd.extend(["--model", profile.model])
        if profile.agent:
            cmd.extend(["--agent", profile.agent])
        if profile.effort:
            cmd.extend(["--effort", profile.effort])
        return cmd

    def _build_agy_prompt(
        self,
        profile: GoogleCodingDispatchProfile,
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

    def _build_prompt(self, brief: BaseModel, output_model: Type[BaseModel]) -> str:
        schema_json = json.dumps(output_model.model_json_schema(), indent=2)
        brief_dump = brief.model_dump_json(indent=2)
        return (
            "TASK BRIEF:\n"
            f"{brief_dump}\n\n"
            "OUTPUT INSTRUCTIONS:\n"
            f"Your output MUST conform to the JSON schema for `{output_model.__name__}`:\n"
            f"```json\n{schema_json}\n```\n\n"
            "Return valid JSON matching this schema."
        )

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
        fd, path = tempfile.mkstemp(prefix="dev_loop_agy_schema_", suffix=".json")
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

    async def _create_process(self, command: Sequence[str], cwd: str) -> Any:
        return await asyncio.create_subprocess_exec(
            *command,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=8 * 1024 * 1024,
        )

    async def _read_stream(self, stream: Any) -> str:
        if stream is None:
            return ""
        data = await stream.read()
        if isinstance(data, bytes):
            return data.decode("utf-8", errors="replace")
        return str(data or "")

    async def _stream_stdout_events(
        self,
        stdout: Any,
        *,
        stream_key: str,
        run_id: str,
        node_id: str,
    ) -> Tuple[Optional[Dict[str, Any]], str]:
        if stdout is None:
            return None, ""
        assistant_chunks: List[str] = []
        result_payload: Optional[Dict[str, Any]] = None

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

            event_type = event.get("type") or event.get("event")
            if event_type == "result":
                res = event.get("result", {})
                if isinstance(res, str):
                    try:
                        res = json.loads(res)
                    except Exception:
                        pass
                if isinstance(res, dict):
                    result_payload = res
            elif event_type == "step_update":
                su = event.get("step_update", {})
                if isinstance(su, dict):
                    text = su.get("text_delta")
                    if text:
                        assistant_chunks.append(text)

            await self._publish_agy_event(stream_key, event, run_id, node_id)

        return result_payload, "".join(assistant_chunks)

    async def _publish_agy_event(
        self,
        stream_key: str,
        event: Dict[str, Any],
        run_id: str,
        node_id: str,
    ) -> None:
        event_type = event.get("type") or event.get("event")
        kind = "dispatch.message"
        if event_type == "init":
            kind = "dispatch.started"
        elif event_type == "result":
            kind = "dispatch.completed"
        elif event_type == "step_update":
            su = event.get("step_update", {})
            st = su.get("step_type") if isinstance(su, dict) else None
            if st == "tool_call":
                kind = "dispatch.tool_use"
            elif st == "tool_response":
                kind = "dispatch.tool_result"

        await self._publish_event(
            stream_key,
            kind=kind,
            run_id=run_id,
            node_id=node_id,
            payload={"agy_event": event},
        )

    def _parse_and_validate_result(
        self,
        result_data: Optional[Dict[str, Any]],
        assistant_text: str,
        output_model: Type[T],
    ) -> T:
        if result_data:
            if "structured_output" in result_data and result_data["structured_output"]:
                try:
                    return output_model.model_validate(result_data["structured_output"])
                except ValidationError as exc:
                    self.logger.warning("structured_output validation failed, trying direct dict: %s", exc)
            try:
                return output_model.model_validate(result_data)
            except ValidationError as exc:
                self.logger.warning("direct dict validation failed, falling back to text parse: %s", exc)

        text_to_parse = ""
        if result_data and isinstance(result_data.get("response"), str):
            text_to_parse = result_data["response"]
        if not text_to_parse.strip():
            text_to_parse = assistant_text

        if not text_to_parse.strip():
            raise DispatchOutputValidationError(
                "agy did not produce structured output or text response.",
                raw_payload="",
            )

        json_text = GeminiCodeDispatcher._extract_last_json_object(text_to_parse)
        if json_text is None:
            raise DispatchOutputValidationError(
                "Could not locate a JSON object in agy output.",
                raw_payload=text_to_parse,
            )
        try:
            return output_model.model_validate_json(json_text)
        except ValidationError as exc:
            raise DispatchOutputValidationError(
                f"Output failed {output_model.__name__} validation: {exc}",
                raw_payload=json_text,
            ) from exc

