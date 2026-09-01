"""Local OpenAI-compatible coding-agent dispatch profile (FEAT-129)."""

from __future__ import annotations

from typing import List, Literal

from pydantic import BaseModel, Field


class LLMCodeDispatchProfile(BaseModel):
    """Declarative profile consumed by ``LLMCodeDispatcher.dispatch()``.

    This profile targets OpenAI-compatible ``AbstractClient`` implementations
    via ``LLMFactory``. The dispatcher supplies the coding-agent loop locally,
    so the model only needs standard chat/tool-calling support.
    """

    subagent: Literal["sdd-worker"] = "sdd-worker"
    llm: str = "nvidia:minimaxai/minimax-m3"
    sandbox: Literal["workspace-write"] = "workspace-write"
    approval_policy: Literal["never"] = "never"
    timeout_seconds: int = Field(default=1800, ge=60, le=7200)
    max_turns: int = Field(default=24, ge=1, le=100)
    max_tokens: int = Field(default=8192, ge=256, le=32768)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    command_timeout_seconds: int = Field(default=300, ge=1, le=3600)
    parallel_tool_calls: bool = Field(
        default=True,
        description=(
            "Let the model request several tools in ONE turn. The dispatch "
            "loop already executes every call in a turn sequentially, so this "
            "only changes how much work fits in a turn — and a turn is the "
            "scarce resource: with it disabled, reading five files costs five "
            "turns of a `max_turns` budget that whole tasks were dying "
            "against. Set False for a backend that mis-handles multi-call "
            "turns."
        ),
    )
    restrict_command_paths: bool = Field(
        default=True,
        description=(
            "Reject a run_command argv whose path arguments point outside "
            "the worktree. A guard-rail, NOT a jail: the command still runs "
            "as this process's user and a script can compute a path at "
            "runtime. It closes the accidental route (a seat running "
            "pytest/sed/git against the main clone by absolute path, or an "
            "inline `python -c` that writes there), which is the one that "
            "actually happens. Real isolation needs a container or "
            "bubblewrap."
        ),
    )
    allowed_commands: List[str] = Field(
        default_factory=lambda: [
            "git",
            "uv",
            "pytest",
            "python",
            "python3",
            "rg",
            "grep",
            "ls",
            "pwd",
            "cat",
            "sed",
            "find",
            "mkdir",
            "mv",
            "ruff",
            "mypy",
        ],
        description=(
            "Executable names allowed through the run_command tool. "
            "`grep`/`mkdir`/`mv`/`ruff`/`mypy` are here because seats "
            "reached for them constantly and every rejection cost a whole "
            "turn: `ruff`/`mypy` ARE this repo's lint gate, `mkdir`/`mv` are "
            "how a task creates a package or files a completed TASK, and "
            "`grep` is what a model falls back to when search_files fails. "
            "This list is an ergonomics guard, not a security boundary — "
            "`python` and `git` are already on it."
        ),
    )
    enable_thinking: bool = Field(
        default=False,
        description="Forward Nvidia reasoning flags for models such as z-ai/glm-5.2.",
    )
    clear_thinking: bool = False
