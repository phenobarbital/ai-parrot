# TASK-4999: Spec `## Decisions` block parser (M2)

**Feature**: FEAT-784 — SDD Decision Audit
**Spec**: `sdd/specs/sdd-decision-audit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4997, TASK-4998
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2. A spec declares decisions in a versioned fenced-YAML block under `## Decisions`
(optional waivers under `## Decision Waivers`); seed ADRs carry one entry under `## Decision Metadata`.
`parse_adr()` is one-record-per-path (audit F04) and its frontmatter reader rejects multiline lists
(parser.py:180), so a dedicated multi-entry parser is required. It never raises: every fault is a
`DecisionDiagnostic` with a stable `SPEC_*` code. Its canonical block bytes feed approvals (TASK-5001)
and digests (TASK-5004).

---

## Scope

- Create `spec_entries.py` with `SpecDecisionEntry`, `SpecDecisionsBlock`, `ConflictWaiver`, the three
  heading constants, `extract_block`, `canonical_block_bytes`, `parse_spec_decisions`, `entries_to_records`.
- Error codes: `SPEC_BLOCK_MISSING`, `SPEC_BLOCK_INVALID_YAML`, `SPEC_DUPLICATE_ENTRY_ID`, `SPEC_INVALID_ID`,
  `SPEC_UNKNOWN_FIELD`, `SPEC_DANGLING_REF`, `SPEC_EMPTY_ABOUT`, `SPEC_EMPTY_TARGETS` (constants from TASK-4997).
- Tests `test_spec_entries.py`.

**NOT in scope**: validating `about` against the taxonomy (TASK-5000/P09), resolving targets (TASK-5002),
approval verification (TASK-5001). `SPEC_DANGLING_REF` here means only an intra-document reference
(`adr:spec:<same document_id>#<x>`) to an entry id that is not in the block; cross-document refs are
checked against the inventory in TASK-5005.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/spec_entries.py` | CREATE | block models + parser |
| `packages/ai-parrot/tests/knowledge/wiki/decisions/test_spec_entries.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import yaml  # PyYAML, core dependency — verified usage: parrot/knowledge/okf/frontmatter.py:25
from pydantic import Field, ValidationError
from parrot.knowledge.wiki.decisions.models import (  # models.py:57,172,215 (+ TASK-4997 symbols/codes)
    _Strict, DecisionRecord, DecisionDiagnostic, DecisionRef, DecisionTarget,
    SPEC_BLOCK_MISSING, SPEC_BLOCK_INVALID_YAML, SPEC_DUPLICATE_ENTRY_ID, SPEC_INVALID_ID,
    SPEC_UNKNOWN_FIELD, SPEC_DANGLING_REF, SPEC_EMPTY_ABOUT, SPEC_EMPTY_TARGETS,
)
from parrot.knowledge.wiki.decisions.codec import spec_decision_id  # TASK-4998
```

### Existing Signatures to Use
```python
# models.py
class DecisionDiagnostic(_Strict):   # line 215 — code: str, message: str = "", path: str | None, decision_id: str | None
class DecisionRecord(_Strict):       # line 172 — decision: str (min_length=1), origin: Literal["documented","inferred"],
                                     #   source_status Literal[...,"accepted",...], source_path: str | None,
                                     #   + schema-2 fields from TASK-4997
# codec.py (TASK-4998)
def spec_decision_id(document_id: str, entry_id: str) -> str   # raises DecisionError(ADR_INVALID_ID)
```

### Does NOT Exist
- ~~`parse_adr(..., multi=True)`~~ / ~~frontmatter `targets:`/`about:` keys~~ — `parse_adr` is single-record and `FRONTMATTER_KEYS` is `id/title/status/supersedes` only (parser.py:28). Do not extend it.
- ~~`yaml.load`~~ — always `yaml.safe_load`.
- ~~`SpecDecisionEntry.kind`~~ — target kind is derived from the prefix when building `DecisionTarget`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/decisions/spec_entries.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/decisions/test_spec_entries.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py#DecisionDiagnostic",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py#DecisionRecord"
  ]
}
```

---

## Implementation Notes

- Grammar (spec §3 M10 seed example): top-level `schema_version: 1`, `document_id`, `entries: [ {id, statement,
  relation, about, targets, revision?, previous_revision?, contradicts?, supersedes?, rationale?,
  rejected_alternatives?} ]`. Waivers block: a YAML list of `ConflictWaiver` mappings.
- Unknown keys: `_Strict` raises `extra_forbidden` → map to `SPEC_UNKNOWN_FIELD`; other validation errors →
  `SPEC_INVALID_ID` for id-shaped fields else `SPEC_BLOCK_INVALID_YAML` (FILL IN mapping, keep codes stable).
- `canonical_block_bytes`: `json.dumps(block.model_dump(mode="json"), sort_keys=True, separators=(",", ":"),
  ensure_ascii=False).encode("utf-8")` — same convention as `codec.canonical_json` (codec.py:47–49).
