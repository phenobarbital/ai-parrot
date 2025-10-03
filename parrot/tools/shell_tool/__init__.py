# parrot/tools/shell_tool.py
from __future__ import annotations
from typing import Any, Dict, List, Optional, Union
import asyncio
import os
import re
import json
from ..abstract import AbstractTool
from .models import CommandObject, ShellToolArgs, PlanStep
from .actions import (
    BaseAction,
    ActionResult,
    RunCommand,
    ExecFile,
    ListFiles,
    ReadFile,
    WriteFile,
    DeleteFile,
    CopyFile,
    MoveFile,
    CheckExists
)
from .engine import EvalAction

class ShellTool(AbstractTool):
    """
    Interactive Shell tool with optional PTY support.

    Features:
        - Accepts single string, list of strings, or list of command objects
        - Plan-mode (tiny sequential DAG) with `uses` and templating
        - Sequential or parallel execution
        - Per-command and global timeouts
        - Global and per-command work_dir, env
        - Optional PTY mode for interactive programs (merged stdout/stderr)
        - Live output callback hook
    """
    name: str = "shell"
    description: str = "Execute shell commands with optional PTY, sequential/parallel control, and rich command objects."
    args_schema = ShellToolArgs

    def _default_output_dir(self):
        # This tool doesn't produce files by default
        return None

    async def _execute(
        self,
        command: Optional[Union[str, List[Union[str, Dict[str, Any]]]]] = None,
        plan: Optional[List[Dict[str, Any]]] = None,
        parallel: bool = False,
        ignore_errors: bool = False,
        timeout: Optional[int] = None,
        work_dir: Optional[str] = None,
        pty: bool = False,
        env: Optional[Dict[str, str]] = None,
        non_interactive: bool = False
    ) -> Dict[str, Any]:
        if plan:
            return await self._run_plan(
                plan=plan,
                ignore_errors=ignore_errors,
                timeout=timeout,
                work_dir=work_dir or os.getcwd(),
                pty=pty,
                env=env or {},
                non_interactive=non_interactive
            )
        if command is not None:
            return await self._run_commands(
                command=command,
                parallel=parallel,
                ignore_errors=ignore_errors,
                timeout=timeout,
                work_dir=work_dir or os.getcwd(),
                pty=pty,
                env=env or {},
                non_interactive=non_interactive
            )
        return {"ok": True, "results": []}

    # ---- helpers ----
    def _normalize_to_objects(
        self,
        command: Union[str, List[Union[str, CommandObject, Dict[str, Any]]]]
    ) -> List[CommandObject]:
        if isinstance(command, str):
            return [CommandObject(command=command)]
        objs: List[CommandObject] = []
        for item in command:
            if isinstance(item, str):
                objs.append(CommandObject(command=item))
            elif isinstance(item, dict):
                objs.append(CommandObject(**item))
            elif isinstance(item, CommandObject):
                objs.append(item)
            else:
                raise ValueError(f"Unsupported command element: {type(item)}")
        return objs

    def _live_cb(self, line: str, is_stderr: bool, cmd: str):
        try:
            self.logger.debug(f"[{cmd}] {'STDERR' if is_stderr else 'STDOUT'}: {line.rstrip()}")
        except Exception:
            pass

    # ---- classic command mode ----
    async def _run_commands(
        self,
        *,
        command: Union[str, List[Union[str, Dict[str, Any]]]],
        parallel: bool,
        ignore_errors: bool,
        timeout: Optional[int],
        work_dir: str,
        pty: bool,
        env: Dict[str, str],
        non_interactive: bool
    ) -> Dict[str, Any]:
        cmds = self._normalize_to_objects(command)
        actions = [
            self._make_action_from_cmdobj(
                c, timeout, work_dir, env, pty, non_interactive, ignore_errors
            ) for c in cmds
        ]

        results: List[ActionResult] = []
        if parallel and len(actions) > 1:
            results = await asyncio.gather(*[a.run() for a in actions])
        else:
            for act in actions:
                r = await act.run()
                results.append(r)
                if not r.ok and not (ignore_errors or act.ignore_errors):
                    break

        payload = [self._result_to_dict(r) for r in results]
        overall_ok = all(item["ok"] for item in payload) if payload else True
        return {"ok": overall_ok, "parallel": parallel, "results": payload}

    def _make_action_from_cmdobj(
        self,
        spec: CommandObject,
        default_timeout: Optional[int],
        base_work_dir: str,
        base_env: Dict[str, str],
        tool_level_pty: bool,
        tool_level_non_interactive: bool,
        tool_level_ignore_errors: bool
    ) -> BaseAction:
        timeout = spec.timeout if spec.timeout is not None else default_timeout
        work_dir = spec.work_dir or base_work_dir
        env = dict(base_env)
        if spec.env:
            env.update(spec.env)
        pty_mode = tool_level_pty if spec.pty is None else bool(spec.pty)
        non_interactive = tool_level_non_interactive if spec.non_interactive is None else bool(spec.non_interactive)
        ignore_errors = tool_level_ignore_errors if spec.ignore_errors is None else bool(spec.ignore_errors)

        raw = spec.command.strip()
        if raw.startswith("ls") or raw == "ls":
            return ListFiles(
                type_name="list_files", cmd=raw, work_dir=work_dir, timeout=timeout,
                env=env, pty_mode=pty_mode, stdin_lines=spec.stdin or [],
                non_interactive=non_interactive, ignore_errors=ignore_errors,
                live_callback=self._live_cb
            )
        elif raw.endswith(".sh") or raw.startswith("./") or raw.startswith("/"):
            return ExecFile(
                type_name="exec_file", cmd=raw, work_dir=work_dir, timeout=timeout,
                env=env, pty_mode=pty_mode, stdin_lines=spec.stdin or [],
                non_interactive=non_interactive, ignore_errors=ignore_errors,
                live_callback=self._live_cb
            )
        else:
            return RunCommand(
                type_name="run_command", cmd=raw, work_dir=work_dir, timeout=timeout,
                env=env, pty_mode=pty_mode, stdin_lines=spec.stdin or [],
                non_interactive=non_interactive, ignore_errors=ignore_errors,
                live_callback=self._live_cb
            )

    def _result_to_dict(self, r: ActionResult) -> Dict[str, Any]:
        return {
            "type": r.type,
            "cmd": r.cmd,
            "work_dir": r.work_dir,
            "ok": r.ok,
            "exit_code": r.exit_code,
            "timed_out": r.timed_out,
            "duration": round(r.duration, 4),
            "stdout": r.stdout,
            "stderr": r.stderr,
            "metadata": r.metadata
        }

    # ---- plan mode ----
    async def _run_plan(
        self,
        *,
        plan: List[Dict[str, Any]],
        ignore_errors: bool,
        timeout: Optional[int],
        work_dir: str,
        pty: bool,
        env: Dict[str, str],
        non_interactive: bool
    ) -> Dict[str, Any]:
        steps = [PlanStep(**s) if not isinstance(s, PlanStep) else s for s in plan]
        results: List[ActionResult] = []
        base_ctx = {"results": results}  # live context for templating / uses

        for idx, step in enumerate(steps):
            # Resolve per-step overrides
            step_timeout = step.timeout if step.timeout is not None else timeout
            step_work_dir = step.work_dir or work_dir
            step_env = dict(env)
            if step.env:
                step_env.update(step.env)
            step_pty = pty if step.pty is None else bool(step.pty)
            step_non_interactive = non_interactive if step.non_interactive is None else bool(step.non_interactive)
            step_ignore = ignore_errors if step.ignore_errors is None else bool(step.ignore_errors)

            # Prepare context for templating / uses
            src = self._resolve_uses(step.uses, results) if step.uses else None
            rendered = self._render_template(step.template, src, results) if step.template else None

            # Build action by type
            action: BaseAction
            if step.type in ("run_command", "exec_file", "list_files"):
                # unify into command list
                command_spec = step.command or rendered or ""
                objs = self._normalize_to_objects(command_spec)
                # Only one command allowed per plan step for now to keep step/result alignment clean
                if len(objs) != 1:
                    raise ValueError(f"Plan step {idx} expects exactly one command; got {len(objs)}.")
                action = self._make_action_from_cmdobj(
                    objs[0], step_timeout, step_work_dir, step_env, step_pty, step_non_interactive, step_ignore
                )
                # Force type to requested for accurate step labeling
                action.type_name = step.type

            elif step.type == "check_exists":
                target = (step.path or rendered or "").strip()
                action = CheckExists(
                    type_name="check_exists",
                    cmd=target,
                    work_dir=step_work_dir,
                    ignore_errors=step_ignore
                )

            elif step.type == "read_file":
                target = (step.path or rendered or "").strip()
                rf = ReadFile(
                    type_name="read_file",
                    cmd=target,
                    work_dir=step_work_dir,
                    ignore_errors=step_ignore
                )
                # attach options
                setattr(rf, "_max_bytes", step.max_bytes)
                setattr(rf, "_encoding", step.encoding or "utf-8")
                action = rf
            elif step.type == "write_file":
                target = (step.path or rendered or "").strip()
                if not target:
                    raise ValueError(f"Plan step {idx}: write_file requires 'path'.")
                content_src: Any = rendered if rendered is not None else (src if src is not None else step.content or "")
                # If content is not a string, JSON-dump it for safety
                if not isinstance(content_src, str):
                    try:
                        content_str = json.dumps(content_src, ensure_ascii=False)
                    except Exception:
                        content_str = str(content_src)
                else:
                    content_str = content_src

                action = WriteFile(
                    path=target,
                    content=content_str,
                    encoding=step.encoding or "utf-8",
                    append=bool(step.append),
                    make_dirs=bool(step.make_dirs if step.make_dirs is not None else True),
                    overwrite=bool(step.overwrite if step.overwrite is not None else True),
                    work_dir=step_work_dir,
                    ignore_errors=step_ignore
                )
            elif step.type == "delete_file":
                target = (step.path or rendered or "").strip()
                if not target:
                    raise ValueError(f"Plan step {idx}: delete_file requires 'path'.")
                action = DeleteFile(
                    path=target,
                    recursive=bool(step.recursive),
                    missing_ok=bool(step.missing_ok if step.missing_ok is not None else True),
                    work_dir=step_work_dir,
                    ignore_errors=step_ignore
                )
            elif step.type == "copy_file":
                src = (step.path or rendered or "").strip()
                dest = (step.dest or "").strip()
                if not src or not dest:
                    raise ValueError(f"Plan step {idx}: copy_file requires 'path' (src) and 'dest'.")
                action = CopyFile(
                    src=src,
                    dest=dest,
                    recursive=bool(step.recursive),
                    overwrite=bool(step.overwrite if step.overwrite is not None else True),
                    make_dirs=bool(step.make_dirs if step.make_dirs is not None else True),
                    work_dir=step_work_dir,
                    ignore_errors=step_ignore
                )
            elif step.type == "move_file":
                src = (step.path or rendered or "").strip()
                dest = (step.dest or "").strip()
                if not src or not dest:
                    raise ValueError(f"Plan step {idx}: move_file requires 'path' (src) and 'dest'.")
                action = MoveFile(
                    src=src,
                    dest=dest,
                    recursive=bool(step.recursive if step.recursive is not None else True),
                    overwrite=bool(step.overwrite if step.overwrite is not None else True),
                    make_dirs=bool(step.make_dirs if step.make_dirs is not None else True),
                    work_dir=step_work_dir,
                    ignore_errors=step_ignore
                )
            elif step.type == "eval":
                eval_src: Any = rendered if rendered is not None else src
                action = EvalAction(
                    eval_type=step.eval_type or "regex",
                    expr=step.expr or "",
                    group=step.group,
                    src_text_or_obj=eval_src,
                    as_json=bool(step.as_json),
                    work_dir=step_work_dir,
                    ignore_errors=step_ignore
                )

            else:
                raise ValueError(
                    f"Unsupported plan step type: {step.type}"
                )

            # Run step
            r = await action.run()
            results.append(r)
            if not r.ok and not (ignore_errors or step_ignore):
                break

        payload = [self._result_to_dict(r) for r in results]
        overall_ok = all(item["ok"] for item in payload) if payload else True
        return {"ok": overall_ok, "results": payload}

    # ---- uses & templating ----
    def _resolve_uses(self, uses: str, results: List[ActionResult]) -> Any:
        """
        Accepts strings like:
            - "prev.stdout"
            - "prev"
            - "result[0].stdout"
            - "result[-1]"
        Returns the object or string (stdout) referenced.
        """
        uses = uses.strip()
        if uses.startswith("prev"):
            base = results[-1] if results else None
            if base is None:
                return ""
            if uses == "prev":
                return self._ar_to_src(base)
            elif uses == "prev.stdout":
                return base.stdout
            elif uses == "prev.stderr":
                return base.stderr
            else:
                return self._attr_path(self._ar_to_src(base), uses[len("prev."):])
        m = re.match(r"result\[(\-?\d+)\](?:\.(stdout|stderr))?$", uses)
        if m:
            i = int(m.group(1))
            if not results:
                return ""
            try:
                base = results[i]
            except IndexError:
                return ""
            stream = m.group(2)
            if stream == "stdout":
                return base.stdout
            if stream == "stderr":
                return base.stderr
            return self._ar_to_src(base)
        # Fallback: direct literal
        return uses

    @staticmethod
    def _ar_to_src(ar: ActionResult) -> Dict[str, Any]:
        return {
            "type": ar.type,
            "stdout": ar.stdout,
            "stderr": ar.stderr,
            "ok": ar.ok,
            "exit_code": ar.exit_code,
            "metadata": ar.metadata,
            "cmd": ar.cmd,
            "work_dir": ar.work_dir
        }

    @staticmethod
    def _attr_path(obj: Any, path: str) -> Any:
        # Just a minimal dot path for dicts
        cur = obj
        for part in path.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                return ""
        return cur

    def _render_template(self, template: str, src: Any, results: List[ActionResult]) -> str:
        """
        Tiny Jinja-lite:
          - {{ prev.stdout }}
          - {{ result[-1].stdout }}
          - {{ json(results) }}  # dumps
        """
        out = template

        def repl_prev(m):
            key = m.group(1).strip()
            if key == "prev":
                return json.dumps(self._ar_to_src(results[-1])) if results else ""
            if key.startswith("prev."):
                return str(self._resolve_uses(key, results) or "")
            if key.startswith("result["):
                return str(self._resolve_uses(key, results) or "")
            if key == "json(results)":
                return json.dumps([self._ar_to_src(r) for r in results], ensure_ascii=False)
            if key == "src":
                return json.dumps(src) if isinstance(src, (dict, list)) else (src or "")
            return ""
        # {{ ... }}
        out = re.sub(r"\{\{\s*(.*?)\s*\}\}", repl_prev, out)
        return out
