---
type: Wiki Overview
title: 'TASK-949: Test suite for OpenAIModel catalog refresh + deprecation registry'
id: doc:sdd-tasks-completed-task-942-deprecation-test-suite-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec §4 enumerates 16 unit + integration tests covering catalog
relates_to:
- concept: mod:parrot
  rel: mentions
- concept: mod:parrot.clients
  rel: mentions
- concept: mod:parrot.clients.gpt
  rel: mentions
- concept: mod:parrot.handlers
  rel: mentions
- concept: mod:parrot.handlers.llm
  rel: mentions
- concept: mod:parrot.loaders.abstract
  rel: mentions
- concept: mod:parrot.models.openai
  rel: mentions
---

# TASK-949: Test suite for OpenAIModel catalog refresh + deprecation registry

**Feature**: FEAT-138 — OpenAI Model Deprecation Refresh
**Spec**: `sdd/specs/openai-model-deprecation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-944, TASK-945, TASK-946, TASK-947, TASK-948
**Assigned-to**: unassigned

---

## Context

Spec §4 enumerates 16 unit + integration tests covering catalog
membership, deprecation-dict shape, helper-function behaviour, warning
emission, default-bump correctness, consumer migration, and the
partitioned listing endpoint. This task lands them as a single new test
module so the regression cost of future model-list refreshes is low.

Implements §3 Module 7.

---

## Scope

- Create `packages/ai-parrot/tests/unit/models/test_openai_deprecations.py`
  with the 14 unit tests listed in spec §4.
- Create `packages/ai-parrot/tests/unit/models/conftest.py` with the
  `upstream_current_models` fixture (snapshot from spec §4 — the set of
  26 model IDs).
- Create `packages/ai-parrot/tests/integration/test_openai_deprecation_warning.py`
  with the 2 integration tests:
  1. `test_openai_client_warns_on_deprecated_call` — `pytest.warns` round-trip.
  2. `test_no_internal_call_site_uses_deprecated_id` — repo-grep across
     `packages/ai-parrot/src/parrot/` (excluding `models/openai.py`)
     for `gpt-4-turbo`, `gpt-3.5-turbo`, `gpt-image-1` (the bare ID, not
     `gpt-image-1-mini` / `gpt-image-1.5`), `gpt-5-chat-latest`.
     Asserts zero hits.

**NOT in scope**:
- Adding tests for `groq`, `claude`, `google` enums.
- Mocking the actual OpenAI API surface (transport).
- Running tests against a live OpenAI account.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/unit/models/__init__.py` | CREATE (if missing) | Empty package marker. |
| `packages/ai-parrot/tests/unit/models/conftest.py` | CREATE | `upstream_current_models` fixture. |
| `packages/ai-parrot/tests/unit/models/test_openai_deprecations.py` | CREATE | 14 unit tests (catalog, dict shape, helpers, defaults). |
| `packages/ai-parrot/tests/integration/test_openai_deprecation_warning.py` | CREATE | 2 integration tests (warning round-trip, repo-grep). |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# After TASK-944 these all exist:
from parrot.models.openai import (
    OpenAIModel,
    DeprecationInfo,
    DEPRECATIONS,
    is_deprecated,
    get_shutoff_date,
    resolve_alias,
)

# After TASK-945 / TASK-946:
from parrot.clients.gpt import (
    OpenAIClient,
    RESPONSES_ONLY_MODELS,
    STRUCTURED_OUTPUT_COMPATIBLE_MODELS,
    DEFAULT_STRUCTURED_OUTPUT_MODEL,
)

# After TASK-948:
from parrot.handlers.llm import LLMClient
```

### Existing Test Conventions

- `pytest` + `pytest-asyncio` (per CLAUDE.md "Testing" section).
- Existing test layout: `packages/ai-parrot/tests/{unit,integration,e2e}/`.
- Verify the directory exists:
  `ls packages/ai-parrot/tests/unit/ 2>/dev/null` — if absent, create `__init__.py`.

### Does NOT Exist

- ~~`parrot.testing.fixtures`~~ — no shared fixtures package; use module-local conftest.
- ~~`pytest.OpenAIClientFactory`~~ — no helper; instantiate directly with `api_key="dummy"`.
- ~~`tests.helpers.assert_no_warnings`~~ — use `warnings.catch_warnings(record=True)` + `pytest.warns` directly.

---

## Implementation Notes

### Test Map (from spec §4)

| Test name | Purpose |
|---|---|
| `test_enum_contains_only_current_models` | every `OpenAIModel.value` not in `DEPRECATIONS` and not an alias of any entry. |
| `test_enum_matches_upstream_catalog_snapshot` | `{m.value for m in OpenAIModel} == upstream_current_models`. |
| `test_deprecations_dict_shape` | every `DEPRECATIONS` value is `DeprecationInfo`; `shutoff` is a `date`; aliases (where present) are also keys OR enum values OR a known migration target. |
| `test_is_deprecated_recognises_dated_id` | `is_deprecated("gpt-4-turbo-2024-04-09") is True`. |
| `test_is_deprecated_recognises_alias` | `is_deprecated("gpt-4-turbo") is True`. |
| `test_is_deprecated_passes_current_id` | `is_deprecated("gpt-5-mini") is False`. |
| `test_get_shutoff_date_returns_iso_date` | `get_shutoff_date("gpt-3.5-turbo-0125") == date(2026, 10, 23)`. |
| `test_resolve_alias_returns_canonical_active` | `resolve_alias("gpt-4-turbo") == "gpt-5-mini"` (interpretation (b); see spec §8 Q3). |
| `test_normalize_model_emits_warning_once` | calling twice yields one warning. |
| `test_normalize_model_silent_for_current_id` | zero warnings for `"gpt-5-mini"`. |
| `test_openaiclient_default_is_gpt5_mini` | class attribute. |
| `test_chat_handler_default_model_is_gpt5_mini` | grep / inspect the chat handler module. |
| `test_loaders_abstract_default_model_name` | inspect `loaders.abstract` default. |
| `test_llm_handler_lists_partitioned_models` | call `_get_supported_models("openai")`. |

### Pattern to Follow

```python
# packages/ai-parrot/tests/unit/models/test_openai_deprecations.py
from datetime import date
import warnings

