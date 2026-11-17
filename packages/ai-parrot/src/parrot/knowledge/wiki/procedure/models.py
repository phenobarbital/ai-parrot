"""Procedure graph models (FEAT-891)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ProcedureMode = Literal["advisory", "mandatory", "constraint"]
ProcedureKind = Literal["command", "skill", "flow", "crew", "rule"]
ProcedureSource = Literal["authored", "learned"]
EdgeRel = Literal["requires", "next", "alternative_to", "escalates_to", "on_failure", "learned_from", "applies_to"]
ProbeCost = Literal["local", "remote"]
GuardKind = Literal["entry", "bypass"]

INDEX_SCHEMA_VERSION = 1
PLANE_DIR = Path(".parrot") / "procedure"
INDEX_FILE = "procedures.json"
#: ProcedureSpec field name -> edge relation.
EDGE_FIELDS: dict[str, str] = {
    "requires_procedures": "requires",
    "next": "next",
    "alternative_to": "alternative_to",
    "escalates_to": "escalates_to",
    "on_failure": "on_failure",
    "learned_from": "learned_from",
    "applies_to": "applies_to",
}


class ProbeCheck(BaseModel):
    """A registered probe and its expected value."""

    probe: str  # registered probe name
    expect: bool | str = True  # compared with the probe's value
    args: dict[str, str] = Field(default_factory=dict)


class ScopeArg(BaseModel):
    """Where a guard reads one scope value from a command line."""

    argv: int | None = None  # positional index after argv_prefix
    flag: str | None = None  # e.g. "--base"; alternatives separated by "|" ("--base|-B")

    @model_validator(mode="after")
    def _exactly_one(self) -> ScopeArg:
        """Require exactly one of ``argv`` and ``flag``."""
        if (self.argv is None) == (self.flag is None):
            raise ValueError("ScopeArg needs exactly one of 'argv' and 'flag'")
        return self


class GuardSpec(BaseModel):
    """A command guard associated with a procedure."""

    kind: GuardKind
    executable: str  # basename, e.g. "parrot", "gh", "mv", "git"
    argv_prefix: list[str] = Field(default_factory=list)  # e.g. ["sdd", "task", "close"]; for git mv: ["mv"]
    path_globs: list[str] = Field(default_factory=list)  # bypass: any argument must match one (repo-relative, fnmatch)
    scope: dict[str, ScopeArg] = Field(default_factory=dict)  # keys: "task", "feature", "base"


class ExecutorRef(BaseModel):
    """An inert v1 reference to an executable procedure implementation."""

    kind: Literal["flow", "crew", "command"]
    ref: str


class ProcedureSpec(BaseModel):
    """One procedure node, independent of how the procedure is implemented."""

    model_config = ConfigDict(extra="forbid")

    id: str  # "<producer>:<name>", kebab-case name
    title: str
    kind: ProcedureKind
    mode: ProcedureMode = "advisory"
    source: ProcedureSource = "authored"
    command: str = ""  # human-readable invocation, e.g. "parrot sdd task close <TASK> <slug> verified"
    intents: list[str] = Field(default_factory=list)
    applies_to: list[str] = Field(default_factory=list)  # entity type names
    scope_kind: Literal["repo", "feature", "task"] = "feature"
    preconditions: list[ProbeCheck] = Field(default_factory=list)
    done_when: list[ProbeCheck] = Field(default_factory=list)
    requires_procedures: list[str] = Field(default_factory=list)
    requires_facts: list[str] = Field(default_factory=list)
    requires_tools: list[str] = Field(default_factory=list)
    next: list[str] = Field(default_factory=list)
    alternative_to: list[str] = Field(default_factory=list)
    escalates_to: list[str] = Field(default_factory=list)
    on_failure: list[str] = Field(default_factory=list)
    learned_from: list[str] = Field(default_factory=list)
    guards: list[GuardSpec] = Field(default_factory=list)
    use_instead: str = ""  # required when any guard is "bypass"
    executor: ExecutorRef | None = None  # inert in v1
    confirm: bool = False  # inert in v1
    advice: str = ""  # <= 300 chars, shown in advisories and the briefing
    body: str = ""  # page body (skill body or manifest description)
    origin_path: str = ""  # repo-relative source file

    def edges(self) -> list[tuple[str, str, str]]:
        """Return ``(src, dst, rel)`` for every id listed in an edge field.

        ``applies_to`` targets are entity type names and are returned as ``type:<Name>``.
        """
        out: list[tuple[str, str, str]] = []
        for field_name, rel in EDGE_FIELDS.items():
            for target in getattr(self, field_name):
                dst = f"type:{target}" if field_name == "applies_to" else target
                out.append((self.id, dst, rel))
        return out


class ProcedureManifest(BaseModel):
    """A producer graph and its procedure specifications."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    graph: str  # producer prefix, e.g. "sdd"
    exclude: list[str] = Field(default_factory=list)  # overlay only: ids removed from the merged graph
    # ids written without the prefix; the producer adds it
    procedures: list[ProcedureSpec] = Field(default_factory=list)
    uncovered_ok: list[str] = Field(default_factory=list)


class ProbeResult(BaseModel):
    """The outcome of evaluating one probe check."""

    check: ProbeCheck
    value: bool | None  # None = unknown
    cost: ProbeCost
    detail: str = ""


class ResolvedProcedure(BaseModel):
    """A procedure enriched with probe results and readiness state."""

    spec: ProcedureSpec
    done: bool | None
    ready: bool  # every requires_procedures is done
    preconditions: list[ProbeResult]


class Resolution(BaseModel):
    """Procedures applicable to a resolved feature or task scope."""

    scope: dict[str, str]  # "feature", "task", "branch"
    stale: bool
    next: list[ResolvedProcedure]  # not done and ready, ordered
    mandatory: list[ProcedureSpec]  # mandatory nodes not yet done
