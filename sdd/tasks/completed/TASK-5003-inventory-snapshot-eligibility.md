# TASK-5003: Inventory snapshot, eligibility, supersession validation (M5)

**Feature**: FEAT-784 — SDD Decision Audit
**Spec**: `sdd/specs/sdd-decision-audit.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-5000, TASK-5001
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5, design-research S1/S4, audit F02/F03/F06, AC5/AC6/AC8/AC10/AC11. The consequence gate must
read the **complete** bounded decision inventory from one consistent snapshot — never the budgeted
`for_symbol()/why()/pack_dossier()` outputs (F02). This module is the single read root: it loads
`DecisionRepository.inventory()` (overflow ⇒ `ADR_INVENTORY_LIMIT` ⇒ `incomplete`; decode errors ⇒
diagnostics ⇒ `incomplete`), verifies approval batches, applies the one eligibility predicate, validates the
supersession graph into effective heads, and hashes everything into a `SnapshotManifest`. A second read
re-checks page hashes so a write racing the evaluation yields `SNAPSHOT_UNSTABLE` ⇒ `incomplete`.

It also owns the **batch-visibility marker** read side (decided at /sdd-task time — spec §8 open question):
one marker page per batch, id `adr-batch:<batch_id>`, category `adr_batch` (not `adr`, which `inventory()`
lists and would mis-decode). A batch counts as approved only when its approval verifies **and** its marker
state is `published`. TASK-5007 writes the markers.

---

## Scope

- Create `inventory.py`: `RULES_VERSION`, `BATCH_MARKER_CATEGORY`, `batch_marker_id`, `SnapshotManifest`,
  `is_eligible`, `InventorySnapshot` (`take`, `eligible`, `manifest`, `diagnostics`, `effective_head`, `governing`).
- Supersession validation (existence, acyclicity, identical canonical target sets, no competing effective
  successors, exact predecessor revision) ⇒ `SUPERSESSION_INVALID` diagnostics.
- Tests `test_inventory.py`.

**NOT in scope**: finding generation / status precedence (TASK-5005); writing records or markers (TASK-5007);
structural revision computation (passed in by the caller, TASK-5005).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/inventory.py` | CREATE | snapshot + eligibility |
| `packages/ai-parrot/tests/knowledge/wiki/decisions/test_inventory.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.decisions.models import (   # models.py:26,47,57,172,215 + TASK-4997
    _Strict, DecisionDiagnostic, DecisionError, DecisionRecord, DecisionRef,
    ADR_INVENTORY_LIMIT, SNAPSHOT_UNSTABLE, SUPERSESSION_INVALID, APPROVAL_UNVERIFIED,
)
from parrot.knowledge.wiki.decisions.codec import canonical_json      # codec.py:47
from parrot.knowledge.wiki.decisions.repository import DecisionRepository  # repository.py:26
from parrot.knowledge.wiki.decisions.taxonomy import Taxonomy          # TASK-5000
from parrot.knowledge.wiki.decisions.approvals import ApprovalAdapter, ApprovalManifest  # TASK-5001
from parrot.knowledge.wiki.store import BaseWikiStore                  # store.py (get_page :765, page_hashes :1074)
```

### Existing Signatures to Use
```python
# decisions/repository.py
class DecisionRepository:                                              # line 26
    def __init__(self, store: BaseWikiStore, max_records: int = 10_000) -> None   # line 29
    self.last_diagnostics: list[DecisionDiagnostic]                    # set by inventory(); decode failures
    async def inventory(self) -> list[DecisionRecord]                  # line 63 — list_pages(category="adr",
        # limit=max_records+1) (line 74); overflow ⇒ DecisionError(ADR_INVENTORY_LIMIT); deleted-between pages skipped
# decisions/codec.py
def canonical_json(record: DecisionRecord) -> str                      # line 47
# page content_hash = sha1(canonical_json(record)) (decision_to_page, codec.py:160-188: content_hash=_sha1(envelope))
# store.py
async def get_page(self, concept_id: str, include_body: bool = True) -> Optional[dict[str, Any]]   # line 765
async def page_hashes(self, concept_ids: list[str]) -> dict[str, Optional[str]]                   # line 1074
# decisions/approvals.py (TASK-5001)
class ApprovalManifest: entries: list[ApprovalEntry]; def digest(self) -> str
class ApprovalAdapter(Protocol): async def verify(self, entry, *, spec_text: str) -> tuple[bool, list[DecisionDiagnostic]]
# decisions/taxonomy.py (TASK-5000)
class Taxonomy: def digest(self) -> str
```

