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
    _DISPATCH_LABELS_CTX,
    _SESSION_HOST_CTX,
    _apply_to_session_host,
    bind_labels,
    normalize_payload,
    summarize_tool_input,
    DispatchExecutionError,
    DispatchOutputValidationError,
)
from parrot.flows.dev_loop.dispatchers.gemini import GeminiCodeDispatcher
from parrot.flows.dev_loop.models import (
    ClaudeCodeDispatchProfile,
    CodexCodeDispatchProfile,
    DispatchEvent,
    DispatchLabels,
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
        """Wrap the event in a :class:`DispatchEvent` and ``XADD`` it.

        FEAT-496 root cause 7: this method previously wrote five flat
        Redis fields (``kind``, ``run_id``, ``node_id``, ``timestamp``,
        ``payload``-as-JSON-string) instead of the single ``{"event": ...}``
        field every other dispatcher writes and
        :class:`FlowStreamMultiplexer` expects — so every ``agy`` dispatch
        event surfaced in the console as ``event_kind="flow.unknown"`` and
        never reached session state at all. This now matches
        ``ClaudeCodeDispatcher._publish_event`` exactly: the session-host
        fold happens BEFORE the Redis round-trip (an independent failure
        domain), and a Redis failure never skips it.
        """
        event = DispatchEvent(
            kind=kind,  # type: ignore[arg-type]
            ts=time.time(),
            run_id=run_id,
            node_id=node_id,
            payload=normalize_payload(kind, payload),
        )
        _apply_to_session_host(event)
        try:
            r = await self._get_redis()
            await r.xadd(stream_key, {"event": event.model_dump_json()})
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
        labels: Optional[DispatchLabels] = None,
    ) -> T:
        """Dispatch a single agy CLI session and return its parsed output."""
        stream_key = f"flow:{run_id}:dispatch:{node_id}"
        schema_path: Optional[str] = None
        process: Any = None
        _host_token = _SESSION_HOST_CTX.set(session_host)
        # FEAT-496: bind labels alongside the session host, same discipline.
        _labels_token = bind_labels(labels)
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
            _DISPATCH_LABELS_CTX.reset(_labels_token)
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
                _DISPATCH_LABELS_CTX.reset(_labels_token)
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

        payload: Dict[str, Any] = {"agy_event": event}
        payload.update(self._extract_agy_display(event))
        await self._publish_event(
            stream_key,
            kind=kind,
            run_id=run_id,
            node_id=node_id,
            payload=payload,
        )

    @staticmethod
    def _extract_agy_display(event: Dict[str, Any]) -> Dict[str, Any]:
        """Best-effort display projection of one agy CLI stream event.

        Never raises; never assumes a field exists — the CLI's event schema
        is not pinned by this repo. ``event["result"]`` may arrive as a
        JSON-encoded string rather than a dict (the same tolerance
        ``_stream_stdout_events`` already applies at line ~375).

        Args:
            event: The parsed agy CLI stdout JSON event.

        Returns:
            A dict of additive display keys (``model``/``cwd``/
            ``session_id`` for ``init``, ``tool_name``/``tool_input`` or
            ``is_error``/``result_snippet`` for a tool step, ``text`` for a
            text delta, turn/duration/status for a terminal ``result``).
            Empty when nothing recognisable is present.
        """
        try:
            out: Dict[str, Any] = {}
            if not isinstance(event, dict):
                return out
            event_type = event.get("type") or event.get("event")

            def _first(source: Dict[str, Any], keys: Sequence[str]) -> Any:
                for key in keys:
                    value = source.get(key)
                    if value:
                        return value
                return None

            if event_type == "init":
                for key in ("model", "cwd", "session_id"):
                    value = event.get(key)
                    if value:
                        out[key] = value
            elif event_type == "step_update":
                su = event.get("step_update")
                if isinstance(su, dict):
                    step_type = su.get("step_type")
                    if step_type == "tool_call":
                        tool_call = su.get("tool_call")
                        name = ""
                        args = None
                        if isinstance(tool_call, dict):
                            found_name = _first(tool_call, ("name", "tool", "toolName"))
                            name = str(found_name) if found_name else ""
                            for key in ("args", "arguments", "input"):
                                if tool_call.get(key) is not None:
                                    args = tool_call.get(key)
                                    break
                        if name:
                            out["tool_name"] = name
                        if args is not None:
                            out["tool_input"] = summarize_tool_input(name, args)
                    elif step_type == "tool_response":
                        tool_response = su.get("tool_response")
                        if isinstance(tool_response, dict):
                            found_name = _first(tool_response, ("name", "tool", "toolName"))
                            if found_name:
                                out["tool_name"] = str(found_name)
                            if tool_response.get("error") or tool_response.get("status") == "error":
                                out["is_error"] = True
                            response = tool_response.get("response")
                            if response is None:
                                response = tool_response.get("output")
                            if response is not None:
                                out["result_snippet"] = str(response)[:400]
                    text_delta = su.get("text_delta")
                    if text_delta:
                        out["text"] = str(text_delta)[:400]
            elif event_type == "result":
                res = event.get("result")
                if isinstance(res, str):
                    try:
                        res = json.loads(res)
                    except Exception:  # noqa: BLE001
                        res = None
                if isinstance(res, dict):
                    for key in ("turns", "num_turns", "duration_ms", "status"):
                        if res.get(key) is not None:
                            out[key] = res[key]

            return out
        except Exception:  # noqa: BLE001 - telemetry must never break a dispatch
            return {}

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

