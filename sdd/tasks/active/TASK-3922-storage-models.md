# TASK-3922: Storage models: partition, keys, definition, records, guard, errors

**Feature**: FEAT-621 — Agent Studio — Database-Backed Storage
**Spec**: `sdd/specs/agentstudio-db-storage.spec.md`
**Spec wave**: W0 — Storage models (M2)
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §2.4 (data models), §2.5c (`tooling_ref`), §3 Module 2. These types are the contract FEAT-605 v0.2 consumes
(X4, X6): storage addresses rows by `StudioPartition` only and never sees groups/superuser.

---

## Scope

- `StudioPartition` (+ `GLOBAL`, `from_scope` duck-typed on `.tenant`), `StudioAgentKey` (`qualified`, `parse`),
  prefixes `STUDIO_KEY_PREFIX` / `STUDIO_TOOLING_REF_PREFIX`.
- `StudioModelParams`, `STUDIO_MODEL_PARAM_KEYS`, `STUDIO_TENANT_CONFIG_KEYS` (empty), `StudioAgentDefinition`
  (+ `from_create_request` normalisation, refusal of factory-overwritten keys), `StudioAgentPatch`,
  `StudioAssetInput`, `StudioAgentBundle` (refuses secret-bearing fields).
- Frozen dataclasses `StudioAgentHead`, `StudioWriteGuard`, `StudioAgentRecord` (`key`, `tooling_ref`),
  `StudioAssetRecord`, `StudioToolingRecord`, `StudioAgentSnapshot`, `StudioDraftRecord`, `StudioSkillRecord`.
- Errors: `StudioNameConflict`, `StudioVersionConflict`, `StudioStaleAuthorization`, `StudioNotFound`,
  `StudioAssetTooLarge`, `StudioToolingRefused`, `StudioStorageUnavailable`, `StudioStorageError`.
- `storage/__init__.py` re-exporting the public names of `models.py`.

**NOT in scope**: Tenant `config` allowlist and reserved-key 400 enforcement at write time (service, TASK-3933/14); repositories; `StudioRepositories`/`StudioServices` containers (TASK-3930/12).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/studio/storage/__init__.py` | CREATE | package docstring + re-exports of models |
| `packages/ai-parrot-server/src/parrot/handlers/studio/storage/models.py` | CREATE | §2.4 types, prefixes, normalisation, errors |
| `packages/ai-parrot-server/tests/studio/storage/__init__.py` | CREATE | test package marker for tests/studio/storage |
| `packages/ai-parrot-server/tests/studio/storage/test_storage_models.py` | CREATE | DB-free unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified code references. Use these exact imports, names and signatures. Anything not listed:
> verify it exists (`grep`/`read`) before using it.

### Verified Imports
```python
from parrot.tools.spec import ToolkitSpec, AgentMCPServerSpec   # spec.py (AgentMCPServerSpec :32)
from parrot.handlers.studio.models import CreateAgentRequest    # packages/ai-parrot-server/src/parrot/handlers/studio/models.py:38
from parrot.handlers.studio._base import STUDIO_SLUG_RE         # _base.py:48  re.compile(r"^[a-z0-9_-]+$")
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/studio/models.py
class CreateAgentRequest(BaseModel):    # line 38
    name: str; bot_class: str = "BasicBot"; llm: str | None = None; description: str | None = None
    persist: bool = False; category: str = "general"; config: dict[str, Any] = Field(default_factory=dict)  # :55-61
```
How a toolkit param is marked secret: read `parrot/tools/config_schema.py::secret_paths` (imported by
`tooling_store.py`) — the bundle refusal must use the same marker (`x-secret`), not a new one.

### Does NOT Exist
- ~~`parrot.handlers.scope.RequestScope`~~ — FEAT-605 v0.2 M1; `from_scope` duck-types `.tenant`, never imports it.
- ~~`BotConfig.origin == "studio"`~~ — `Literal["repo","factory"]` only.
- ~~Any of the §2.4 names~~ — all new here.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/storage/__init__.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/storage/models.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/tests/studio/storage/__init__.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/tests/studio/storage/test_storage_models.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/models.py#CreateAgentRequest"
  ]
}
```

---

## Implementation Notes

- Parallelism: no dependency; creates storage/__init__.py and storage/models.py, which every later storage task imports (StudioPartition, records, errors)
- Cross-feature ordering: none — X16 lists STORAGE W0 in the early, sibling-independent subset (with FEAT-605 W0.1–W0.3/W1.1–W1.5 and TOOLKITS Wave 1). FEAT-605 W2.1 waits for this task (X4/X6 consumer).
- `StudioAgentKey.qualified`: `studio:<tenant>:<name>` or `studio:-:<name>`; `parse` rejects a name containing `:`
  and the tenant `-` given explicitly (only `None` maps to `-`).