### Does NOT Exist
- ~~`DecisionService.for_symbol()/why()` / `pack_dossier()` as gate inputs~~ — budgeted, omit records (F02).
- ~~`review_status == "accepted"` as an eligibility requirement~~ — `parse_adr()` never sets it; requiring it would make every legacy ADR ineligible (F03, AC6).
- ~~multi-page transactions on `BaseWikiStore`~~ — batch atomicity is the marker page (one CAS).
- ~~`DecisionRepository.inventory_with_hashes()`~~ — no such method; recompute hashes as `sha1(canonical_json(r))`.
- ~~`ADR_UNSUPPORTED_SCHEMA`~~ — the code is `ADR_SCHEMA_UNSUPPORTED`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/decisions/inventory.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/decisions/test_inventory.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/repository.py#DecisionRepository",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/codec.py#canonical_json",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore"
  ]
}
```

---

## Implementation Notes

- **Signature extension (additive, keyword-only)**: the spec skeleton fixes
  `take(cls, repo, taxonomy, approvals, adapter, structural_revision)`. Reading marker pages and the current
  spec text for `adapter.verify(spec_text=...)` needs the store and the repo root, and the manifest needs a
  config digest, so `take` adds keyword-only `store: BaseWikiStore, root: Path, config_digest: str`. Positional
  order of the skeleton is unchanged. Record this in the Completion Note.
- **Eligibility** (spec §2, one predicate): `origin == "documented"` ∧ `source_status == "accepted"` ∧
  `review_status != "rejected"` ∧ `lifecycle == "active"` ∧ (legacy: `batch_id is None and decision_id.startswith("adr:doc:")`
  ∨ `batch_id in approved_batches`). Effective-under-supersession is applied after, in `eligible`.
- **Approved batches**: for each manifest entry of kind `spec`/`seed`: read `root / entry.spec_path` (missing ⇒
  `APPROVAL_UNVERIFIED` diagnostic, not approved); `await adapter.verify(entry, spec_text=...)`; then marker page
  `batch_marker_id(entry.batch_id)` must exist with JSON body `{"state": "published", ...}`.
- **Two-phase read**: phase 1 `records = await repo.inventory()`; `inventory = {r.decision_id: sha1(canonical_json(r))}`;
  phase 2 `await store.page_hashes(sorted(inventory))` must equal phase-1 hashes, and marker states re-read must be
  unchanged ⇒ else `raise DecisionError(SNAPSHOT_UNSTABLE, ...)`. Decode diagnostics from `repo.last_diagnostics`
  are copied into `diagnostics` (the evaluator maps any of them to `incomplete`).
- **Supersession** (v1 = full replacement only): for each eligible record with `supersedes_refs`, each ref must
  name an inventory record with exactly that revision, same sorted target-id set, no cycle across the graph, and no
  second eligible successor of the same predecessor; any violation ⇒ `SUPERSESSION_INVALID` diagnostic naming both
  ids, and NO repair (AC8). Predecessors with a valid eligible successor are dropped from `eligible`.
  A ref to a predecessor that is already historical (not eligible) ⇒ diagnostic listing active heads (AC8 last clause).
- **governing(about, scope_ids)**: eligible records where `set(r.about) & about` or any `t.target_id in scope_ids`
  or `r.decision_id in scope_ids` (explicit cross-domain refs passed by the caller); union by id; sorted by id.
  The full set is returned — no limit/budget here (AC5).

---

## Implementation Blueprint

### Steps (in order)
1. Constants, `batch_marker_id`, `SnapshotManifest`, `is_eligible` — *why*: pure, shared by TASK-5005/P11/P18.
2. `InventorySnapshot.__init__` holding computed state; `take()` classmethod doing approvals → phase 1 → eligibility → supersession → phase 2 → manifest.
3. `effective_head`, `governing`.
4. Tests on `adr_store` with records written via `DecisionRepository.save`.

### `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/inventory.py` (CREATE — part 1)
```python
"""Consistent decision inventory snapshot and the eligibility predicate (FEAT-784 Module 5)."""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

