"""Experience domain schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

LessonCategory = Literal["pitfall"]
LessonState = Literal["candidate", "confirmed", "quarantined", "retired"]
LessonTier = Literal["repo", "global"]
LessonSource = Literal["paired", "authored", "mined"]


class LessonTrigger(BaseModel):
    """LessonTrigger schema for experience memory."""

    model_config = ConfigDict(extra="forbid")

    executable: str
    subcommand: str = ""
    error_signature: str = ""
    error_excerpt: str = ""
    command_example: str = ""


class LessonDraft(BaseModel):
    """What an agent or the pairing logic submits. extra='forbid'."""

    model_config = ConfigDict(extra="forbid")

    category: LessonCategory = "pitfall"
    trigger: LessonTrigger
    symptom: str = ""
    solution: str
    fix_example: str = ""
    scope_paths: list[str] = Field(default_factory=list)


class Lesson(BaseModel):
    """Reduced view; never persisted as a source of truth."""

    lesson_id: str
    draft: LessonDraft
    solution_rev: str
    revisions: list[str]
    tier: LessonTier
    state: LessonState
    hits: int
    validations: int
    refutations: int
    sessions: int
    issue_id: str = ""
    issue_ledger: str = ""
    recorded_by: str
    recorded_at: str


class CommandOutcome(BaseModel):
    """CommandOutcome schema for experience memory."""

    model_config = ConfigDict(extra="forbid")

    command: str
    ok: bool | None
    error: str = ""
    observation_id: str = ""


class ExperienceConfig(BaseModel):
    """ExperienceConfig schema for experience memory."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    confirm_sessions: int = 2
    quarantine_refutations: int = 2
    graduate_hits: int = 5
    graduate_sessions: int = 3
    brief_max_entries: int = 5
    brief_token_budget: int = 400
    inject_min_score: float = 0.35
    advice_cooldown_seconds: int = 600
    max_triggers_bytes: int = 262144
    max_transcript_tail_bytes: int = 262144
    max_session_pending: int = 32
    pairing_excluded_executables: list[str] = Field(
        default_factory=lambda: [
            "pytest",
            "ruff",
            "mypy",
            "black",
            "pylint",
            "vitest",
            "cargo",
            "grep",
            "rg",
            "ls",
            "cat",
            "find",
            "test",
            "head",
            "tail",
            "wc",
        ]
    )
