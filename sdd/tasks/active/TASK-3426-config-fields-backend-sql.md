# TASK-3426: `PlanogramConfig` new fields, backend resolution module, `table.sql` + idempotent ALTER script

**Feature**: FEAT-574 — New Planogram Compliance Pipeline
**Spec**: `sdd/specs/new-planogram-pipeline.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 5** (goals G9, G10, G12). Three configuration facts change:

1. `PlanogramConfig` gains `slots_definition` (a dict — the JSONB row value — or a path to a
   JSON file) and `llm_backend` (one `"provider:model"` string, the `LLMFactory.create` format).
2. `roi_detection_prompt` / `object_identification_prompt` stop being mandatory (OpenCV now does
   detection zero-shot; only the legacy adapter path still uses the prompts).
3. Provider/model selection gets one documented precedence, implemented once in a new
   `planogram/backend.py`: explicit `llm` → explicit `llm_provider`/`llm_model` overrides →
   `PlanogramConfig.llm_backend` → package default. An `UNSET` sentinel distinguishes "argument
   omitted" from the historical `"google"` default so the config field cannot be masked.

The database side ships as SQL only (the user applies it): `table.sql` is updated and an
idempotent ALTER script is added next to it (both are package data via the existing `"*.sql"` glob).

This task is a root of the graph: it only adds fields, a new module and SQL. Wiring the resolver
into `AbstractPipeline` is the next task (TASK-3427).

---

## Scope

- `models.py`: make both prompts `Optional[str] = None`; add `slots_definition` and `llm_backend`;
  add a `field_validator("llm_backend")`.
- Create `planogram/backend.py`: `_Unset` / `UNSET`, `DEFAULT_LLM_BACKEND`, `ResolvedBackend`,
  `resolve_backend(...)` implementing the precedence matrix below.
- `table.sql`: add `slots_definition JSONB NULL`, `llm_backend TEXT NULL`; drop `NOT NULL` on both
  prompt columns; add `COMMENT ON COLUMN` for the two new columns.
- Create `alter_planograms_configurations_feat574.sql` (idempotent, four statements).
- Tests: full precedence matrix, config field behaviour, static check of the ALTER script.

**NOT in scope**: touching `AbstractPipeline` / `PlanogramCompliance` constructors (TASK-3427 and
the run-template task); parsing or validating the *content* of `slots_definition` (a later task owns
the loader — this task stores the raw dict/path untouched); type-specific validation such as
"legacy types require prompts" (type-hooks task); adding a `planogram_type` column (spec §8 open
question — default: not added); the stale duplicate `packages/ai-parrot/src/parrot/pipelines/table.sql`
(NOT touched); applying any SQL to a database.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/models.py` | MODIFY | Optional prompts, `slots_definition`, `llm_backend` + validator |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/backend.py` | CREATE | `UNSET`, `DEFAULT_LLM_BACKEND`, `ResolvedBackend`, `resolve_backend` |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/table.sql` | MODIFY | New nullable columns, prompts lose `NOT NULL`, comments |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/alter_planograms_configurations_feat574.sql` | CREATE | Idempotent ALTER for deployed databases |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_backend_resolution.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.

### Verified Imports
```python
from typing import Optional, Dict, List, Any, Union        # already in models.py:1
from pathlib import Path                                   # already in models.py:2
from pydantic import BaseModel, Field                      # already in models.py:5  (ADD: field_validator)
from pydantic import field_validator                       # pydantic v2 — used e.g. packages/ai-parrot/src/parrot/models/detections.py:45
from parrot.clients.factory import LLMFactory              # verified: packages/ai-parrot/src/parrot/clients/factory.py:163
from parrot.conf import DEFAULT_LLM_MODEL                  # verified: packages/ai-parrot/src/parrot/conf.py:443
from enum import Enum                                      # stdlib
from typing import Literal, Tuple                          # stdlib
# tests
from parrot_pipelines.models import PlanogramConfig        # verified: models.py:29
import parrot_pipelines                                    # package root — locate the .sql files via Path(parrot_pipelines.__file__).parent
```

### Existing Signatures to Use
```python
# packages/ai-parrot-pipelines/src/parrot_pipelines/models.py  (108 lines)
class PlanogramConfig(BaseModel):                                   # :29-108 — NO validators today
    planogram_config: Dict[str, Any] = Field(description=...)       # :50-52  REQUIRED (stays required)
    roi_detection_prompt: str = Field(                              # :55-57  REQUIRED today
        description="Prompt for ROI detection phase (used by _find_poster method)")
    object_identification_prompt: str = Field(                      # :60-62  REQUIRED today
        description="Prompt for Phase 2 object identification (used by _identify_objects method)")
    detection_grid: Optional[DetectionGridConfig] = Field(...)      # :90-96  (last field)
    class Config: arbitrary_types_allowed = True                    # :98-100 (old-style config — keep as is)
    def get_planogram_description(self) -> PlanogramDescription     # :102-108