from parrot.knowledge.wiki.decisions.approvals import ApprovalAdapter, ApprovalManifest
from parrot.knowledge.wiki.decisions.codec import canonical_json
from parrot.knowledge.wiki.decisions.models import (
    APPROVAL_UNVERIFIED, SNAPSHOT_UNSTABLE, SUPERSESSION_INVALID,
    DecisionDiagnostic, DecisionError, DecisionRecord, DecisionRef, _Strict,
)
from parrot.knowledge.wiki.decisions.repository import DecisionRepository
from parrot.knowledge.wiki.decisions.taxonomy import Taxonomy
from parrot.knowledge.wiki.store import BaseWikiStore

RULES_VERSION = 1
#: Category of batch-visibility marker pages — deliberately NOT ``adr`` (inventory() lists category "adr").
BATCH_MARKER_CATEGORY = "adr_batch"

logger = logging.getLogger(__name__)


def batch_marker_id(batch_id: str) -> str:
    """Page id of a batch's visibility marker."""
    return f"adr-batch:{batch_id}"


def record_hash(record: DecisionRecord) -> str:
    """The page content_hash the codec stores for ``record`` (sha1 of the canonical envelope line)."""
    return hashlib.sha1(canonical_json(record).encode("utf-8")).hexdigest()  # noqa: S324 — identity, not security


class SnapshotManifest(_Strict):
    """Every input the evaluation depended on, hashed."""

    inventory: dict[str, str]
    taxonomy_digest: str
    approvals_digest: str
    structural_revision: str
    rules_version: int
    config_digest: str


def is_eligible(record: DecisionRecord, *, approved_batches: frozenset[str]) -> bool:
    """documented ∧ source_status=='accepted' ∧ review_status!='rejected' ∧ lifecycle=='active' ∧ (legacy adr:doc ∨ batch_id ∈ approved_batches)."""
    if record.origin != "documented" or record.source_status != "accepted":
        return False
    if record.review_status == "rejected" or record.lifecycle != "active":
        return False
    if record.batch_id is None:
        return record.decision_id.startswith("adr:doc:")
    return record.batch_id in approved_batches
