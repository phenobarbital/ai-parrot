# TASK-4396: Compatibility gate + `wiki_store_matrix` backend contract matrix

**Feature**: FEAT-670 — HelixDB graph provider
**Spec**: `sdd/specs/helixdb-provider.spec.md` (§3 Module 11, §9 S9 + S10, AC1, AC14, AC15, AC24)
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4392, TASK-4393
**Assigned-to**: unassigned

---

## Context

Design research S9: the behavioural wiki-store suites must run as **one body against every backend**
(`sqlite`, `helix-memory`, `helix-live`) instead of per-backend copies. S10: the SDK (`helix-db==0.3.4`), the
embedded wheel (`helix-db-embedded==0.3.3`) and the pinned server image (`v0.0.12`) are versioned independently,
so a **compatibility gate** must be green before any backend logic test is trusted. This task adds the
`wiki_store_matrix` fixture to the helix conftest (created by TASK-4373), the unit half of the gate, and the
matrix suite. The live server suites are TASK-4397.

Parallel: **false** — `tests/knowledge/helix/conftest.py` is loaded by every helix test module.

---

## Scope

- MODIFY `tests/knowledge/helix/conftest.py`: add the `wiki_store_matrix` fixture (params `sqlite`, `helix-memory`,
  `helix-live` marked `live`).
- CREATE `tests/knowledge/helix/test_compat_gate.py`: `test_native_wheel_imports`, `test_async_only_usage`,
  `test_extras_and_ruff_exemption` (unit); `test_sdk_speaks_to_pinned_image` stays in TASK-4397 (live).
- CREATE `tests/knowledge/wiki/test_wiki_store_matrix.py`: CAS, attrs, symbols, replace-slice, read-only writes,
  close/reopen, search contract (archive exclusion, score scale, 800 clamp), bootstrap failure — one body per case.

**NOT in scope**: per-backend `test_helix_store*.py` files (TASK-4376/4377 own them); live-only suites (TASK-4397);
any source change (if a matrix case fails on a backend, fix it in the owning task's file via a follow-up, not here).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/knowledge/helix/conftest.py` | MODIFY | `wiki_store_matrix` fixture |
| `packages/ai-parrot/tests/knowledge/helix/test_compat_gate.py` | CREATE | compatibility gate (unit) |
| `packages/ai-parrot/tests/knowledge/wiki/test_wiki_store_matrix.py` | CREATE | contract matrix suite |

---

## Codebase Contract (Anti-Hallucination)

Verified 2026-10-16 on `dev` @ `1c239a5ca`.

### Verified Imports
```python
from parrot.knowledge.wiki.store import BaseWikiStore, SQLiteWikiStore, WikiPageRecord   # wiki/store.py:697, :1092, :433
from parrot.knowledge.wiki.symbols import SymbolRecord                                  # wiki/symbols.py:58
# created by dependency tasks:
from parrot.knowledge.helix.settings import HelixMode, HelixSettings, resolve_helix_settings   # TASK-4372
from parrot.knowledge.wiki.helix_store import HelixWikiStore                                 # TASK-4376
# tests/knowledge/helix/conftest.py (TASK-4373) provides fixtures: helix_memory_settings, helix_live_settings
```

### Existing Signatures to Use
```python
# wiki/store.py — SQLiteWikiStore(db_path, wiki_name="", *, read_only=False, sqlite_policy=None, persistent_writer=False)
#   compare_and_swap_page(page, expected_content_hash) -> bool; get_attrs / upsert_attrs; upsert_symbols / symbols_for /
#   find_symbols / search_symbols_fts; replace_source_slice(source_id, pages, edges=None) -> dict;
#   search_fts(query, category=None, limit=10) (category None excludes "archive"); search_vector(embedding, limit=10) (score in [-1,1])
# Existing per-backend suites to port case-for-case (bodies, not files):
#   tests/knowledge/wiki/test_store_cas.py, test_store_attrs.py, test_postgres_symbols.py, test_arango_store_cas.py:17-44 (live skip shape)

# ruff.toml — per-file ignores block; TID251 bans "httpx" (ruff.toml:127); TASK-4373 adds
#   "packages/ai-parrot/src/parrot/knowledge/helix/client.py" = ["TID251"]
# packages/ai-parrot/pyproject.toml — TASK-4373 adds extras `helixdb` / `helixdb-embedded`; root pyproject.toml dev group gains both wheels
# pytest.ini:6 — `live` marker registered
```

### Does NOT Exist
- ~~`tests/knowledge/conftest.py`~~ — none; a conftest in `tests/knowledge/helix/` is **not** visible to `tests/knowledge/wiki/`.
  The matrix module imports the fixtures explicitly (see Implementation Notes).
- ~~`helixdb.Client` usage anywhere~~ — must stay absent (AC14); only `AsyncClient`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/tests/knowledge/helix/conftest.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/helix/test_compat_gate.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/test_wiki_store_matrix.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#SQLiteWikiStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#WikiPageRecord",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/symbols.py#SymbolRecord"
  ]
}
```

---

## Implementation Notes

### Spec drift
- Spec §3 M11 puts `wiki_store_matrix` in `tests/knowledge/helix/conftest.py` and the matrix suite in
  `tests/knowledge/wiki/`. Pytest conftest fixtures are directory-scoped, so the wiki module must re-export them:
  `from tests.knowledge.helix.conftest import helix_live_settings, helix_memory_settings, wiki_store_matrix  # noqa: F401`
  (`tests.knowledge.*` absolute imports are already used, e.g. `tests/knowledge/graphindex/test_graph_document.py:9`).
  This needs `packages/ai-parrot/tests/knowledge/helix/__init__.py`; if TASK-4373 did not create it, add an empty one
  and list it in the Completion Note (it is a package marker, not logic).
