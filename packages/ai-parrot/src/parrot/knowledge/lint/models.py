"""Lint engine data models (FEAT-625)."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

Severity = Literal["info", "warning", "error"]
SEVERITY_RANK: dict[str, int] = {"info": 0, "warning": 1, "error": 2}


class Finding(BaseModel):
    """One lint finding produced by a rule."""

    rule_id: str
    severity: Severity
    subjects: list[str] = Field(default_factory=list)
    message: str
    fixable: bool = False
    fingerprint: str
    data: dict[str, Any] = Field(default_factory=dict)


class FixResult(BaseModel):
    """Outcome of applying one fix."""

    fingerprint: str
    applied: bool
    detail: str = ""


class LintOptions(BaseModel):
    """Options controlling one lint run."""

    rules: list[str] | None = None
    skip: list[str] = Field(default_factory=list)
    fix: bool = False
    llm: bool = False
    llm_model: str | None = None
    llm_max_pairs: int = 50
    ledger: bool = True
    notes: bool = True
    ledger_cap_per_rule: int = 20
    fail_on: Severity | None = "error"
    export_dir: Path | None = None
    report_dir: Path | None = None


class LintReport(BaseModel):
    """Result of a lint run (findings are what remains after fixes)."""

    wiki_name: str = ""
    backend: str = ""
    rules_run: list[str] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    fixed: list[FixResult] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)
    started_at: str = ""
    duration_ms: int = 0
    routing: dict[str, int] = Field(default_factory=dict)