- Record mapping: `decision=statement`, `title=entry.id`, `normative=relation`, `targets=[DecisionTarget(...)]`,
  `supersedes_refs=entry.supersedes`, `document_id`, `entry_id`, `batch_id`, `revision=entry.revision`,
  `origin="documented"`, `source_status="accepted"`, `lifecycle="active"`, `schema_version=2`, `source_path`.

---

## Implementation Blueprint

### Steps (in order)
1. Write the models and constants — *why*: shape fixed by spec §2 Data Models.
2. Implement `extract_block` with a line scan — *why*: line numbers feed diagnostics and the renderer.
3. Implement `parse_spec_decisions` collecting diagnostics, never raising — *why*: invalid content must surface as status `invalid`, not a crash (spec §3 M6 "never raises for spec faults").
4. Implement `entries_to_records`.
5. Tests covering every error code.

### `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/spec_entries.py` (CREATE)
```python
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
    SPEC_BLOCK_INVALID_YAML, SPEC_BLOCK_MISSING, SPEC_DANGLING_REF, SPEC_DUPLICATE_ENTRY_ID,
    SPEC_EMPTY_ABOUT, SPEC_EMPTY_TARGETS, SPEC_INVALID_ID, SPEC_UNKNOWN_FIELD,
    DecisionDiagnostic, DecisionRecord, DecisionRef, DecisionTarget, _Strict,
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
    """Return ``(yaml_source, start_line, end_line)`` of the first fenced yaml block under ``heading``.

    Lines are 1-based and refer to the YAML body (fences excluded); ``(None, 0, 0)`` when the heading or
    its fenced block is absent. The search stops at the next ``## `` heading.
    """
    # FILL IN: scan lines; find a line == heading (rstrip); then the first line starting with "```yaml"
    #          before the next "## " heading; collect until the closing "```" — bounded by spec §3 M2
    return None, 0, 0


