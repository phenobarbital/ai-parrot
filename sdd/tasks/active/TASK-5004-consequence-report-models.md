# TASK-5004: Consequence report models, digests and spec canonicalization (M6a)

**Feature**: FEAT-784 — SDD Decision Audit
**Spec**: `sdd/specs/sdd-decision-audit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5003
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6 splits into a pure, deterministic half (report models, finding fingerprints, input/evaluation
digests, spec canonicalization) and the evaluator itself (TASK-5005). This task creates
`decisions/consequences.py` with the pure half so the digest contract (spec §2 "input digest", "evaluation
digest"; audit F07 "digest self-reference") is fixed and unit-tested before any evaluation logic depends on it.
Every surface (render/check, gate script, MCP, CLI) compares these digests byte-for-byte (AC10, G5).

---

## Scope

- Create `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/consequences.py` with: `CoverageSummary`,
  `Finding`, `GoverningEntry`, `GoverningDossier`, `ConsequenceReport`, the `EXIT_CODES` map,
  `finding_fingerprint()`, `canonicalize_spec()`, `input_digest()`, `evaluation_digest()`, `status_precedence()`.
- Write `test_consequence_digests.py` covering canonicalization, digest stability and precedence.

**NOT in scope**: `ConsequenceService` (TASK-5005), Markdown rendering (TASK-5006), any I/O, any store access.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/consequences.py` | CREATE | Report models + pure digest/canonicalization functions |
| `packages/ai-parrot/tests/knowledge/wiki/decisions/test_consequence_digests.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.decisions.models import DecisionDiagnostic, _Strict  # verified: models.py:215, :57
from parrot.knowledge.wiki.decisions.models import DecisionRef               # created by TASK-4997 (spec §3 M1 skeleton)
from parrot.knowledge.wiki.decisions.inventory import SnapshotManifest       # created by TASK-5003 (spec §3 M5 skeleton)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py
class _Strict(BaseModel):                 # line 57 — model_config = ConfigDict(extra="forbid") (line 60)
class DecisionDiagnostic(_Strict):        # line 215
    code: str; message: str = ""; path: str | None = None; decision_id: str | None = None   # lines 218-221

# packages/ai-parrot/src/parrot/knowledge/wiki/decisions/codec.py
def canonical_json(record: DecisionRecord) -> str   # line 47 — json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False)
#   ↑ pattern to mirror for canonical bytes; do not call it (it takes a DecisionRecord).

# From TASK-5003 (inventory.py, spec §3 M5):
class SnapshotManifest(_Strict):
    inventory: dict[str, str]; taxonomy_digest: str; approvals_digest: str
    structural_revision: str; rules_version: int; config_digest: str
RULES_VERSION = 1
# From TASK-4997 (models.py): class DecisionRef(_Strict): decision_id: str; revision: int
```

### Does NOT Exist
- ~~`ConsequenceService` / `ConsequenceReport` / `Finding` / `GoverningDossier` / `GoverningEntry` / `CoverageSummary`~~ — all new here (service in TASK-5005).
- ~~`parrot.knowledge.wiki.decisions.consequences`~~ — the module does not exist yet; this task creates it.
- ~~`scripts/sdd/check_task_graph.Finding`~~ — a different, unrelated model (level/code/tasks/message); do NOT import or reuse it.
- ~~`ADR_UNSUPPORTED_SCHEMA`~~ — the code is `ADR_SCHEMA_UNSUPPORTED` (models.py:19).
- ~~`DecisionRecord.tags`~~ — no tag field on records.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/decisions/consequences.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/decisions/test_consequence_digests.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py#_Strict",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py#DecisionDiagnostic",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/codec.py#canonical_json"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Pure functions only: no `async`, no store, no filesystem, no clock (`datetime.now` forbidden — AC10 byte stability).
- Canonical JSON everywhere = `json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")`,
  mirroring `codec.canonical_json` (codec.py:47).
- Hashes are `sha256` hex prefixed `"sha256:"` — the approvals manifest and test contract already use this shape.
- `skipped` is a terminal status for unconfigured repos (spec §2 portability, G8) with exit 0.
- Status precedence (spec M6 docstring, AC11): `invalid > incomplete > conflict > pass`; `skipped` only when no
  other status applies AND the evaluator decided the repo is unconfigured — precedence must never produce `skipped`
  from a list containing anything else.

