# TASK-4467: sidemantic spike, model loader and sidemantic engine (M4)

**Feature**: FEAT-704 — Semantic Layer — governed metric queries for agents (`ai-parrot-semantic`)
**Spec**: `sdd/specs/semantic-layer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4465, TASK-4466
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 + §8 Q2. This task opens with a bounded **spike** against the installed `sidemantic==0.12.0` wheel: confirm the API names the spec marks `(unverified — check before use)` (`SemanticLayer`, the directory loader, `compile(...)` kwargs, filter-string grammar, how `security:` blocks surface, the Ossie importer) and whether `compile` is reentrant. Then it implements the loader, the sidemantic engine and the single `compile()` dispatch, and creates the shared model/DuckDB fixtures every later test uses.

---

## Scope

- Spike: record every confirmed sidemantic name/signature (module path + line) and the reentrancy verdict in the Completion Note; update this task's Codebase Contract first.
- Implement `packages/ai-parrot-semantic/src/parrot/semantic/loader.py`: `PhysicalSchema`, `LoadedModel`, `SemanticModelLoader` (`load`, `reload_if_changed`).
- Implement `packages/ai-parrot-semantic/src/parrot/semantic/engines/sidemantic_engine.py`: `filter_tree_to_sidemantic`, `compile_sidemantic`.
- Implement `packages/ai-parrot-semantic/src/parrot/semantic/engines/__init__.py`: async `compile()` dispatch on `model.policy.engine` (native branch imports `.native` lazily), per-model `asyncio.Lock` unless the spike proves reentrancy, `asyncio.to_thread`, optional cache lookup.
- Create `packages/ai-parrot-semantic/tests/_models.py` (fixtures `models_dir`, `duckdb_warehouse`, `loaded_models`) and `packages/ai-parrot-semantic/tests/fixtures/models/orders.yml` + `orders.policy.yaml`.
- Write `test_loader.py` and `test_sidemantic_engine.py`.

**NOT in scope**: the native compiler (TASK-4468 creates `engines/native.py`); `CompileCache` (TASK-4475 — referenced here only by a TYPE_CHECKING string annotation); governance.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-semantic/src/parrot/semantic/loader.py` | CREATE | model loader + physical schema |
| `packages/ai-parrot-semantic/src/parrot/semantic/engines/__init__.py` | CREATE | compile() dispatch |
| `packages/ai-parrot-semantic/src/parrot/semantic/engines/sidemantic_engine.py` | CREATE | sidemantic compile adapter |
| `packages/ai-parrot-semantic/tests/_models.py` | CREATE | shared model + DuckDB fixtures (imported by test modules) |
| `packages/ai-parrot-semantic/tests/fixtures/models/orders.yml` | CREATE | sidemantic `orders` model |
| `packages/ai-parrot-semantic/tests/fixtures/models/orders.policy.yaml` | CREATE | policy side-file fixture |
| `packages/ai-parrot-semantic/tests/test_loader.py` | CREATE | loader tests |
| `packages/ai-parrot-semantic/tests/test_sidemantic_engine.py` | CREATE | engine tests (3 dialects, concurrency, snapshots) |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (re-verified on `dev` @ 754878f67, 2026-10-19). Use these exact imports, class names and
> method signatures. **DO NOT** invent, guess or assume anything not listed here — verify first.
> `grep` in this repo is aliased to `ugrep` by RTK: use `grep -F` for anchors with `(`, `[`, `{`.

### Verified Imports
```python
from parrot.semantic.models import SemanticQuery, CompiledQuery, ModelMember, FilterGroup, FilterLeaf   # TASK-4464
from parrot.semantic.errors import SemanticPolicyError, SemanticValidationError                       # TASK-4464
from parrot.semantic.policy import ModelPolicy, load_policy                                           # TASK-4465
from parrot.semantic.ossie import is_ossie_document, validate_ossie_document                          # TASK-4466
import sqlglot; from sqlglot import exp                                                               # sqlglot 30.23.0
# sidemantic (unverified — check before use; confirmed by this task's spike):
#   from sidemantic import SemanticLayer ; layer.compile(metrics=, dimensions=, filters=, order_by=, limit=, dialect=)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/common/sql_dialects.py
SQLGLOT_DIALECT_MAP: Dict[str, str]   # line 6 — postgres/postgresql→postgres, bigquery, duckdb, ...
# packages/ai-parrot/src/parrot/tools/dataset_manager/sources/dialects.py
def driver_to_dialect(driver)          # line 41 — "pg" → "postgres"
```

