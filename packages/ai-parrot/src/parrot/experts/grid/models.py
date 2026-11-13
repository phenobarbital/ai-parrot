"""Scope grid models (FEAT-890 M5)."""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from parrot.bots.flows.core.gates import GateSpec

StageMode = Literal["subagent", "pipeline", "mob", "inline"]


class ExpertStageConfig(BaseModel):
    """One stage of a scope.

    Attributes:
        stage: Stage name (unique within a grid).
        experts: Expert names taking part in the stage.
        mode: Dispatch mode.
        gate: Optional gate attached to the stage.
        synthesis: Optional synthesis instruction/name.
        strict: Whether failures are fatal.
        conductor: Conductor agent name (inline mode only).
    """

    model_config = ConfigDict(extra="forbid")

    stage: str
    experts: list[str] = Field(min_length=1)
    mode: StageMode
    gate: GateSpec | None = None
    synthesis: str | None = None
    strict: bool = False
    conductor: str | None = None

    @model_validator(mode="after")
    def _check_mode(self) -> "ExpertStageConfig":
        if self.mode == "subagent" and len(self.experts) != 1:
            raise ValueError("subagent mode requires exactly one expert")
        if self.mode == "inline" and not self.conductor:
            raise ValueError("inline mode requires a conductor")
        return self


class ScopeMatch(BaseModel):
    """Selector matching a grid to projects/tags."""

    model_config = ConfigDict(extra="forbid")

    projects: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class ScopeGrid(BaseModel):
    """A scope: an ordered list of expert stages."""

    model_config = ConfigDict(extra="forbid")

    scope: str
    description: str = ""
    match: ScopeMatch | None = None
    stages: list[ExpertStageConfig] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_stages(self) -> "ScopeGrid":
        names = [s.stage for s in self.stages]
        dupes = sorted({n for n in names if names.count(n) > 1})
        if dupes:
            raise ValueError(f"duplicate stage names: {', '.join(dupes)}")
        return self


class ScopeGridErrorCode(str, Enum):
    """Error codes raised while loading/compiling a scope grid."""

    UNKNOWN_EXPERT = "UNKNOWN_EXPERT"
    CAPABILITY_MISMATCH = "CAPABILITY_MISMATCH"
    UNKNOWN_GATE_KIND = "UNKNOWN_GATE_KIND"
    CYCLE = "CYCLE"
    INVALID = "INVALID"


class ScopeGridError(Exception):
    """Scope grid error carrying a :class:`ScopeGridErrorCode`."""

    def __init__(self, code: ScopeGridErrorCode, message: str) -> None:
        super().__init__(f"{code.value}: {message}")
        self.code = code