- The conftest must **not** `importorskip("helixdb_uniffi")` at module top (spec §4 sketch): that would skip the
  `sqlite` param too once re-exported. Skip inside the `helix-memory` branch of the fixture instead.

### Fixture shape (decided)
```python
@pytest.fixture(params=["sqlite", "helix-memory", pytest.param("helix-live", marks=pytest.mark.live)])
async def wiki_store_matrix(request, tmp_path): ...
```
Resolve `helix_memory_settings` / `helix_live_settings` lazily with `request.getfixturevalue(...)` inside the branch, so
the `sqlite` param never touches HelixDB fixtures and `helix-live` skips through `helix_live_settings`'s reachability skip.
Yield an initialised store; after the test call `close()` only when the store defines it (`SQLiteWikiStore` has **no** `close()` — verified, no `def close` in `wiki/store.py`; `HelixWikiStore.close()` is async).

### Compatibility gate (unit)
- `test_native_wheel_imports`: `importorskip("helixdb_uniffi")`; open `HelixDbSource.IN_MEMORY(<db>)` through
  `helixdb.AsyncClient.embedded(InMemory(<db>))`, run one trivial read batch, close.
- `test_async_only_usage`: `ast` scan over `packages/*/src/**/*.py`: no `Call` whose func is `Attribute(attr="Client")`
  on a `helixdb` name or `Name("Client")` imported from `helixdb`, no `Client.embedded(`; `import httpx` / `from httpx` /
  `helixdb.async_client` imports only in `packages/ai-parrot/src/parrot/knowledge/helix/client.py`.
- `test_extras_and_ruff_exemption`: parse `packages/ai-parrot/pyproject.toml` (tomllib) — extras `helixdb ==
  ["helix-db==0.3.4"]`, `helixdb-embedded` contains `helix-db-embedded==0.3.3`; root `pyproject.toml` dev group has
  both; `ruff.toml` per-file-ignores has `helix/client.py = ["TID251"]` and no other `helix/` entry.

---

## Implementation Blueprint

