# TASK-4397: Live-server suites + operator docs (migration per plane, projections, embedded guard)

**Feature**: FEAT-670 — HelixDB graph provider
**Spec**: `sdd/specs/helixdb-provider.spec.md` (§3 Module 11, §4 Integration Tests, AC15, AC17, AC21, AC23, AC24, AC25, AC26)
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4396, TASK-4375, TASK-4395, TASK-4381, TASK-4389, TASK-4390
**Assigned-to**: unassigned

---

## Context

Last task of FEAT-670. Everything is implemented and unit-tested on embedded `InMemory`; what remains is the
**live tier** against a real server (`docker/helixdb`, TASK-4375) and the operator documentation. The live tests
are `pytest.mark.live` and skip when `HELIXDB_URL` is unset/unreachable (AC15), using the `helix_live_settings`
fixture (TASK-4373). The docs skeleton `docs/wiki/helixdb.md` exists (TASK-4375: start, env vars, modes); this
task adds the migration-per-plane section (AC23), ledger rebuild, projections, the embedded-mode guard
(spike result, `sdd/state/FEAT-670/spike-embedded-two-writers.md`) and the `wikitoolkit migrate` reference, plus
the cheatsheet lines.

---

## Scope

- CREATE `tests/knowledge/helix/test_live_server.py` with the spec §4 integration tests:
  `test_live_server_wiki_roundtrip`, `test_live_server_concurrent_writers`, `test_live_graphindex_commit_revert`,
  `test_compose_readyz`, `test_sdk_speaks_to_pinned_image`, `test_rebuild_from_canonical_sources`,
  `test_migrate_live_roundtrip`, `test_traversal_spec_parity_aql_vs_helix`, and `test_commit_seq_and_edge_key_atomic`
  on `helix-live` (AC21).
- MODIFY `docs/wiki/helixdb.md`: sections "Switching an existing project" (migration per plane), "Ledger",
  "Projections (PageIndex / BookStore)", "Embedded mode and the wiki.lock guard", "`wikitoolkit migrate` reference",
  "Rollback".
- MODIFY `docs/wiki/cheatsheet.md`: `build --backend helixdb`, `migrate --to helixdb`, `migrate --to sqlite --replace`,
  `make docker-helixdb`.

