# TASK-5007: Batch publisher and ingest extension (M8)

**Feature**: FEAT-784 — SDD Decision Audit
**Spec**: `sdd/specs/sdd-decision-audit.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-5005
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8 (owner: not delegation-eligible — partial-batch invisibility is a concurrency design). Approved
decisions become authoritative only when their whole batch is published: `BatchPublisher.publish(batch_id)`
re-verifies the approval, replays the evaluation with the recorded baseline (must be `pass`), writes the batch's
records through the existing per-record CAS, and only then flips one marker page to `published`. Retirement of
predecessors happens strictly after the successor batch is published (AC12). `ingest.py` gains the approved-spec
discovery hook, the seed exclusion, and projection of `about`/normative edges.

**Decisions fixed at /sdd-task time (binding, see plan):**
- *Marker shape (spec §8 open question):* ONE page per batch, id `batch_marker_id(batch_id)` = `adr-batch:<batch_id>`,
  category `BATCH_MARKER_CATEGORY` = `"adr_batch"` (both defined in `inventory.py` by TASK-5003). Body = canonical JSON
  `{"batch_id","state":"pending"|"published","decision_ids":[...]}`. A single `compare_and_swap_page` flips it →
  atomic visibility. Not category `adr`: `DecisionRepository.inventory()` lists `category="adr"` (repository.py:74)
  and would report the marker as an `ADR_SCHEMA_UNSUPPORTED` decode diagnostic.
- *Retirement* sets BOTH `lifecycle="retired"` and `source_status="superseded"` on the predecessor, so FEAT-778
  `ADRSource` (filters `source_status`, adr.py:52) and `DecisionService` hide it with no runtime change (AC17).
- *Seed exclusion:* `docs/decisions/` is in the default `adr_globs` (models.py:67-68); legacy discovery must skip
  any file carrying a `## Decision Metadata` block, otherwise each seed is ALSO ingested as an unbatched legacy
  `adr:doc:` record that `is_eligible` accepts — bypassing approval (AC6, AC13).

---

## Scope

- Create `decisions/publish.py` with `PublishResult` and `BatchPublisher.publish()` (+ explicit retirement).
- Modify `ingest.py`: `discover_adr_sources(..., *, approved_specs=None)`, seed exclusion in legacy discovery,
  `project_links` projects `about` (→ `concept:<id>`) and normative (→ target id) edges.
- Write `test_publish.py` (spec §4 M8 tests + the ingest changes).

**NOT in scope**: CLI `wikitoolkit decisions publish` (TASK-5009), the seed approval entry (TASK-5013), any change
to `refresh_decisions` beyond what the seed exclusion requires, `ADRSource` (no runtime change — AC17).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/publish.py` | CREATE | `BatchPublisher`, `PublishResult` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/ingest.py` | MODIFY | approved-spec discovery, seed exclusion, about/normative edge projection |
| `packages/ai-parrot/tests/knowledge/wiki/decisions/test_publish.py` | CREATE | M8 + ingest tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.decisions.models import DecisionConfig, DecisionRecord, DecisionDiagnostic, DecisionError, _Strict  # verified: models.py:63,172,215,47,57
from parrot.knowledge.wiki.decisions.repository import DecisionRepository   # verified: repository.py:26
from parrot.knowledge.wiki.store import BaseWikiStore, WikiPageRecord, estimate_tokens   # verified: store.py; codec.py:31 imports WikiPageRecord, estimate_tokens
# Created by earlier FEAT-784 tasks:
from parrot.knowledge.wiki.decisions.models import BATCH_PARTIAL, APPROVAL_UNVERIFIED, ADR_REVISION_CONFLICT   # BATCH_PARTIAL/APPROVAL_UNVERIFIED: TASK-4997; ADR_REVISION_CONFLICT verified models.py:20
from parrot.knowledge.wiki.decisions.approvals import ApprovalManifest, ApprovalAdapter, ApprovalEntry   # TASK-5001
from parrot.knowledge.wiki.decisions.spec_entries import parse_spec_decisions, entries_to_records, SEED_HEADING   # TASK-4999
from parrot.knowledge.wiki.decisions.inventory import BATCH_MARKER_CATEGORY, batch_marker_id   # TASK-5003
from parrot.knowledge.wiki.decisions.consequences import ConsequenceService   # TASK-5005
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/decisions/repository.py
class DecisionRepository:                                                     # line 26
    async def get(self, decision_id: str) -> tuple[DecisionRecord, str | None] | None   # line 45
    async def inventory(self) -> list[DecisionRecord]                         # line 63 — list_pages(category=ADR_CATEGORY, ...) line 74
    async def save(self, record: DecisionRecord, expected_content_hash: str | None) -> DecisionRecord   # line 96 — per-record CAS; ADR_REVISION_CONFLICT on lost race

