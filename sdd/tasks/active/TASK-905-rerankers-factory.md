# TASK-905: Implement parrot/rerankers/factory.py

**Feature**: FEAT-133 — DB-Persisted Reranker & Parent-Searcher Config for AI Bots
**Spec**: `sdd/specs/bot-reranker-and-parent-searcher-config.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Bots loaded by `BotManager` need a way to turn a JSONB
`reranker_config` dict into a concrete `AbstractReranker` instance. This task
creates the factory module + unit tests. Implements spec section 3 / Module 1.

---

## Scope

- Create `packages/ai-parrot/src/parrot/rerankers/factory.py` exposing
  `create_reranker(config: dict, *, bot_llm_client=None) -> Optional[AbstractReranker]`.
- Implement two internal builders:
  - `_build_local_cross_encoder(config)` → `LocalCrossEncoderReranker`
  - `_build_llm_reranker(config, bot_llm_client)` → `LLMReranker`
- Maintain a module-level `RERANKER_TYPES` dict mapping `type` strings
  to builders (registry hook for future types).
- Empty-dict guard returns `None` early.
- Missing or unknown `type` raises `parrot.exceptions.ConfigError`.
- Use **lazy imports** (mirror `parrot/rerankers/__init__.py:30-50`) so
  importing the factory does NOT pull `transformers` / `torch`.
- Write unit tests at `packages/ai-parrot/tests/rerankers/test_factory.py`
  covering: empty config, valid local-cross-encoder config, valid llm config,
  unknown type, missing type, valid `bot_llm_client` reuse.

**NOT in scope**:
- New reranker implementations (factory only registers existing classes).
- BotManager wiring (TASK-908).
- Patching `bot_llm_client` onto an already-constructed bot — the factory
  takes the client as a kwarg; sequencing in the manager is TASK-908.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/rerankers/factory.py` | CREATE | `create_reranker` + builders + RERANKER_TYPES |
| `packages/ai-parrot/tests/rerankers/test_factory.py` | CREATE | Unit tests for the factory |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Verified 2026-04-29
from typing import Callable, Optional
from parrot.exceptions import ConfigError                            # exceptions.py:45
from parrot.rerankers.abstract import AbstractReranker               # rerankers/__init__.py:26
from parrot.rerankers.models import RerankerConfig                   # rerankers/__init__.py:27
# Heavy imports — keep INSIDE the builder functions only:
#   from parrot.rerankers.local import LocalCrossEncoderReranker     # local.py:50
#   from parrot.rerankers.llm import LLMReranker                     # llm.py:44
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/rerankers/local.py:50
class LocalCrossEncoderReranker(AbstractReranker):
    def __init__(
        self,
        config: Optional[RerankerConfig] = None,
        **kwargs,                 # forwarded to RerankerConfig if config is None
    ) -> None: ...                # accepts e.g. model_name="...", device="cpu"

# packages/ai-parrot/src/parrot/rerankers/llm.py:65
class LLMReranker(AbstractReranker):
    def __init__(
        self,
        client: AbstractClient,
        model_name: str = "llm-reranker",
        **kwargs,
    ) -> None: ...

# packages/ai-parrot/src/parrot/exceptions.py:45
class ConfigError(ParrotError): ...   # already imported by BotManager
```

### Lazy-import pattern to mirror
```python
# packages/ai-parrot/src/parrot/rerankers/__init__.py:30-50
def __getattr__(name: str):
    if name == "LocalCrossEncoderReranker":
        from parrot.rerankers.local import LocalCrossEncoderReranker
        return LocalCrossEncoderReranker
    ...
```

### Does NOT Exist
- ❌ `parrot.rerankers.factory` — to be created by this task.
- ❌ `RerankerConfig` does NOT live in `parrot.rerankers.local`; it's in
  `parrot.rerankers.models`.
- ❌ Any factory helper currently registered in `parrot/rerankers/__init__.py`
  — the registry must live in the new `factory.py` module.

---

## Implementation Notes

### Pattern to Follow
Mirror `parrot/interfaces/vector.py:_get_database_store` for the type-dispatch
shape (config dict → builder lookup → instantiation). Use lazy imports inside
builders so `import parrot.rerankers.factory` stays cheap.

### Reference signature (from spec §2)
```python
# parrot/rerankers/factory.py
def create_reranker(
    config: dict,
    *,
    bot_llm_client: Optional[AbstractClient] = None,
) -> Optional[AbstractReranker]:
    """Instantiate a reranker from a config dict.

    Empty dict ⇒ returns None (no reranker).
    Missing or unknown 'type' ⇒ raises ConfigError.
    """
