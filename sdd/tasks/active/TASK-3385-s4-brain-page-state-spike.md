# TASK-3385: G4/S4 gate — brain page state storage, version identity and lineage

**Feature**: FEAT-571 — Agent Memory Dynamics
**Spec**: `sdd/specs/memory-dynamics.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 row **G4** (Lane 0a gate, brainstorm spike S4). Brain pages (`BrainStore`,
FEAT-390 dream cycle) must carry mutable FSRS state without polluting indexed prose or
being lost by `remember()`/`copy_page_to()`; every re-distillation must produce a
*distinguishable content version* even with the same title/category (today
`page_id = "mem-" + sha1(title|category…)` — C6), and lineage (episodes → page versions →
supersession) must be bounded, cycle-free and never double-apply a review through
episode/page aliases (AC12).

`WikiPageRecord` has **no** `metadata` member (spec C6); the three candidates are
prose-frontmatter in `body`, a sidecar record (e.g. `summary`/companion page), or a new
`metadata` column on `WikiPageRecord` (which touches `SQLiteWikiStore`, `ArangoDBWikiStore`
and `PostgresWikiStore`). S4 must compare them for search/packing behaviour, copy/edit
preservation, repeated supersession, watermark recovery of old episodes, and duplicate
forwarding, then **freeze** storage/migration, version identity and the promotion-evidence
policy (inherited priors ≠ earned evidence). Atomicity requirements are coordinated with
G2 *before passing* (spec §3 G4 "coordinate atomic requirements with G2 before passing").

---

## Scope

- Prototype the three page-state designs in `harness.py` against a **real**
  `SQLiteWikiStore` under `tmp_path` (via `create_wiki_store` as `BrainStore` does):
  (A) YAML-ish frontmatter block prepended to `body`; (B) sidecar page/record keyed by
  `concept_id` + version; (C) simulated `metadata` JSON kept in a companion table the
  prototype owns (do **not** alter `WikiPageRecord` — the column arm is *simulated* and the
  amendment names the real migration).
- For each design measure: FTS hits/ranking drift when state text is present (`search_fts`
  + `pack_results`), token cost of packed results, survival across `remember()` re-write
  and `copy_page_to()`, behaviour under 5 successive re-distillations of the same
  title/category (distinct version ids? old versions excluded from ordinary search?),
  recovery of episodes older than `DreamState.last_run` watermark, and duplicate forwarding
  (two episode aliases → one page version → exactly one review credit).
- Prototype **version identity** (`content_version` = sha1 of body + provenance tuple) and
  a **lineage** structure (episode ids → page version, `supersedes` edge) with bounded
  traversal and cycle rejection; test that a review on version N does not auto-credit
  version N+1 (spec §2 "A review of old content must not automatically count as verified
  success of newly synthesized content").
- Enumerate what `DreamCycleRunner` uses as evidence today (`reinforcement_counts` ≥
  `org_promotion_cycles`) and what `DreamCycleReport` lacks (`pages_redistilled`,
  `memories_forgotten`), for the amendment.
- Commit `REPORT.md`, `metrics.json`, `amendment.md` (chosen design + migration list per
  wiki backend, version identity rule, forwarding/admission policy, promotion evidence
  policy, report field semantics, FEAT-390 supersession note). Logs → `artifacts/logs/`.

**NOT in scope**: editing `WikiPageRecord`, any wiki store backend, `BrainStore`,
`DreamCycleRunner`, `dream/models.py` (M4 after this gate); `parrot/memory/dynamics/*`
(M1); editing the spec or the FEAT-390 spec (owner applies `amendment.md`); the atomic
review protocol itself (G2 — S4 only records the coordination points).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/memory/dynamics/spikes/s4_brain_state/__init__.py` | CREATE | package marker |
| `packages/ai-parrot/tests/memory/dynamics/spikes/s4_brain_state/harness.py` | CREATE | three page-state designs, version identity, lineage graph, metrics, report writer |
| `packages/ai-parrot/tests/memory/dynamics/spikes/s4_brain_state/test_s4_harness.py` | CREATE | fast design/lineage tests + env-gated comparison run |
| `sdd/state/FEAT-571/spikes/s4-brain-state/REPORT.md` | CREATE | reproducible gate report |
| `sdd/state/FEAT-571/spikes/s4-brain-state/metrics.json` | CREATE | raw per-design metrics |
| `sdd/state/FEAT-571/spikes/s4-brain-state/amendment.md` | CREATE | proposed page-state/lineage/promotion amendment |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `fc1a5728a55648566e264cb95c5df36190438204` on 2026-09-18.
> `core/` = `packages/ai-parrot/src/parrot/`.

### Verified Imports
```python
from parrot.memory.dream.brain import BrainStore                                        # core/memory/dream/brain.py:21
from parrot.memory.dream.models import DreamState, DreamConfig, DistilledKnowledge, DreamCycleReport  # core/memory/dream/models.py:29,58,87,103
from parrot.memory.dream.runner import DreamCycleRunner                                 # core/memory/dream/runner.py:71
from parrot.knowledge.wiki import create_wiki_store, pack_results                       # as imported by brain.py:17 ; pack_results def: core/knowledge/wiki/context.py:208
from parrot.knowledge.wiki.store import WikiPageRecord, BaseWikiStore, SQLiteWikiStore  # core/knowledge/wiki/store.py:409,525,821
from parrot.memory.episodic.models import EpisodicMemory                                # core/memory/episodic/models.py:55
```

### Existing Signatures to Use
```python
# core/memory/dream/brain.py
class BrainStore:                                                                        # :21 ; __init__ :31
    async def remember(self, text: str, title: str | None = None, category: str = "note",
                       related_pages: list[str] | None = None) -> dict[str, Any]: ...   # :53 — page_id = "mem-" + hashlib.sha1(...) :81 (title/category hash → same id on re-distill)
    #   writes via await self._store.upsert_pages([record]) :97
    async def search(self, query: str, top_k: int = 5, max_tokens: int = 600) -> str: ...  # :113 — self._store.search_fts(query, limit=top_k) :133 → pack_results(results, budget_tokens=max_tokens) :143
    async def copy_page_to(self, page_id: str, other: BrainStore) -> str: ...            # :146 — other._store.upsert_pages([record]) :176 (whatever is not in the record is lost)

# core/knowledge/wiki/store.py
class WikiPageRecord(BaseModel):   # :409 — concept_id, node_id, title, category, summary, body, source_id, token_count, origin, asserted_by, updated_at, content_hash ; NO `metadata`
class BaseWikiStore(ABC):          # :525
    async def upsert_pages(self, pages: list[WikiPageRecord]) -> int: ...                                   # :544 (abstract) / SQLite :1514
    async def get_page(self, concept_id: str, include_body: bool = True) -> Optional[dict[str, Any]]: ...  # :565 / SQLite :1877
    async def search_fts(self, query: str, category: Optional[str] = None, limit: int = 10) -> list[dict[str, Any]]: ...  # :576 / SQLite :1944
class SQLiteWikiStore(BaseWikiStore)        # :821
# other backends a `metadata` column would touch: ArangoDBWikiStore (core/knowledge/wiki/arango_store.py:135), PostgresWikiStore (core/knowledge/wiki/postgres_store.py:127)
# core/knowledge/wiki/context.py
def pack_results(...)                        # :208 — token-budgeted packing used by BrainStore.search

# core/memory/dream/runner.py
class DreamCycleRunner:                      # :71 ; async def run_cycle(self, state: DreamState) -> DreamCycleReport :105
#   state.reinforcement_counts[page_id] += 1 :183-185 ; promotion when ≥ self._config.org_promotion_cycles :198-199 (legacy cycle-count evidence)
#   async def _collect(self, state) :235 — skips "consolidated_into" in ep.metadata :265 and uses state.last_run as the created-at watermark
# core/memory/dream/models.py
class DreamState(BaseModel):     # :29 — last_run :47, reinforcement_counts: dict[str,int] :54, promoted_pages :55
class DreamConfig(BaseModel):    # :58 — org_promotion_cycles: int = 3 :81
class DistilledKnowledge(BaseModel):  # :87 — title, body, category: str = "lesson" :99 (open string, NOT an enum), confidence
class DreamCycleReport(BaseModel):    # :103 — episodes_collected, groups_formed, groups_distilled, groups_skipped, pages_written, pages_promoted, aborted ; NO pages_redistilled / memories_forgotten
# wiring: core/memory/unified/mixin.py:208-230 builds BrainStore/DreamConfig/DreamCycleRunner
# FEAT-390 spec: sdd/specs/dream-cycle-brain-consolidation.spec.md (cycle-count promotion policy S4 proposes to supersede in dynamics mode)
```

### Does NOT Exist
- ~~`WikiPageRecord.metadata`~~ — absent (spec C6). The "metadata column" arm is *simulated* in a prototype-owned companion table; the amendment lists the real DDL per backend.
- ~~page version ids distinct from `page_id`~~ — `remember()` hashes title/category, so re-distillation overwrites in place; `content_version` is the experiment.
- ~~`MemoryCandidate`, `BrainStore.search_memories()`~~ — M4 adds them after this gate; keep `search()` as the only production surface touched (read-only here).
- ~~`pages_redistilled` / `memories_forgotten` on `DreamCycleReport`~~ — absent (spec C7); S4 proposes their count semantics only.
- ~~a closed `DistilledKnowledge.category` enum~~ — it is an open string; do not propose an enum migration here (spec §6).
- ~~atomic page-state updates in any wiki store~~ — `upsert_pages` is a whole-record upsert; atomic review/state coordination is G2's protocol (record the coordination points, do not design a second protocol).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/tests/memory/dynamics/spikes/s4_brain_state/__init__.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/memory/dynamics/spikes/s4_brain_state/harness.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/memory/dynamics/spikes/s4_brain_state/test_s4_harness.py", "action": "CREATE"},
    {"path": "sdd/state/FEAT-571/spikes/s4-brain-state/REPORT.md", "action": "CREATE"},
    {"path": "sdd/state/FEAT-571/spikes/s4-brain-state/metrics.json", "action": "CREATE"},
    {"path": "sdd/state/FEAT-571/spikes/s4-brain-state/amendment.md", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/memory/dream/brain.py#BrainStore",
    "sym:packages/ai-parrot/src/parrot/memory/dream/brain.py#BrainStore.remember",
    "sym:packages/ai-parrot/src/parrot/memory/dream/brain.py#BrainStore.search",
    "sym:packages/ai-parrot/src/parrot/memory/dream/brain.py#BrainStore.copy_page_to",
    "sym:packages/ai-parrot/src/parrot/memory/dream/runner.py#DreamCycleRunner",
    "sym:packages/ai-parrot/src/parrot/memory/dream/runner.py#DreamCycleRunner._collect",
    "sym:packages/ai-parrot/src/parrot/memory/dream/models.py#DreamState",
    "sym:packages/ai-parrot/src/parrot/memory/dream/models.py#DreamConfig",
    "sym:packages/ai-parrot/src/parrot/memory/dream/models.py#DistilledKnowledge",
    "sym:packages/ai-parrot/src/parrot/memory/dream/models.py#DreamCycleReport",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#WikiPageRecord",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#SQLiteWikiStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/context.py#pack_results"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Real store, temp path**: instantiate the SQLite wiki store the same way `BrainStore.__init__` does (read `brain.py:31-52` for the exact `create_wiki_store(...)` call) under `tmp_path`; never touch `.parrot/`.
- **Designs are adapters over the same record**: each design exposes `write(page, state)`, `read_state(page_id, version)`, `strip_for_search(body)`; the harness runs identical scenarios through all three.
- **Version identity**: `content_version = sha1(body_without_state + "|" + sorted(source_episode_ids))`; same title/category with new evidence ⇒ new version; identical inputs ⇒ same version (idempotent re-distill).
- **Lineage**: directed edges `episode → version`, `version --supersedes--> version`; traversal depth-bounded (report the bound), cycle ⇒ `lineage_cycle` (spec §7 category); alias dedupe ⇒ one credit per outcome per canonical version.
- **Priors vs evidence**: inherited max stability / mean difficulty are recorded as `prior_*` fields; summed source `review_count` must **not** appear as the new version's review count (spec §2 "summed source review counts are not evidence").
- Formatting: `black` 120 cols; `ruff check` clean on the spike package. No new deps.

### References in Codebase
- `core/memory/dream/runner.py:105-235` — collect/cluster/distill/mark/promote flow and watermark rule S4 must recover old episodes from.
- `core/memory/dream/brain.py:53-112` — how a page record is built today (fields that survive `copy_page_to`).
- `sdd/state/FEAT-569/findings/F005-brain.md` — proposal finding this gate quantifies.

---

## Implementation Blueprint

### Steps (in order)
1. Write `harness.py`: store factory (mirrors `BrainStore.__init__`), `PageState` dataclass, the three `Design` adapters, `content_version()`, `Lineage` graph, scenario runners, `write_report()` — *why*: one module produces every comparison row.
2. Write `test_s4_harness.py`: fast tests (version identity idempotence, lineage cycle rejection, no double credit via aliases, frontmatter stripped before FTS) + `PARROT_SPIKE_FULL=1` comparison run — *why*: FEAT-563 validation is a pytest file; the comparison writes the report.
3. Run the comparison once, `tee` to `artifacts/logs/feat-571-s4-<ts>.log`; fill REPORT.md / metrics.json / amendment.md; list G2 coordination points explicitly — *why*: spec §3 G4 requires the freeze plus G2 coordination before passing.

### `packages/ai-parrot/tests/memory/dynamics/spikes/s4_brain_state/harness.py` (CREATE)
```python
"""S4 spike harness: brain page-state designs, version identity, lineage and report writer."""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from parrot.knowledge.wiki.store import WikiPageRecord  # store.py:409

logger = logging.getLogger(__name__)
REPO_ROOT = Path(__file__).resolve().parents[7]
SPIKE_DIR = REPO_ROOT / "sdd" / "state" / "FEAT-571" / "spikes" / "s4-brain-state"
MAX_LINEAGE_DEPTH = 32  # report parameter — the amendment freezes the production bound


@dataclass(frozen=True)
class PageState:
    """Mutable dynamics state a page version carries (subset of spec §2 MemoryState + priors)."""

    stability: float
    difficulty: float
    review_count: int
    prior_stability: float | None
    prior_difficulty: float | None
    parameter_version: str


def content_version(body_without_state: str, source_episode_ids: list[str]) -> str:
    """Deterministic version id: same prose + same sources ⇒ same version; new evidence ⇒ new version."""
    digest = hashlib.sha1()
    digest.update(body_without_state.encode("utf-8"))
    digest.update(b"|")
    digest.update(",".join(sorted(source_episode_ids)).encode("utf-8"))
    return digest.hexdigest()


class Design(Protocol):
    """One page-state storage design; all three run identical scenarios."""

    name: str

    async def write(self, store: Any, record: WikiPageRecord, state: PageState, version: str) -> None: ...
    async def read_state(self, store: Any, concept_id: str, version: str) -> PageState | None: ...
    def searchable_body(self, body: str) -> str: ...


class FrontmatterDesign:
    name = "A-frontmatter"
    # FILL IN: prepend a fenced state block to body; searchable_body strips it; read_state parses it back.


class SidecarDesign:
    name = "B-sidecar"
    # FILL IN: state lives in a companion record (concept_id + ":state:" + version); body untouched.


class SimulatedMetadataColumnDesign:
    name = "C-metadata-column(simulated)"
    # FILL IN: state kept in a prototype-owned sqlite table beside the wiki DB (NOT a WikiPageRecord change); body untouched.


@dataclass
class Lineage:
    """episode → version edges and version --supersedes--> version edges, depth-bounded and cycle-checked."""

    episode_to_version: dict[str, str] = field(default_factory=dict)
    supersedes: dict[str, str] = field(default_factory=dict)  # new_version -> old_version

    def canonical(self, version: str) -> str:
        # FILL IN: follow `supersedes` forward (old → newest) up to MAX_LINEAGE_DEPTH; raise LineageCycle on revisit. Spec §7 `lineage_cycle`.
        raise NotImplementedError

    def credit_targets(self, cited_ids: list[str]) -> set[str]:
        # FILL IN: map episode ids/version ids to canonical versions; return the deduped set (one credit per outcome per version).
        raise NotImplementedError


async def make_store(tmp_dir: Path) -> Any:
    # FILL IN: mirror BrainStore.__init__ (brain.py:31-52) create_wiki_store(...) call against tmp_dir; return the store.
    raise NotImplementedError


async def scenario_redistill_5x(design: Design, store: Any) -> dict[str, Any]:
    # FILL IN: same title/category, 5 successive bodies/evidence → distinct versions? old versions excluded from search_fts? state preserved per version?
    raise NotImplementedError


async def scenario_copy_and_edit(design: Design, store: Any) -> dict[str, Any]:
    # FILL IN: remember-style re-write + copy to a second store → does state survive (mirrors brain.py:97 and :176)?
    raise NotImplementedError


async def scenario_search_drift(design: Design, store: Any) -> dict[str, Any]:
    # FILL IN: FTS hit set + rank + pack_results token cost with vs without state text present.
    raise NotImplementedError


def scenario_watermark_recovery() -> dict[str, Any]:
    # FILL IN: episodes older than DreamState.last_run without consolidated_into → how a re-distill query would find them (runner.py:235-265).
    raise NotImplementedError


def write_report(results: dict[str, Any], *, commands: list[str]) -> Path:
    SPIKE_DIR.mkdir(parents=True, exist_ok=True)
    (SPIKE_DIR / "metrics.json").write_text(json.dumps(results, indent=2, sort_keys=True, default=str) + "\n")
    # FILL IN: REPORT.md — Commands · Versions · Per-design table (search drift, token cost, copy/edit survival, 5× re-distill, duplicate
    # forwarding) · Lineage bound/cycle results · Legacy evidence inventory (reinforcement_counts / org_promotion_cycles) · G2 coordination
    # points · Pass/Fail · Limitations · amendment pointer.
    raise NotImplementedError
```
**Why this shape**: `content_version` is complete because the spec fixes its property (distinguishable version per re-distillation); the three designs share one protocol so the report compares like with like; `Lineage.canonical`/`credit_targets` are exactly the two operations M4 will need to prevent double credit.

### `packages/ai-parrot/tests/memory/dynamics/spikes/s4_brain_state/test_s4_harness.py` (CREATE)
```python
"""S4 gate tests: fast identity/lineage/design checks (always) + design comparison (PARROT_SPIKE_FULL=1)."""
from __future__ import annotations

import os

import pytest

from . import harness

FULL = os.environ.get("PARROT_SPIKE_FULL") == "1"
DESIGNS = [harness.FrontmatterDesign(), harness.SidecarDesign(), harness.SimulatedMetadataColumnDesign()]


def test_content_version_is_deterministic_and_evidence_sensitive() -> None:
    a = harness.content_version("lesson", ["e1", "e2"])
    assert a == harness.content_version("lesson", ["e2", "e1"])
    assert a != harness.content_version("lesson", ["e1", "e2", "e3"])


def test_lineage_rejects_cycles_and_bounds_depth() -> None:
    # FILL IN: v1→v2→v1 raises LineageCycle; chain longer than MAX_LINEAGE_DEPTH raises. Spec §7 `lineage_cycle`.
    raise NotImplementedError


def test_alias_dedupe_gives_one_credit() -> None:
    # FILL IN: two episode ids mapped to the same canonical version → credit_targets returns exactly one version.
    raise NotImplementedError


def test_review_on_old_version_does_not_credit_new_version() -> None:
    # FILL IN: canonical() forwards, but credit for version N must be recorded against N (source version preserved) — assert both ids retained.
    raise NotImplementedError


@pytest.mark.parametrize("design", DESIGNS, ids=lambda d: d.name)
def test_searchable_body_has_no_state_text(design) -> None:
    # FILL IN: after write(), searchable_body() contains no numeric state tokens (e.g. "stability").
    raise NotImplementedError


@pytest.mark.skipif(not FULL, reason="set PARROT_SPIKE_FULL=1 to run the design comparison and write REPORT.md")
async def test_full_comparison_writes_report(tmp_path) -> None:
    # FILL IN: for each design: store = await make_store(tmp_path / design.name); run the four scenarios; write_report(...).
    raise NotImplementedError
```
**Why**: the always-on tests fix the invariants AC12 names (version identity, bounded cycle-free lineage, no double credit, no prose pollution); the gated test produces the design comparison.

### `sdd/state/FEAT-571/spikes/s4-brain-state/amendment.md` (CREATE)
```markdown
# Proposed spec amendment — S4 (TASK-3385) · status: PROPOSED (owner + architecture review; G2 coordination required)

## Freeze
- Page-state storage: FILL IN (A frontmatter | B sidecar | C `WikiPageRecord.metadata` column) — evidence: REPORT rows FILL IN
- Migration list if C: SQLiteWikiStore (store.py:821) · ArangoDBWikiStore (arango_store.py:135) · PostgresWikiStore (postgres_store.py:127) · `WikiPageRecord` (store.py:409) — DDL/field: FILL IN
- Version identity: content_version = sha1(body_without_state | sorted source episode ids); page_id stays the family key
- Forwarding/admission: reviews credit the delivered version; canonical forwarding only for ranking/exclusion; lineage depth bound: FILL IN; cycles → `lineage_cycle`
- Promotion evidence: direct verified reviews on the promoted version + S1 retention/lapse policy; `reinforcement_counts`/`org_promotion_cycles` read-only legacy in dynamics mode
- Report fields: `pages_redistilled` = FILL IN semantics ; `memories_forgotten` = FILL IN (materialized vs evaluated-at-report-clock)
- FEAT-390 note: cycle-count promotion superseded in dynamics mode only (document in sdd/specs/dream-cycle-brain-consolidation.spec.md on acceptance)

## G2 coordination points
- FILL IN: which page-state writes must join the G2 atomic review transaction; which may be best-effort

## Pass/Fail
- State survives remember()/copy_page_to(): PASS|FAIL per design · FTS/pack unaffected: PASS|FAIL per design
- 5× re-distill → 5 distinct versions, old excluded: PASS|FAIL · watermark recovery path identified: PASS|FAIL · duplicate forwarding → one credit: PASS|FAIL

## Sections to edit on acceptance
§2 "Durable Storage and Lineage" (brain paragraph), §2 Data Models (MemoryRef.content_version), §3 M4 eligibility + file list, §6 C6/C7, §8 brain-state question.
```
**Why**: spec §3 G4 "Freeze storage/migration, version identity and promotion evidence policy" — the owner merges this into the spec; the task never edits the spec.

### FILL IN checklist
- [ ] `harness.py::FrontmatterDesign/SidecarDesign/SimulatedMetadataColumnDesign` — three adapters over one protocol; bounded by spec §3 row G4
- [ ] `harness.py::Lineage.canonical/credit_targets` — bounded, cycle-checked, alias-deduped; bounded by AC12 and §7 `lineage_cycle`
- [ ] `harness.py::make_store/scenario_*` — real SQLite wiki store under tmp_path, four scenarios; bounded by spec §2 brain paragraph
- [ ] `REPORT.md`, `metrics.json`, `amendment.md` — from the logged run; G2 coordination points listed

---

## Acceptance Criteria

- [ ] Fast tests pass (version identity, cycle/bound rejection, alias dedupe, old-version credit preservation, no state text in searchable body for all three designs)
- [ ] Full comparison run once (`PARROT_SPIKE_FULL=1`), log under `artifacts/logs/`, REPORT.md quotes the command
- [ ] REPORT.md compares the three designs on search drift, packed token cost, copy/edit survival, 5× re-distillation, watermark recovery and duplicate forwarding, and inventories legacy promotion evidence
- [ ] `amendment.md` freezes design + per-backend migration list, version identity, forwarding/admission, promotion evidence, report field semantics, FEAT-390 note, and lists G2 coordination points
- [ ] `black --check` and `ruff check` clean on `packages/ai-parrot/tests/memory/dynamics/spikes/s4_brain_state/`
- [ ] No edits to `WikiPageRecord`, wiki backends, `BrainStore`, dream runner/models, or any spec

---

## Validation Commands

- `pytest packages/ai-parrot/tests/memory/dynamics/spikes/s4_brain_state/test_s4_harness.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/memory/dynamics/spikes/s4_brain_state/test_s4_harness.py — see blueprint
def test_content_version_is_deterministic_and_evidence_sensitive(): ...
def test_lineage_rejects_cycles_and_bounds_depth(): ...
def test_alias_dedupe_gives_one_credit(): ...
def test_review_on_old_version_does_not_credit_new_version(): ...
def test_searchable_body_has_no_state_text(design): ...      # ×3 designs
async def test_full_comparison_writes_report(tmp_path): ...  # PARROT_SPIKE_FULL=1 only
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** — §2 "Durable Storage and Lineage" (brain paragraphs), §3 rows G4/M4, §6 C6/C7, §8 brain-state question; skim `sdd/specs/dream-cycle-brain-consolidation.spec.md` (FEAT-390)
2. **Check dependencies** — none (coordinate findings with S2's report if it lands first, but do not block on it)
3. **Verify the Codebase Contract** — every anchor with `grep`/`sed -n`; read `brain.py:31-52` for the store factory call
4. **Update status** in `sdd/tasks/index/memory-dynamics.json` → `"in-progress"`
5. **Implement** from the blueprint; complete every `FILL IN`; keep all code in the spike dir
6. **Run the comparison once**, save the log, fill REPORT.md / metrics.json / amendment.md
7. **Verify** acceptance criteria; the gate passes only on owner/architecture review of `amendment.md` with G2 coordination
8. **Move this file** to `sdd/tasks/completed/TASK-3385-s4-brain-page-state-spike.md`, update the index → `"done"`, fill the Completion Note

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
