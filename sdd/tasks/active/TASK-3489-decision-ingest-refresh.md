# TASK-3489: `refresh_decisions` — discovery, idempotent sync, and link repair

**Feature**: FEAT-578 — ADR extraction and decision retrieval in the LLM wiki
**Spec**: `sdd/specs/sdd-spec-wiki-adr.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3485, TASK-3486, TASK-3487
**Assigned-to**: unassigned

---

## Context

Module 3's orchestration half: the only writer of documented records. It
discovers ADR sources by glob, parses them, resolves Python citations against
the **full stored inventory**, and persists each record through the CAS
repository.

Three requirements from spec §2 Module 3 that are easy to miss and are the
reason this task is not trivial:

- *"changing an ADR must repair links in unchanged citing code"* — a citation in
  a file that did not change still has to be re-resolved.
- *"Code citation removals must remove canonical applicability links, not merely
  add new edges."* — the sync is a replace, not an append.
- *"Batch writes are per-record atomic, not globally atomic; retrying a partial
  sync converges idempotently"* — a failure halfway through must be safe to
  re-run.

And the hard invariant: refresh must **preserve candidate and review data**.
A documented-record refresh may never touch an `adr:candidate:` record.

---

## Scope

- Implement source discovery over `DecisionConfig.adr_globs`, honouring the
  project's existing relevance/exclusion rules.
- Implement `refresh_decisions(store, root, config, paths=None)` → `SyncResult`,
  covering full and incremental sync, link re-resolution, and disappeared
  sources.
- Build the synthetic fixture repository the integration suite (TASK-3497)
  reuses.
- Test idempotency, partial-retry convergence, link repair and candidate
  preservation.

**NOT in scope**: parsing internals (TASK-3486), citation extraction internals
(TASK-3487), graph-edge projection into the wiki edge table beyond what the
record's `links` require, generation (TASK-3491), CLI wiring (TASK-3496).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/ingest.py` | CREATE | Discovery, refresh, link resolution, edge projection |
| `packages/ai-parrot/tests/knowledge/wiki/decisions/conftest.py` | CREATE | Synthetic ADR repository fixture (shared with TASK-3497) |
| `packages/ai-parrot/tests/knowledge/wiki/decisions/test_ingest.py` | CREATE | Idempotency, link repair, retry, preservation |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.knowledge.wiki.store import BaseWikiStore                       # store.py:525
from parrot.knowledge.wiki.decisions.codec import content_fingerprint, documented_decision_id  # TASK-3480
from parrot.knowledge.wiki.decisions.evidence import extract_python_citations, build_evidence   # TASK-3487
from parrot.knowledge.wiki.decisions.models import (                        # TASK-3479
    ADR_REFERENCE_AMBIGUOUS, ADR_REFERENCE_MISSING, ADR_SOURCE_UNAVAILABLE,
    DecisionConfig, DecisionDiagnostic, DecisionError, DecisionLink,
    DecisionRecord, SyncResult,
)
from parrot.knowledge.wiki.decisions.parser import parse_adr                # TASK-3486
from parrot.knowledge.wiki.decisions.repository import DecisionRepository   # TASK-3485
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/store.py:525
async def add_edges(self, edges: list[tuple]) -> int: ...   # (src, dst, rel[, provenance]); line 546 abstract
async def neighbors(self, concept_id: str, rel: Optional[str] = None,
                    direction: str = 'both') -> list[dict[str, Any]]: ...   # line 582

# packages/ai-parrot/src/parrot/knowledge/wiki/decisions/repository.py  (TASK-3485)
class DecisionRepository:
    async def get(self, decision_id: str) -> tuple[DecisionRecord, str | None] | None: ...
    async def inventory(self) -> list[DecisionRecord]: ...
    async def save(self, record: DecisionRecord, expected_content_hash: str | None) -> DecisionRecord: ...

