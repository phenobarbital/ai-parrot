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
    llm: str = "nvidia:moonshotai/kimi-k2-instruct-0905"
    sandbox: Literal["workspace-write"] = "workspace-write"
    approval_policy: Literal["never"] = "never"
    timeout_seconds: int = Field(default=1800, ge=60, le=7200)
    max_turns: int = Field(default=24, ge=1, le=100)
    max_tokens: int = Field(default=4096, ge=256, le=32768)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    command_timeout_seconds: int = Field(default=300, ge=1, le=3600)
    allowed_commands: List[str] = Field(
        default_factory=lambda: [
            "git",
            "uv",
            "pytest",
            "python",
            "python3",
            "rg",
            "ls",
            "pwd",
            "cat",
            "sed",
            "find",
        ],
        description="Executable names allowed through the run_command tool.",
    )
    enable_thinking: bool = Field(
        default=False,
        description="Forward Nvidia reasoning flags for models such as z-ai/glm-5.1.",
    )
    clear_thinking: bool = False