# packages/ai-parrot/src/parrot/knowledge/wiki/store.py
async def get_page(self, concept_id: str, include_body: bool = True) -> Optional[dict[str, Any]]   # line 765
async def compare_and_swap_page(self, page: WikiPageRecord, expected_content_hash: Optional[str]) -> bool   # line 824 — insert-if-absent when expected is None
async def add_edges(self, edges: list[tuple]) -> int                          # line 747 (abstract), :1891 sqlite
class WikiPageRecord: concept_id, node_id, title, category="concept", summary, body, source_id, token_count, origin="ingest", asserted_by, updated_at, content_hash, attrs

# packages/ai-parrot/src/parrot/knowledge/wiki/decisions/ingest.py
def discover_adr_sources(root: Path, config: DecisionConfig) -> list[str]:    # line 43 — globs config.adr_globs, skips SCAN_EXCLUDE_DIRS, sorted posix rel paths
async def refresh_decisions(store, root, config, paths=None) -> SyncResult    # line 252 — sources = paths or discover_adr_sources(root, config) (line 277); parse_adr per source
async def project_links(store: BaseWikiStore, records: list[DecisionRecord]) -> int:   # line 380
    edges = [(record.decision_id, link.target_id, link.relation, link.provenance) for record in records for link in record.links]
    if not edges: return 0
    return await store.add_edges(edges)

# packages/ai-parrot/src/parrot/knowledge/wiki/decisions/codec.py
def decision_to_page(record) -> WikiPageRecord     # line 160 — pattern for building a page; content_hash = sha1(envelope)