# packages/ai-parrot/src/parrot/knowledge/wiki/decisions/parser.py  (TASK-3486)
def parse_adr(rel_path: str, text: str) -> tuple[DecisionRecord | None, list[DecisionDiagnostic]]: ...
```

`pathspec>=0.12` is already a declared dependency (`pyproject.toml:194`) and is
what the existing scanner uses for exclusion rules.

### Does NOT Exist

- ~~`replace_source_slice` as the ADR write path~~ — ADR pages carry
  `source_id=None` precisely so a source-slice replacement cannot delete them
  (spec §9 finding A3). Write only through `DecisionRepository.save`.
- ~~a globally atomic multi-record sync~~ — spec §2 Module 3: "Batch writes are
  per-record atomic, not globally atomic."
- ~~an ADR mirror in the GraphIndex plane~~ — spec §2: "v1 does not mirror ADR
  records/edges into the separate GraphIndex plane." Do not emit GraphIndex
  nodes or edges.
- ~~rename detection~~ — spec §2: "Renames create a new path ID; old records
  remain with missing source evidence. V1 does not infer identity across
  renames." Do not add similarity matching.
- ~~`config.decisions.adr_globs` being the only filter~~ — the project's normal
  relevance/exclusion rules still apply (spec §2 "Discover only configured globs
  **and** normal repository relevance/exclusion rules").

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/decisions/ingest.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/decisions/conftest.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/decisions/test_ingest.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/repository.py#DecisionRepository"
  ]
}
```

---

## Implementation Notes

### Key Constraints

- Idempotent: re-running an unchanged sync must report `unchanged`, perform no
  write, and not bump any revision. Compare via `content_fingerprint`.
- Per-record failures become diagnostics and are counted; the sync continues.
- All file reads via `asyncio.to_thread`; read the **complete** file text so
  AC1's long-ADR case holds.
- Never write to an `adr:candidate:` id from this module.

---

## Implementation Blueprint

### Steps (in order)

1. Write `discover_adr_sources` — *why*: everything downstream is a function of
   which files are in scope, and glob+exclusion is where a wrong answer is
   silently plausible.
2. Write `_resolve_citations` against the **full inventory**, not just the
   changed files — *why*: spec §2 requires an ADR change to repair links in
   unchanged citing code; resolving only changed files cannot do that.
3. Write `refresh_decisions` as discover → parse → resolve → save-per-record —
   *why*: per-record atomicity plus fingerprint comparison is what makes a
   partial retry converge.
4. Build the synthetic fixture repo in `conftest.py` — *why*: TASK-3497 reuses
   it, so it belongs in a shared conftest, not inline in this test module.

### `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/ingest.py` (CREATE)