# packages/ai-parrot/src/parrot/clients/factory.py
class LLMFactory:                                                   # :163
    @staticmethod
    def parse_llm_string(llm: str) -> Tuple[str, Optional[str]]     # :173-174
        # ":" in llm → provider, model = llm.split(":", 1) (both .strip()); else (llm.strip(), None)   :190-193
        # pure string parsing — triggers NO client discovery and NO import of a provider SDK

# packages/ai-parrot/src/parrot/conf.py:443
DEFAULT_LLM_MODEL = config.get("LLM_MODEL", fallback="gemini-flash-latest")

# packages/ai-parrot-pipelines/src/parrot_pipelines/abstract.py:33-34  (how an injected client names its provider)
#   self.llm_provider = llm.client_name.lower()

# packages/ai-parrot-pipelines/src/parrot_pipelines/table.sql  (97 lines)
#   :3   CREATE TABLE troc.planograms_configurations (
#   :13      planogram_config JSONB NOT NULL,
#   :16      roi_detection_prompt TEXT NOT NULL,
#   :17      object_identification_prompt TEXT NOT NULL,
#   :20      reference_images JSONB DEFAULT '{}',
#   :74-78   COMMENT ON TABLE / COMMENT ON COLUMN ... block
# packages/ai-parrot-pipelines/pyproject.toml:46-47  "parrot_pipelines" = ["py.typed", "*.sql"]  → a new *.sql next to
#   table.sql ships automatically; pyproject.toml is NOT edited by this task.
# parrot_pipelines/planogram/__init__.py:12-22 is a lazy __getattr__ — importing
#   parrot_pipelines.planogram.backend does NOT import plan.py (no circular import).
```

### Does NOT Exist
- ~~`PlanogramConfig.slots_definition` / `.llm_backend`~~ — added by this task.
- ~~any validator on `PlanogramConfig`~~ — none today; this task adds the first one.
- ~~`parrot_pipelines/planogram/backend.py`~~ — new file.
- ~~`LLMFactory.supported_clients` as an attribute~~ — it is a static **method**; do not call it here at all (validation must stay offline and SDK-free).
- ~~a `slots_definition`, `llm_backend` or `planogram_type` column in `table.sql`~~ — the first two are added here; `planogram_type` is deliberately NOT added.
- ~~any ALTER / migration `.sql` in the pipelines package~~ — `table.sql` is the only one today.
- ~~a `conftest.py` in `packages/ai-parrot-pipelines/tests/`~~ — do not rely on shared fixtures; build what the tests need inline.
- ~~`__init__.py` in `tests/planogram_cycle/`~~ — the folder is created by whichever task lands first and deliberately has no `__init__.py`; test basenames are unique.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-pipelines/src/parrot_pipelines/models.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/backend.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-pipelines/src/parrot_pipelines/table.sql",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-pipelines/src/parrot_pipelines/alter_planograms_configurations_feat574.sql",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_backend_resolution.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/models.py#PlanogramConfig",
    "sym:packages/ai-parrot/src/parrot/clients/factory.py#LLMFactory",
    "sym:packages/ai-parrot/src/parrot/clients/factory.py#LLMFactory.parse_llm_string"
  ]
}
```

---

## Implementation Notes

### The precedence matrix (fixed by spec §2 "Backend selection" — implement exactly)

`base` = parsed `config_backend` when given (origin `"config"`), else parsed `DEFAULT_LLM_BACKEND`
(origin `"package_default"`). "explicit" = the argument is not `UNSET` (for `llm_model`, also not `None`).

| # | `llm` | `llm_provider` | `llm_model` | Result (provider, model, origin) |
|---|---|---|---|---|
| 1 | client instance | any | any | (`llm.client_name.lower()`, `getattr(llm, "model", None)`, `"llm_instance"`) |
| 2 | `"p:m"` / `"p"` string | any | any | (`p`, `m` or `None`, `"llm_string"`) |
| 3 | `None` | UNSET | UNSET/None | `base` unchanged, origin = base origin |
| 4 | `None` | explicit, **== base provider** | UNSET/None | (base provider, base model, `"constructor"`) |
| 5 | `None` | explicit, **!= base provider** | UNSET/None | (that provider, **`None`**, `"constructor"`) — never inherit the other provider's model id |
| 6 | `None` | explicit | explicit | (that provider, that model, `"constructor"`) |
| 7 | `None` | UNSET | explicit | (base provider, that model, `"constructor"`) |

Providers are compared and stored lower-cased. `model=None` means "provider default".
An unparseable / empty backend string ⇒ `ValueError`.

### Key Constraints
- `backend.py` must import **no provider SDK** and trigger no client discovery — only
  `LLMFactory.parse_llm_string` (pure string split) and `parrot.conf.DEFAULT_LLM_MODEL`.
- `DEFAULT_LLM_BACKEND` is the single documented package default and the only place a model name
  may originate inside the package; it preserves today's effective handler behaviour
  (`google` + `DEFAULT_LLM_MODEL`). Callers that pass nothing still get provider `"google"`.
- Pydantic v2; Google-style docstrings; strict type hints; no `print`.
- `slots_definition` is stored **as given** (dict, str or Path). Do not open files or validate
  structure here.
- Both SQL files: nullable columns only; the ALTER script contains nothing but
  `ADD COLUMN IF NOT EXISTS` and `ALTER COLUMN … DROP NOT NULL` (re-runnable on any database state).
- Run tests inside the worktree with
  `PYTHONPATH=packages/ai-parrot-pipelines/src:packages/ai-parrot/src` (the shared venv is
  editable-installed against the main checkout). Never `uv sync` in the worktree.

### References in Codebase
- `packages/ai-parrot/src/parrot/models/detections.py:45-52` — `@field_validator(..., mode="before")` style used in this repo

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block to its declared path nearly
> verbatim, then complete every `# FILL IN:` marker. Never change a signature, class name or path.

### Steps (in order)
1. Create `planogram/backend.py` (block A) — *why*: the resolver has no dependency on the model changes and the tests import it first.
2. Edit `models.py` (blocks B1-B3) — *why*: optional prompts and the two new fields are what the DB columns hydrate into.
3. Edit `table.sql` (block C) and create the ALTER script (block D) — *why*: a fresh install and a deployed database must end in the same schema.
4. Write the tests (block E); run the Validation Command — *why*: the matrix is the contract every later task relies on.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/backend.py` (CREATE) — block A
```python
"""LLM backend (provider + model) resolution for planogram pipelines (FEAT-574)."""
from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Optional, Tuple, Union

from pydantic import BaseModel

from parrot.clients.factory import LLMFactory  # verified: parrot/clients/factory.py:163
from parrot.conf import DEFAULT_LLM_MODEL  # verified: parrot/conf.py:443


class _Unset(Enum):
    """Sentinel type for 'argument omitted' (distinct from None and from "google")."""

    UNSET = "unset"


UNSET = _Unset.UNSET

#: The single documented package default — today's effective handler behaviour.
DEFAULT_LLM_BACKEND: str = f"google:{DEFAULT_LLM_MODEL}"

BackendOrigin = Literal["llm_instance", "llm_string", "constructor", "config", "package_default"]


class ResolvedBackend(BaseModel):
    """Provider/model a pipeline run resolved to, and where the decision came from."""

    provider: str
    model: Optional[str] = None  # None ⇒ provider default
    origin: BackendOrigin

    def as_string(self) -> str:
        """Return ``"provider:model"``, or just ``"provider"`` when no model is pinned."""
        return f"{self.provider}:{self.model}" if self.model else self.provider


def _parse(backend: str) -> Tuple[str, Optional[str]]:
    """Parse ``"provider:model"``; raise ValueError on an empty provider or a non-string."""
    # FILL IN: reject non-str / blank; call LLMFactory.parse_llm_string; lower-case the provider;
    #          treat an empty model ("google:") as None — bounded by matrix rows 2-3.
    raise ValueError(f"Invalid llm backend: {backend!r}")