```
**Why**: the predicate is verbatim spec §3 M5; `record_hash` mirrors codec.py's `content_hash=_sha1(envelope)` so
phase-2 page hashes compare directly (do not import the private `_sha1`).

### `inventory.py` (CREATE — part 2, same file)
```python
class InventorySnapshot:
    """One consistent read of inventory + taxonomy + approvals + structural revision."""

    def __init__(self, eligible: list[DecisionRecord], manifest: SnapshotManifest,
                 diagnostics: list[DecisionDiagnostic], heads: dict[str, DecisionRef]) -> None:
        self.eligible = eligible
        self.manifest = manifest
        self.diagnostics = diagnostics
        self._heads = heads

    @classmethod
    async def take(cls, repo: DecisionRepository, taxonomy: Taxonomy, approvals: ApprovalManifest,
                   adapter: ApprovalAdapter, structural_revision: str, *, store: BaseWikiStore,
                   root: Path, config_digest: str) -> "InventorySnapshot":
        """Two-phase read with revision recheck; raises DecisionError(ADR_INVENTORY_LIMIT|SNAPSHOT_UNSTABLE) ⇒ incomplete."""
        diagnostics: list[DecisionDiagnostic] = []
        # FILL IN: approved, markers = await cls._approved_batches(approvals, adapter, store, root, diagnostics)
        records = await repo.inventory()                      # ADR_INVENTORY_LIMIT propagates
        diagnostics.extend(repo.last_diagnostics)
        hashes = {r.decision_id: record_hash(r) for r in records}
        # FILL IN: candidates = [r for r in records if is_eligible(r, approved_batches=approved)]
        # FILL IN: eligible, heads = cls._validate_supersession(candidates, records, diagnostics) — AC8, no repair
        # FILL IN: phase 2 — await store.page_hashes(sorted(hashes)) != hashes, or re-read marker states != markers
        #          ⇒ raise DecisionError(SNAPSHOT_UNSTABLE, "...") — AC10/AC11
        manifest = SnapshotManifest(inventory=hashes, taxonomy_digest=taxonomy.digest(),
                                    approvals_digest=approvals.digest(), structural_revision=structural_revision,
                                    rules_version=RULES_VERSION, config_digest=config_digest)
        return cls(sorted(eligible, key=lambda r: r.decision_id), manifest, diagnostics, heads)

    @staticmethod
    async def _approved_batches(approvals: ApprovalManifest, adapter: ApprovalAdapter, store: BaseWikiStore,
                                root: Path, diagnostics: list[DecisionDiagnostic]) -> tuple[frozenset[str], dict[str, str]]:
        """(approved batch ids, {batch_id: marker state}) — approved = verified approval ∧ marker 'published'."""
        # FILL IN: per Implementation Notes "Approved batches"; marker body = json.loads(page["body"]);
        #          unreadable marker ⇒ treat as not published (no diagnostic needed; absence is normal before publish)
        return frozenset(), {}

    @staticmethod
    def _validate_supersession(candidates: list[DecisionRecord], records: list[DecisionRecord],
                               diagnostics: list[DecisionDiagnostic]) -> tuple[list[DecisionRecord], dict[str, DecisionRef]]:
        """Drop validly-superseded predecessors; report every violation as SUPERSESSION_INVALID (never repair)."""
        # FILL IN: existence + exact revision; identical sorted target-id sets; cycle detection (DFS over
        #          supersedes_refs); competing successors; historical predecessor ⇒ diagnostic naming active heads.
        #          heads[decision_id] = DecisionRef of the effective record for every chain member — AC8
        return candidates, {r.decision_id: DecisionRef(decision_id=r.decision_id, revision=r.revision) for r in candidates}

    def effective_head(self, decision_id: str) -> DecisionRef | None:
        """The effective (id, revision) a decision resolves to, or ``None`` when it is not effective."""
        return self._heads.get(decision_id)

    def governing(self, about: set[str], scope_ids: set[str]) -> list[DecisionRecord]:
        """union by canonical id; explicit cross-domain refs included."""
        # FILL IN: per Implementation Notes "governing" — full set, sorted by decision_id, no limit (AC5)
        return []
```
**Why this shape**: `eligible`, `manifest`, `diagnostics`, `effective_head`, `governing` are fixed by the spec
skeleton; supersession is validated against the full inventory (not just candidates) so a ref to a historical
or rejected predecessor is detected rather than silently ignored.

### `packages/ai-parrot/tests/knowledge/wiki/decisions/test_inventory.py` (CREATE)
```python
"""FEAT-784 M5 — inventory snapshot and eligibility."""

from __future__ import annotations

import pytest

from parrot.knowledge.wiki.decisions.inventory import InventorySnapshot, batch_marker_id, is_eligible
from parrot.knowledge.wiki.decisions.models import DecisionRecord