```python
"""ADR discovery and idempotent source refresh (FEAT-578 Module 3).

The only writer of ``adr:doc:`` records. Candidate (``adr:candidate:``)
records are read to resolve links but NEVER written here — a documented
refresh must not disturb independently reviewed candidates (spec §2, AC7).
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from parrot.knowledge.wiki.decisions.codec import content_fingerprint
from parrot.knowledge.wiki.decisions.evidence import build_evidence, extract_python_citations
from parrot.knowledge.wiki.decisions.models import (
    ADR_REFERENCE_AMBIGUOUS,
    ADR_REFERENCE_MISSING,
    ADR_SOURCE_UNAVAILABLE,
    DecisionConfig,
    DecisionDiagnostic,
    DecisionError,
    DecisionLink,
    DecisionRecord,
    SyncResult,
)
from parrot.knowledge.wiki.decisions.parser import parse_adr
from parrot.knowledge.wiki.decisions.repository import DecisionRepository
from parrot.knowledge.wiki.store import BaseWikiStore

logger = logging.getLogger(__name__)


def discover_adr_sources(root: Path, config: DecisionConfig) -> list[str]:
    """Repository-relative POSIX paths of every eligible ADR document.

    Applies ``config.adr_globs`` AND the project's normal relevance /
    exclusion rules — a matching glob inside an excluded directory is still
    excluded (spec §2).
    """
    # FILL IN: expand each glob with Path.glob, keep files only, convert to
    # repo-relative POSIX strings, drop anything under the scanner's excluded
    # directories (reuse the same exclusion source the repo scanner uses rather
    # than re-listing names here), and return them sorted for determinism.
    # Bounded by spec §2 "Discover only configured globs and normal repository
    # relevance/exclusion rules".
    raise NotImplementedError


def _alias_index(inventory: list[DecisionRecord]) -> tuple[dict[str, str], set[str]]:
    """Map ``ADR-42`` -> decision_id, plus the set of ambiguous aliases.

    Built per call: spec §2 forbids a persistent cache without an
    invalidation contract.
    """
    # FILL IN: fold every record's external_id; an alias claimed by two
    # decision_ids goes into the ambiguous set and is REMOVED from the map, so
    # it resolves to nothing rather than to an arbitrary winner. Bounded by
    # spec §2 "duplicate aliases are ambiguous" / "missing or duplicate aliases
    # stay unresolved".
    raise NotImplementedError


async def _resolve_citations(
    root: Path,
    code_paths: list[str],
    inventory: list[DecisionRecord],
) -> tuple[dict[str, list[DecisionLink]], list[DecisionDiagnostic]]:
    """Resolve Python ADR citations into per-decision ``explains`` links.

    Args:
        code_paths: EVERY indexed Python target, not only changed files —
            changing an ADR must repair links in unchanged citing code
            (spec §2 Module 3).

    Returns:
        ``(links_by_decision_id, diagnostics)``. An alias with no record is
        ``ADR_REFERENCE_MISSING``; a duplicated alias is
        ``ADR_REFERENCE_AMBIGUOUS``. Both stay unresolved.
    """
    # FILL IN: read each path (asyncio.to_thread), extract_python_citations,
    # look each alias up in the _alias_index, and build a DecisionLink with
    # relation='explains', provenance='extracted' and evidence_indexes pointing
    # at the EvidenceRef this function also builds via build_evidence.
    # Bounded by spec §2 and AC2 ("only evidence-backed applicability").
    raise NotImplementedError


async def refresh_decisions(
    store: BaseWikiStore,
    root: Path,
    config: DecisionConfig,
    paths: list[str] | None = None,
) -> SyncResult:
    """Refresh documented ADR records and their links, idempotently.

    Args:
        paths: Repository-relative paths to refresh, or ``None`` for the full
            configured inventory. An incremental run still re-resolves
            aliases against the FULL stored inventory.

    Returns:
        Counts plus diagnostics. Never raises for a per-record failure —
        writes are per-record atomic, so a retry converges (spec §2).
    """
    repo = DecisionRepository(store, max_records=config.max_records)
    result = SyncResult()
    if not config.enabled:
        return result
    # FILL IN:
    #   1. inventory = await repo.inventory()  (for alias resolution)
    #   2. sources = paths or discover_adr_sources(root, config)
    #   3. for each source: read the COMPLETE text (asyncio.to_thread), parse_adr;
    #      None -> continue with its diagnostic; else build the record
    #   4. links = await _resolve_citations(root, <all indexed python targets>,
    #      inventory + freshly parsed records) and ATTACH them, REPLACING the
    #      record's previous 'explains' links wholesale — a removed citation
    #      must lose its link, not merely stop gaining one (spec §2)
    #   5. existing = await repo.get(record.decision_id); when
    #      content_fingerprint is unchanged -> result.unchanged += 1 and SKIP
    #      the write entirely (no revision bump); else save with the hash from
    #      `get` (or None when absent), counting created/updated
    #   6. catch DecisionError per record -> append diagnostic, keep going
    #   7. count records whose source_path no longer exists as `missing`, but
    #      DO NOT delete them (spec §2 "retain records whose sources disappeared")
    #   8. NEVER touch a decision_id starting with "adr:candidate:" (AC7)
    # Bounded by AC1, AC7, and spec §2 Module 3.
    raise NotImplementedError


async def project_links(store: BaseWikiStore, records: list[DecisionRecord]) -> int:
    """Rebuild the navigational edge projection for ``records``.

    Edges are a rebuildable cache, never authority: retrieval validates the
    corresponding record link, so a stale projected edge can never establish
    applicability (spec §2). Safe to re-run.
    """
    # FILL IN: emit (decision_id, target_id, relation, provenance) tuples from
    # each record's `links` via store.add_edges. Do NOT emit GraphIndex nodes
    # or edges — spec §2 keeps the ADR plane out of GraphIndex in v1.
    raise NotImplementedError
```

**Why this shape**: `_resolve_citations` taking *all* code paths rather than the
changed subset is the single design choice that satisfies "changing an ADR must
repair links in unchanged citing code"; narrowing it later is a silent
regression. Skipping the write when `content_fingerprint` is unchanged is what
makes re-running the sync free and keeps revisions meaningful. `project_links`
is separate and re-runnable because spec §2 explicitly allows source replacement
to erase edges and expects a post-ingest pass to rebuild them.