### Does NOT Exist
- ~~sidemantic async API~~ — none; compile under `asyncio.to_thread`.
- ~~`sidemantic-rs`~~ — not required by the 0.12.0 wheel.
- ~~sidemantic `user_attributes` / `SecurityPolicy` use~~ — never passed; `security:` blocks are REJECTED at load (spec Non-Goals).
- ~~`parrot.semantic.cache.CompileCache` at this task's start~~ — created by TASK-4475; reference it only as a string annotation under `TYPE_CHECKING`.
- ~~`parrot.semantic.engines.native`~~ — created by TASK-4468; import it lazily inside `compile()` only.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-semantic/src/parrot/semantic/loader.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-semantic/src/parrot/semantic/engines/__init__.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-semantic/src/parrot/semantic/engines/sidemantic_engine.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-semantic/tests/_models.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-semantic/tests/fixtures/models/orders.yml",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-semantic/tests/fixtures/models/orders.policy.yaml",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-semantic/tests/test_loader.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-semantic/tests/test_sidemantic_engine.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/dataset_manager/sources/dialects.py#driver_to_dialect"
  ]
}
```

---

## Implementation Notes

- If sidemantic is not importable in the venv, STOP: the operator install from TASK-4463's Completion Note has not happened.
- `model_digest` = SHA-256 over the sorted (relative path, bytes) of the model's source files; `engine_version` = `sidemantic.__version__` (verify attribute) or `"native-1"`.
- `PhysicalSchema.tables` types: take them from the sidemantic model definitions when declared, else introspect nothing — FILL IN from the spike (no DB connection at compile time, AC2).
- The DuckDB fixture creates `sales.orders(region, tenant_id, order_date, amount, customer_id)` and `dim.customers(id, email, salary)` with seeded rows (spec §4 Test Data).

### Key Constraints
- Async-first; sync CPU-only work (sqlglot, sidemantic compile) runs under `asyncio.to_thread` at the call site.
- Pydantic v2 models; `logging.getLogger(__name__)` / `self.logger`, never `print`.
- Google-style docstrings, strict type hints, 120-column lines; `ruff check` clean (TID251 bans apply).
- Fail closed wherever governance is involved (spec §7 "Patterns to Follow").
- Worktree testing: prefix pytest with `PYTHONPATH=packages/ai-parrot-semantic/src:packages/ai-parrot/src` (add `:packages/ai-parrot-server/src` for server tests); never `uv sync` inside a worktree.

---

## Implementation Blueprint

> **Executor-ready starting point.** Write each block to its declared path nearly verbatim,
> then complete every `# FILL IN:` marker. Never change a signature, class name or path the
> blueprint fixes (they come from the spec §3 Interface Skeletons).

### Steps (in order)
1. Run the spike in a scratch script; record names + reentrancy verdict; fix the Verified Imports above — *why*: §8 Q2 is delegated to this task.
2. Write `loader.py` — *why*: every later module consumes `LoadedModel`/`PhysicalSchema`.
3. Write the engine + dispatch — *why*: one internal `compile()`, no plugin protocol (spec §2 item 2).
4. Write fixtures (`_models.py`, model + policy files) — *why*: shared by TASK-4468..4481 tests without touching conftest.
5. Write tests, including the 32-way concurrent compile and the postgres/bigquery SQL snapshots.

### `packages/ai-parrot-semantic/src/parrot/semantic/loader.py` (CREATE)
```python
"""Load a models directory into LoadedModel objects (spec §3 Module 4)."""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from .errors import SemanticPolicyError
from .models import ModelMember
from .ossie import is_ossie_document, validate_ossie_document
from .policy import ModelPolicy, load_policy

logger = logging.getLogger(__name__)


class PhysicalSchema(BaseModel):
    driver: str
    tables: dict[str, dict[str, str]]   # "schema.table" -> {column: sqlglot type}

    def sqlglot_schema(self) -> dict:
        """Nested mapping accepted by sqlglot.optimizer.qualify.qualify(schema=...)."""
        out: dict[str, dict[str, dict[str, str]]] = {}
        for qualified, cols in self.tables.items():
            schema, table = qualified.split(".", 1)
            out.setdefault(schema, {})[table] = dict(cols)
        return out


class LoadedModel(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    name: str
    layer: Any            # sidemantic SemanticLayer (name confirmed by the spike)
    policy: ModelPolicy
    members: list[ModelMember]
    schema: PhysicalSchema
    model_digest: str
    policy_digest: str
    engine_version: str


class SemanticModelLoader:
    def __init__(self, models_dir: Path, *, driver: str) -> None:
        self.models_dir = Path(models_dir)
        self.driver = driver
        self._fingerprint: str | None = None
        self.logger = logger

    def load(self) -> dict[str, LoadedModel]:
        """Load every model + policy pair; reject `security:` blocks and policy/model mismatch."""
        # FILL IN: discover model files (sidemantic formats + *.ossie.json -> validate_ossie_document first);
        #   reject any model containing a sidemantic security block (SemanticPolicyError "security_block");
        #   build members + PhysicalSchema; load_policy(<name>.policy.yaml, members, set(schema.tables));
        #   a model without a policy file -> SemanticPolicyError "missing_policy" (governed by default)
        raise NotImplementedError

    def reload_if_changed(self) -> bool:
        """Re-read when any file digest changed; returns True when versions moved."""
        # FILL IN: hash sorted (relpath, sha256(bytes)) of models_dir; compare with self._fingerprint
        raise NotImplementedError
```