def canonical_block_bytes(block: SpecDecisionsBlock) -> bytes:
    """Deterministic JSON (sorted keys, UTF-8, compact) used by approvals and digests."""
    return json.dumps(
        block.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
```
*(continued in the next block — same file)*

```python
def _diag(code: str, message: str, source_path: str, decision_id: str | None = None) -> DecisionDiagnostic:
    return DecisionDiagnostic(code=code, message=message, path=source_path, decision_id=decision_id)


def parse_spec_decisions(
    text: str, *, source_path: str, heading: str = DECISIONS_HEADING
) -> tuple[SpecDecisionsBlock | None, list[ConflictWaiver], list[DecisionDiagnostic]]:
    """Parse and validate the decisions block (+ waivers); never raises.

    ``heading`` is ``DECISIONS_HEADING`` for specs and ``SEED_HEADING`` for seed ADRs. A missing block yields
    ``(None, [], [SPEC_BLOCK_MISSING])`` — callers decide whether absence is an error (a no-decision spec is
    valid, spec §7 edge cases).
    """
    diagnostics: list[DecisionDiagnostic] = []
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
        # FILL IN: map each error: type "extra_forbidden" → SPEC_UNKNOWN_FIELD; otherwise SPEC_BLOCK_INVALID_YAML;
        #          one diagnostic per error (loc joined with ".") — bounded by spec §3 M2 code list
        return None, [], diagnostics
    # FILL IN: document_id / entry ids must match _ENTRY_ID → SPEC_INVALID_ID
    # FILL IN: duplicate entry ids → SPEC_DUPLICATE_ENTRY_ID
    # FILL IN: empty about → SPEC_EMPTY_ABOUT; empty targets → SPEC_EMPTY_TARGETS
    # FILL IN: contradicts/supersedes refs whose decision_id starts with f"adr:spec:{block.document_id}#"
    #          must name an entry id present in the block → else SPEC_DANGLING_REF
    # FILL IN: previous_revision, when set, must equal revision - 1 → SPEC_INVALID_ID (revisions pin, AC3)
    waivers: list[ConflictWaiver] = []
    if heading == DECISIONS_HEADING:
        # FILL IN: extract WAIVERS_HEADING block (optional); safe_load → list; validate each ConflictWaiver;
        #          failures → SPEC_BLOCK_INVALID_YAML / SPEC_UNKNOWN_FIELD diagnostics
        pass
    return (None if diagnostics else block), waivers, diagnostics


def entries_to_records(
    block: SpecDecisionsBlock, *, source_path: str, batch_id: str | None
) -> list[DecisionRecord]:
    """Map entries to schema-2 records (origin='documented', source_status='accepted', lifecycle='active')."""
    records: list[DecisionRecord] = []
    for entry in block.entries:
        targets = [DecisionTarget(target_id=t, kind=_kind_of(t)) for t in entry.targets]
        # FILL IN: build DecisionRecord(schema_version=2, decision_id=spec_decision_id(block.document_id, entry.id),
        #          revision=entry.revision, title=entry.id, decision=entry.statement, normative=entry.relation,
        #          about=entry.about, targets=targets, contradicts=entry.contradicts, supersedes_refs=entry.supersedes,
        #          document_id=..., entry_id=entry.id, batch_id=batch_id, rationale, rejected_alternatives,
        #          origin="documented", source_status="accepted", source_path=source_path) — spec §3 M2
        pass
    return records


def _kind_of(target_id: str) -> str:
    """``sym:``→symbol, ``file:``→file, ``dir:``→dir; anything else → "file" so DecisionTarget's validator rejects it."""
    # FILL IN: prefix dispatch — an invalid prefix must surface as a validation error, never be silently accepted
    return "file"
```
**Why this shape**: signatures are fixed by the spec §3 M2 skeleton (the `heading` keyword with a default is
the only addition — it is how the same grammar is reused for `## Decision Metadata`, as M2 requires). Returning
`None` for the block whenever any diagnostic exists keeps callers from evaluating a half-valid block.
Note: `entries_to_records` can raise `ValidationError` on a bad target prefix — callers only call it on a block
that parsed without diagnostics, and TASK-5002 resolves targets before records are built.

### `packages/ai-parrot/tests/knowledge/wiki/decisions/test_spec_entries.py` (CREATE)
```python
"""FEAT-784 M2 — spec Decisions block parser."""

from __future__ import annotations

import pytest

from parrot.knowledge.wiki.decisions.spec_entries import (
    SEED_HEADING, canonical_block_bytes, entries_to_records, extract_block, parse_spec_decisions,
)

FENCE = "`" * 3  # built at runtime so this file nests inside markdown fences
GOOD = f'''# Spec

## Decisions

{FENCE}yaml
schema_version: 1
document_id: feat-784
entries:
  - id: one
    statement: Clients never persist history.
    relation: forbids
    about: [clients, memory]
    targets: [dir:packages/ai-parrot/src/parrot/clients]
  - id: two
    statement: Bots own history.
    relation: requires
    about: [memory]
    targets: [file:packages/ai-parrot/src/parrot/bots/abstract.py]
    contradicts: [{{decision_id: "adr:spec:feat-784#one", revision: 1}}]
{FENCE}
'''


def test_parse_spec_block_happy():
    block, waivers, diags = parse_spec_decisions(GOOD, source_path="sdd/specs/x.spec.md")
    assert diags == [] and block is not None and [e.id for e in block.entries] == ["one", "two"]


@pytest.mark.parametrize("mutation,code", [
    # FILL IN: one (text-transform, expected code) pair per error code:
    # SPEC_BLOCK_MISSING, SPEC_BLOCK_INVALID_YAML, SPEC_DUPLICATE_ENTRY_ID, SPEC_INVALID_ID,
    # SPEC_UNKNOWN_FIELD, SPEC_DANGLING_REF, SPEC_EMPTY_ABOUT, SPEC_EMPTY_TARGETS
])
def test_parse_spec_block_errors(mutation, code):
    block, _, diags = parse_spec_decisions(mutation(GOOD), source_path="x")
    assert block is None and code in {d.code for d in diags}


def test_canonical_block_bytes_stable():
    # FILL IN: reorder keys inside an entry → identical canonical bytes


def test_entries_to_records_ids_and_fields():
    # FILL IN: ids adr:spec:feat-784#one / #two; schema_version 2; targets kinds dir/file; batch_id propagated


def test_seed_heading_reuses_grammar():
    # FILL IN: GOOD with "## Decisions" replaced by SEED_HEADING parses with heading=SEED_HEADING


def test_extract_block_line_numbers():
    # FILL IN: start/end lines point at the yaml body lines
```

### FILL IN checklist
- [ ] `extract_block` scan — spec §3 M2
- [ ] ValidationError → code mapping; id/dup/empty/dangling/revision checks — spec §3 M2 codes, AC3
- [ ] waivers parsing
- [ ] `entries_to_records` record construction; `_kind_of`
- [ ] every parametrized error case

---

## Acceptance Criteria

- [ ] Every `SPEC_*` code is produced by at least one test case; parser never raises on malformed text.
- [ ] Two entries → distinct ids `adr:spec:<doc>#<entry>`; identity independent of `source_path` (AC3).
- [ ] Reordered YAML keys ⇒ identical canonical bytes.
- [ ] `ruff check` clean.

## Validation Commands
- `pytest packages/ai-parrot/tests/knowledge/wiki/decisions/test_spec_entries.py -q`

---

## Test Specification

See the `test_spec_entries.py` blueprint (spec §4 `test_parse_spec_block_happy_and_errors`, `test_canonical_block_bytes_stable`).

---

## Agent Instructions

1. Worktree `feat-FEAT-784-sdd-decision-audit`; TASK-4997 and TASK-4998 must be `done`.
2. Implement the blueprint; complete FILL INs; run Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
3. Commit only the two files; `scripts/sdd/close_task.sh TASK-4999 sdd-decision-audit verified`.

---

## Completion Note

*(filled in by the implementing agent)*
