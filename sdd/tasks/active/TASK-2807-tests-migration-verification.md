# TASK-2807: Tests & Migration Verification

**Feature**: FEAT-523 — PEP 420 LLM Client Extraction
**Spec**: `sdd/specs/pep-420-llm-clients.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2795, TASK-2796
**Assigned-to**: unassigned

---

## Context

Comprehensive test suite for the factory refactor, entry-point discovery,
MetaPathFinder, and backward compatibility of all import paths. Implements
spec Module 8. Can start after TASK-2795 (factory refactor) + at least one
satellite (TASK-2796 recommended for integration tests).

---

## Scope

- Create `packages/ai-parrot/tests/clients/test_factory_discovery.py`:
  - Test `_discover()` loads entry points and merges into `SUPPORTED_CLIENTS`
  - Test core client keys take precedence over entry-point keys
  - Test duplicate entry-point keys log a warning
  - Test lazy-load: entry-point client class loaded only on first `create()`
  - Test `create("nonexistent:...")` → actionable `ImportError` naming the
    missing package
  - Test `PROVIDER_BACKEND` injection works with lazy-loaded entry-point
    clients (`bedrock`, `anthropic-aws`)
  - Test `list_providers()` returns installed provider→package mapping

- Create `packages/ai-parrot/tests/clients/test_metapath_finder.py`:
  - Test `from parrot.clients.claude import AnthropicClient` resolves via
    finder when satellite is installed
  - Test finder does NOT redirect core submodules (`base`, `openai_base`,
    `factory`, `models`, `protocols`, `openrouter`, `moonshot`)
  - Test recursion guard (`_RESOLVING`) prevents infinite loops
  - Test `sys.modules` synchronization after redirect

- Create `packages/ai-parrot/tests/clients/test_import_compat.py`:
  - Test all documented import paths resolve when satellites installed
  - Test `LLMFactory.create()` works for every registered provider key
  - Test PEP 420 namespace merging (satellite modules visible under
    `parrot.clients`)

- Use `monkeypatch` / `mock` for entry-point fixtures to avoid requiring
  all satellites to be installed during test runs.

**NOT in scope**: implementing the factory or satellites (separate tasks),
modifying `pyproject.toml` extras (TASK-2806).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/clients/test_factory_discovery.py` | CREATE | Unit tests for _discover(), list_providers(), lazy loading |
| `packages/ai-parrot/tests/clients/test_metapath_finder.py` | CREATE | Unit tests for _ParrotClientsRedirector |
| `packages/ai-parrot/tests/clients/test_import_compat.py` | CREATE | Integration tests for backward-compatible imports |
| `packages/ai-parrot/tests/clients/__init__.py` | CREATE | Test package init (if not exists) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.clients.factory import LLMFactory, SUPPORTED_CLIENTS  # factory.py:107,161
from parrot.clients.factory import PROVIDER_BACKEND  # factory.py:155
from parrot.clients import AbstractClient  # clients/__init__.py
from parrot.clients import OpenAIBaseClient  # clients/__init__.py
```

### Existing Signatures to Use
```python
# parrot/clients/factory.py:161
class LLMFactory:
    @staticmethod
    def parse_llm_string(llm: str) -> Tuple[str, Optional[str]]:  # line 171
    @staticmethod
    def create(llm: str, model_args=None, tool_manager=None,
               **kwargs) -> AbstractClient:  # line 193
    # NEW (added by TASK-2795):
    @staticmethod
    def _discover() -> None: ...
    @staticmethod
    def list_providers() -> dict[str, str]: ...
```

### Does NOT Exist
- ~~`parrot.clients.registry`~~ — no client registry module
- ~~`AbstractClient.__init_subclass__`~~ — no auto-registration hook
- ~~`ai-parrot-embeddings` entry points~~ — embeddings uses PEP 420 only, no entry points

---

## Implementation Notes

### Pattern to Follow
```python
# tests/clients/test_factory_discovery.py
import pytest
from unittest.mock import patch, MagicMock
from importlib.metadata import EntryPoint


