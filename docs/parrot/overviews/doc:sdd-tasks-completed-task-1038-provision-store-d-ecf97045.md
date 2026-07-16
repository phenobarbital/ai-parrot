---
type: Wiki Overview
title: 'TASK-1038: _provision_vector_store dim-equality check'
id: doc:sdd-tasks-completed-task-1038-provision-store-dim-equality-check-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: pgvector table with a fixed dimension read from
relates_to:
- concept: mod:parrot.embeddings.matryoshka
  rel: mentions
- concept: mod:parrot.exceptions
  rel: mentions
- concept: mod:parrot.handlers.bots
  rel: mentions
---

# TASK-1038: _provision_vector_store dim-equality check

**Feature**: FEAT-150 — Matryoshka Embedding Truncation
**Spec**: `sdd/specs/matryoshka-embedding-truncation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1034
**Assigned-to**: unassigned

---

## Context

`_provision_vector_store` (`handlers/bots.py:836`) creates the
pgvector table with a fixed dimension read from
`vector_store_config['dimension']`. If the operator declares
Matryoshka with a different `dimension`, the table is created at the
wrong size — inserts later fail at runtime with a cryptic pgvector
error from `parrot/stores/postgres.py:1274`.

This task adds a configure-time equality check so the mismatch is
rejected upfront with a clear message.

Implements spec §3 Module 5.

---

## Scope

- In `_provision_vector_store(self, bot, vector_store_config)`,
  immediately after extracting `dimension` and `embedding_model`
  (lines 863-864), check whether `embedding_model.get('matryoshka')`
  declares `enabled=True`.
- If yes, parse it into `MatryoshkaConfig` (TASK-1034). If parsing
  fails (e.g. invalid types), raise `ConfigError` with a clear
  message referencing the field path
  `vector_store_config.embedding_model.matryoshka`.
- Then enforce
  `vector_store_config['dimension'] == matryoshka_cfg.dimension`.
  Mismatch raises `ConfigError` listing both values.
- Validate the model against the catalog
  (`validate_against_catalog`) so unsupported models / dims are
  caught at configure time, not at first embedding call. The
  `SentenceTransformerModel.__init__` will validate too (TASK-1035),
  but doing it here lets the handler return a clean 400 to the
  operator instead of a deferred runtime error.
- Add unit tests covering: valid match, dim mismatch, missing
  `matryoshka_dimensions` for the model, dim absent from
  `matryoshka_dimensions`.

**NOT in scope**: the embedding-side validation (TASK-1035 handles
it inside the model class). Do NOT duplicate the truncation logic
here.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/handlers/bots.py` | MODIFY | Insert dim-equality + catalog validation in `_provision_vector_store` |
| `packages/ai-parrot/tests/handlers/test_provision_matryoshka.py` | CREATE | Unit tests for the new validation paths |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.embeddings.matryoshka import MatryoshkaConfig, validate_against_catalog
from parrot.exceptions import ConfigError                       # parrot/exceptions.py:45
```

### Existing Signatures to Use

```python
# parrot/handlers/bots.py
async def _provision_vector_store(self, bot, vector_store_config: dict) -> dict:  # line 836
    if not bot or not vector_store_config:
        return {"status": "none"}
    table = vector_store_config.get('table')                   # line 857
    schema = vector_store_config.get('schema')                 # line 858
    if not table or not schema:
        return {"status": "none"}
    store_type = vector_store_config.get('name', 'postgres')   # line 862
    dimension = vector_store_config.get('dimension', 384)      # line 863
    embedding_model = vector_store_config.get('embedding_model')  # line 864

    # ↓ NEW VALIDATION GOES HERE (between line 864 and the existing store_kwargs build)

    store_kwargs = {
        'table': table,
        'schema': schema,
        'dimension': dimension,
    }
    if embedding_model:
        store_kwargs['embedding_model'] = embedding_model
    try:
        bot.define_store(vector_store=store_type, **store_kwargs)
        ...
```

### Does NOT Exist

- ~~A pre-existing `_validate_vector_store_config` helper~~ — no
  such function. Inline the check, or extract a small private helper
  inside `bots.py` if it grows.
- ~~`bot.validate_matryoshka()`~~ — no. The bot doesn't validate
  config; the handler does, and the model double-checks.

---

## Implementation Notes

### Pattern to Follow

```python
# After line 864
if embedding_model:
    matryoshka_dict = embedding_model.get("matryoshka")
    if isinstance(matryoshka_dict, dict) and matryoshka_dict.get("enabled"):
        try:
            cfg = MatryoshkaConfig(**matryoshka_dict)
        except Exception as exc:
            raise ConfigError(
                f"Invalid matryoshka config in vector_store_config.embedding_model: {exc}"
            ) from exc
        # Validate against the catalog
        validate_against_catalog(cfg, embedding_model.get("model_name", ""))
        # Enforce dim equality
        if cfg.dimension != dimension:
            raise ConfigError(
                f"vector_store_config.dimension ({dimension}) must equal "
                f"embedding_model.matryoshka.dimension ({cfg.dimension}) "
                f"because the pgvector column is created with the former."
            )
