# parrot/tools/shell_tool.py
from __future__ import annotations
from typing import Any, Dict, List, Optional, Sequence, Union
import asyncio
import os
import pty
import signal
import time
from dataclasses import dataclass, field
from pathlib import Path
from pydantic import BaseModel, Field, field_validator
from ..abstract import AbstractToolArgsSchema


# ---------- Command spec & args schema ----------

class CommandObject(BaseModel):
    """
    Represents a shell command to be executed.
    """
    command: str = Field(..., description="The command string to execute, e.g. 'git status'")
    timeout: Optional[int] = Field(None, description="Timeout in seconds for this command")
    work_dir: Optional[str] = Field(None, description="Working directory for this command")
    env: Optional[Dict[str, str]] = Field(default=None, description="Extra environment variables")
    pty: Optional[bool] = Field(default=None, description="Force PTY for this command (overrides tool-level)")
    stdin: Optional[List[str]] = Field(default=None, description="Lines to feed to stdin/PTY (each line ends with \\n)")
    non_interactive: Optional[bool] = Field(default=None, description="If true, do not wait for interactive prompts")
    ignore_errors: Optional[bool] = Field(default=None, description="If true, do not stop pipeline on failure")


class PlanStep(BaseModel):
    """
    Represents a step in a shell command plan.
    """
    # type: run_command | exec_file | list_files | check_exists | read_file | eval
    type: str = Field(..., description="Action type")
    # Optional "uses" reference (e.g., 'prev.stdout', 'result[0].stdout')
    uses: Optional[str] = Field(None, description="Reference to previous output")
    # Optional templated text to inject previous outputs into command/args
    template: Optional[str] = Field(None, description="A Jinja-lite string to render with context")
    # Command / args depending on type
    command: Optional[Union[str, List[Union[str, CommandObject]]]] = None
    path: Optional[str] = None            # for check_exists/read_file
    max_bytes: Optional[int] = None       # for read_file
    encoding: Optional[str] = "utf-8"     # for read_file
    # Eval:
    eval_type: Optional[str] = Field(None, description="regex | jsonpath | jq")
    expr: Optional[str] = Field(None, description="Pattern or path for evaluation")
    group: Optional[Union[int, str]] = Field(None, description="Regex group to extract")
    as_json: bool = Field(False, description="Try loading uses/template as JSON for jsonpath/jq")
    # Per-step overrides:
    timeout: Optional[int] = None
    work_dir: Optional[str] = None
    env: Optional[Dict[str, str]] = None
    pty: Optional[bool] = None
    stdin: Optional[List[str]] = None
    non_interactive: Optional[bool] = None
    ignore_errors: Optional[bool] = None
    # File ops:
    content: Optional[str] = None       # for write_file
    encoding: Optional[str] = "utf-8"   # for write_file + read_file
    append: Optional[bool] = False      # for write_file (append vs overwrite)
    make_dirs: Optional[bool] = True    # for write_file (create parent dirs)
    overwrite: Optional[bool] = True    # for write_file (ignored if append=True)
    # For copy/move:
    dest: Optional[str] = None          # destination path for copy/move

    recursive: Optional[bool] = False   # for delete_file (directories)
    missing_ok: Optional[bool] = True   # for delete_file (ignore if not exists)
    make_dirs: Optional[bool] = True    # create dest parent dirs if needed


class ShellToolArgs(AbstractToolArgsSchema):
    """
    Arguments for the ShellTool.
    """
    command: Union[str, List[Union[str, CommandObject]]] = Field(
        ...,
        description="Shell command(s) to execute. Accepts string, list of strings, or list of objects."
    )
    # NEW: tiny DAG plan mode:
    plan: Optional[List[PlanStep]] = Field(
        default=None,
        description="A list of steps (tiny DAG, sequential)."
    )
    parallel: bool = Field(False, description="Execute multiple commands in parallel")
    ignore_errors: bool = Field(False, description="Continue when a command fails")
    timeout: Optional[int] = Field(None, description="Default timeout for each command (seconds)")
    work_dir: Optional[str] = Field(None, description="Base working directory for all commands")
    pty: bool = Field(False, description="Enable pseudoterminal (interactive TTY) mode")
    env: Optional[Dict[str, str]] = Field(default=None, description="Environment variables to add/override")
    non_interactive: bool = Field(False, description="Run without user prompts (do not wait for input)")

    @field_validator("work_dir")
    @classmethod
    def _abs_or_none(cls, v):
        if v is None:
            return v
        return str(Path(v).expanduser().resolve())


@dataclass
class ActionResult:
    """Result of a shell action execution."""
    ok: bool
    exit_code: Optional[int]
    stdout: str
    stderr: str
    started_at: float
    ended_at: float
    duration: float
    cmd: str
    work_dir: str
    timed_out: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)
    type: str = "command"  # store the action type for plan steps