### References in Codebase
- `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/codec.py:47` — canonical JSON shape.
- `scripts/sdd/check_task_graph.py:77-100` — report-model style (Pydantic, `--json` dump).

---

## Implementation Blueprint

### Steps (in order)
1. Create `consequences.py` from the block below — *why*: TASK-5005/P10 attach to the anchors it defines
   (`class ConsequenceReport(_Strict):` and `# --- evaluator (TASK-5005) ---`), so keep those lines verbatim.
2. Implement `canonicalize_spec` — *why*: writing `## Governing Decisions`/`## Consequences` or flipping
   `**Status**:` must not change `input_digest` (spec §4 `test_digests_exclude_generated_sections`, F07).
3. Implement the two digests and the fingerprint exactly as specified — *why*: they are the replay/stale contract (AC10).
4. Write the tests, run validation.

### `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/consequences.py` (CREATE)
```python
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
    """Deterministic JSON bytes (mirrors codec.canonical_json, codec.py:47)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha256(data: bytes) -> str:
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
```
**Why this shape**: field names follow spec §2 Data Models verbatim. `snapshot` is optional because a
`skipped` (unconfigured) or early-`invalid` report has no snapshot — the evaluator must still return a report,
never raise (spec M6 docstring). Do not add fields beyond these without a spec change; TASK-5006 renders them all.

### `consequences.py` — functions (continue the same file, below `ConsequenceReport`)
```python
def finding_fingerprint(kind: str, rule_version: int, participants: list[DecisionRef], scope: list[str]) -> str:
    """sha256 of (kind, rule_version, sorted (id, revision) participants, sorted scope) — spec §3 M6."""
    payload = {
        "kind": kind,
        "rule_version": rule_version,
        "participants": sorted([p.decision_id, p.revision] for p in participants),
        "scope": sorted(scope),
    }
    return _sha256(_canonical(payload))


def canonicalize_spec(text: str) -> bytes:
    """Strip generated sections and the ``**Status**`` line; normalize newlines; UTF-8 bytes."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    # FILL IN: remove each GENERATED_HEADINGS section (heading line through the line before the next
    #   `^## ` heading or EOF) and every line matching r"^\*\*Status\*\*:" — bounded by spec §4
    #   test_digests_exclude_generated_sections: render twice / flip draft→approved ⇒ identical bytes.
    #   Also strip trailing whitespace per line and collapse the blank-line run left by a removed section
    #   to a single blank line, so "section absent" and "section present" canonicalize identically.
    return normalized.encode("utf-8")


def input_digest(canonical_spec: bytes, block: bytes, waivers: bytes, config_digest: str, manifest: SnapshotManifest | None) -> str:
    """Digest of everything the evaluation reads (spec §2)."""
    payload = {
        "spec": hashlib.sha256(canonical_spec).hexdigest(),
        "block": hashlib.sha256(block).hexdigest(),
        "waivers": hashlib.sha256(waivers).hexdigest(),
        "config": config_digest,
        "manifest": None if manifest is None else manifest.model_dump(mode="json"),
    }
    return _sha256(_canonical(payload))


def evaluation_digest(input_digest_value: str, findings: list[Finding]) -> str:
    """Input digest plus canonical findings, order-independent."""
    canon = sorted((f.model_dump(mode="json") for f in findings), key=lambda d: (d["kind"], d["fingerprint"]))
    return _sha256(_canonical({"input": input_digest_value, "findings": canon}))


def status_precedence(statuses: list[str]) -> str:
    """Highest-precedence status: invalid > incomplete > conflict > pass (AC11)."""
    # FILL IN: return the first of _PRECEDENCE present in `statuses`; empty list ⇒ "pass";
    #   never return "skipped" here (the evaluator sets it directly) — bounded by AC11.
    raise NotImplementedError


