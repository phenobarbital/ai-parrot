"""Spec ``## Decisions`` block parser (FEAT-784 Module 2).

Multi-entry, never-raising parser for the structured decision block a spec (or a seed ADR's
``## Decision Metadata``) declares. Identity is ``adr:spec:<document_id>#<entry_id>``.
"""

from __future__ import annotations

import json
import re
from typing import Literal

import yaml
from pydantic import Field, ValidationError

from parrot.knowledge.wiki.decisions.codec import spec_decision_id
from parrot.knowledge.wiki.decisions.models import (
    SPEC_BLOCK_INVALID_YAML,
    SPEC_BLOCK_MISSING,
    SPEC_DANGLING_REF,
    SPEC_DUPLICATE_ENTRY_ID,
    SPEC_EMPTY_ABOUT,
    SPEC_EMPTY_TARGETS,
    SPEC_INVALID_ID,
    SPEC_UNKNOWN_FIELD,
    DecisionDiagnostic,
    DecisionRecord,
    DecisionRef,
    DecisionTarget,
    _Strict,
)

DECISIONS_HEADING = "## Decisions"
WAIVERS_HEADING = "## Decision Waivers"
SEED_HEADING = "## Decision Metadata"
_ENTRY_ID = re.compile(r"^[a-z0-9_-]+$")


class SpecDecisionEntry(_Strict):
    """One authored decision entry."""

    id: str
    statement: str = Field(..., min_length=1)
    relation: Literal["constrains", "forbids", "requires"]
    about: list[str]
    targets: list[str]
    revision: int = Field(default=1, ge=1)
    previous_revision: int | None = None
    contradicts: list[DecisionRef] = Field(default_factory=list)
    supersedes: list[DecisionRef] = Field(default_factory=list)
    rationale: str = ""
    rejected_alternatives: list[str] = Field(default_factory=list)


class SpecDecisionsBlock(_Strict):
    """The versioned block."""

    schema_version: Literal[1]
    document_id: str
    entries: list[SpecDecisionEntry]


class ConflictWaiver(_Strict):
    """An approved waiver bound to one finding and its exact participants."""

    finding_fingerprint: str = Field(..., min_length=1)
    participants: list[DecisionRef]
    actor: str = Field(..., min_length=1)
    reason: str = Field(..., min_length=1)
    approval_ref: str = Field(..., min_length=1)


def extract_block(text: str, heading: str) -> tuple[str | None, int, int]:
    """Return ``(yaml_source, start_line, end_line)`` of a fenced YAML block under ``heading``.

    Lines are 1-based and refer to the YAML body (fences excluded); ``(None, 0, 0)`` is returned when
    the heading or its fenced block is absent. The search stops at the next ``## `` heading.
    """
    lines = text.splitlines(keepends=True)
    heading_index = next((index for index, line in enumerate(lines) if line.rstrip() == heading), None)
    if heading_index is None:
        return None, 0, 0

    fence_index: int | None = None
    for index in range(heading_index + 1, len(lines)):
        stripped = lines[index].rstrip()
        if stripped.startswith("## "):
            return None, 0, 0
        if stripped.startswith("```yaml"):
            fence_index = index
            break
    if fence_index is None:
        return None, 0, 0

    body: list[str] = []
    for index in range(fence_index + 1, len(lines)):
        if lines[index].rstrip() == "```":
            return "".join(body), fence_index + 2, index
        body.append(lines[index])
    return None, 0, 0