```

### Config shapes (from spec §2)
```jsonc
// type=local_cross_encoder
{
  "type": "local_cross_encoder",
  "model_name": "cross-encoder/ms-marco-MiniLM-L-12-v2",
  "device": "cpu",
  "rerank_oversample_factor": 4
}
// type=llm
{
  "type": "llm",
  "client_ref": "bot",                       // when "bot", reuse bot_llm_client
  "rerank_oversample_factor": 4
}
```

### Key Constraints
- Builders must `pop` the `type` key before forwarding kwargs to the
  reranker constructor.
- For `type=llm`: if `client_ref == "bot"` (or absent) and `bot_llm_client`
  is provided → use it. Otherwise raise `ConfigError("LLMReranker requires a client")`.
- `rerank_oversample_factor` is consumed by the bot, NOT by the reranker.
  The factory MAY ignore it; document this.
- Add Google-style docstrings + full type hints.
- Use `logger = logging.getLogger(__name__)`.

### References in Codebase
- `parrot/rerankers/__init__.py:30-50` — lazy-import pattern.
- `parrot/interfaces/vector.py:42-75` — type-dispatch pattern reference.
- `parrot/rerankers/local.py:50-100` — `LocalCrossEncoderReranker` constructor.
- `parrot/rerankers/llm.py:65-83` — `LLMReranker` constructor.

---

## Acceptance Criteria

- [ ] `parrot.rerankers.factory.create_reranker` exists with the signature
  in this task.
- [ ] `create_reranker({})` returns `None`.
- [ ] `create_reranker({"type": "local_cross_encoder", "model_name": "...", "device": "cpu"})`
  returns a `LocalCrossEncoderReranker` instance.
- [ ] `create_reranker({"type": "llm"}, bot_llm_client=fake_client)`
  returns an `LLMReranker` instance with `.client is fake_client`.
- [ ] `create_reranker({"model_name": "..."})` raises `ConfigError` matching
  `"missing 'type'"`.
- [ ] `create_reranker({"type": "magic"})` raises `ConfigError` matching
  `"unknown reranker type"`.
- [ ] `create_reranker({"type": "llm"})` (no client) raises `ConfigError`.
- [ ] Importing `parrot.rerankers.factory` does NOT import `transformers`
  or `torch` (verify with `sys.modules` check in a test).
- [ ] All unit tests pass:
  `pytest packages/ai-parrot/tests/rerankers/test_factory.py -v`.
- [ ] `ruff check packages/ai-parrot/src/parrot/rerankers/factory.py` clean.
- [ ] Maps to spec AC3.

---

## Test Specification

```python
# packages/ai-parrot/tests/rerankers/test_factory.py
import sys
import pytest
from parrot.exceptions import ConfigError
from parrot.rerankers.factory import create_reranker


class FakeClient:
    """Stand-in for AbstractClient — no network."""
    pass


def test_empty_config_returns_none():
    assert create_reranker({}) is None


def test_local_cross_encoder_returns_instance():
    pytest.importorskip("transformers")
    cfg = {
        "type": "local_cross_encoder",
        "model_name": "cross-encoder/ms-marco-MiniLM-L-6-v2",
        "device": "cpu",
    }
    r = create_reranker(cfg)
    from parrot.rerankers.local import LocalCrossEncoderReranker
    assert isinstance(r, LocalCrossEncoderReranker)


def test_llm_reranker_reuses_bot_client():
    fake = FakeClient()
    r = create_reranker({"type": "llm"}, bot_llm_client=fake)
    from parrot.rerankers.llm import LLMReranker
    assert isinstance(r, LLMReranker)
    assert r.client is fake


def test_llm_reranker_without_client_raises():
    with pytest.raises(ConfigError):
        create_reranker({"type": "llm"})


def test_missing_type_raises_config_error():
    with pytest.raises(ConfigError, match="missing 'type'"):
        create_reranker({"model_name": "x"})


def test_unknown_type_raises_config_error():
    with pytest.raises(ConfigError, match="unknown reranker type"):
        create_reranker({"type": "magic"})


def test_factory_import_does_not_load_torch():
    # Cold import the factory and assert torch/transformers stay out of
    # sys.modules. Run as the first import in a fresh subprocess in CI;
    # in-process this only checks that the factory module itself doesn't
    # eagerly trigger them.
    import importlib
    if "torch" in sys.modules or "transformers" in sys.modules:
        pytest.skip("torch already imported by another test")
    importlib.import_module("parrot.rerankers.factory")
    assert "torch" not in sys.modules
    assert "transformers" not in sys.modules
```

---

## Agent Instructions

1. Read spec section 3 (Module 1) and section 6 (Codebase Contract).
2. Verify every signature in the Codebase Contract still matches the source.
3. Update `tasks/.index.json` → `"in-progress"`.
4. Implement `factory.py` with lazy imports.
5. Add tests under `packages/ai-parrot/tests/rerankers/test_factory.py`.
6. Run `pytest packages/ai-parrot/tests/rerankers/test_factory.py -v` until green.
7. Run `ruff check packages/ai-parrot/src/parrot/rerankers/factory.py`.
8. Move this file to `tasks/completed/` and update the index.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