def resolve_backend(
    llm: Any,
    llm_provider: Union[str, _Unset],
    llm_model: Union[str, None, _Unset],
    config_backend: Optional[str],
) -> ResolvedBackend:
    """Resolve the backend by the FEAT-574 precedence.

    Order: explicit ``llm`` (instance or "provider:model" string) → explicit
    ``llm_provider`` / ``llm_model`` overrides applied to the configured backend →
    ``config_backend`` → ``DEFAULT_LLM_BACKEND``. A provider switch without a model
    never inherits the other provider's model id.

    Raises:
        ValueError: For an unparseable backend string.
    """
    # FILL IN: implement matrix rows 1-7 from "Implementation Notes" in that order.
    #          Row 1 test: `llm is not None and not isinstance(llm, str)`.
    #          Bounded by the matrix table; every row has a test.
    raise ValueError("unreachable")
```
**Why this shape**: names, fields and the `origin` literals are fixed by the spec Module 5 skeleton. `_Unset`
is an `Enum` so `UNSET` is a singleton that survives pickling and compares by identity. The file deliberately
imports nothing from a provider package. Replace both placeholder `raise` lines with the real logic — they
exist only so the skeleton is importable.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/models.py` (MODIFY) — block B1: imports
```python
# occurrences: 1 (verified: grep -c '^from pydantic import BaseModel, Field$' models.py)
# REPLACE `from pydantic import BaseModel, Field` (verified: models.py:5) WITH:
from pydantic import BaseModel, Field, field_validator
# occurrences: 1 (verified: grep -c '^from parrot_pipelines.planogram.grid.models import DetectionGridConfig$' models.py)
# AFTER — insert below `from parrot_pipelines.planogram.grid.models import DetectionGridConfig` (verified: models.py:10)
from parrot.clients.factory import LLMFactory
```
**Why**: `LLMFactory.parse_llm_string` is the one parser for the `"provider:model"` format; `abstract.py:8`
already imports `LLMFactory` in this package, so no new dependency is introduced.

### `models.py` (MODIFY) — block B2: optional prompts
```python
# occurrences: 1 each (verified: grep -c 'roi_detection_prompt: str = Field(' / 'object_identification_prompt: str = Field(' models.py)
# REPLACE the two field definitions (verified: models.py:55-57 and :60-62) WITH:
    roi_detection_prompt: Optional[str] = Field(
        default=None,
        description="Prompt for ROI detection (legacy adapter path only; optional since FEAT-574)"
    )

    object_identification_prompt: Optional[str] = Field(
        default=None,
        description="Prompt for object identification (legacy adapter path only; optional since FEAT-574)"
    )
```
**Why**: goal G10. Whether a given *type* still needs them is validated at type construction by a later task,
not here — this model must accept a migrated-type config with no prompts.

### `models.py` (MODIFY) — block B3: new fields + validator
```python
# occurrences: 1 (verified: grep -c '    class Config:' models.py)
# BEFORE — insert above `    class Config:` (verified: models.py:98), i.e. right after the detection_grid field (:90-96)
    # Slots definition (FEAT-574): dict (JSONB row value) or a path to a JSON file.
    slots_definition: Optional[Union[Dict[str, Any], str, Path]] = Field(
        default=None,
        description="Shelves/slots/products definition for migrated types: a dict or a path to a JSON file"
    )

    # LLM backend (FEAT-574): "provider:model" — the LLMFactory.create format.
    llm_backend: Optional[str] = Field(
        default=None,
        description='LLM backend as "provider:model"; explicit PlanogramCompliance arguments still win'
    )

    @field_validator("llm_backend")
    @classmethod
    def _check_backend(cls, v: Optional[str]) -> Optional[str]:
        """Must parse via LLMFactory.parse_llm_string into a non-empty provider."""
        if v is None:
            return v
        # FILL IN: strip; reject blank; provider, _ = LLMFactory.parse_llm_string(v); reject empty provider
        #          with ValueError("llm_backend must be 'provider:model', got ..."); return the stripped value —
        #          bounded by AC "invalid llm_backend rejected".
        return v
```
**Why**: field names and types are fixed by the spec skeleton. `slots_definition` stays raw on purpose —
loading/validating it belongs to the slots-definition task, and doing file I/O in a model validator would
block the event loop in the handler.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/table.sql` (MODIFY) — block C
```sql
-- occurrences: 1 each (verified: grep -c 'roi_detection_prompt TEXT NOT NULL' / 'object_identification_prompt TEXT NOT NULL' table.sql)
-- REPLACE (verified: table.sql:16-17):
    roi_detection_prompt TEXT NOT NULL,
    object_identification_prompt TEXT NOT NULL,