### `packages/ai-parrot-semantic/src/parrot/semantic/engines/__init__.py` (CREATE)
```python
"""Single compile() dispatch on model.policy.engine — no plugin protocol (spec §2 item 2)."""
from __future__ import annotations

import asyncio
import hashlib
from typing import TYPE_CHECKING

from ..models import CompiledQuery, SemanticQuery

if TYPE_CHECKING:
    from ..cache import CompileCache
    from ..loader import LoadedModel

_LOCKS: dict[str, asyncio.Lock] = {}


def cache_key(query: SemanticQuery, model: "LoadedModel", dialect: str) -> str:
    """(model digest, policy digest, canonical query, dialect, engine+version, connection) — no subject data."""
    parts = [model.model_digest, model.policy_digest, query.canonical_json(), dialect,
             f"{model.policy.engine}:{model.engine_version}", model.policy.connection or ""]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


async def compile(query: SemanticQuery, model: "LoadedModel", dialect: str, *,
                  cache: "CompileCache | None" = None) -> CompiledQuery:
    """Compile pre-governance SQL; an LRU hit skips compilation only (governance always re-runs)."""
    key = cache_key(query, model, dialect)
    if cache is not None and (hit := cache.get(key)) is not None:
        return hit
    if model.policy.engine == "native":
        from .native import NativeCompiler   # created by TASK-4468
        compiled = await asyncio.to_thread(NativeCompiler(model).compile, query, dialect)
    else:
        from .sidemantic_engine import compile_sidemantic
        # FILL IN: if the spike proved compile NOT reentrant, wrap in _LOCKS.setdefault(model.name, asyncio.Lock());
        #          otherwise call to_thread directly — record the choice in a one-line comment (§8 Q2)
        compiled = await asyncio.to_thread(compile_sidemantic, query, model, dialect)
    compiled = compiled.model_copy(update={"cache_key": key})
    if cache is not None:
        cache.put(compiled)
    return compiled
```
**Why**: `cache_key` lives here so both engines and the cache agree on it; CompiledQuery is frozen, hence `model_copy`.

### `packages/ai-parrot-semantic/src/parrot/semantic/engines/sidemantic_engine.py` (CREATE)
```python
"""sidemantic compile adapter — sync, CPU-only, never touches a database."""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..errors import SemanticValidationError
from ..models import CompiledQuery, FilterGroup, ModelMember, SemanticQuery

if TYPE_CHECKING:
    from ..loader import LoadedModel


def filter_tree_to_sidemantic(filters: FilterGroup | None, members: dict[str, ModelMember]) -> list[str]:
    """Translate the typed filter tree into sidemantic filter expressions; values as sqlglot-typed literals."""
    # FILL IN: grammar confirmed by the spike; literals via sqlglot exp.Literal.string/number (never f-string
    #          concatenation of raw values); unsupported op -> SemanticValidationError("unsupported_filter")
    raise NotImplementedError


def compile_sidemantic(query: SemanticQuery, model: "LoadedModel", dialect: str) -> CompiledQuery:
    """Compile with sidemantic; never passes user_attributes (no sidemantic SecurityPolicy)."""
    # FILL IN: query.validate_against(...) from model.members; call the confirmed compile API;
    #          parse result with sqlglot to collect tables ("schema.table") and members; cache_key="" (set by caller)
    raise NotImplementedError
```

### `packages/ai-parrot-semantic/tests/_models.py` (CREATE)
```python
"""Model + DuckDB fixtures shared by test modules (`from ._models import *`); conftest stays untouched."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def models_dir(tmp_path: Path) -> Path:
    """Copy of fixtures/models (+ the Ossie document) into a temp dir."""
    dst = tmp_path / "models"
    shutil.copytree(FIXTURES / "models", dst)
    shutil.copy(FIXTURES / "ossie/orders.ossie.json", dst / "orders_ossie.ossie.json")
    return dst


@pytest.fixture
def duckdb_warehouse(tmp_path: Path) -> str:
    """DuckDB file with sales.orders and dim.customers seeded (spec §4 Test Data)."""
    duckdb = pytest.importorskip("duckdb")
    path = str(tmp_path / "wh.duckdb")
    # FILL IN: CREATE SCHEMA sales/dim; CREATE TABLE + INSERT >= 2 regions, >= 2 tenants, 3 months of orders
    return path


@pytest.fixture
def loaded_models(models_dir: Path):
    pytest.importorskip("sidemantic")
    from parrot.semantic.loader import SemanticModelLoader
    return SemanticModelLoader(models_dir, driver="duckdb").load()
```
**Why**: fixtures imported by test modules avoid editing `conftest.py` (which would make every later task exclusive).