- `StudioAgentDefinition.config` must never contain `STUDIO_MODEL_PARAM_KEYS`, `system_prompt`, `tools`, `llm`,
  `model`, `model_config`, `chatbot_id`, `name`, `mcp_servers`, `toolkits`, `vector_store_config`: `from_create_request`
  moves the first three groups, the rest raise `ValueError` (a validator). FEAT-605 reserved keys (`tenant`,
  `created_by`, `visibility`, `allowed_groups`) also raise here with a distinguishable message so the handler can
  answer 400 `reserved_config_key` (X14).
- Keep `models.py` ≤ 500 lines; if it grows past, split errors into `storage/errors.py` re-exported by `models.py`.

### Common constraints (all FEAT-621 tasks)
- Contract verified against `dev` @ `32b1a45d4` (2026-09-30). Earlier FEAT-621 tasks shift line numbers:
  re-run every `grep -c` before editing and fix this file first if an anchor moved.
- Async throughout; the pool is the host's `app["database"]` (asyncdb `pg` pool); no sync driver, no second pool.
- Raw parametrised SQL (`$1…$n`), never value interpolation; schema literal `navigator`.
- Transactions only through `studio_transaction`; statements only through `_exec` (spec §2.5a).
- Pydantic for payloads, frozen dataclasses for records; `self.logger` in views,
  `logging.getLogger("Parrot.AgentStudio.Storage")` in storage/services/runtime.
- ARCHITECTURE Rule 4: functions ≤ 60 lines, cyclomatic complexity ≤ 10, modules ≤ 500 lines.
- **Database rule** (spec §4): integration tests read `TEST_STUDIO_PG_DSN` and `pytest.skip` with a reason when it is
  unset. Point it at a PostgreSQL ≥ 14 database dedicated to this worktree — the fixtures truncate `navigator.ai_*`.
- **Request/session rule** (spec §4, ARCHITECTURE R6): handler tests use `aiohttp_client` with the real session
  middleware or `make_mocked_request(..., app=app)` + `request["NAV_SESSION"] = SessionData(...)`; never a `Mock`
  with a hand-set `.session`. Each new assertion is mutation-checked (revert the guarded line ⇒ RED).
- Worktree tests: prefix with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src` as needed;
  never `uv sync` inside a worktree.

---

## Implementation Blueprint

> Write each block to its declared path nearly verbatim, then complete every `# FILL IN:` marker. Never change a
> signature, class name or file path the blueprint fixes (they come from spec §2.4/§2.5/§3 skeletons).

### Steps (in order)
1. Write the dataclasses/models exactly as §2.4 (names and field order fixed) — *why*: FEAT-605 imports them (X6).
2. Implement `from_create_request` and the config-key validator — *why*: §2.7 routes every constructor value
   through exactly one channel; overwritten keys must never reach `config`.
3. Re-export from `__init__.py`; write tests.

### `packages/ai-parrot-server/src/parrot/handlers/studio/storage/models.py` (CREATE) — head
```python
"""Agent Studio storage types (spec §2.4). Records are frozen; payloads are Pydantic."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, ClassVar, Final, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from parrot.tools.spec import AgentMCPServerSpec, ToolkitSpec

STUDIO_KEY_PREFIX: Final = "studio:"
STUDIO_TOOLING_REF_PREFIX: Final = "studio-agent:"
STUDIO_MODEL_PARAM_KEYS: Final = frozenset({"temperature", "max_tokens", "top_k", "top_p"})
STUDIO_TENANT_CONFIG_KEYS: Final[frozenset[str]] = frozenset()
STUDIO_FORBIDDEN_CONFIG_KEYS: Final = frozenset({"llm", "model", "model_config", "chatbot_id", "name",
                                                 "mcp_servers", "toolkits", "vector_store_config"})
STUDIO_RESERVED_CONFIG_KEYS: Final = frozenset({"tenant", "created_by", "visibility", "allowed_groups"})


@dataclass(frozen=True, slots=True)
class StudioPartition:
    """The ONLY way to address rows. tenant=None is the non-tenant partition."""
    tenant: str | None
    GLOBAL: ClassVar["StudioPartition"]

    @classmethod
    def from_scope(cls, scope: Any) -> "StudioPartition":
        return cls(getattr(scope, "tenant", None))


StudioPartition.GLOBAL = StudioPartition(None)


@dataclass(frozen=True, slots=True)
class StudioAgentKey:
    tenant: str | None
    name: str

    @property
    def qualified(self) -> str:
        return f"{STUDIO_KEY_PREFIX}{self.tenant or '-'}:{self.name}"

    @classmethod
    def parse(cls, qualified: str) -> "StudioAgentKey":
        # FILL IN: strip prefix, split once on ':', '-' -> None; ValueError on bad prefix, ':' in name — bounded by
        #   test_agent_key_qualified_roundtrip.
        raise NotImplementedError
# FILL IN: the remaining §2.4 types and errors verbatim (StudioModelParams … StudioStorageError).
```
**Why this shape**: `ClassVar` + module-level assignment is how a frozen slotted dataclass gets a `GLOBAL` constant.