-- WITH:
    roi_detection_prompt TEXT NULL,
    object_identification_prompt TEXT NULL,

-- occurrences: 1 (verified: grep -c "reference_images JSONB DEFAULT '{}'," table.sql)
-- AFTER — insert below `    reference_images JSONB DEFAULT '{}',` (verified: table.sql:20)

    -- FEAT-574: slots definition (shelves / slots / products) and LLM backend ("provider:model")
    slots_definition JSONB NULL,
    llm_backend TEXT NULL,

-- occurrences: 1 (verified: grep -c "COMMENT ON COLUMN troc.planograms_configurations.object_identification_prompt" table.sql)
-- AFTER — insert below that COMMENT line (verified: table.sql:78)
COMMENT ON COLUMN troc.planograms_configurations.slots_definition IS 'FEAT-574: shelves/slots/products definition for migrated planogram types (NULL for legacy types)';
COMMENT ON COLUMN troc.planograms_configurations.llm_backend IS 'FEAT-574: LLM backend as provider:model (NULL = package default)';
```
**Why**: a database built from this DDL must equal a deployed database after the ALTER script. Leave the
commented example INSERT (`:81-97`) and everything else untouched.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/alter_planograms_configurations_feat574.sql` (CREATE) — block D
```sql
-- FEAT-574 — idempotent schema change for deployed databases. Safe to run repeatedly.
-- Applied by the operator; the application never runs DDL.
-- A nullable column is NOT a completed migration: migrated planogram types also need a reviewed
-- slots_definition backfill (see the FEAT-574 migration runbook).

ALTER TABLE troc.planograms_configurations ADD COLUMN IF NOT EXISTS slots_definition JSONB NULL;
ALTER TABLE troc.planograms_configurations ADD COLUMN IF NOT EXISTS llm_backend TEXT NULL;
ALTER TABLE troc.planograms_configurations ALTER COLUMN roi_detection_prompt DROP NOT NULL;
ALTER TABLE troc.planograms_configurations ALTER COLUMN object_identification_prompt DROP NOT NULL;
```
**Why**: the four statements are fixed verbatim by the spec Module 5 skeleton. `DROP NOT NULL` is a no-op
on an already-nullable column, so the whole script is re-runnable.

### `packages/ai-parrot-pipelines/tests/planogram_cycle/test_backend_resolution.py` (CREATE) — block E
```python
"""Backend resolution, PlanogramConfig new fields and ALTER-script checks (FEAT-574, spec Module 5)."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

import parrot_pipelines
from parrot_pipelines.models import PlanogramConfig
from parrot_pipelines.planogram.backend import (
    DEFAULT_LLM_BACKEND,
    UNSET,
    ResolvedBackend,
    resolve_backend,
)

_PKG = Path(parrot_pipelines.__file__).parent
_MIN_CONFIG = {"brand": "X", "category": "Y", "aisle": {"name": "a"}, "shelves": []}


def _fake_client(name: str = "Anthropic", model: str | None = "claude-sonnet-5") -> SimpleNamespace:
    return SimpleNamespace(client_name=name, model=model)

# FILL IN: test bodies per the Test Specification below — one parametrized test for matrix rows 1-7.
```
**Why**: `SimpleNamespace` is enough for row 1 because the resolver only reads `client_name` and `model`.

### FILL IN checklist
- [ ] `backend.py::_parse` — string validation; bounded by matrix rows 2-3 and the `ValueError` AC
- [ ] `backend.py::resolve_backend` — rows 1-7 in order; bounded by the matrix table
- [ ] `models.py::_check_backend` — reject blank/empty provider; bounded by AC "invalid llm_backend rejected"
- [ ] `test_backend_resolution.py` — test bodies; bounded by the Test Specification

---

## Acceptance Criteria

- [ ] `PlanogramConfig(planogram_config={...})` validates with **no** prompts; both prompts default to `None`.
- [ ] `slots_definition` accepts a dict, a `str` path and a `Path`, stored untouched; defaults to `None`.
- [ ] `llm_backend="anthropic:claude-sonnet-5"` and `"google"` are accepted; `""`, `"   "` and `":model"` raise `ValidationError`.
- [ ] Every row of the precedence matrix resolves exactly as specified, including: omitted args + `config_backend` ⇒ config wins (the historical `"google"` default cannot mask it); provider switch without model ⇒ `model is None`; nothing given ⇒ provider `"google"`, origin `"package_default"`.
- [ ] `resolve_backend(..., config_backend="not valid:")`-style garbage with an empty provider raises `ValueError`.
- [ ] `backend.py` imports no provider SDK (`grep -n "import" backend.py` shows only stdlib, pydantic, `parrot.clients.factory`, `parrot.conf`).
- [ ] `table.sql`: both prompts nullable; `slots_definition JSONB NULL` and `llm_backend TEXT NULL` present.
- [ ] The ALTER script's executable statements are exactly the four of block D, each `ADD COLUMN IF NOT EXISTS` or `DROP NOT NULL`.
- [ ] Existing tests still pass: `pytest tests/pipelines/test_config_extensions.py -q`
- [ ] All tests pass: `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_backend_resolution.py -q`
- [ ] `ruff check packages/ai-parrot-pipelines/src/parrot_pipelines/models.py packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/backend.py` clean.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_backend_resolution.py -q`

---

## Test Specification

```python
@pytest.mark.parametrize("llm, provider, model, config, expected", [
    # row 1 — instance wins over everything
    (_fake_client(), "google", "gemini-x", "google:gemini-y", ("anthropic", "claude-sonnet-5", "llm_instance")),
    # row 2 — string
    ("anthropic:claude-sonnet-5", UNSET, UNSET, "google:gemini-y", ("anthropic", "claude-sonnet-5", "llm_string")),
    ("anthropic", UNSET, UNSET, None, ("anthropic", None, "llm_string")),
    # row 3 — config, then package default
    (None, UNSET, UNSET, "anthropic:claude-sonnet-5", ("anthropic", "claude-sonnet-5", "config")),
    (None, UNSET, None, "anthropic:claude-sonnet-5", ("anthropic", "claude-sonnet-5", "config")),
    # row 4 / 5 — explicit provider, same vs different
    (None, "anthropic", UNSET, "anthropic:claude-sonnet-5", ("anthropic", "claude-sonnet-5", "constructor")),
    (None, "google", UNSET, "anthropic:claude-sonnet-5", ("google", None, "constructor")),
    # row 6 / 7
    (None, "Google", "gemini-x", "anthropic:claude-sonnet-5", ("google", "gemini-x", "constructor")),
    (None, UNSET, "claude-opus-4-8", "anthropic:claude-sonnet-5", ("anthropic", "claude-opus-4-8", "constructor")),
])
def test_backend_precedence_matrix(llm, provider, model, config, expected): ...

def test_package_default_is_google():
    """resolve_backend(None, UNSET, UNSET, None) → provider 'google', origin 'package_default',
    as_string() == DEFAULT_LLM_BACKEND."""

def test_invalid_backend_string_raises(): ...

def test_planogram_config_optional_prompts_and_new_fields(tmp_path):
    """No prompts OK; slots_definition dict / str / Path stored as given; invalid llm_backend rejected."""

def test_table_sql_has_new_nullable_columns():
    """Reads _PKG / 'table.sql': new columns present, no 'prompt TEXT NOT NULL' left."""

def test_alter_script_is_idempotent_text():
    """Non-comment, non-blank statements of the ALTER script == the four of block D; each contains
    'IF NOT EXISTS' or 'DROP NOT NULL'."""
```
Note: `_MIN_CONFIG` is only passed as `planogram_config=`; `PlanogramConfig` does not validate its
content at construction (`get_planogram_description()` is lazy), so any dict works.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** (§2 "Backend selection", §3 Module 5, §6 Codebase Contract)
2. **Check dependencies** — none
3. **Verify the Codebase Contract** — re-grep the anchors and occurrence counts before editing
4. **Implement** — start from the blueprint blocks; complete every `# FILL IN:`; never change a fixed signature
5. **Verify** all acceptance criteria
6. Commit only the five files listed above; never touch `sdd/`
7. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