### FILL IN checklist
- [ ] Spike record (Completion Note + this file's Verified Imports).
- [ ] `SemanticModelLoader.load` / `reload_if_changed`.
- [ ] Lock vs lock-free in `compile()` — bounded by the spike verdict (§8 Q2).
- [ ] `filter_tree_to_sidemantic` / `compile_sidemantic`.
- [ ] Model + policy fixture files (policy example in spec §2: roles analyst/admin, mask `customers.email`, RLS on `sales.orders` by `programs`).
- [ ] DuckDB seed data.

---

## Acceptance Criteria

- [ ] `test_loader_rejects_security_block`, `test_sidemantic_compile_pg_bq_duckdb`, `test_compile_concurrent_to_thread`, `test_dialect_sql_snapshots` (sidemantic half) pass (AC2, AC18).
- [ ] Compile opens no DB connection (AC2) and output contains no subject values.
- [ ] The Ossie fixture loads as a model (AC15).
- [ ] Completion Note records the confirmed sidemantic API and the reentrancy verdict (§8 Q2).

---

## Validation Commands

> File-level pytest only — no directories, no package roots. Run with `PYTHONPATH=packages/ai-parrot-semantic/src:packages/ai-parrot/src` in a worktree.

- `pytest packages/ai-parrot-semantic/tests/test_loader.py -q`
- `pytest packages/ai-parrot-semantic/tests/test_sidemantic_engine.py -q`

---

## Test Specification

```python
# packages/ai-parrot-semantic/tests/test_sidemantic_engine.py
import asyncio
import pytest
from ._models import models_dir, loaded_models  # noqa: F401
from parrot.semantic.engines import compile
from parrot.semantic.models import SemanticQuery


@pytest.mark.parametrize("dialect", ["postgres", "bigquery", "duckdb"])
async def test_sidemantic_compile_pg_bq_duckdb(loaded_models, dialect):
    q = SemanticQuery(model="orders", metrics=["revenue"], dimensions=["region"])
    cq = await compile(q, loaded_models["orders"], dialect)
    assert cq.dialect == dialect and "sales" in " ".join(cq.tables)


async def test_compile_concurrent_to_thread(loaded_models):
    q = SemanticQuery(model="orders", metrics=["revenue"], dimensions=["region"])
    serial = await compile(q, loaded_models["orders"], "duckdb")
    results = await asyncio.gather(*[compile(q, loaded_models["orders"], "duckdb") for _ in range(32)])
    assert {r.sql for r in results} == {serial.sql}

# FILL IN: test_dialect_sql_snapshots (normalized sqlglot AST vs files under tests/fixtures/snapshots/ — create
#          them in this task) and test_loader_rejects_security_block in test_loader.py
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug semantic-layer --feature-id FEAT-704 --spec sdd/specs/semantic-layer.spec.md --index sdd/tasks/index/semantic-layer.json`).
2. **Read the spec** (`sdd/specs/semantic-layer.spec.md`), especially the sections named in Context.
3. **Check dependencies** — every `Depends-on` task is `done` in `sdd/tasks/index/semantic-layer.json`.
4. **Verify the Codebase Contract** before writing code; fix a stale entry in this file first.
5. **Implement** exactly the files above, following the blueprint; touch nothing else.
6. **Validate**: `ruff check --fix <files>`, then the Validation Commands.
7. **Commit** only the listed files: `feat(semantic-layer): TASK-4467 — sidemantic spike, model loader and sidemantic engine (M4)`.
8. **Close** with `scripts/sdd/close_task.sh TASK-4467 semantic-layer verified` and fill in the Completion Note.

---

## Completion Note

- Task: TASK-4467
- Feature: semantic-layer
- Closed at (UTC): 2026-10-19
- Fix commits: none
- Seat: gpt-5.6-sol · Backend: codex · Model: gpt-5.6-sol · Attempts: 2 (a1 gpt-5.6-terra empty_delivery) · Duration: 609.1s · Tokens: n/a
- Validation: merge-tier ad0839b5:wave4:merge completed exit 0 (11 passed).
- Review: no corrections. compiled.tables only lists declared physical tables — not fail-open because PBAC (TASK-4469) uses model.schema.tables and the positive guard (TASK-4471) rejects undeclared tables. Deferred: issue:46e8f6219bf5 (contains-filter LIKE wildcards unescaped, minor).
- Note: pydantic warns LoadedModel.schema shadows BaseModel.schema (harmless).