```

### Key Constraints

- The check runs ONLY when `matryoshka.enabled` is true. Disabled or
  absent → no validation, no behaviour change.
- Raise `ConfigError`, never let the cryptic pgvector error surface
  to the operator.
- The error message must mention BOTH conflicting values to help the
  operator fix the config.

### References in Codebase

- `parrot/handlers/bots.py:836-889` — function to modify.
- `parrot/stores/postgres.py:1274` — the cryptic error this validation
  prevents.

---

## Acceptance Criteria

- [ ] When `matryoshka.enabled=true`, `dimension=512`, and
      `vector_store_config.dimension=512`, provisioning proceeds
      (existing happy path unchanged).
- [ ] When the two dims disagree, `_provision_vector_store` raises
      `ConfigError` with a message that names both values.
- [ ] When `matryoshka.enabled=true` and `model_name` is absent from
      the catalog, `ConfigError` is raised.
- [ ] When `matryoshka.enabled=true` and `dimension` is not in the
      model's `matryoshka_dimensions` list, `ConfigError` is raised.
- [ ] When `matryoshka` is absent or `enabled=false`, no new
      validation runs and behaviour is identical to today.
- [ ] Unit tests pass: `pytest packages/ai-parrot/tests/handlers/test_provision_matryoshka.py -v`
- [ ] No regression in existing handler tests: `pytest packages/ai-parrot/tests/handlers/ -v`
- [ ] No lint errors: `ruff check packages/ai-parrot/src/parrot/handlers/bots.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/handlers/test_provision_matryoshka.py
import pytest
from unittest.mock import AsyncMock, MagicMock

from parrot.exceptions import ConfigError


@pytest.fixture
def handler_factory():
    """Build a minimal handler instance with the methods we need to call.

    Inspect packages/ai-parrot/tests/handlers/conftest.py for the
    project's idiomatic fixture; adapt this stub to match.
    """
    from parrot.handlers.bots import BotsHandler  # adjust if class is named differently
    h = BotsHandler.__new__(BotsHandler)
    h.logger = MagicMock()
    return h


class TestProvisionMatryoshka:
    @pytest.mark.asyncio
    async def test_dim_match_proceeds(self, handler_factory):
        h = handler_factory
        bot = MagicMock()
        bot.store = MagicMock()
        bot.store.connection = AsyncMock()
        bot.store.create_collection = AsyncMock()
        cfg = {
            "table": "t", "schema": "s", "dimension": 512,
            "embedding_model": {
                "model_name": "nomic-ai/nomic-embed-text-v1.5",
                "model_type": "huggingface",
                "matryoshka": {"enabled": True, "dimension": 512},
            },
        }
        result = await h._provision_vector_store(bot, cfg)
        assert result["status"] in {"ready", "pending"}

    @pytest.mark.asyncio
    async def test_dim_mismatch_raises(self, handler_factory):
        h = handler_factory
        cfg = {
            "table": "t", "schema": "s", "dimension": 768,
            "embedding_model": {
                "model_name": "nomic-ai/nomic-embed-text-v1.5",
                "model_type": "huggingface",
                "matryoshka": {"enabled": True, "dimension": 512},
            },
        }
        with pytest.raises(ConfigError, match="dimension"):
            await h._provision_vector_store(MagicMock(), cfg)

    @pytest.mark.asyncio
    async def test_unsupported_dim_raises(self, handler_factory):
        h = handler_factory
        cfg = {
            "table": "t", "schema": "s", "dimension": 300,
            "embedding_model": {
                "model_name": "nomic-ai/nomic-embed-text-v1.5",
                "model_type": "huggingface",
                "matryoshka": {"enabled": True, "dimension": 300},
            },
        }
        with pytest.raises(ConfigError):
            await h._provision_vector_store(MagicMock(), cfg)

    @pytest.mark.asyncio
    async def test_disabled_no_validation(self, handler_factory):
        h = handler_factory
        bot = MagicMock()
        bot.store = MagicMock()
        bot.store.connection = AsyncMock()
        bot.store.create_collection = AsyncMock()
        cfg = {
            "table": "t", "schema": "s", "dimension": 768,
            "embedding_model": {
                "model_name": "nomic-ai/nomic-embed-text-v1.5",
                "model_type": "huggingface",
                "matryoshka": {"enabled": False, "dimension": 512},
            },
        }
        result = await h._provision_vector_store(bot, cfg)
        assert "vector_store_error" not in result or result.get("status") != "rejected"
```

> **Note for the agent**: the test stubs above sketch the call pattern.
> Adapt the handler instantiation to whatever the existing test suite
> uses (`tests/handlers/conftest.py`).

---

## Agent Instructions

1. Verify TASK-1034 is completed (`MatryoshkaConfig` + validator must exist).
2. Re-read spec §3 Module 5 and §7 Known Risks ("dimension drift").
3. Make the surgical insertion in `_provision_vector_store`.
4. Run handler and embedding test suites.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**:
