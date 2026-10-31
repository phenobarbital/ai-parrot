"""Consequence evaluation for spec-declared decisions (FEAT-784 Module 6).

This module half (TASK-5004) is pure: report models, finding fingerprints,
spec canonicalization and the two digests. The evaluator lives below the
``# --- evaluator (TASK-5005) ---`` marker.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Literal

from pydantic import Field

from parrot.knowledge.wiki.decisions.inventory import SnapshotManifest
from parrot.knowledge.wiki.decisions.models import DecisionDiagnostic, DecisionRef, _Strict

Status = Literal["pass", "skipped", "conflict", "invalid", "incomplete"]
FindingKind = Literal["contradiction", "potential-conflict", "possible-supersession", "blast-radius", "evidence-gap"]

#: Exit matrix (spec G5, AC11). Public contract — never renumber.
EXIT_CODES: dict[str, int] = {"pass": 0, "skipped": 0, "conflict": 1, "invalid": 2, "incomplete": 3}
_PRECEDENCE: tuple[str, ...] = ("invalid", "incomplete", "conflict", "pass")
GENERATED_HEADINGS: tuple[str, ...] = ("## Governing Decisions", "## Consequences")


def _canonical(obj: Any) -> bytes:
    """Return deterministic JSON bytes mirroring ``codec.canonical_json``."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha256(data: bytes) -> str:
    """Return the prefixed SHA-256 digest for ``data``."""
    return "sha256:" + hashlib.sha256(data).hexdigest()


class CoverageSummary(_Strict):
    """What the evaluation could and could not see."""

    subsystems: list[str] = Field(default_factory=list)
    unmapped_tags: list[str] = Field(default_factory=list)
    targets_resolved: int = 0
    targets_total: int = 0
    impact_complete: bool = True
    inventory_complete: bool = True
    omitted_ids: list[str] = Field(default_factory=list)


class Finding(_Strict):
    """One stable, fingerprinted consequence finding."""

    kind: FindingKind
    rule_version: int
    fingerprint: str
    participants: list[DecisionRef] = Field(default_factory=list)
    scope: list[str] = Field(default_factory=list)
    blocking: bool = False
    waived_by: str | None = None
    message: str = ""


class GoverningEntry(_Strict):
    """One eligible decision as shown in ``## Governing Decisions``."""

    decision_id: str
    revision: int
    title: str = ""
    statement: str = ""
    normative: str | None = None
    about: list[str] = Field(default_factory=list)
    targets: list[str] = Field(default_factory=list)
    rationale: str = ""
    consequences: str = ""
    supersedes: list[DecisionRef] = Field(default_factory=list)
    freshness: Literal["current", "stale", "missing", "unverified"] = "unverified"
    source_path: str | None = None


class GoverningDossier(_Strict):
    """The complete governing set; the token budget applies to rendering only."""

    entries: list[GoverningEntry] = Field(default_factory=list)
    omitted_ids: list[str] = Field(default_factory=list)
    searched_subsystems: list[str] = Field(default_factory=list)
    empty_plane: bool = False
    truncated: bool = False
    snapshot: SnapshotManifest | None = None


class ConsequenceReport(_Strict):
    """Result of evaluating one spec."""

    status: Status
    exit_code: int
    input_digest: str = ""
    evaluation_digest: str = ""
    snapshot: SnapshotManifest | None = None
    findings: list[Finding] = Field(default_factory=list)
    diagnostics: list[DecisionDiagnostic] = Field(default_factory=list)
    coverage: CoverageSummary = Field(default_factory=CoverageSummary)


def finding_fingerprint(kind: str, rule_version: int, participants: list[DecisionRef], scope: list[str]) -> str:
    """Return the stable fingerprint for one finding's identity fields."""
    payload = {
        "kind": kind,
        "rule_version": rule_version,
        "participants": sorted([participant.decision_id, participant.revision] for participant in participants),
        "scope": sorted(scope),
    }
    return _sha256(_canonical(payload))


def canonicalize_spec(text: str) -> bytes:
    """Strip generated sections and status, normalizing Markdown to UTF-8 bytes."""
    normalized_lines = [line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    retained: list[str] = []
    index = 0
    while index < len(normalized_lines):
        line = normalized_lines[index]
        if line in GENERATED_HEADINGS:
            index += 1
            while index < len(normalized_lines) and not normalized_lines[index].startswith("## "):
                index += 1
            continue
        if re.match(r"^\*\*Status\*\*:", line):
            index += 1
            continue
        retained.append(line)
        index += 1

    canonical_lines: list[str] = []
    for line in retained:
        if not line:
            if canonical_lines and canonical_lines[-1]:
                canonical_lines.append("")
            continue
        canonical_lines.append(line)
    if canonical_lines and not canonical_lines[-1]:
        canonical_lines.pop()
    return "\n".join(canonical_lines).encode("utf-8")


def input_digest(
    canonical_spec: bytes,
    block: bytes,
    waivers: bytes,
    config_digest: str,
    manifest: SnapshotManifest | None,
) -> str:
    """Return the digest of every input the evaluation reads."""
    payload = {
        "spec": hashlib.sha256(canonical_spec).hexdigest(),
        "block": hashlib.sha256(block).hexdigest(),
        "waivers": hashlib.sha256(waivers).hexdigest(),
        "config": config_digest,
        "manifest": None if manifest is None else manifest.model_dump(mode="json"),
    }
    return _sha256(_canonical(payload))


def evaluation_digest(input_digest_value: str, findings: list[Finding]) -> str:
    """Return the digest of inputs and canonical findings, independent of input order."""
    canonical_findings = sorted(
        (finding.model_dump(mode="json") for finding in findings),
        key=lambda finding: (finding["kind"], finding["fingerprint"]),
    )
    return _sha256(_canonical({"input": input_digest_value, "findings": canonical_findings}))


def status_precedence(statuses: list[str]) -> str:
    """Return the highest status: invalid, incomplete, conflict, then pass."""
    for status in _PRECEDENCE:
        if status in statuses:
            return status
    return "pass"


# --- evaluator (TASK-5005) ---
