# TASK-837: `PydanticModelResolver` — static registry + `datamodel-code-generator` cache

**Feature**: FEAT-121 — Parrot FormDesigner POST Submission Pipeline
**Spec**: `sdd/specs/parrot-formdesigner-post-method.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-833
**Assigned-to**: unassigned

---

## Context

The submission pipeline needs a strong Pydantic model per `(form_id, version)`. Developer-authored
models are preferred; when absent, we pre-generate classes offline from the form's JSON schema
using `datamodel-code-generator`. This module holds the static registry, the generated cache, and
the `warm_up()` hook called at `FormRegistry.load_from_storage()` time. Spec §2 New Public
Interfaces, §3 Module 5, §7 Known Risks.

---

## Scope

- Create `packages/parrot-formdesigner/src/parrot/formdesigner/services/pydantic_resolver.py`.
- Implement `PydanticModelResolver` with:
  - `__init__(self, static_models: dict[tuple[str, str], type[BaseModel]] | None = None)` —
    accepts a pre-built static registry.
  - `async def warm_up(self, registry: "FormRegistry") -> None` — iterates registered forms,
    generates+caches a Pydantic class for each `(form_id, version)` that is not already in
    `static_models`. Failures are logged at WARNING and recorded in a `_failed: set` so we don't
    retry them per request.
  - `async def resolve(self, form_id: str, version: str, schema: "FormSchema") -> type[BaseModel] | None` —
    returns static → generated-cache → lazy-generated class, or `None` on failure.
- The generator uses `datamodel_code_generator` programmatically to produce Python source from
  the form's JSON schema, then `exec`s the source in an isolated namespace to obtain the class.
  Cache the resulting class by `(form_id, version)`.
- Unit tests covering: static wins over cache, warm-up populates cache, lazy generation on cache
  miss, failure of codegen returns `None` and records failure (no retry).

**NOT in scope**:
- Using the resolver from the handler (TASK-839).
- Hooking into `FormRegistry.load_from_storage()` (done at handler wire-up in TASK-839/840).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot/formdesigner/services/pydantic_resolver.py` | CREATE | `PydanticModelResolver` |
| `packages/parrot-formdesigner/tests/unit/test_pydantic_resolver.py` | CREATE | Unit tests |
| `packages/parrot-formdesigner/tests/fixtures/form_schemas/` | CREATE (if missing) | Test fixture: sample FormSchema for codegen |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Inside pydantic_resolver.py
from __future__ import annotations

import json
import logging
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

# datamodel-code-generator — added in TASK-833
from datamodel_code_generator import generate, InputFileType, PythonVersion, DataModelType

if TYPE_CHECKING:
    from parrot.formdesigner.core.schema import FormSchema
    from parrot.formdesigner.services.registry import FormRegistry
```

### Existing Signatures to Use

```python
# packages/parrot-formdesigner/src/parrot/formdesigner/core/schema.py:107-133
class FormSchema(BaseModel):
    form_id: str
    version: str = "1.0"
    title: LocalizedString
    description: LocalizedString | None = None
    sections: list[FormSection]
    submit: SubmitAction | None = None
    cancel_allowed: bool = True
    meta: dict[str, Any] | None = None
```

```python
# packages/parrot-formdesigner/src/parrot/formdesigner/services/registry.py (FormRegistry)
# Verify with: grep -n "class FormRegistry" packages/parrot-formdesigner/src/parrot/formdesigner/services/registry.py
# Use these methods:
class FormRegistry:
    async def list_form_ids(self) -> list[str]: ...
    async def get(self, form_id: str, version: str | None = None) -> FormSchema | None: ...
```

**Before implementation**: run `grep -n "async def" packages/parrot-formdesigner/src/parrot/formdesigner/services/registry.py`
and confirm the `FormRegistry` method names you rely on in `warm_up()`. If any method is named
differently, update the contract and code accordingly.

### Does NOT Exist
- ~~`PydanticModelResolver`~~ — created here.
- ~~Existing JSON-schema → Pydantic helper in parrot~~ — no such utility exists; this task adds one.
- ~~A shared `parrot.codegen` package~~ — not present.
- ~~`FormSchema.to_json_schema()` method~~ — verify before assuming; if absent, build the JSON
  schema payload yourself from `FormSchema.model_dump()` plus the existing `JsonSchemaRenderer`
  (search `packages/parrot-formdesigner/src/parrot/formdesigner/` for it; the spec only mentions
  it exists, so confirm at implementation time).

---

## Implementation Notes

### Pattern to Follow

```python
class PydanticModelResolver:
    def __init__(
        self,
        static_models: dict[tuple[str, str], type[BaseModel]] | None = None,
    ) -> None:
        self.static_models = dict(static_models or {})
        self._cache: dict[tuple[str, str], type[BaseModel]] = {}
        self._failed: set[tuple[str, str]] = set()
        self.logger = logging.getLogger(__name__)

    async def warm_up(self, registry: "FormRegistry") -> None:
        """Pre-generate a Pydantic class for every (form_id, version) not in static_models."""
        ...

    async def resolve(
        self, form_id: str, version: str, schema: "FormSchema",
    ) -> type[BaseModel] | None:
        key = (form_id, version)
        if key in self.static_models:
            return self.static_models[key]
        if key in self._cache:
            return self._cache[key]
        if key in self._failed:
            return None
        cls = await self._generate(form_id, version, schema)
        if cls is None:
            self._failed.add(key)
            return None
        self._cache[key] = cls
        return cls

    async def _generate(
        self, form_id: str, version: str, schema: "FormSchema",
    ) -> type[BaseModel] | None:
        # Convert FormSchema → JSON Schema string → datamodel_code_generator.generate(...)
        # exec the produced source in an empty namespace
        # return the single generated BaseModel subclass (by introspection)
        ...