### Steps (in order)
1. Add the fixture to the helix conftest. 2. Gate tests. 3. Matrix suite. 4. Run with and without the wheel.

### `packages/ai-parrot/tests/knowledge/helix/conftest.py` (MODIFY)
```python
# Anchor: append at END of file (TASK-4373 created it; re-read it first and reuse its imports / helpers).
@pytest.fixture(params=["sqlite", "helix-memory", pytest.param("helix-live", marks=pytest.mark.live)])
async def wiki_store_matrix(request: pytest.FixtureRequest, tmp_path: Path):
    """Contract-matrix fixture: the same behavioural body runs against every wiki backend (S9)."""
    if request.param == "sqlite":
        from parrot.knowledge.wiki.store import SQLiteWikiStore

        store = SQLiteWikiStore(tmp_path / "wiki.db", wiki_name="matrix")
    else:
        if request.param == "helix-memory":
            pytest.importorskip("helixdb_uniffi", reason="helix-db-embedded not installed (ai-parrot[helixdb-embedded])")
            settings = request.getfixturevalue("helix_memory_settings")
        else:
            settings = request.getfixturevalue("helix_live_settings")
        from parrot.knowledge.wiki.helix_store import HelixWikiStore

        store = HelixWikiStore(settings, wiki_name="matrix")
    # FILL IN: await store.initialize() when the store defines it; yield; in finally await store.close() only when
    #   defined (SQLiteWikiStore has none) — bounded by
    #   spec §7 "Bootstrap, not migration" (initialize is idempotent)
```