### `packages/ai-parrot/tests/knowledge/wiki/decisions/conftest.py` (CREATE)

```python
"""Synthetic ADR repository fixtures (FEAT-578 Modules 3 and 7).

Shared with the integration suite. The matrix mirrors spec §4 "Test Data /
Fixtures" exactly — change it there first.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from parrot.knowledge.wiki.decisions.models import DecisionConfig


@pytest.fixture
def adr_repo(tmp_path: Path) -> Path:
    """A synthetic repository covering the full spec §4 fixture matrix.

    Contains: accepted / superseded / proposed / unknown-status ADRs, two
    files both claiming ``ADR-42``, malformed frontmatter, a long ADR whose
    Decision sits past 16000 characters, a Python module with two same-named
    symbols, a module-level comment citation, an executable string holding a
    false citation, one undocumented symbol, and a Markdown document linking
    an exact ``sym:`` id.
    """
    # FILL IN: write every file listed above under tmp_path and return tmp_path.
    # Keep content deterministic — spec §4: "Fixture hashes and paths are
    # deterministic." Name each file so its role is obvious from the path.
    raise NotImplementedError


@pytest.fixture
def adr_config() -> DecisionConfig:
    """Default config with generation disabled (the shipped default)."""
    return DecisionConfig()


@pytest.fixture
async def adr_store(tmp_path):
    """A file-backed wiki plane for ADR round-trips."""
    from parrot.knowledge.wiki.file_store import InMemoryWikiStore

    return InMemoryWikiStore(tmp_path / "wiki-pages", wiki_name="adr-test")
```

### `packages/ai-parrot/tests/knowledge/wiki/decisions/test_ingest.py` (CREATE)

```python
"""refresh_decisions idempotency, link repair and preservation (FEAT-578 M3)."""

from __future__ import annotations

import pytest

from parrot.knowledge.wiki.decisions.ingest import discover_adr_sources, refresh_decisions
from parrot.knowledge.wiki.decisions.repository import DecisionRepository


class TestDiscovery:
    def test_only_configured_globs_are_discovered(self, adr_repo, adr_config):
        found = discover_adr_sources(adr_repo, adr_config)
        assert all(p.startswith(("docs/adr/", "docs/adrs/", "docs/decisions/")) for p in found)

    def test_excluded_directories_win_over_globs(self, adr_repo, adr_config):
        """A matching glob inside an excluded dir is still excluded (spec §2)."""
        # FILL IN: place an ADR under an excluded directory in adr_repo and
        # assert it is not discovered
        raise NotImplementedError


class TestRefresh:
    async def test_first_sync_creates_records(self, adr_repo, adr_config, adr_store):
        result = await refresh_decisions(adr_store, adr_repo, adr_config)
        assert result.created > 0 and result.updated == 0

    async def test_second_sync_is_a_no_op(self, adr_repo, adr_config, adr_store):
        """Idempotent: unchanged sources bump nothing."""
        await refresh_decisions(adr_store, adr_repo, adr_config)
        before = {r.decision_id: r.revision for r in await DecisionRepository(adr_store).inventory()}
        result = await refresh_decisions(adr_store, adr_repo, adr_config)
        assert result.created == 0 and result.updated == 0 and result.unchanged > 0
        after = {r.decision_id: r.revision for r in await DecisionRepository(adr_store).inventory()}
        assert after == before

    async def test_changed_adr_repairs_links_in_unchanged_code(self, adr_repo, adr_config, adr_store):
        """spec §2 Module 3 — the requirement most easily missed."""
        # FILL IN: sync; edit ONLY the ADR file (change its id/alias); re-sync
        # with paths=[that adr]; assert the link from the UNCHANGED citing
        # Python file was re-resolved to the new state
        raise NotImplementedError

    async def test_removed_citation_removes_the_link(self, adr_repo, adr_config, adr_store):
        """A removal must delete the applicability link, not just stop adding."""
        # FILL IN: sync; delete the ADR reference from the citing comment;
        # re-sync; assert the record no longer carries an 'explains' link to
        # that symbol
        raise NotImplementedError

    async def test_deleted_adr_source_is_missing_not_deleted(self, adr_repo, adr_config, adr_store):
        """spec §2: retain records whose sources disappeared (AC7)."""
        # FILL IN: sync; delete an ADR file; re-sync; assert the record still
        # exists and result.missing >= 1
        raise NotImplementedError

    async def test_rename_creates_a_new_record(self, adr_repo, adr_config, adr_store):
        """V1 does not infer identity across renames (spec §2)."""
        # FILL IN: sync; rename an ADR file; re-sync; assert TWO records exist
        # and the old one is reported missing
        raise NotImplementedError

    async def test_candidate_records_are_untouched(self, adr_repo, adr_config, adr_store):
        """AC7: a documented refresh never disturbs a reviewed candidate."""
        # FILL IN: save an adr:candidate: record with review_status='accepted'
        # and a review_history entry; run a full refresh; assert the candidate's
        # revision, review_status and review_history are byte-identical
        raise NotImplementedError

    async def test_partial_failure_retries_to_convergence(self, adr_repo, adr_config, adr_store):
        """spec §2: per-record atomic; a retry converges without duplicates."""
        # FILL IN: patch DecisionRepository.save to raise on the SECOND record
        # only; run refresh (expect a diagnostic, first record persisted);
        # unpatch and re-run; assert every record exists exactly once
        raise NotImplementedError

    async def test_ambiguous_alias_stays_unresolved(self, adr_repo, adr_config, adr_store):
        """Two files claiming ADR-42 resolve to neither (spec §2)."""
        # FILL IN: assert an ADR_REFERENCE_AMBIGUOUS diagnostic and that the
        # citing symbol gained no 'explains' link
        raise NotImplementedError

    async def test_sync_makes_zero_llm_calls(self, adr_repo, adr_config, adr_store, monkeypatch):
        """AC5: ordinary scan/read paths never construct or invoke a client."""
        # FILL IN: monkeypatch LLMFactory.create and AbstractClient.invoke to
        # raise AssertionError; run a full refresh; assert it completes
        raise NotImplementedError
```