def canonical_block_bytes(block: SpecDecisionsBlock) -> bytes:
    """Return deterministic JSON used by approvals and digests."""
    return json.dumps(block.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def _diag(code: str, message: str, source_path: str, decision_id: str | None = None) -> DecisionDiagnostic:
    """Create a parser diagnostic bound to its source document."""
    return DecisionDiagnostic(code=code, message=message, path=source_path, decision_id=decision_id)


def _validation_diagnostics(exc: ValidationError, source_path: str) -> list[DecisionDiagnostic]:
    """Map Pydantic errors into the stable parser diagnostic vocabulary."""
    diagnostics: list[DecisionDiagnostic] = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"])
        if error["type"] == "extra_forbidden":
            code = SPEC_UNKNOWN_FIELD
        elif any(part in {"id", "document_id", "decision_id"} for part in error["loc"]):
            code = SPEC_INVALID_ID
        else:
            code = SPEC_BLOCK_INVALID_YAML
        diagnostics.append(_diag(code, f"{location}: {error['msg']}", source_path))
    return diagnostics


def parse_spec_decisions(
    text: str, *, source_path: str, heading: str = DECISIONS_HEADING
) -> tuple[SpecDecisionsBlock | None, list[ConflictWaiver], list[DecisionDiagnostic]]:
    """Parse and validate a decisions block and optional waivers without raising.

    ``heading`` is ``DECISIONS_HEADING`` for specs and ``SEED_HEADING`` for seed ADRs. A missing block
    yields ``(None, [], [SPEC_BLOCK_MISSING])``; callers determine whether it is required.
    """
    source, _, _ = extract_block(text, heading)
    if source is None:
        return None, [], [_diag(SPEC_BLOCK_MISSING, f"no fenced yaml block under {heading!r}", source_path)]
    try:
        raw = yaml.safe_load(source)
    except yaml.YAMLError as exc:
        return None, [], [_diag(SPEC_BLOCK_INVALID_YAML, str(exc), source_path)]
    try:
        block = SpecDecisionsBlock.model_validate(raw)
    except ValidationError as exc:
        return None, [], _validation_diagnostics(exc, source_path)

    diagnostics: list[DecisionDiagnostic] = []
    document_id_valid = bool(_ENTRY_ID.fullmatch(block.document_id))
    if not document_id_valid:
        diagnostics.append(_diag(SPEC_INVALID_ID, "invalid document_id", source_path))

    entry_ids = [entry.id for entry in block.entries]
    for entry in block.entries:
        decision_id: str | None = None
        if not _ENTRY_ID.fullmatch(entry.id):
            diagnostics.append(_diag(SPEC_INVALID_ID, f"invalid entry id {entry.id!r}", source_path, entry.id))
        elif document_id_valid:
            decision_id = spec_decision_id(block.document_id, entry.id)
        if not entry.about:
            diagnostics.append(_diag(SPEC_EMPTY_ABOUT, "about must not be empty", source_path, decision_id))
        if not entry.targets:
            diagnostics.append(_diag(SPEC_EMPTY_TARGETS, "targets must not be empty", source_path, decision_id))
        if entry.previous_revision is not None and entry.previous_revision != entry.revision - 1:
            diagnostics.append(
                _diag(SPEC_INVALID_ID, "previous_revision must equal revision - 1", source_path, decision_id)
            )

    duplicate_ids = {entry_id for entry_id in entry_ids if entry_ids.count(entry_id) > 1}
    for entry_id in sorted(duplicate_ids):
        diagnostics.append(_diag(SPEC_DUPLICATE_ENTRY_ID, f"duplicate entry id {entry_id!r}", source_path, entry_id))

    local_prefix = f"adr:spec:{block.document_id}#"
    known_ids = set(entry_ids)
    for entry in block.entries:
        for reference in [*entry.contradicts, *entry.supersedes]:
            if reference.decision_id.startswith(local_prefix):
                target_entry_id = reference.decision_id.removeprefix(local_prefix)
                if target_entry_id not in known_ids:
                    diagnostics.append(
                        _diag(
                            SPEC_DANGLING_REF,
                            f"reference {reference.decision_id!r} does not name an entry in this block",
                            source_path,
                            reference.decision_id,
                        )
                    )

    waivers: list[ConflictWaiver] = []
    if heading == DECISIONS_HEADING:
        waiver_source, _, _ = extract_block(text, WAIVERS_HEADING)
        if waiver_source is not None:
            try:
                raw_waivers = yaml.safe_load(waiver_source)
            except yaml.YAMLError as exc:
                diagnostics.append(_diag(SPEC_BLOCK_INVALID_YAML, str(exc), source_path))
            else:
                if not isinstance(raw_waivers, list):
                    diagnostics.append(_diag(SPEC_BLOCK_INVALID_YAML, "waivers block must be a list", source_path))
                else:
                    for index, raw_waiver in enumerate(raw_waivers):
                        try:
                            waivers.append(ConflictWaiver.model_validate(raw_waiver))
                        except ValidationError as exc:
                            for diagnostic in _validation_diagnostics(exc, source_path):
                                diagnostics.append(
                                    diagnostic.model_copy(update={"message": f"waivers.{index}: {diagnostic.message}"})
                                )

    return (None if diagnostics else block), waivers, diagnostics


def entries_to_records(block: SpecDecisionsBlock, *, source_path: str, batch_id: str | None) -> list[DecisionRecord]:
    """Map entries to accepted, active schema-2 decision records."""
    records: list[DecisionRecord] = []
    for entry in block.entries:
        targets = [DecisionTarget(target_id=target_id, kind=_kind_of(target_id)) for target_id in entry.targets]
        records.append(
            DecisionRecord(
                schema_version=2,
                decision_id=spec_decision_id(block.document_id, entry.id),
                revision=entry.revision,
                title=entry.id,
                decision=entry.statement,
                normative=entry.relation,
                about=entry.about,
                targets=targets,
                contradicts=entry.contradicts,
                supersedes_refs=entry.supersedes,
                document_id=block.document_id,
                entry_id=entry.id,
                batch_id=batch_id,
                lifecycle="active",
                rationale=entry.rationale,
                rejected_alternatives=entry.rejected_alternatives,
                origin="documented",
                source_status="accepted",
                source_path=source_path,
            )
        )
    return records


def _kind_of(target_id: str) -> str:
    """Return the structural kind dictated by a decision target prefix."""
    for prefix, kind in (("sym:", "symbol"), ("file:", "file"), ("dir:", "dir")):
        if target_id.startswith(prefix):
            return kind
    return "file"