# TASK-5005: ConsequenceService.evaluate(spec_path, *, mode="replay") -> ConsequenceReport (status must be "pass")
# TASK-5001: ApprovalManifest.load(path); .for_document(document_id) -> list[ApprovalEntry];
#           ApprovalEntry(kind, batch_id, spec_path, document_id, entries: list[DecisionRef], block_sha256, commit, actor, recorded_at)
#           ApprovalAdapter.verify(entry, *, spec_text) -> (bool, list[DecisionDiagnostic])
# TASK-4997: DecisionRecord schema-2 fields batch_id, lifecycle, supersedes_refs, about, targets (list[DecisionTarget]), normative
```

### Does NOT Exist
- ~~multi-record transactions on `BaseWikiStore`~~ — atomicity comes from the marker flip only.
- ~~`ApprovalManifest.by_batch()`~~ — unless TASK-5001 delivered it; otherwise filter entries by `batch_id` yourself.
- ~~`DecisionService.review()` as a publication path~~ — never publish through review (spec S10).
- ~~a `pending` value on `DecisionRecord.lifecycle`~~ — lifecycle is `active|retired`; visibility is the marker's job.
- ~~`ADR_UNSUPPORTED_SCHEMA`~~ — the code is `ADR_SCHEMA_UNSUPPORTED`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/decisions/publish.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/decisions/ingest.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/decisions/test_publish.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/repository.py#DecisionRepository",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/repository.py#DecisionRepository.get",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/repository.py#DecisionRepository.save",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/ingest.py#discover_adr_sources",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/ingest.py#project_links",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/ingest.py#refresh_decisions",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore.compare_and_swap_page",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#WikiPageRecord"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Write order (AC12): (1) marker `pending` (insert-if-absent, or confirm existing `pending`); (2) every record with
  `batch_id` via `repo.save` (idempotent: skip a record whose stored canonical content already equals the target);
  (3) marker `pending → published` via one CAS; (4) only then retire predecessors named in `supersedes_refs`.
- A crash anywhere before (3) leaves the marker `pending` ⇒ TASK-5003's eligibility excludes every record of the
  batch. A retry re-runs from (1) and converges (`already-published` when the marker is already `published`).
- Refuse (status `refused`, no writes) on: unverified approval (`APPROVAL_UNVERIFIED`), replay not `pass`, a block
  digest that no longer matches the approved one, marker in an unknown state (`BATCH_PARTIAL`).
- `ingest.refresh_decisions` signature unchanged; it keeps calling `discover_adr_sources(root, config)` without
  `approved_specs`, so spec files are NEVER fed to `parse_adr` (F04, one document → one record).
- Edge projection is a rebuildable cache, never authority (ingest.py:381-386 docstring) — provenance `"asserted"`.
- Async throughout; filesystem reads via `asyncio.to_thread`; `self.logger` for progress.

---

## Implementation Blueprint

### Steps (in order)
1. Modify `ingest.py` (blocks 1–2) — *why*: the publisher reuses `discover_adr_sources(approved_specs=...)` to locate batch sources, and the seed exclusion must land before any seed file exists (TASK-5012).
2. Create `publish.py` (block 3) — *why*: the protocol order above is the whole safety argument; keep the four phases as separate helpers.
3. Fill the `FILL IN`s; write tests that inject a failing `save` mid-batch.
4. Run validation.

### `ingest.py` — block 1 (MODIFY `discover_adr_sources`)
```python
# occurrences: 1 (verified: grep -c 'def discover_adr_sources(root: Path, config: DecisionConfig) -> list\[str\]:' packages/ai-parrot/src/parrot/knowledge/wiki/decisions/ingest.py)
# REPLACE the signature line `def discover_adr_sources(root: Path, config: DecisionConfig) -> list[str]:` (verified: ingest.py:43) with:
def discover_adr_sources(root: Path, config: DecisionConfig, *, approved_specs: list[str] | None = None) -> list[str]:
# …keep the existing docstring and glob loop (ingest.py:44-58), then REPLACE the final
# `return sorted(p.relative_to(root).as_posix() for p in found)` (verified: ingest.py:59, occurrences: 1) with:
    legacy = sorted(
        p.relative_to(root).as_posix() for p in found if not _has_seed_metadata(p)
    )
    if approved_specs is None:
        return legacy
    # FILL IN: return the sorted union of `legacy`-excluded seed files and `approved_specs` that exist under root
    #   (confined; skip missing with no error) — these are BATCH sources for the publisher, never legacy
    #   sources. Keep the default (approved_specs=None) path byte-identical to today for non-seed files.
    return legacy


def _has_seed_metadata(path: Path) -> bool:
    """True when the ADR carries a ``## Decision Metadata`` block — it enters only via its approved batch (AC13)."""
    # FILL IN: cheap line scan for a line equal to SEED_HEADING (TASK-4999); unreadable file ⇒ False.
    raise NotImplementedError
```
**Why**: the seed exclusion lives inside discovery so both `refresh_decisions` and `wikitoolkit adr sync`
inherit it with no other change; default-call behaviour is unchanged for existing ADRs (G7).

### `ingest.py` — block 2 (MODIFY `project_links`)
```python
# occurrences: 1 (verified: grep -c 'async def project_links(store: BaseWikiStore, records: list\[DecisionRecord\]) -> int:' packages/ai-parrot/src/parrot/knowledge/wiki/decisions/ingest.py)
# REPLACE the `edges = [...]` list (verified: ingest.py:387-391) with:
    edges = [
        (record.decision_id, link.target_id, link.relation, link.provenance)
        for record in records
        for link in record.links
    ]
    for record in records:
        if record.schema_version != 2 or record.lifecycle != "active":
            continue
        edges.extend((record.decision_id, f"concept:{subsystem}", "about", "asserted") for subsystem in record.about)
        if record.normative is not None:
            edges.extend((record.decision_id, target.target_id, record.normative, "asserted") for target in record.targets)