import pytest
from pydantic import ValidationError

from parrot.models.openai import (
    OpenAIModel,
    DeprecationInfo,
    DEPRECATIONS,
    is_deprecated,
    get_shutoff_date,
    resolve_alias,
)


class TestCatalog:
    def test_enum_contains_only_current_models(self):
        for member in OpenAIModel:
            assert member.value not in DEPRECATIONS
            for info in DEPRECATIONS.values():
                assert info.alias != member.value, (
                    f"{member.name} ({member.value}) is the alias of a deprecated entry"
                )

    def test_enum_matches_upstream_catalog_snapshot(self, upstream_current_models):
        assert {m.value for m in OpenAIModel} == upstream_current_models


class TestDeprecationsDict:
    def test_deprecations_dict_shape(self):
        for key, info in DEPRECATIONS.items():
            assert isinstance(info, DeprecationInfo)
            assert isinstance(info.shutoff, date)
            if info.alias is not None:
                assert isinstance(info.alias, str)


class TestHelpers:
    @pytest.mark.parametrize("model", [
        "gpt-4-turbo-2024-04-09",
        "gpt-4-turbo",
        "gpt-3.5-turbo-0125",
    ])
    def test_is_deprecated_true(self, model):
        assert is_deprecated(model) is True

    @pytest.mark.parametrize("model", ["gpt-5-mini", "gpt-4.1", "o3"])
    def test_is_deprecated_false(self, model):
        assert is_deprecated(model) is False

    def test_get_shutoff_date(self):
        assert get_shutoff_date("gpt-3.5-turbo-0125") == date(2026, 10, 23)
        assert get_shutoff_date("gpt-5-mini") is None

    def test_resolve_alias(self):
        # Interpretation (b) per spec §8 Q3 (TODO: revisit).
        assert resolve_alias("gpt-4-turbo") == "gpt-5-mini"
        assert resolve_alias("gpt-5-mini") == "gpt-5-mini"
```

```python
# packages/ai-parrot/tests/unit/models/test_openai_deprecations.py — warnings + defaults
class TestNormalizeModel:
    def test_emits_warning_once(self):
        # Reset module-level _warned cache so test is order-independent.
        from parrot.clients import gpt as gpt_mod
        gpt_mod._warned.clear()

        client = gpt_mod.OpenAIClient(api_key="dummy")
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            assert client._normalize_model("gpt-4-turbo") == "gpt-4-turbo"
            assert len(w) == 1
            assert issubclass(w[0].category, DeprecationWarning)
            client._normalize_model("gpt-4-turbo")  # second call
            assert len(w) == 1                       # still one

    def test_silent_for_current_id(self):
        from parrot.clients import gpt as gpt_mod
        gpt_mod._warned.clear()
        client = gpt_mod.OpenAIClient(api_key="dummy")
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            client._normalize_model("gpt-5-mini")
            assert len(w) == 0


class TestDefaults:
    def test_openaiclient_default_is_gpt5_mini(self):
        from parrot.clients.gpt import OpenAIClient
        assert OpenAIClient.model == "gpt-5-mini"
        assert OpenAIClient._default_model == "gpt-5-mini"

    def test_chat_handler_no_gpt4_turbo_literal(self):
        import inspect
        from parrot.handlers import chat
        src = inspect.getsource(chat)
        assert '"gpt-4-turbo"' not in src

    def test_loaders_abstract_default_model_name(self):
        from parrot.loaders.abstract import <CLASS_NAME>  # see note below
        sig = inspect.signature(<CLASS_NAME>.__init__)
        assert sig.parameters["model_name"].default == "gpt-4.1-mini"


class TestPartitionedListing:
    def test_llm_handler_active_deprecated_partition(self):
        from parrot.handlers.llm import LLMClient
        inst = LLMClient.__new__(LLMClient)
        out = inst._get_supported_models("openai")
        assert isinstance(out, dict)
        assert set(out.keys()) == {"active", "deprecated"}
        assert "gpt-5-mini" in out["active"]
        assert "gpt-3.5-turbo-0125" in out["deprecated"]
```

> **Note on `<CLASS_NAME>`**: `parrot/loaders/abstract.py:156` is in a
> class `__init__`. Read the file to identify the class name before
> writing the test:
> `grep -n "class \|model_name: str = " packages/ai-parrot/src/parrot/loaders/abstract.py`.

### Integration test pattern

```python
# packages/ai-parrot/tests/integration/test_openai_deprecation_warning.py
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC = REPO_ROOT / "packages/ai-parrot/src/parrot"


def test_no_internal_call_site_uses_deprecated_id():
    # Search every .py file under src/parrot/ EXCEPT models/openai.py
    # for known-deprecated literal IDs.
    forbidden = ["gpt-4-turbo", "gpt-3.5-turbo", "gpt-5-chat-latest"]
    cmd = [
        "grep", "-rn", "--include=*.py",
        "--exclude-dir=__pycache__",
        "-E", "|".join(forbidden),
        str(SRC),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    # Allow only matches inside models/openai.py (the registry):
    bad = [
        ln for ln in result.stdout.splitlines()
        if "models/openai.py" not in ln
    ]
    assert not bad, "Found deprecated model literals:\n" + "\n".join(bad)


def test_openai_client_warns_on_deprecated_call():
    from parrot.clients import gpt as gpt_mod
    gpt_mod._warned.clear()
    with pytest.warns(DeprecationWarning, match="deprecated"):
        gpt_mod.OpenAIClient(api_key="dummy", model="gpt-4-turbo")
```

### Key Constraints

- Reset `gpt._warned.clear()` at the start of any test that asserts on
  warning emission — the cache is process-global.
- Use `pytest.warns` (not `assertWarns`) — repo style is pytest, not unittest.
- Tests must NOT hit the network. Use `api_key="dummy"`.
- Tests must NOT depend on order. Each warning test clears `_warned` first.

### References in Codebase

- `packages/ai-parrot/tests/unit/` — existing unit tests for layout reference.
- `packages/ai-parrot/tests/integration/` — existing integration tests.

---

## Acceptance Criteria

- [ ] `pytest packages/ai-parrot/tests/unit/models/ -v` passes (14+ tests).
- [ ] `pytest packages/ai-parrot/tests/integration/test_openai_deprecation_warning.py -v` passes (2 tests).
- [ ] No test depends on test order (run with `-p no:randomly` and
      `--random-order` if available; both must pass).
- [ ] No test hits the live OpenAI API.
- [ ] `conftest.py` fixture `upstream_current_models` returns exactly
      26 strings.
- [ ] No linting errors:
      `ruff check packages/ai-parrot/tests/unit/models/ packages/ai-parrot/tests/integration/test_openai_deprecation_warning.py`.

---

## Test Specification

The tests ARE the specification. Run them.

---

## Agent Instructions

1. Verify TASK-944 through TASK-948 are all in `sdd/tasks/completed/`.
2. Read each completion note for any deviations that affect tests.
3. Update `.index.json` → `"in-progress"`.
4. Implement; run all tests.
5. Move file to `sdd/tasks/completed/`, update index → `"done"`.

---

## Completion Note

**Completed by**: Claude (Opus 4.7) via /sdd-start
**Date**: 2026-05-01
**Notes**: 33 unit tests + 2 integration tests landed and passing
(`pytest tests/unit/models/ tests/integration/test_openai_deprecation_warning.py` →
35 passed in 2.34s). Implementation in worktree commit `3f4e15c6` on
branch `feat-137-openai-model-deprecation`.

**Deviations from spec**:
1. **Test pattern relaxed.** `test_enum_contains_only_current_models` no
   longer asserts that current enum values are absent from any
   `DeprecationInfo.alias` field. Spec §7 explicitly keeps
   `gpt-4.1-nano` as a current member while the dated source
   `gpt-4.1-nano-2025-04-14` aliases it — the implementation-note
   pattern (every-alias check) was overstrict.
2. **Helper semantics tightened.** `is_deprecated` / `get_shutoff_date`
   now skip alias-matches when the alias itself is a current
   `OpenAIModel` value, so `is_deprecated("gpt-4.1-nano")` returns
   `False` (it remains alive upstream). Direct keys and bare-alias dead
   families are still flagged. Added explicit
   `test_is_deprecated_skips_alive_alias` regression test.
3. **TASK-940 residual cleanup.** Migrated two further
   `kwargs.get('model_name', 'gpt-3.5-turbo')` fallbacks in
   `parrot/loaders/abstract.py:220, 242` to `'gpt-4.1-mini'`. Without
   this, the §4 integration test "no internal call site uses deprecated
   ID" would fail. Bundled into TASK-942 because it surfaced through
   the test-suite acceptance gate.
