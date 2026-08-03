"""Claude Code dispatch/review profiles for the dev-loop flow (FEAT-129/270)."""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class ClaudeCodeDispatchProfile(BaseModel):
    """Declarative profile consumed by ``ClaudeCodeDispatcher.dispatch()``.

    ``subagent`` selects a programmatic subagent from the ``agents=`` dict
    passed to the SDK; when ``None``, ``system_prompt_override`` is used
    and the dispatcher falls back to a generic session.
    """

    subagent: Optional[
        Literal[
            "sdd-research",
            "sdd-worker",
            "sdd-qa",
            "sdd-codereview",
            "sdd-planner",
            "sdd-feedback",
        ]
    ] = "sdd-worker"
    system_prompt_override: Optional[str] = None
    allowed_tools: List[str] = Field(default_factory=list)
    permission_mode: Literal["default", "acceptEdits", "plan", "bypassPermissions"] = "default"
    setting_sources: List[Literal["user", "project", "local"]] = Field(default_factory=lambda: ["project"])
    strict_mcp_config: bool = Field(
        default=True,
        description=(
            "When True (the default), the dispatched headless CLI ignores "
            "claude.ai account connectors and filesystem .mcp.json, using "
            "only MCP servers explicitly provided. This isolates server-side "
            "dispatches from the operator's interactive Claude Code "
            "environment, whose connector/OAuth setup (e.g. the claude.ai "
            "Design MCP connector) otherwise makes the non-interactive run "
            "exit with an empty error result. Set False only when a dispatch "
            "genuinely needs the inherited MCP surface."
        ),
    )
    timeout_seconds: int = Field(default=1800, ge=60, le=7200)
    model: str = "claude-sonnet-4-6"


class ClaudeCodeReviewProfile(ClaudeCodeDispatchProfile):
    """Review profile for the Claude Code review dispatcher (FEAT-270).

    Inherits ``ClaudeCodeDispatchProfile`` so it carries the ``setting_sources``
    and ``strict_mcp_config`` fields that ``ClaudeCodeDispatcher._resolve_run_options()``
    accesses. Overrides defaults for the write-enabled review use case: the
    ``sdd-codereview`` subagent is allowed to fix issues it finds and commit
    the fixes to the worktree branch.
    """

    subagent: Optional[Literal["sdd-research", "sdd-worker", "sdd-qa", "sdd-codereview"]] = "sdd-codereview"
    permission_mode: Literal["default", "acceptEdits", "plan", "bypassPermissions"] = "default"
    allowed_tools: List[str] = Field(
        default_factory=lambda: ["Read", "Write", "Edit", "Bash", "Grep", "Glob"]
    )
    model: str = "claude-sonnet-4-6"
    timeout_seconds: int = Field(default=1800, ge=60, le=7200)
