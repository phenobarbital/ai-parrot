# TASK-2833: Meta model catalog (`parrot/clients/meta/models.py`)

**Feature**: FEAT-526 — Meta Model API (Muse Spark) LLM Client
**Spec**: `sdd/specs/meta-llm-client.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements **Module 1** of the spec. Every other task imports `MetaModel`, so this
is the root of the dependency graph. Pure data — no I/O, no async.

**This task creates the `parrot/clients/meta/` package itself** — FEAT-526 is the
first client written to the FEAT-523 folder convention
(`clients/<provider>/{__init__,client,models}.py`). FEAT-523 depends on this
feature landing `meta/` already in that shape, then relocates the whole folder to
an `ai-parrot-client-meta` satellite with a pure `git mv`. Getting the layout
right here is therefore load-bearing for another feature — do not flatten it back
to a single module.

The seven model ids below were **verified live** against `GET /v1/models` on
2026-09-04 (finding F013), not transcribed from documentation. Do not add,
rename, or "correct" any id.

---

## Scope

- Create the package `parrot/clients/meta/` with `__init__.py` and `models.py`.
- Define `MetaModel(str, Enum)` in `models.py`.
- Add capability frozensets: `CONTRIBUTOR_MODELS`, `SPARK_MODELS`,
  `IMAGE_MODELS`, `TRANSCRIBE_MODELS`, and a `CONTEXT_WINDOW` constant.
- Document the contributor-tier data-training caveat in the module docstring
  and on `CONTRIBUTOR_MODELS`.
- Write unit tests.

**NOT in scope**: the client itself (TASK-2834), factory registration
(TASK-2835), any Muse Image / Voice Transcribe endpoint work (explicit
spec Non-Goal — the enum members are reserved placeholders only).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/meta/__init__.py` | CREATE | Package init; re-exports `MetaModel` |
| `packages/ai-parrot/src/parrot/clients/meta/models.py` | CREATE | Enum + frozensets |
| `tests/clients/test_meta_models.py` | CREATE | Unit tests |

> **Codebase Contract correction (verified during implementation,
> 2026-09-04)**: the task file originally listed
> `packages/ai-parrot/tests/clients/test_meta_models.py`, but the root
> `pyproject.toml` sets `testpaths = ["tests"]` and every sibling wire
> client's tests (e.g. `test_moonshot_client.py`, and the roster files
> `test_openai_compatible_defaults.py:49` / `test_openai_base_parity.py:341`
> referenced elsewhere in this spec) live under the **root** `tests/clients/`,
> not `packages/ai-parrot/tests/clients/` (a separate, unrelated test tree
> for bedrock/nova). Corrected to `tests/clients/test_meta_models.py` to
> match the actual collected/runnable location and sibling convention.

> `client.py` is created by TASK-2834, which also extends `__init__.py` to
> re-export `MetaClient`. Leave a placeholder comment in `__init__.py` marking
> where that export goes — do not import a module that does not exist yet.

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from enum import Enum   # stdlib only — this module needs nothing else
```

### Existing Signatures to Use

The pattern to copy is `MoonshotModel`, verified 2026-09-04:
```python
# packages/ai-parrot/src/parrot/models/moonshot.py
class MoonshotModel(str, Enum):
    """String-valued enum so members interchange with raw model strings."""
    KIMI_K3 = "kimi-k3"
    ...
K_SERIES_MODELS: frozenset[str] = frozenset({MoonshotModel.KIMI_K3.value, ...})
VISION_MODELS: frozenset[str] = frozenset({...})
```
Sibling model modules confirming the convention:
`packages/ai-parrot/src/parrot/models/{openrouter,nvidia,zai,groq,localllm,vllm}.py`

### Live-verified model ids (`GET https://api.meta.ai/v1/models` → 200)
```
muse-spark-1.3                 muse-spark-1.3-contributor
muse-spark-1.2                 muse-spark-1.2-contributor
muse-spark-1.1                 (NO contributor variant — do not invent one)
muse-image-1.0                 muse-voice-transcribe-1.0
```

### Does NOT Exist
- ~~`parrot/clients/meta/`~~ (the whole package) — you are creating it.
- ~~`parrot/models/meta.py`~~ — **the wrong location.** Provider enums no longer
  live under `parrot.models` (FEAT-523 v0.3). Nothing named `meta` may exist
  under `parrot/models/`.
- ~~A flat `parrot/clients/meta.py` module~~ — the convention is a **folder**.
- ~~`MetaModel`~~ — does not exist anywhere yet.
- ~~`muse-spark-1.1-contributor`~~ — **not a real model id**. Only 1.2 and 1.3
  have contributor variants. Adding it will fail the live catalog test.
- ~~`muse-spark-1.0`~~, ~~`muse-spark-2.0`~~ — do not exist.
- ~~Pydantic response wrappers~~ — not needed. Meta's Chat Completions shape
  matches OpenAI's and is already covered by existing `AIMessage` /
  `CompletionUsage` models (same rationale as `models/moonshot.py`).

---

## Implementation Notes

### Pattern to Follow
```python
"""Meta Model API data models for AI-Parrot.

Model enums and capability constants for Meta Model API
(https://api.meta.ai/v1). No Pydantic wrappers are needed — Meta's
Chat Completions response shape matches OpenAI's and is already covered
by the existing AIMessage / CompletionUsage models.
"""
from enum import Enum


class MetaModel(str, Enum):
    """Meta Model API model identifiers.

    Verified live against ``GET /v1/models`` on 2026-09-04.
    """
    MUSE_SPARK_1_3 = "muse-spark-1.3"
    ...
```

### Key Constraints
- `str, Enum` so members interchange with raw model strings.
- **`CONTRIBUTOR_MODELS` must carry an explicit warning**: the contributor tier
  trades a lower price for Meta's permission to *train on your prompts and
  completions*. It must never be used as a default anywhere in library code —
  synthetic e2e test prompts only.
- `CONTEXT_WINDOW: int = 1_048_576` — uniform across all Muse Spark models.
- Google-style docstrings; no `print`.

---

## Acceptance Criteria

- [ ] `parrot/clients/meta/` exists as a package with `__init__.py` and `models.py`.
- [ ] `from parrot.clients.meta import MetaModel` works (via the package init).
- [ ] `from parrot.clients.meta.models import MetaModel` also works.
- [ ] Nothing named `meta` exists under `parrot/models/`.
- [ ] `MetaModel` contains exactly the 7 live-verified ids — no more, no fewer.
- [ ] `MetaModel.MUSE_SPARK_1_3.value == "muse-spark-1.3"` and members compare
      equal to their raw strings.
- [ ] `CONTRIBUTOR_MODELS` contains exactly the two `-contributor` ids.
- [ ] No `muse-spark-1.1-contributor` member exists.
- [ ] Contributor training caveat is documented in the module.
- [ ] Tests pass: `pytest packages/ai-parrot/tests/clients/test_meta_models.py -v`
- [ ] `ruff check packages/ai-parrot/src/parrot/clients/meta/models.py` clean.

---

## Test Specification

```python
import pytest
from parrot.clients.meta import (
    MetaModel, CONTRIBUTOR_MODELS, SPARK_MODELS, CONTEXT_WINDOW,
)
from parrot.clients.meta.models import MetaModel as MetaModelDirect

LIVE_CATALOG = {
    "muse-spark-1.3", "muse-spark-1.3-contributor",
    "muse-spark-1.2", "muse-spark-1.2-contributor",
    "muse-spark-1.1", "muse-image-1.0", "muse-voice-transcribe-1.0",
}


class TestMetaModel:
    def test_matches_live_catalog_exactly(self):
        assert {m.value for m in MetaModel} == LIVE_CATALOG

    def test_str_enum_interchanges_with_raw_string(self):
        assert MetaModel.MUSE_SPARK_1_3 == "muse-spark-1.3"

    def test_muse_spark_1_1_has_no_contributor_variant(self):
        assert "muse-spark-1.1-contributor" not in {m.value for m in MetaModel}

    def test_contributor_frozenset(self):
        assert CONTRIBUTOR_MODELS == {
            "muse-spark-1.3-contributor", "muse-spark-1.2-contributor",
        }

    def test_context_window(self):
        assert CONTEXT_WINDOW == 1_048_576

    def test_package_init_reexports(self):
        assert MetaModelDirect is MetaModel

    def test_no_enum_left_under_parrot_models(self):
        with pytest.raises(ImportError):
            __import__("parrot.models.meta")
```

---

## Agent Instructions

1. Read the spec at the path above (§2 Data Models, §6 Codebase Contract).
2. Verify the Codebase Contract before writing code.
3. Implement, run tests, verify acceptance criteria.
4. Move this file to `sdd/tasks/completed/` and set status `done` in
   `sdd/tasks/index/meta-llm-client.json`.
5. Fill in the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-09-04
**Notes**: Created `parrot/clients/meta/{__init__,models}.py` per the FEAT-523
folder convention. `MetaModel` enum has exactly the 7 live-verified ids;
`CONTRIBUTOR_MODELS`/`SPARK_MODELS`/`IMAGE_MODELS`/`TRANSCRIBE_MODELS`/
`CONTEXT_WINDOW` all present. `client.py` intentionally not created here
(TASK-2834). 8/8 unit tests pass, `ruff` clean.
**Deviations from spec**: Corrected a stale Codebase Contract entry in this
task file: the test file lives at `tests/clients/test_meta_models.py`
(root-level, matching `pyproject.toml`'s `testpaths = ["tests"]` and the
sibling `test_moonshot_client.py`), not
`packages/ai-parrot/tests/clients/test_meta_models.py` as originally
written — that path is an unrelated bedrock/nova test tree not on the
default `pytest` collection path.