### FILL IN checklist

- [ ] `ingest.py::discover_adr_sources` — glob + exclusion + determinism; bounded by spec §2
- [ ] `ingest.py::_alias_index` — ambiguity removal; bounded by spec §2
- [ ] `ingest.py::_resolve_citations` — full-corpus resolution; bounded by spec §2 Module 3 / AC2
- [ ] `ingest.py::refresh_decisions` — the eight numbered steps; bounded by AC1 / AC7
- [ ] `ingest.py::project_links` — edge projection, no GraphIndex mirror; bounded by spec §2
- [ ] `conftest.py::adr_repo` — the full spec §4 fixture matrix
- [ ] `test_ingest.py` — ten test bodies; bounded by the assertions named in each docstring

---

## Acceptance Criteria

- [ ] Discovery honours `adr_globs` **and** the project's exclusion rules
- [ ] A second sync over unchanged sources reports `unchanged`, writes nothing, bumps no revision
- [ ] Changing an ADR repairs links in **unchanged** citing code (spec §2 Module 3)
- [ ] Removing a code citation removes the canonical `explains` link
- [ ] A deleted ADR source leaves its record in place and counts as `missing` (AC7)
- [ ] A rename yields a new record; the old one remains, reported missing (spec §2)
- [ ] `adr:candidate:` records are never written by refresh; review history is byte-identical afterwards (AC7)
- [ ] A per-record failure becomes a diagnostic; a retry converges with no duplicates
- [ ] Duplicate `ADR-42` aliases stay unresolved with `ADR_REFERENCE_AMBIGUOUS`
- [ ] A full sync makes zero LLM calls (AC5)
- [ ] No GraphIndex node or edge is emitted (spec §2)

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/decisions/test_ingest.py -q`

---

## Agent Instructions

1. **Read the spec** §2 Module 3 in full, plus AC1/AC5/AC7.
2. **Verify the Codebase Contract** — confirm `store.py:546`, `:582` and the three dependency modules exist as described.
3. **Implement** from the blueprint; complete every `# FILL IN:`.
4. **Verify** the Validation Command passes.
5. **Move** to `sdd/tasks/completed/`, set the index entry to `done`.
6. **Fill in the Completion Note**.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
