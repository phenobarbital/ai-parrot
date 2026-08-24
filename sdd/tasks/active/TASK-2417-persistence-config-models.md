# TASK-2417: Persistence configuration models (`core/persistence.py`)

**Feature**: FEAT-457 — Autonomous FormSchema Persistence (Standalone Forms)
**Spec**: `sdd/specs/formbuilder-formschema-persistency.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: none
**Assigned-to**: unassigned
**Implements**: Spec section 3 Module 1

---

## Context

Foundation of FEAT-457. Every other task imports from this module. It
introduces the declarative, credential-free description of *where* a form's data goes,
copying the `AuthConfig` pattern already proven in this package: a Pydantic
**discriminated union** whose members carry only the *name* of a credential source
(here, a connection **alias**), never a secret.

Implements spec section 3 Module 1 and the models sketched in spec section 2 "Data Models".

---

## Scope

- Create `core/persistence.py`.
- Implement `SinkCapability(str, Enum)` with members `WRITE`, `READ`, `LIST`, `PROVISION`, `EXTEND`.
- Implement the four target models, each with `model_config = ConfigDict(extra="forbid")` and a `type: Literal[...]` discriminator: `PostgresTableTarget` (`connection`, `schema_name`, `table`), `AsyncDBTarget` (`connection`, `driver`, `collection`), `CsvFileTarget` (`connection`, `path`, `delimiter=","`), `GoogleSheetTarget` (`connection`, `spreadsheet_id`, `worksheet="Sheet1"`).
- Implement `FileDefinitionTarget` (`connection`, `path`) and the `DefinitionTarget` alias.
- Define `SubmissionTarget` as an `Annotated[..., Field(discriminator="type")]` union.
- Implement `FormPersistenceConfig` with `data: SubmissionTarget` and `definition: DefinitionTarget | None = None`.
- Validate every Postgres identifier field (`schema_name`, `table`, `collection`) through `validate_identifier()` at construction.
- Reject any `path` containing a traversal segment (`..`) or an absolute path, at construction.
- Write unit tests in `tests/unit/test_persistence_models.py`.

**NOT in scope**: Adding the field to `FormSchema` (TASK-2421). The alias registry that resolves `connection` (TASK-2418). Any sink implementation. `RESERVED_COLUMNS` - that belongs to the mapper (TASK-2420).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/persistence.py` | CREATE | Config models + capability enum |
| `packages/parrot-formdesigner/tests/unit/test_persistence_models.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.
>
> Verified against `dev` on 2026-08-24. All paths are relative to the repo root.
> Line numbers shift as soon as anything above them changes — **re-`grep` before editing**.

### Verified Imports

```python
# Verified to resolve today:
from parrot_formdesigner.services._identifiers import validate_identifier  # services/_identifiers.py:24
# Standard Pydantic v2 surface used by this package:
from pydantic import BaseModel, ConfigDict, Field
from typing import Annotated, Literal
```

### Existing Signatures to Use

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/services/_identifiers.py
def validate_identifier(value: str, *, kind: str = "identifier") -> str: ...  # line 24
def qualified_table(schema: str, table: str) -> str: ...                      # line 45
_IDENTIFIER_RE = r"^[A-Za-z_][A-Za-z0-9_]{0,62}$"                           # line 21
```

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/core/auth.py - THE pattern to copy (discriminated union, env-name only)
AuthConfig = NoAuth | BearerAuth | ApiKeyAuth          # line 145
def _get_env(var_name: str) -> str: ...                # line 22
#   navconfig first (`from navconfig import config`, line 39);
#   falls back to os.environ (line 47); raises ValueError if absent (line 51).
class BearerAuth(BaseModel):                           # line 77
    type: Literal["bearer"] = "bearer"                 # line 90
    token_env: str                                     # line 91
    def resolve(self) -> dict[str, str]: ...