class BaseAction:
    """Base class for shell and utility actions."""
    def __init__(
        self,
        *,
        type_name: str,
        cmd: str = "",
        work_dir: Optional[str] = None,
        timeout: Optional[int] = None,
        env: Optional[Dict[str, str]] = None,
        pty_mode: Optional[bool] = None,
        stdin_lines: Optional[List[str]] = None,
        non_interactive: Optional[bool] = None,
        ignore_errors: Optional[bool] = None,
        live_callback=None,  # callable(line: str, is_stderr: bool, cmd: str)
    ):
        self.type_name = type_name
        self.cmd = cmd
        self.work_dir = work_dir or os.getcwd()
        self.timeout = timeout
        self.env = env or {}
        self.pty_mode = bool(pty_mode)
        self.stdin_lines = stdin_lines or []
        self.non_interactive = bool(non_interactive)
        self.ignore_errors = bool(ignore_errors)
        self.live_callback = live_callback

    async def run(self) -> ActionResult:
        return await self._run_impl()

    async def _run_impl(self) -> ActionResult:
        raise NotImplementedError

    async def _run_subprocess(self, argv: Sequence[str]) -> ActionResult:
        """
        Executes argv with optional PTY and returns ActionResult.
        """
        started = time.time()
        work_dir = self.work_dir
        stdout_buf: List[bytes] = []
        stderr_buf: List[bytes] = []
        timed_out = False

        env = os.environ.copy()
        env.update(self.env)

        if self.pty_mode:
            master_fd, slave_fd = pty.openpty()
            loop = asyncio.get_event_loop()
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                cwd=work_dir,
                env=env,
                preexec_fn=os.setsid
            )
            os.close(slave_fd)
            out_q: asyncio.Queue[bytes] = asyncio.Queue()

            def _reader():
                try:
                    data = os.read(master_fd, 4096)
                    if data:
                        out_q.put_nowait(data)
                except OSError:
                    pass

            loop.add_reader(master_fd, _reader)

            async def _drain():
                while True:
                    try:
                        chunk = await asyncio.wait_for(out_q.get(), timeout=0.05)
                        stdout_buf.append(chunk)
                        if self.live_callback:
                            try:
                                self.live_callback(chunk.decode(errors="ignore"), False, self.cmd)
                            except Exception:
                                pass
                    except asyncio.TimeoutError:
                        if proc.returncode is not None:
                            break

            async def _feed():
                for line in self.stdin_lines:
                    os.write(master_fd, (line if line.endswith("\n") else line + "\n").encode())
                    await asyncio.sleep(0.02)

            async def _timeout():
                nonlocal timed_out
                if self.timeout:
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=self.timeout)
                    except asyncio.TimeoutError:
                        timed_out = True
                        try:
                            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                        except ProcessLookupError:
                            pass

            tasks = [asyncio.create_task(_drain()), asyncio.create_task(_feed())]
            if self.timeout:
                tasks.append(asyncio.create_task(_timeout()))
            else:
                tasks.append(asyncio.create_task(proc.wait()))

            await asyncio.gather(*tasks, return_exceptions=True)
            loop.remove_reader(master_fd)
            try:
                os.close(master_fd)
            except OSError:
                pass

            exit_code = proc.returncode
            ended = time.time()
            return ActionResult(
                ok=(not timed_out) and (exit_code == 0 or self.ignore_errors),
                exit_code=exit_code,
                stdout=b"".join(stdout_buf).decode(errors="replace"),
                stderr="",
                started_at=started,
                ended_at=ended,
                duration=ended - started,
                cmd=" ".join(argv),
                work_dir=work_dir,
                timed_out=timed_out,
                metadata={"pty": True},
                type=self.type_name
            )
        else:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=work_dir,
                env=env,
                preexec_fn=os.setsid
            )

            async def _pump(reader: asyncio.StreamReader, sink: List[bytes], is_err: bool):
                while True:
                    chunk = await reader.readline()
                    if not chunk:
                        break
                    sink.append(chunk)
                    if self.live_callback:
                        try:
                            self.live_callback(chunk.decode(errors="ignore"), is_err, self.cmd)
                        except Exception:
                            pass

            pumps = [
                asyncio.create_task(_pump(proc.stdout, stdout_buf, False)),
                asyncio.create_task(_pump(proc.stderr, stderr_buf, True)),
            ]

            async def _feed():
                if self.stdin_lines:
                    for line in self.stdin_lines:
                        proc.stdin.write((line if line.endswith("\n") else line + "\n").encode())
                        await proc.stdin.drain()
                        await asyncio.sleep(0.02)
                if proc.stdin:
                    try:
                        proc.stdin.close()
                    except Exception:
                        pass

            feeder = asyncio.create_task(_feed())

            timed_out = False
            try:
                if self.timeout is None:
                    await proc.wait()
                else:
                    await asyncio.wait_for(proc.wait(), timeout=self.timeout)
            except asyncio.TimeoutError:
                timed_out = True
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass
            finally:
                await asyncio.gather(*pumps, feeder, return_exceptions=True)

            exit_code = proc.returncode
            ended = time.time()
            return ActionResult(
                ok=(not timed_out) and (exit_code == 0 or self.ignore_errors),
                exit_code=exit_code,
                stdout=b"".join(stdout_buf).decode(errors="replace"),
                stderr=b"".join(stderr_buf).decode(errors="replace"),
                started_at=started,
                ended_at=ended,
                duration=ended - started,
                cmd=" ".join(argv),
                work_dir=work_dir,
                timed_out=timed_out,
                metadata={"pty": False},
                type=self.type_name
            )