# --- evaluator (TASK-5005) ---
```
**Why**: the spec's `input_digest` skeleton names the `input_digest` parameter of `evaluation_digest` identically
to the function; renaming the parameter to `input_digest_value` avoids shadowing while keeping positional calls
compatible. `manifest` is optional so a skipped/invalid-before-snapshot report still gets a digest.

### FILL IN checklist
- [ ] `consequences.py::canonicalize_spec` — section/Status stripping; bounded by `test_digests_exclude_generated_sections`
- [ ] `consequences.py::status_precedence` — precedence order; bounded by AC11

---

## Acceptance Criteria

- [ ] Identical inputs ⇒ identical `input_digest`/`evaluation_digest` (AC10); finding order does not change `evaluation_digest`.
- [ ] Adding/removing `## Governing Decisions` / `## Consequences`, or editing the `**Status**:` line, does not change `canonicalize_spec` output.
- [ ] Any change to block bytes, waivers, config digest or any manifest field changes `input_digest`.
- [ ] `status_precedence(["conflict","invalid","incomplete"]) == "invalid"`; `EXIT_CODES` matches spec G5.
- [ ] `ruff check` clean on both files; no `async`, no I/O in the module.

---

## Validation Commands
- `pytest packages/ai-parrot/tests/knowledge/wiki/decisions/test_consequence_digests.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/wiki/decisions/test_consequence_digests.py
from parrot.knowledge.wiki.decisions.consequences import (
    EXIT_CODES, Finding, canonicalize_spec, evaluation_digest, finding_fingerprint, input_digest, status_precedence,
)
from parrot.knowledge.wiki.decisions.inventory import SnapshotManifest
from parrot.knowledge.wiki.decisions.models import DecisionRef

SPEC = "# T\n\n**Status**: draft\n\n## 2. Design\nbody\n"

def _manifest(**kw):
    base = dict(inventory={}, taxonomy_digest="t", approvals_digest="a", structural_revision="s", rules_version=1, config_digest="c")
    return SnapshotManifest(**{**base, **kw})

def test_status_line_and_generated_sections_ignored():
    with_sections = SPEC.replace("## 2.", "## Governing Decisions\nx\n\n## 2.") + "\n## Consequences\ny\n"
    assert canonicalize_spec(SPEC) == canonicalize_spec(SPEC.replace("draft", "approved")) == canonicalize_spec(with_sections)

def test_input_digest_sensitive_to_every_input():
    base = input_digest(b"s", b"b", b"w", "c", _manifest())
    assert base == input_digest(b"s", b"b", b"w", "c", _manifest())
    for variant in (input_digest(b"s", b"B", b"w", "c", _manifest()), input_digest(b"s", b"b", b"w", "c", _manifest(structural_revision="z"))):
        assert variant != base

def test_evaluation_digest_order_independent():
    # FILL IN: two Findings in both orders ⇒ equal digests
    ...

def test_fingerprint_sorted_participants():
    a, b = DecisionRef(decision_id="adr:x", revision=1), DecisionRef(decision_id="adr:y", revision=2)
    assert finding_fingerprint("contradiction", 1, [a, b], ["s2", "s1"]) == finding_fingerprint("contradiction", 1, [b, a], ["s1", "s2"])

def test_precedence_and_exit_codes():
    assert status_precedence(["conflict", "incomplete", "invalid"]) == "invalid"
    assert status_precedence([]) == "pass"
    assert EXIT_CODES == {"pass": 0, "skipped": 0, "conflict": 1, "invalid": 2, "incomplete": 3}
```

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug sdd-decision-audit --feature-id FEAT-784`).
2. Read spec §2 (Data Models), §3 Module 6, §7 F07.
3. Confirm TASK-5003 is `done` in `sdd/tasks/index/sdd-decision-audit.json` and `SnapshotManifest` exists in `inventory.py`.
4. Verify the Codebase Contract; update it first if anything drifted.
5. Mark in-progress, implement from the blueprint, complete every `FILL IN`, keep the `# --- evaluator (TASK-5005) ---` marker.
6. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
7. Commit only the listed files; close with `scripts/sdd/close_task.sh TASK-5004 sdd-decision-audit verified`.

---

## Completion Note

*(Agent fills this in when done)*