@pytest.fixture
def mock_entry_points(monkeypatch):
    """Mock entry_points() to return test client registrations."""
    class FakeClient:
        pass

    eps = [
        EntryPoint(
            name="test-provider",
            value="test_pkg:FakeClient",
            group="parrot.clients",
        ),
    ]

    def fake_entry_points(*, group):
        if group == "parrot.clients":
            return eps
        return []

    monkeypatch.setattr("importlib.metadata.entry_points", fake_entry_points)

    # Mock the load() to return FakeClient
    for ep in eps:
        monkeypatch.setattr(ep, "load", lambda: FakeClient)

    return eps, FakeClient


@pytest.fixture(autouse=True)
def reset_discovery():
    """Reset the discovery state between tests."""
    from parrot.clients import factory
    # Reset the _discovered flag (implementation detail from TASK-2795)
    factory._discovered = False
    yield
```

### Key Constraints
- Tests must work without all satellites installed — use mocks for entry points
- Integration tests that import from satellites should be marked with
  `@pytest.mark.skipif(...)` when the satellite is not installed
- Follow `pytest-asyncio` patterns for any async tests
- Use `monkeypatch` to isolate `sys.modules` and `sys.meta_path` changes

### References in Codebase
- `packages/ai-parrot/tests/` — existing test directory structure
- `parrot/tools/__init__.py:50–136` — MetaPathFinder to test against

---

## Acceptance Criteria

- [ ] All unit tests pass: `pytest packages/ai-parrot/tests/clients/ -v`
- [ ] Entry-point discovery tests pass with mocked entry points
- [ ] MetaPathFinder tests verify core submodules are NOT redirected
- [ ] MetaPathFinder tests verify satellite modules ARE redirected
- [ ] `PROVIDER_BACKEND` injection tested with lazy-loaded clients
- [ ] `list_providers()` returns correct mapping
- [ ] Backward-compatible import paths verified
- [ ] No linting errors: `ruff check packages/ai-parrot/tests/clients/`
- [ ] Tests are independent (no test ordering dependency)

---

## Test Specification

```python
# tests/clients/test_factory_discovery.py

class TestDiscovery:
    def test_discover_entry_points(self, mock_entry_points):
        """_discover() loads entry points and merges into SUPPORTED_CLIENTS."""
        from parrot.clients.factory import LLMFactory, SUPPORTED_CLIENTS
        LLMFactory._discover()
        assert "test-provider" in SUPPORTED_CLIENTS

    def test_core_precedence(self, mock_entry_points):
        """Core-shipped client keys win over entry-point keys."""
        ...

    def test_duplicate_entry_point_warning(self, mock_entry_points, caplog):
        """Duplicate EP keys log a warning."""
        ...

    def test_lazy_load(self, mock_entry_points):
        """Entry-point client class is loaded only on first create()."""
        ...

    def test_create_missing_satellite(self):
        """create() with missing satellite raises actionable ImportError."""
        with pytest.raises(ImportError, match="ai-parrot-client"):
            LLMFactory.create("nonexistent-provider:model")

    def test_provider_backend_lazy(self, mock_entry_points):
        """bedrock/anthropic-aws backend injection works with lazy client."""
        ...

    def test_list_providers(self):
        """list_providers() returns installed provider→package mapping."""
        providers = LLMFactory.list_providers()
        assert isinstance(providers, dict)


class TestMetaPathFinder:
    def test_finder_skips_core(self):
        """Finder does NOT redirect core modules."""
        import parrot.clients.base  # should resolve normally
        import parrot.clients.openai_base
        import parrot.clients.factory

    def test_finder_redirects_satellite(self):
        """Finder redirects parrot.clients.<satellite> when installed."""
        ...

    def test_recursion_guard(self):
        """_RESOLVING set prevents infinite loops."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/pep-420-llm-clients.spec.md` for full context
2. **Check dependencies** — verify TASK-2795 and TASK-2796 are completed
3. **Verify the Codebase Contract** — confirm factory.py has the new discovery API
4. **Update status** in `sdd/tasks/index/pep-420-llm-clients.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2807-tests-migration-verification.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