### `packages/ai-parrot-server/src/parrot/handlers/studio/storage/models.py` (CREATE) — record identity
```python
@dataclass(frozen=True, slots=True)
class StudioAgentRecord:
    agent_id: UUID
    tenant: str | None
    name: str
    owner: str
    visibility: str
    allowed_groups: tuple[str, ...]
    definition: "StudioAgentDefinition"
    status: str
    version: int
    created_at: datetime
    updated_at: datetime

    @property
    def key(self) -> StudioAgentKey:
        return StudioAgentKey(self.tenant, self.name)

    @property
    def tooling_ref(self) -> str:
        return f"{STUDIO_TOOLING_REF_PREFIX}{self.agent_id}"   # str(UUID) is canonical lowercase hyphenated
```

### `packages/ai-parrot-server/src/parrot/handlers/studio/storage/__init__.py` (CREATE)
```python
"""Agent Studio database-backed storage (FEAT-621)."""
from .models import *  # noqa: F401,F403  — FILL IN: replace with an explicit list + __all__ of the §2.4 names
```

### `packages/ai-parrot-server/tests/studio/storage/test_storage_models.py` (CREATE)
```python
"""FEAT-621 M2 — DB-free model tests."""
import pytest

from parrot.handlers.studio.models import CreateAgentRequest
from parrot.handlers.studio.storage.models import StudioAgentDefinition, StudioAgentKey


def test_agent_key_qualified_roundtrip() -> None:
    assert StudioAgentKey("acme", "sales").qualified == "studio:acme:sales"
    assert StudioAgentKey.parse("studio:-:sales") == StudioAgentKey(None, "sales")
    # FILL IN: ':' in name and explicit '-' tenant rejected.


def test_definition_from_create_request() -> None:
    req = CreateAgentRequest(name="sales", config={"temperature": 0.3, "system_prompt": "hi", "tools": ["x"]}, persist=True)
    d = StudioAgentDefinition.from_create_request(req)
    assert d.model_params.temperature == 0.3 and d.system_prompt == "hi" and d.tools == ["x"]
    assert "temperature" not in d.config
    # FILL IN: max_tokens/top_k/top_p moved; persist and name dropped.

# FILL IN: test_definition_rejects_reserved_and_overwritten_keys, test_tooling_ref_scheme (record.tooling_ref and
#   "no STUDIO_SLUG_RE slug equals a ref"), test_bundle_rejects_secret_fields.
```

### FILL IN checklist
- [ ] `StudioAgentKey.parse`.
- [ ] Remaining §2.4 types + errors verbatim; config-key validator; bundle secret refusal.
- [ ] Explicit `__all__` in `__init__.py`.
- [ ] Test bodies.

---

## Acceptance Criteria

- [ ] All §2.4 names importable from `parrot.handlers.studio.storage.models` and the package root.
- [ ] `StudioAgentKey` round-trips; `:` in a name and an explicit `-` tenant are rejected (`test_agent_key_qualified_roundtrip`).
- [ ] `record.tooling_ref == f"studio-agent:{agent_id}"`; no `STUDIO_SLUG_RE` slug can equal a ref (`test_tooling_ref_scheme`, AC12).
- [ ] `from_create_request` moves model params / system_prompt / tools; drops `persist`, `name` (`test_definition_from_create_request`).
- [ ] Overwritten and reserved config keys are refused (`test_definition_rejects_reserved_and_overwritten_keys`); bundle secret fields refused (`test_bundle_rejects_secret_fields`).
- [ ] `ruff check` clean on every touched Python file; new functions within Rule-4 budgets (`flake8` complexity).

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/studio/storage/test_storage_models.py -q`

---

## Test Specification

| Test | Covers |
|---|---|
| `test_agent_key_qualified_roundtrip` | §2.4 |
| `test_tooling_ref_scheme` | §2.5c, AC12 |
| `test_definition_from_create_request` | §2.4, §2.7 map |
| `test_definition_rejects_reserved_and_overwritten_keys` | §2.4 (model half) |
| `test_bundle_rejects_secret_fields` | §2.4 (model half) |

---

## Agent Instructions

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug agentstudio-db-storage --feature-id FEAT-621`).
2. Read the spec sections cited in Context; check every `Depends-on` task is `"done"` in
   `sdd/tasks/index/agentstudio-db-storage.json`.
3. Verify the Codebase Contract anchors (`grep -c`) before editing; fix stale entries in this file first.
4. Set this task `"in-progress"` in the index (with `started_at`) and commit only the index.
5. Implement exactly the files listed, starting from the Blueprint; no refactors outside scope.
6. `ruff check --fix` the touched Python files; run the Validation Commands.
7. Commit code only (never `git add .`/`-A`):
   `feat(agentstudio-db-storage): TASK-3922 — Storage models: partition, keys, definition, records, guard, errors`.
8. Close with `scripts/sdd/close_task.sh TASK-3922 agentstudio-db-storage verified` and fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, deviations, issues.

**Deviations from spec**: none | describe if any