**NOT in scope**: any source change (a live failure is a bug in the owning task's module → ledger issue + follow-up);
`docker/helixdb/*` (TASK-4375); unit-tier tests.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/knowledge/helix/test_live_server.py` | CREATE | live suites (`-m live`) |
| `docs/wiki/helixdb.md` | MODIFY | migration/ledger/projection/guard/migrate sections |
| `docs/wiki/cheatsheet.md` | MODIFY | helix commands |

---

## Codebase Contract (Anti-Hallucination)

Verified 2026-10-16 on `dev` @ `1c239a5ca`.

### Verified Imports
```python
from click.testing import CliRunner
from parrot.knowledge.wiki.cli import wiki                                   # click group; `build` :1603 has `--backend` (:1553), `lint` :2358, `status --json` :2442
from parrot.knowledge.graphindex.publish import GraphPublisher               # publish.py:40; __init__(persistence, ctx) :50; publish(update) :90; revert_commit(commit_id) :138
from parrot.knowledge.graphindex.factory import make_stub_tenant_context     # factory.py:45
from parrot.knowledge.graphindex.backends import create_graph_persistence    # backends.py:95 (async)
from parrot.knowledge.ontology.contracts import create_ontology_graph_store  # contracts.py:182
from parrot.knowledge.ontology.schema import TraversalPattern, TenantContext # ontology/schema.py
# tests/knowledge/graphindex/persistence_conformance.py — case_apply_and_revert :37, case_seq_monotonic :48,
#   case_edge_key_identity :59, case_incident_edge_preimages :68, case_revert_conflict :81 (async, (persistence, ctx))
# created by dependency tasks:
#   helix_live_settings fixture (tests/knowledge/helix/conftest.py, TASK-4373); HelixWikiStore (4376); migrate CLI (4395);
#   tests/knowledge/ontology/fixtures/portable.ontology.yaml (4385); HelixOntologyGraphStore (4387/4388)
```

### Existing Signatures to Use
```text
docs/wiki/cheatsheet.md:43   `wikitoolkit build --backend arangodb # plano compartido en ArangoDB`   (grep -c -F → 1)
docs/wiki/helixdb.md          created by TASK-4375 — re-read; append sections after its last section
wikitoolkit ledger rebuild    wiki/cli.py:3505 (@ledger.command("rebuild")) — event-log replay (spec §3 M5 migration note)
tests/knowledge/wiki/test_arango_store_cas.py:17-50   live skip shape (bounded socket probe, module-level skip)
pytest.ini:6                  `live` marker registered
```

### Does NOT Exist
- ~~`wikitoolkit stats`~~ — use `wikitoolkit status --json` (`cli.py:2442`).
- ~~`wikitoolkit reproject`~~ — projections re-project via `PageIndexToolkit(helix_settings=…)` persistence and `Bookstore.reproject(scope)`; document those APIs.
- ~~A Makefile embedded target~~ — deliberately absent (AC12, Q2).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/tests/knowledge/helix/test_live_server.py", "action": "CREATE"},
    {"path": "docs/wiki/helixdb.md", "action": "MODIFY"},
    {"path": "docs/wiki/cheatsheet.md", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/graphindex/publish.py#GraphPublisher",
    "sym:packages/ai-parrot/src/parrot/knowledge/graphindex/factory.py#make_stub_tenant_context",
    "sym:packages/ai-parrot/src/parrot/knowledge/graphindex/backends.py#create_graph_persistence",
    "sym:packages/ai-parrot/src/parrot/knowledge/ontology/contracts.py#create_ontology_graph_store",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#build",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#lint",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#status"
  ]
}
```

---

## Implementation Notes

### Gates (decided)
- Module: `pytestmark = pytest.mark.live`; every test takes `helix_live_settings` (skips when unreachable).
- `test_compose_readyz`: additionally skip unless `shutil.which("docker")` and `PARROT_TEST_HELIX_COMPOSE=1`
  (it starts/stops a container; never implicit). Probe `/readyz` with **aiohttp** (never httpx — only
  `helix/client.py` may import it).
- `test_traversal_spec_parity_aql_vs_helix`: also skip unless ArangoDB is reachable (copy the bounded socket probe of
  `test_arango_store_cas.py:33-44`).
- `test_live_server_concurrent_writers`: two **processes** (`multiprocessing` spawn or `subprocess` running a tiny
  script) each upserting 50 distinct pages through the server; afterwards `stats()["pages"] == 100`.
- `test_commit_seq_and_edge_key_atomic`: two `HelixPersistence` instances (two clients) racing `apply_update` on the
  same tenant ⇒ distinct `seq`, no duplicate `edge_key`; node removal records incident edges; revert restores them;
  then run the five conformance cases against the live persistence.
- `test_rebuild_from_canonical_sources` / `test_migrate_live_roundtrip`: use a tmp copy of a small tree (e.g.
  `packages/ai-parrot/tests/fixtures` subset) with `.parrot/wiki.json`; `wikitoolkit build --backend sqlite` and
  `--backend helixdb` (env `HELIXDB_URL`, unique database per test) ⇒ `lint` clean and `status --json` counts equal;
  migrate sqlite→helixdb then `--to sqlite --replace` into a second tmp root ⇒ both reports `ok`, counts equal across
  the three planes.
- Every test uses a unique database name (`test_<uuid>`) and drops nothing else on the server.

### Docs content (decided — AC23 is the checklist)
- Per plane: wiki/graphindex = rebuild from canonical sources (`wikitoolkit build --backend helixdb`) **or**
  `wikitoolkit migrate --to helixdb` when sources are gone; schema = `migrate --plane schema`; ledger =
  `wikitoolkit ledger rebuild` (never copied); pageindex/bookstore = re-project; rollback = `wikitoolkit migrate --to sqlite --replace`.
- Fidelity notes from TASK-4394 (origin/asserted_by/provenance/symbol source_id gaps) — copy them from its Completion Note.
- Embedded guard: quote the exact exception class from the spike file; say multi-process use goes through the server.
- Memory footprint: a `dump_*` loads one whole part (≈ plane size on disk).
- `wikitoolkit migrate` option table and exit codes (0 ok · 1 not ok · 2 refused).
- No deprecation language about ArangoDB (AC16).

---

## Implementation Blueprint

### Steps (in order)
1. Live test module. 2. Run it against `make docker-helixdb` locally if available (record results or "not run" in the
Completion Note — never claim a pass you did not observe). 3. Docs. 4. Cheatsheet.

### `packages/ai-parrot/tests/knowledge/helix/test_live_server.py` (CREATE)
```python
"""FEAT-670 live tier — real HelixDB server (`make docker-helixdb`); skipped without HELIXDB_URL (AC15)."""
from __future__ import annotations

import os
import shutil
import uuid

import pytest

pytestmark = pytest.mark.live


def _db() -> str:
    return f"test_{uuid.uuid4().hex}"


async def test_live_server_wiki_roundtrip(helix_live_settings) -> None:
    """Build a small wiki on the server: FTS + vector + neighbours; lint methods clean."""
    # FILL IN — bounded by AC1/AC18


async def test_live_server_concurrent_writers(helix_live_settings) -> None:
    """Two processes upsert concurrently through the server; no lost writes."""
    # FILL IN — bounded by G8


async def test_live_graphindex_commit_revert(helix_live_settings) -> None:
    """GraphPublisher apply → revert on HelixPersistence (server)."""
    # FILL IN — bounded by AC4/AC21


async def test_commit_seq_and_edge_key_atomic(helix_live_settings) -> None:
    """Two clients race apply_update: distinct seq, no duplicate edge_key; incident-edge pre-images; conformance cases."""
    # FILL IN — bounded by AC21


@pytest.mark.skipif(not (shutil.which("docker") and os.getenv("PARROT_TEST_HELIX_COMPOSE") == "1"),
                    reason="set PARROT_TEST_HELIX_COMPOSE=1 with docker available to start docker/helixdb")
async def test_compose_readyz() -> None:
    """docker compose up → /readyz 200 within start_period (aiohttp probe)."""
    # FILL IN — bounded by AC12


async def test_sdk_speaks_to_pinned_image(helix_live_settings) -> None:
    """helix-db==0.3.4 DSL read batch accepted by ghcr.io/helixdb/helixdb:${HELIXDB_IMAGE_TAG} (S10)."""
    # FILL IN — bounded by AC24


async def test_rebuild_from_canonical_sources(tmp_path, helix_live_settings) -> None:
    """wikitoolkit build --backend helixdb → lint clean; status --json counts == SQLite build of the same tree (S11)."""
    # FILL IN — bounded by AC23


async def test_migrate_live_roundtrip(tmp_path, helix_live_settings) -> None:
    """migrate --to helixdb, then --to sqlite --replace into a second root; both ok; counts equal across 3 planes."""
    # FILL IN — bounded by AC26


async def test_traversal_spec_parity_aql_vs_helix(helix_live_settings) -> None:
    """portable.ontology.yaml patterns: equal id sets on ArangoDB and HelixDB via execute_pattern (skip w/o Arango)."""
    # FILL IN — bounded by AC25
```

### `docs/wiki/helixdb.md` (MODIFY)
```markdown
<!-- Append after the last section TASK-4375 wrote (re-read the file; keep its headings untouched). -->
## Switching an existing project to HelixDB
<!-- FILL IN: per-plane table (wiki · schema · graphindex · ledger · pageindex · bookstore) → command; rebuild is
     preferred when sources exist; `migrate` when they are gone — bounded by AC23 -->
## `wikitoolkit migrate`
<!-- FILL IN: synopsis, options table, checkpoint location `.parrot/migrate/<plane>.<from>-<to>.json`, --resume
     semantics, exit codes, report fields, fidelity notes, memory footprint — bounded by AC26 -->
## Ledger
<!-- FILL IN: `wikitoolkit ledger rebuild` replays `events.jsonl`; why it is never copied -->
## Projections (PageIndex, BookStore)
<!-- FILL IN: opt-in via helix_settings; generation fallback; projection_stale + Bookstore.reproject(scope) — bounded by AC22 -->
## Embedded mode and the `wiki.lock` guard
<!-- FILL IN: quote the spike's exception class; server mode for multi-process — bounded by AC13 -->
## Rollback
<!-- FILL IN: `wikitoolkit migrate --to sqlite --replace`, then set "backend": "sqlite" in .parrot/wiki.json -->
```

### `docs/wiki/cheatsheet.md` (MODIFY)
```bash
# occurrences: 1 (verified: grep -c -F 'wikitoolkit build --backend arangodb # plano compartido en ArangoDB' docs/wiki/cheatsheet.md) — line 43
# AFTER that line insert (same column alignment, Spanish comments like the surrounding block):
wikitoolkit build --backend helixdb  # plano en HelixDB (servidor: make docker-helixdb)
wikitoolkit migrate --to helixdb     # copia el plano actual a HelixDB (reanudable, con informe)
wikitoolkit migrate --to sqlite --replace   # vuelta atrás a SQLite
```

### FILL IN checklist
- [ ] Nine live test bodies — bounded by the ACs named on each.
- [ ] Six docs sections — bounded by AC23/AC26/AC22/AC13.

---

## Acceptance Criteria

- [ ] AC15: `pytest -m live` runs these against a server; without `HELIXDB_URL` every test skips (collected, not errored).
- [ ] AC21: `test_commit_seq_and_edge_key_atomic` green on `helix-live` (when a server is available; otherwise recorded "not run").
- [ ] AC23: `docs/wiki/helixdb.md` documents the migration path per plane + rollback; `test_rebuild_from_canonical_sources` exists.
- [ ] AC24: `test_sdk_speaks_to_pinned_image` exists.
- [ ] AC25: live AQL-vs-Helix parity test exists.
- [ ] AC17: docs and cheatsheet updated; `ruff check` clean on the test module.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/helix/test_live_server.py -q`

---

## Test Specification

See the blueprint module: nine named live tests; skip semantics per "Gates (decided)".

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — `python -m scripts.sdd.ensure_worktree --slug helixdb-provider --feature-id FEAT-670`
2. **Read the spec** §4 Integration Tests, AC23; read the spike file and TASK-4394's Completion Note.
3. **Check dependencies** — TASK-4396, 4375, 4395, 4381, 4389, 4390 `done`.
4. **Verify the Codebase Contract**.
5. **Update status** → `"in-progress"`, commit only the index file.
6. **Implement** from the blueprint; complete every `# FILL IN:` / `<!-- FILL IN -->`.
7. **Verify** — Validation Commands with `PYTHONPATH=packages/ai-parrot/src`; run `-m live` only if a server is up,
   and report honestly ("live tier not run: no HELIXDB_URL") otherwise — close as `partial` in that case.
8. **Commit the code** — only the three listed files.
9. **Close** with `scripts/sdd/close_task.sh TASK-4397 helixdb-provider verified` (or `partial` when the live tier could not run).
10. **Fill in the Completion Note**, then commit the SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
