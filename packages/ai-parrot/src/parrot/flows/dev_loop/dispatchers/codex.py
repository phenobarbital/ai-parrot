"""CodexCodeDispatcher — orchestration glue between AgentsFlow and Codex CLI.

Mirrors the public ``dispatch`` contract of :class:`ClaudeCodeDispatcher`
so Development can choose a coding-agent backend without changing the
dev-loop graph. Shells out to ``codex exec --json`` and streams its
stdout events the same way the Claude dispatcher streams SDK events.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import time
from typing import Any, Dict, List, Optional, Sequence, Type

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
from parrot.flows.dev_loop.models import (
    CodexAdversarialReviewProfile,
    CodexCodeDispatchProfile,
    DispatchEvent,
    DispatchLabels,
)
from parrot.flows.dev_loop.session_state import SessionHost


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
        labels: Optional[DispatchLabels] = None,
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
        # FEAT-496: bind labels alongside the session host, same discipline.
        _labels_token = bind_labels(labels)
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
            _DISPATCH_LABELS_CTX.reset(_labels_token)
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
                _DISPATCH_LABELS_CTX.reset(_labels_token)
                for path in (schema_path, output_path):
                    if path is None:
                        continue
                    try:
                        os.unlink(path)
                    except OSError:
                        pass

    # FEAT-375 (Module 3): table mapping `CodexAdversarialReviewProfile.review_scope`
    # to the `codex exec review` scope flag and the profile field that carries its
    # value. Kept module-accessible (class attribute) so tests can enumerate shapes
    # without needing to invoke the CLI.
    _REVIEW_SCOPE_FLAGS: Dict[str, str] = {
        "base": "--base",
        "commit": "--commit",
    }

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
        if isinstance(profile, CodexAdversarialReviewProfile):
            return self._build_adversarial_review_command(
                profile=profile,
                cwd=cwd,
                schema_path=schema_path,
                output_path=output_path,
                prompt=prompt,
            )
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

    def _build_review_scope_args(self, profile: CodexAdversarialReviewProfile) -> List[str]:
        """Return the `codex exec review` scope-specific arguments (FEAT-375 G5).

        Table-driven via ``_REVIEW_SCOPE_FLAGS`` so CLI-surface drift is
        contained to this one mapping. Raises ``ValueError`` when a
        non-``"uncommitted"`` scope is missing its required target.
        """
        if profile.review_scope == "uncommitted":
            return []
        flag = self._REVIEW_SCOPE_FLAGS[profile.review_scope]
        value = profile.review_base if profile.review_scope == "base" else profile.review_commit
        field_name = "review_base" if profile.review_scope == "base" else "review_commit"
        if not value:
            raise ValueError(
                f"CodexAdversarialReviewProfile.review_scope={profile.review_scope!r} "
                f"requires a non-empty {field_name}"
            )
        return [flag, value]

    def _build_adversarial_review_command(
        self,
        *,
        profile: CodexAdversarialReviewProfile,
        cwd: str,
        schema_path: str,
        output_path: str,
        prompt: str,
    ) -> List[str]:
        """Build `codex exec review` / `codex exec resume --last` shapes (FEAT-375 G5/G6).

        The installed CLI treats ``--cd``, ``--sandbox``, and ``--model`` as
        options of the top-level ``exec`` command that MUST precede the
        ``review``/``resume`` subcommand name (verified via ``codex exec
        review --help`` / ``codex exec resume --help`` — neither subcommand
        lists them as its own options). ``--json``, ``--output-schema``,
        ``-o``, ``--ignore-user-config``, and ``--ignore-rules`` are
        subcommand-level options and follow the subcommand name.

        ``codex exec resume`` does not honor ``--sandbox`` (the gotcha
        documented in the repo's ``CLAUDE.md``): omit it and pass
        ``-c sandbox_mode="<mode>"`` instead so the read-only restriction
        still applies to the resumed turn.
        """
        cmd = [self.codex_bin, "exec", "--cd", cwd]
        if not profile.resume_last:
            cmd += ["--sandbox", profile.sandbox]
        cmd += ["--model", profile.model]

        if profile.resume_last:
            cmd += ["-c", f'sandbox_mode="{profile.sandbox}"']
            cmd += ["resume", "--last"]
        else:
            cmd.append("review")
            cmd += self._build_review_scope_args(profile)

        cmd += ["--json", "--output-schema", schema_path, "-o", output_path]
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
            limit=8 * 1024 * 1024,
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
        payload: Dict[str, Any] = {"codex_event": event}
        payload.update(self._extract_codex_display(event))
        await self._publish_event(
            stream_key,
            kind=self._codex_event_kind(event),
            run_id=run_id,
            node_id=node_id,
            payload=payload,
        )

    @staticmethod
    def _extract_codex_display(event: Dict[str, Any]) -> Dict[str, Any]:
        """Best-effort display projection of one Codex CLI stream event.

        Never raises and never assumes a field is present — the CLI's event
        schema is not pinned by this repo; every field is read defensively
        via ``.get()``.

        Args:
            event: The parsed Codex CLI stdout JSON event.

        Returns:
            A dict of additive display keys (``tool_name``, ``tool_input``,
            ``text``, and any status/exit detail the item carries). Empty
            when nothing recognisable is present.
        """
        try:
            out: Dict[str, Any] = {}
            item = event.get("item") if isinstance(event, dict) else None
            item_type = item.get("type") if isinstance(item, dict) else None

            if item_type == "command_execution":
                out["tool_name"] = "shell"
                command = item.get("command")
                if command:
                    out["tool_input"] = summarize_tool_input("shell", {"command": command})
                exit_code = item.get("exit_code")
                if exit_code is not None:
                    out["exit_code"] = exit_code
                status = item.get("status")
                if status:
                    out["status"] = status
            elif item_type == "file_change":
                out["tool_name"] = "edit"
                changes = item.get("changes")
                path = item.get("path")
                if changes:
                    out["tool_input"] = summarize_tool_input("edit", {"path": str(changes)})
                elif path:
                    out["tool_input"] = summarize_tool_input("edit", {"path": path})
            elif item_type == "mcp_tool_call":
                server = item.get("server") or ""
                tool = item.get("tool") or ""
                name = " ".join(part for part in (server, tool) if part)
                if name:
                    out["tool_name"] = name
                arguments = item.get("arguments")
                if arguments is not None:
                    out["tool_input"] = summarize_tool_input(name, arguments)
            elif item_type == "web_search":
                out["tool_name"] = "web_search"
                query = item.get("query")
                if query:
                    out["tool_input"] = summarize_tool_input("web_search", {"prompt": query})
            else:
                text = None
                if isinstance(item, dict):
                    text = item.get("text")
                if not text and isinstance(event, dict):
                    text = event.get("message")
                if text:
                    out["text"] = str(text)[:400]

            return out
        except Exception:  # noqa: BLE001 - telemetry must never break a dispatch
            return {}

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
            payload=normalize_payload(kind, payload),
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