class _OkAdapter:
    async def verify(self, entry, *, spec_text):
        return True, []


def test_eligibility_predicate():
    """AC6: legacy accepted+unreviewed eligible; rejected/retired not; spec record w/o approved batch not."""
    # FILL IN: parametrize-style asserts over hand-built DecisionRecords (schema 1 legacy adr:doc:..., schema 2 adr:spec:...)


async def test_snapshot_collects_full_inventory(adr_store, tmp_path):
    """AC5: >50 eligible records all present in snapshot.eligible (no limit)."""
    # FILL IN: save 60 legacy accepted records via DecisionRepository(adr_store).save(rec, None); take(); len == 60


async def test_unpublished_batch_invisible(adr_store, tmp_path):
    # FILL IN: approved entry but marker state "pending" (or absent) ⇒ batch records not eligible; "published" ⇒ eligible


@pytest.mark.parametrize("case", ["cycle", "changed_revision", "competing", "partial_targets"])
async def test_supersession_graph_validation(adr_store, tmp_path, case):
    """AC8: each case ⇒ SUPERSESSION_INVALID diagnostic, nothing repaired."""
    # FILL IN


async def test_snapshot_unstable_is_incomplete(adr_store, tmp_path, monkeypatch):
    """A page hash changing between phases ⇒ DecisionError(SNAPSHOT_UNSTABLE)."""
    # FILL IN: monkeypatch adr_store.page_hashes to return a different hash for one id


async def test_inventory_overflow_raises(adr_store, tmp_path):
    # FILL IN: DecisionRepository(adr_store, max_records=1) with 2 records ⇒ DecisionError ADR_INVENTORY_LIMIT


def test_manifest_changes_with_inputs():
    """AC10 groundwork: taxonomy/approvals/structural/config digests all land in the manifest."""
    # FILL IN
```

### FILL IN checklist
- [ ] `take` approvals → eligibility → supersession → phase-2 recheck — AC5/AC6/AC10/AC11
- [ ] `_approved_batches` marker semantics — decision "batch marker" above
- [ ] `_validate_supersession` — AC8
- [ ] `governing` — AC5, AC7 (scope ids include ancestors supplied by caller)
- [ ] tests (fixtures write `approvals.jsonl` + spec file in `tmp_path`, marker page via `adr_store.upsert_pages`)

---

## Acceptance Criteria

- [ ] AC6 predicate holds exactly; unpublished/unverified batches are invisible.
- [ ] All eligible records returned regardless of count (AC5); overflow ⇒ `ADR_INVENTORY_LIMIT`.
- [ ] Supersession violations ⇒ `SUPERSESSION_INVALID`, never repaired (AC8).
- [ ] Hash change between phases ⇒ `SNAPSHOT_UNSTABLE`.
- [ ] Only `inventory.py` lists pages (through `DecisionRepository`); `ruff check` clean.

## Validation Commands
- `pytest packages/ai-parrot/tests/knowledge/wiki/decisions/test_inventory.py -q`

---

## Test Specification

See blueprint test block (spec §4 `test_eligibility_predicate`, `test_supersession_graph_validation`, `test_snapshot_unstable_is_incomplete`).

---

## Agent Instructions

1. Worktree `feat-FEAT-784-sdd-decision-audit`; TASK-5000 and TASK-5001 `done`.
2. Implement; complete FILL INs; run Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
3. Commit only the two files; `scripts/sdd/close_task.sh TASK-5003 sdd-decision-audit verified`.
4. Note the keyword-only `take()` extension in the Completion Note.

---

## Completion Note

Seat: gpt-5.6-terra · Backend: codex · Model: gpt-5.6-terra · Attempts: 1 · Duration: 268s · Tokens: n/a

- Delivered files match the task list.
- Merge-tier validation: 223 passed, 1 failed — pre-existing env-gated test_backend_parity_is_reported (fails identically on origin/dev). No review fixes.