```
**Why**: spec M8 "project_links projects about (→ concept: pages) and normative edges (→ target pages) as
rebuildable cache". Relation strings match the `RelationType` values TASK-4997 adds (`constrains/forbids/requires`, existing `about`).

### `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/publish.py` (CREATE)
```python
"""All-or-nothing publication of an approved decision batch (FEAT-784 Module 8)."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from pathlib import Path
from typing import Literal

from pydantic import Field

from parrot.knowledge.wiki.decisions.approvals import ApprovalAdapter, ApprovalManifest
from parrot.knowledge.wiki.decisions.consequences import ConsequenceService
from parrot.knowledge.wiki.decisions.inventory import BATCH_MARKER_CATEGORY, batch_marker_id
from parrot.knowledge.wiki.decisions.models import (
    APPROVAL_UNVERIFIED, BATCH_PARTIAL, DecisionConfig, DecisionDiagnostic, DecisionError, _Strict,
)
from parrot.knowledge.wiki.decisions.repository import DecisionRepository
from parrot.knowledge.wiki.store import BaseWikiStore, WikiPageRecord, estimate_tokens


class PublishResult(_Strict):
    batch_id: str
    written: int = 0
    retired: int = 0
    skipped: int = 0
    status: Literal["published", "already-published", "refused"]
    diagnostics: list[DecisionDiagnostic] = Field(default_factory=list)


def _marker_page(batch_id: str, state: str, decision_ids: list[str]) -> WikiPageRecord:
    body = json.dumps({"batch_id": batch_id, "state": state, "decision_ids": sorted(decision_ids)}, sort_keys=True, separators=(",", ":"))
    return WikiPageRecord(
        concept_id=batch_marker_id(batch_id), node_id=batch_marker_id(batch_id), title=f"ADR batch {batch_id}",
        category=BATCH_MARKER_CATEGORY, summary=f"{state}", body=body, token_count=estimate_tokens(body),
        origin="authored", content_hash=hashlib.sha1(body.encode("utf-8")).hexdigest(),  # noqa: S324 — identity, not authenticity
    )


class BatchPublisher:
    """Publish one approved batch; retries converge to the same result."""

    def __init__(self, store: BaseWikiStore, root: Path, config: DecisionConfig, service: ConsequenceService,
                 approvals: ApprovalManifest, adapter: ApprovalAdapter) -> None:
        self.store, self.root, self.config, self.service = store, root, config, service
        self.approvals, self.adapter = approvals, adapter
        self.repo = DecisionRepository(store, max_records=config.max_records)
        self.logger = logging.getLogger(__name__)

    async def publish(self, batch_id: str) -> PublishResult:
        """Refuse on stale approval, non-pass replay, or partial batch."""
        # FILL IN phase 0 (verify): entries = [e for e in self.approvals entries if e.batch_id == batch_id and e.kind in ("spec","seed")];
        #   none ⇒ refused/APPROVAL_UNVERIFIED; read spec_text (asyncio.to_thread), adapter.verify(entry, spec_text=...)
        #   false ⇒ refused; report = await self.service.evaluate(Path(entry.spec_path), mode="replay");
        #   report.status != "pass" ⇒ refused with report.diagnostics.
        # FILL IN phase 1: marker = await self.store.get_page(batch_marker_id(batch_id)); state "published" ⇒
        #   return already-published (skipped=len(records)); absent ⇒ compare_and_swap_page(_marker_page(.., "pending", ids), None);
        #   any other body/state ⇒ refused/BATCH_PARTIAL.
        # FILL IN phase 2: records = entries_to_records(block, source_path=entry.spec_path, batch_id=batch_id) (TASK-4999);
        #   for each: existing = await self.repo.get(id); identical ⇒ skipped += 1; else await self.repo.save(record, existing hash or None).
        #   A DecisionError here returns refused WITHOUT touching the marker (stays pending ⇒ invisible, AC12).
        # FILL IN phase 3: CAS marker pending → published (expected = pending page's content_hash).
        # FILL IN phase 4: retired = await self._retire_predecessors(records) — AFTER phase 3 only (spec §4 test_retirement_after_successor).
        raise NotImplementedError

    async def _retire_predecessors(self, records) -> int:
        """Set lifecycle='retired' AND source_status='superseded' on each exact supersedes_refs predecessor (AC12, AC17)."""
        # FILL IN: for ref in record.supersedes_refs: got = await self.repo.get(ref.decision_id); skip if already retired;
        #   require got.revision == ref.revision (else diagnostic, no write); save model_copy(update={...}) with CAS.
        raise NotImplementedError
```
**Why this shape**: spec §3 M8 skeleton verbatim (`PublishResult`, constructor, `publish`). The marker helper is
module-level so tests can build the expected pending/published pages. Phase boundaries are the AC12 argument —
do not merge phases 2 and 3.

### FILL IN checklist
- [ ] `ingest.discover_adr_sources` approved-spec union; bounded by G7 (default path unchanged)
- [ ] `ingest._has_seed_metadata`; bounded by AC6/AC13
- [ ] `publish.BatchPublisher.publish` phases 0–4; bounded by AC12, AC13
- [ ] `publish._retire_predecessors`; bounded by AC12, AC17

---

## Acceptance Criteria

- [ ] AC12: injected `save` failure mid-batch ⇒ marker stays `pending`, no record of the batch is eligible (TASK-5003 predicate), no retirement; retry converges to `published`.
- [ ] Second `publish()` of a published batch ⇒ `already-published`, zero writes.
- [ ] Predecessor retired only after successor marker is `published`; retired record has `source_status="superseded"`.
- [ ] Replay of an approved batch yields no self-conflict (`evaluate(mode="replay") == pass`).
- [ ] A `docs/decisions/*.md` file with `## Decision Metadata` is NOT returned by `discover_adr_sources(root, config)`; files without it are unchanged.
- [ ] `project_links` emits `about` and normative edges for active schema-2 records only; legacy edges unchanged.
- [ ] Existing `test_ingest.py` still passes; `ruff check` clean.

---

## Validation Commands
- `pytest packages/ai-parrot/tests/knowledge/wiki/decisions/test_publish.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/decisions/test_ingest.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/wiki/decisions/test_publish.py
import pytest
from parrot.knowledge.wiki.decisions.ingest import discover_adr_sources, project_links
from parrot.knowledge.wiki.decisions.publish import BatchPublisher, PublishResult

# Use adr_store / adr_config fixtures (conftest.py:190, :185); a fake ApprovalAdapter (verify → (True, []));
# a fake ConsequenceService whose evaluate(mode="replay") returns a pass/conflict report on demand.

async def test_publish_all_or_nothing(adr_store, tmp_path, monkeypatch): ...      # FILL IN — patch DecisionRepository.save to raise on 2nd record
async def test_publish_is_idempotent(adr_store, tmp_path): ...                    # FILL IN
async def test_retirement_after_successor(adr_store, tmp_path): ...               # FILL IN
async def test_replay_uses_recorded_baseline(adr_store, tmp_path): ...            # FILL IN
async def test_refuses_unverified_or_non_pass(adr_store, tmp_path): ...           # FILL IN
def test_seed_files_excluded_from_legacy_discovery(tmp_path, adr_config): ...     # FILL IN
async def test_project_links_about_and_normative_edges(adr_store): ...            # FILL IN
```

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug sdd-decision-audit --feature-id FEAT-784`).
2. Read spec §3 Module 8, AC12, AC13, AC17, §7 Known Risks, and the "Decisions fixed at /sdd-task time" above.
3. Confirm TASK-5005 (and transitively P03, P05, P07) are `done`; read the delivered `batch_marker_id`, `BATCH_MARKER_CATEGORY`, `entries_to_records`, `ApprovalManifest` APIs.
4. Verify the Codebase Contract; update first on drift.
5. Implement from the blueprint; resolve each `FILL IN` within its bound.
6. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
7. Commit only the listed files; close with `scripts/sdd/close_task.sh TASK-5007 sdd-decision-audit verified`.

---

## Completion Note

Seat: opus(native) · Backend: native · Model: opus · Attempts: 1 · Duration: 140s · Tokens: n/a

- Delivered files match the task list.
- Merge-tier validation (chunk 6): 232 passed, 1 failed — pre-existing env-gated test_backend_parity_is_reported. No review fixes.
- Decision for review: seed approvals parse with SEED_HEADING, spec approvals with DECISIONS_HEADING (mirrors GitCommitApprovalAdapter). Schema-1 predecessors get only source_status=superseded (they cannot carry lifecycle).