#   -> members store the NAME of an env var, NEVER the secret. Copy this shape.
```

### Does NOT Exist

- ~~a target field literally named `schema`~~ - `schema` shadows Pydantic's `BaseModel.schema`. The Postgres target field MUST be named `schema_name`.
- ~~`FormSchema.persistence`~~ - does NOT exist on `dev`. It is added by TASK-2421. Until that task lands, do not read it off a `FormSchema` instance.
- ~~`FormSubmissionStorage.DEFAULT_SCHEMA`~~ / ~~`PostgresFormStorage.DEFAULT_SCHEMA`~~ as **class attributes** - they are **module-level** constants (`services/submissions.py:31-32`, `services/storage.py:65-66`), despite the dotted form used in the `FormRegistry.__init__` docstring (`services/registry.py:293`).
- ~~`navconfig` as a direct dependency of `parrot-formdesigner`~~ - NOT in its dependency list. `core/auth.py:39` imports it inside `try/except ImportError` and falls back to `os.environ`. Keep that guarded pattern.
- ~~`python-datamodel`~~ - not a dependency of `parrot-formdesigner` (it belongs to `ai-parrot`). Do not reach for dynamic model generation.
- ~~`SinkCapability` / `FormPersistenceConfig` / any `*Target`~~ - none of these exist yet anywhere; this task creates all of them.
- ~~`openpyxl` in `parrot-formdesigner`~~ - NOT a dependency. `.xlsx` is an explicit Non-Goal for v1 (spec section 1). Do not add an xlsx sink.

---

## Implementation Notes

### Pattern to Follow

Mirror `packages/parrot-formdesigner/src/parrot_formdesigner/core/auth.py` exactly:

```python
# The shape to copy - a Literal discriminator + a NAME of a credential source.
class BearerAuth(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["bearer"] = "bearer"
    token_env: str = Field(..., description="Name of the env var holding the token")

AuthConfig = NoAuth | BearerAuth | ApiKeyAuth   # core/auth.py:145
```

Here, `connection` plays the role `token_env` plays there: an indirection resolved
server-side, so a `FormSchema` JSON dump can never contain a secret.

### Key Constraints

- `extra="forbid"` on EVERY model - this is what structurally blocks a `dsn` or `password` key from being smuggled into a schema.
- NO field may accept a DSN, password, key, or file:// URL. Only aliases.
- The Postgres field is `schema_name`, never `schema` (shadows `BaseModel.schema`).
- Google-style docstrings and strict type hints on every model and validator.
- Pure Pydantic - this module must not import any sink, storage, or aiohttp code.

### References in Codebase

- `packages/parrot-formdesigner/src/parrot_formdesigner/core/auth.py` - the union pattern to copy (lines 22, 77, 145)
- `packages/parrot-formdesigner/src/parrot_formdesigner/services/_identifiers.py` - identifier validation (line 24)
- `packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py:208` - `SubmitAction`, an existing sibling config model

---

## Acceptance Criteria

- [ ] `from parrot_formdesigner.core.persistence import FormPersistenceConfig, SinkCapability` works
- [ ] Each `type` literal resolves to the correct member via the discriminated union
- [ ] A dict containing `dsn` / `password` raises `ValidationError` (extra=forbid)
- [ ] An invalid `schema_name` / `table` / `collection` raises `ValueError` from `validate_identifier`
- [ ] `CsvFileTarget(path="../../etc/passwd")` raises at construction
- [ ] `CsvFileTarget(path="/etc/passwd")` raises at construction
- [ ] Round-trips through `model_dump_json()` -> `model_validate_json()` unchanged
- [ ] `pytest packages/parrot-formdesigner/tests/unit/test_persistence_models.py -v` passes
- [ ] `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/core/persistence.py` clean
- [ ] `mypy` clean on the new module

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/test_persistence_models.py
import pytest
from pydantic import ValidationError

from parrot_formdesigner.core.persistence import (
    FormPersistenceConfig, PostgresTableTarget, CsvFileTarget, SinkCapability,
)


class TestPersistenceModels:
    def test_union_discriminates_postgres(self):
        cfg = FormPersistenceConfig.model_validate(
            {"data": {"type": "postgres_table", "connection": "survey_db",
                       "schema_name": "surveys", "table": "nps_2026"}}
        )
        assert isinstance(cfg.data, PostgresTableTarget)

    def test_rejects_raw_dsn(self):
        with pytest.raises(ValidationError):
            PostgresTableTarget(
                type="postgres_table", connection="x", schema_name="s",
                table="t", dsn="postgresql://u:p@h/db",
            )

    def test_rejects_invalid_identifier(self):
        with pytest.raises(ValueError):
            PostgresTableTarget(
                type="postgres_table", connection="x",
                schema_name="bad-schema!", table="t",
            )

    @pytest.mark.parametrize("bad", ["../../etc/passwd", "/etc/passwd", "a/../../b"])
    def test_rejects_path_traversal(self, bad):
        with pytest.raises(ValueError):
            CsvFileTarget(type="csv_file", connection="exports", path=bad)

    def test_capabilities_enum_members(self):
        assert {c.value for c in SinkCapability} == {
            "write", "read", "list", "provision", "extend"
        }

    def test_roundtrip(self):
        cfg = FormPersistenceConfig.model_validate(
            {"data": {"type": "csv_file", "connection": "exports", "path": "nps.csv"}}
        )
        assert FormPersistenceConfig.model_validate_json(cfg.model_dump_json()) == cfg
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context.
2. **Check dependencies** - verify every `Depends-on` task is in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** - before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source).
   - Confirm every class/method in "Existing Signatures" still has the listed attributes.
   - If anything has changed, update the contract FIRST, then implement.
   - **NEVER** reference an import, attribute, or method not in the contract without
     verifying it exists.
4. **Update status** in `sdd/tasks/index/formbuilder-formschema-persistency.json` ->
   `"in-progress"` with your session ID.
5. **Implement** following the scope, codebase contract, and notes above.
6. **Verify** all acceptance criteria are met.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** -> `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