### `packages/ai-parrot/tests/knowledge/helix/test_compat_gate.py` (CREATE)
```python
"""FEAT-670 compatibility gate (S10) — SDK, embedded wheel and async-only usage."""
from __future__ import annotations

import ast
import tomllib
import uuid
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[5]
CLIENT = REPO / "packages/ai-parrot/src/parrot/knowledge/helix/client.py"


async def test_native_wheel_imports() -> None:
    pytest.importorskip("helixdb_uniffi", reason="helix-db-embedded not installed (ai-parrot[helixdb-embedded])")
    from helixdb import AsyncClient, InMemory

    client = await AsyncClient.embedded(InMemory(f"gate_{uuid.uuid4().hex}"))
    try:
        # FILL IN: one trivial read batch (e.g. count of a label) through client.query(...) — bounded by §6 SDK surface
        pass
    finally:
        await client.close()


def test_async_only_usage() -> None:
    offenders: list[str] = []
    for path in REPO.glob("packages/*/src/**/*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            # FILL IN: flag `import httpx`, `from httpx …`, `from helixdb.async_client …` outside CLIENT; flag
            #   `helixdb.Client(` / `Client(` imported from helixdb / `.embedded(` on a `Client` name — bounded by AC14
            pass
    assert offenders == []


def test_extras_and_ruff_exemption() -> None:
    core = tomllib.loads((REPO / "packages/ai-parrot/pyproject.toml").read_text(encoding="utf-8"))
    extras = core["project"]["optional-dependencies"]
    assert extras["helixdb"] == ["helix-db==0.3.4"]
    assert "helix-db-embedded==0.3.3" in extras["helixdb-embedded"]
    root = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    dev = root["dependency-groups"]["dev"]
    assert "helix-db==0.3.4" in dev and "helix-db-embedded==0.3.3" in dev
    ruff = tomllib.loads((REPO / "ruff.toml").read_text(encoding="utf-8"))
    ignores = ruff["lint"]["per-file-ignores"]
    helix = {k: v for k, v in ignores.items() if "knowledge/helix/" in k}
    assert helix == {"packages/ai-parrot/src/parrot/knowledge/helix/client.py": ["TID251"]}
```
(Verify `REPO` depth: the file is `packages/ai-parrot/tests/knowledge/helix/test_compat_gate.py` → `parents[5]` is the
repo root; `ruff.toml` keys are under `[lint.per-file-ignores]` (verified `ruff.toml:137`).)

### `packages/ai-parrot/tests/knowledge/wiki/test_wiki_store_matrix.py` (CREATE)
```python
"""Backend contract matrix (FEAT-670 S9): one body per behaviour, run on sqlite / helix-memory / helix-live."""
from __future__ import annotations

import pytest

from parrot.knowledge.wiki.store import WikiPageRecord
from tests.knowledge.helix.conftest import helix_live_settings, helix_memory_settings, wiki_store_matrix  # noqa: F401


def _page(cid: str, *, category: str = "concept", body: str = "body", content_hash: str | None = None) -> WikiPageRecord:
    return WikiPageRecord(concept_id=cid, title=cid, category=category, body=body, content_hash=content_hash)


async def test_cas_insert_only_and_mismatch(wiki_store_matrix) -> None:
    store = wiki_store_matrix
    assert await store.compare_and_swap_page(_page("p:1", content_hash="a"), None) is True
    assert await store.compare_and_swap_page(_page("p:1", content_hash="b"), None) is False
    assert await store.compare_and_swap_page(_page("p:1", content_hash="b"), "zzz") is False
    assert await store.compare_and_swap_page(_page("p:1", content_hash="b"), "a") is True


# FILL IN: test_attrs_roundtrip_and_list_by_attrs, test_symbols_roundtrip_and_fts, test_replace_source_slice_drops_old,
#   test_read_only_rejects_writes (reopen read-only → PermissionError), test_close_reopen_persists (sqlite + helix-live only;
#   helix-memory is per-instance → skip with reason), test_search_fts_archive_excluded_by_default, test_search_fts_limit_clamped
#   (limit=5000 does not raise, ≤ 800 rows), test_search_vector_score_scale_and_zero_vector, test_meta_roundtrip,
#   test_bootstrap_failure_surfaces (helix only: unreachable/blocked → HelixUnavailable; sqlite param skips) — port the
#   assertions of test_store_cas.py / test_store_attrs.py / test_postgres_symbols.py — bounded by AC1, AC11, AC18
```

### FILL IN checklist
- [ ] conftest fixture lifecycle — bounded by spec §7.
- [ ] `test_native_wheel_imports` read batch; `test_async_only_usage` AST rules — bounded by AC14/AC24.
- [ ] Matrix cases — bounded by AC1/AC11/AC18.

---

## Acceptance Criteria

- [ ] AC1 / AC15: the matrix runs the same bodies on `sqlite` and `helix-memory` in CI; `helix-live` is `-m live` and skips without `HELIXDB_URL`.
- [ ] AC14 / AC24 (unit half): `test_native_wheel_imports`, `test_async_only_usage`, `test_extras_and_ruff_exemption` green.
- [ ] Without the embedded wheel the `sqlite` params still run (helix params skip with the extra named).

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/helix/test_compat_gate.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_wiki_store_matrix.py -q`
- `pytest packages/ai-parrot/tests/knowledge/helix/test_registrations.py -q`

---

## Test Specification

As in the blueprint blocks: three gate tests, ≥ 11 matrix cases each parametrised ×3 by the fixture.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — `python -m scripts.sdd.ensure_worktree --slug helixdb-provider --feature-id FEAT-670`
2. **Read the spec** §3 M11, §9 S9/S10.
3. **Check dependencies** — TASK-4392 and TASK-4393 `done`. **Exclusive** (`parallel: false`): no other task may edit the helix conftest concurrently.
4. **Verify the Codebase Contract** — read TASK-4373's conftest and reuse its fixture names exactly.
5. **Update status** → `"in-progress"`, commit only the index file.
6. **Implement** from the blueprint; complete every `# FILL IN:`.
7. **Verify** — Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
8. **Commit the code** — only the listed files (+ `tests/knowledge/helix/__init__.py` if you had to create it).
9. **Close** with `scripts/sdd/close_task.sh TASK-4396 helixdb-provider verified`.
10. **Fill in the Completion Note**, then commit the SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