```

### Key Constraints
- The resolver itself must be async-friendly; use `asyncio.to_thread(...)` to run
  `datamodel_code_generator.generate` (it is sync) so we don't block the event loop.
- Cache per `(form_id, version)`. Never re-run codegen for the same key unless explicitly cleared.
- On codegen failure, log at `WARNING`, add the key to `_failed`, and return `None`. The caller
  (handler in TASK-839) then falls back to `FormValidator`.
- Generated code is **not** written to disk permanently — generate in a `TemporaryDirectory`.
- Do not use `exec()` with untrusted input; the form schemas come from the registry (trusted).
- Google-style docstrings.

### References in Codebase
- `packages/parrot-formdesigner/src/parrot/formdesigner/core/schema.py` — FormSchema shape.
- `packages/parrot-formdesigner/src/parrot/formdesigner/services/registry.py` — FormRegistry shape.

---

## Acceptance Criteria

- [ ] `PydanticModelResolver` class exists at the specified path.
- [ ] Importing works: `from parrot.formdesigner.services.pydantic_resolver import PydanticModelResolver`.
- [ ] `resolve()` returns the static-registered class when present in `static_models`, without
      invoking codegen.
- [ ] After `warm_up(registry)`, a subsequent `resolve(form_id, version, schema)` returns the
      cached generated class.
- [ ] On cache miss, `resolve()` generates, caches, and returns the class; subsequent calls hit
      the cache.
- [ ] On codegen failure, `resolve()` returns `None`, logs a warning, and records the key in
      `_failed`. Subsequent calls for the same key return `None` without re-invoking codegen.
- [ ] Unit tests pass: `pytest packages/parrot-formdesigner/tests/unit/test_pydantic_resolver.py -v`.
- [ ] `ruff check packages/parrot-formdesigner/src/parrot/formdesigner/services/pydantic_resolver.py` clean.

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/test_pydantic_resolver.py
import pytest
from pydantic import BaseModel
from unittest.mock import AsyncMock, MagicMock

from parrot.formdesigner.services.pydantic_resolver import PydanticModelResolver


class StaticModel(BaseModel):
    x: int


class TestResolver:
    @pytest.mark.asyncio
    async def test_static_model_wins(self):
        r = PydanticModelResolver(static_models={("f", "1.0"): StaticModel})
        cls = await r.resolve("f", "1.0", schema=MagicMock())
        assert cls is StaticModel

    @pytest.mark.asyncio
    async def test_cache_hit_after_generation(self, monkeypatch):
        r = PydanticModelResolver()
        async def fake_generate(form_id, version, schema):
            return StaticModel
        monkeypatch.setattr(r, "_generate", fake_generate)
        first = await r.resolve("f", "1.0", schema=MagicMock())
        second = await r.resolve("f", "1.0", schema=MagicMock())
        assert first is second is StaticModel

    @pytest.mark.asyncio
    async def test_generation_failure_cached_as_failed(self, monkeypatch, caplog):
        r = PydanticModelResolver()
        calls = {"n": 0}
        async def fake_generate(form_id, version, schema):
            calls["n"] += 1
            return None
        monkeypatch.setattr(r, "_generate", fake_generate)
        assert await r.resolve("f", "1.0", schema=MagicMock()) is None
        assert await r.resolve("f", "1.0", schema=MagicMock()) is None
        assert calls["n"] == 1  # no retry

    @pytest.mark.asyncio
    async def test_warm_up_populates_cache(self, monkeypatch):
        r = PydanticModelResolver()
        registry = MagicMock()
        registry.list_form_ids = AsyncMock(return_value=["f1"])
        sample = MagicMock()
        sample.form_id = "f1"
        sample.version = "1.0"
        registry.get = AsyncMock(return_value=sample)

        async def fake_generate(form_id, version, schema):
            return StaticModel
        monkeypatch.setattr(r, "_generate", fake_generate)

        await r.warm_up(registry)
        assert ("f1", "1.0") in r._cache
        assert r._cache[("f1", "1.0")] is StaticModel
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path above (§3 Module 5, §2 New Public Interfaces, §7 Known Risks).
2. **Check dependencies** — `TASK-833` (datamodel-code-generator must be installed).
3. **Verify the Codebase Contract** — re-read `core/schema.py:107-133`, and `grep` for the
   `FormRegistry` method names you use in `warm_up()`.
4. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`.
5. **Implement** the resolver and tests.
6. **Verify** all acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/TASK-837-pydantic-model-resolver.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
