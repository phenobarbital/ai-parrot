# TASK-2795: Factory Refactor + MetaPathFinder

**Feature**: FEAT-523 — PEP 420 LLM Client Extraction
**Spec**: `sdd/specs/pep-420-llm-clients.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This is the foundation task for FEAT-523. All satellite packages depend on
the factory being refactored to support entry-point discovery and the
MetaPathFinder being installed. Implements spec Module 1.

---

## Scope

- Refactor `SUPPORTED_CLIENTS` in `factory.py` into a two-tier dict:
  - **Core clients** (static, eagerly imported): `OpenRouterClient`,
    `MoonshotClient` — the thin wrappers that stay in core.
  - **Discovered clients** (lazy, loaded via entry points on first use).
- Add `LLMFactory._discover()` static method:
  - Calls `importlib.metadata.entry_points(group="parrot.clients")`.
  - Merges discovered clients into `SUPPORTED_CLIENTS`. Core keys take
    precedence; duplicate entry-point keys log a warning.
  - Idempotent — runs once per process (cached flag).
- Add `LLMFactory.list_providers()` public static method:
  - Returns `dict[str, str]` mapping installed provider keys → package name.
  - Triggers `_discover()` if not already called.
- Modify `LLMFactory.create()` to call `_discover()` on first invocation.
- Remove all non-core client imports from `factory.py` (satellite client
  imports and their `_lazy_*` closures).
- Keep `PROVIDER_BACKEND` in `factory.py` unchanged — it injects `backend=`
  kwargs for `bedrock`/`anthropic-aws` keys.
- Add `_ParrotClientsRedirector` MetaPathFinder to `__init__.py`:
  - Modeled exactly on `_ParrotToolsRedirector` in `parrot/tools/__init__.py`.
  - `_CORE_SUBMODULES` frozenset guards: `base`, `openai_base`, `factory`,
    `models`, `protocols`, `openrouter`, `moonshot`.
  - Recursion guard via `_RESOLVING` set.
  - `sys.modules` synchronization after successful redirect.
- Remove the `ZaiClient` import from `__init__.py` entirely (hard cut).

**NOT in scope**: moving any client files to satellite packages (that's
tasks TASK-2796–TASK-2806), updating `pyproject.toml` extras (TASK-2806),
or writing tests (TASK-2807).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/factory.py` | MODIFY | Refactor SUPPORTED_CLIENTS, add _discover(), add list_providers(), remove non-core imports |
| `packages/ai-parrot/src/parrot/clients/__init__.py` | MODIFY | Add _ParrotClientsRedirector, remove ZaiClient import |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.clients.base import AbstractClient          # clients/base.py:230
from parrot.clients.openai_base import OpenAIBaseClient  # clients/openai_base.py:59
from parrot.clients.factory import LLMFactory, SUPPORTED_CLIENTS  # clients/factory.py:107,161
```

### Existing Signatures to Use
```python
# parrot/clients/factory.py:107
SUPPORTED_CLIENTS = {
    # ~30 key→class mappings (eagerly imported or lazy-loaded)
}

# parrot/clients/factory.py:155
PROVIDER_BACKEND: Dict[str, str] = {
    "bedrock": "bedrock",
    "anthropic-aws": "aws",
}

# parrot/clients/factory.py:161
class LLMFactory:
    @staticmethod
    def parse_llm_string(llm: str) -> Tuple[str, Optional[str]]:  # line 171
        ...
    @staticmethod
    def create(llm: str, model_args=None, tool_manager=None,
               **kwargs) -> AbstractClient:  # line 193
        ...

# parrot/tools/__init__.py:50 — TEMPLATE for MetaPathFinder
class _ParrotToolsRedirector(importlib.abc.MetaPathFinder):
    _PREFIX = "parrot.tools."
    _RESOLVING: set = set()
    _loader = _AliasLoader()  # line 31
    def find_spec(self, fullname, path, target=None):
        # 1. Skip if not parrot.tools.*
        # 2. Skip core submodules (_CORE_SUBMODULES frozenset)
        # 3. Try parrot_tools.<rest>, then plugins.tools.<rest>
        # 4. Synchronize all aliases in sys.modules
        ...

# parrot/clients/__init__.py (current):
from .base import LLM_PRESETS, AbstractClient, StreamingRetryConfig
from .openai_base import OpenAIBaseClient
from .zai import ZaiClient  # ← REMOVE
```

### Does NOT Exist
- ~~`parrot.clients.registry`~~ — no client registry module exists
- ~~`[project.entry-points."parrot.clients"]`~~ — no entry points used today
- ~~`AbstractClient.__init_subclass__`~~ — no auto-registration hook

---

## Implementation Notes

### Pattern to Follow
```python
# Model _ParrotClientsRedirector on _ParrotToolsRedirector
# (parrot/tools/__init__.py:50–136)
import importlib
import importlib.abc
import importlib.machinery
import importlib.util
import sys
from pathlib import Path as _Path

class _AliasLoader(importlib.abc.Loader):
    def create_module(self, spec):
        return sys.modules.get(spec.name)
    def exec_module(self, module):
        pass

_CORE_CLIENTS_DIR = _Path(__file__).parent
_CORE_SUBMODULES: frozenset = frozenset(
    {p.stem for p in _CORE_CLIENTS_DIR.glob("*.py") if p.stem != "__init__"}
    | {p.name for p in _CORE_CLIENTS_DIR.iterdir()
       if p.is_dir() and (p / "__init__.py").exists()}
)

class _ParrotClientsRedirector(importlib.abc.MetaPathFinder):
    _PREFIX = "parrot.clients."
    _RESOLVING: set = set()
    _loader = _AliasLoader()
    # ... follow the same find_spec pattern
```

### Key Constraints
- `_discover()` must be idempotent — use a module-level `_discovered` flag
- Core client keys MUST win over entry-point keys
- Duplicate entry-point keys log `logger.warning()`
- `list_providers()` is a public API method
- `PROVIDER_BACKEND` stays unchanged — `bedrock`/`anthropic-aws` keys
  must still inject `backend=` before creating `AnthropicClient`

### References in Codebase
- `parrot/tools/__init__.py:50–136` — MetaPathFinder pattern to replicate
- `parrot/clients/factory.py:107–160` — current SUPPORTED_CLIENTS + PROVIDER_BACKEND
- `parrot/clients/__init__.py` — current exports (17 lines)

---

## Acceptance Criteria

- [ ] `SUPPORTED_CLIENTS` is a hybrid static+discovered dict
- [ ] `LLMFactory._discover()` loads entry points from `"parrot.clients"` group
- [ ] `LLMFactory.list_providers()` returns installed provider→package mapping
- [ ] Core client keys win over entry-point keys
- [ ] `_ParrotClientsRedirector` in `__init__.py` redirects `parrot.clients.<x>` imports
- [ ] Finder does NOT redirect core submodules (`base`, `openai_base`, `factory`, etc.)
- [ ] `ZaiClient` import removed from `__init__.py`
- [ ] All non-core client imports removed from `factory.py`
- [ ] `PROVIDER_BACKEND` still injects `backend=` for `bedrock`/`anthropic-aws`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/clients/`

---

## Test Specification

```python
# tests/unit/test_factory_discovery.py
import pytest
from unittest.mock import patch, MagicMock
from parrot.clients.factory import LLMFactory, SUPPORTED_CLIENTS


class TestFactoryDiscovery:
    def test_discover_entry_points(self, mock_entry_points):
        """_discover() loads entry points and merges into SUPPORTED_CLIENTS."""
        LLMFactory._discover()
        assert "test-provider" in SUPPORTED_CLIENTS

    def test_core_precedence(self, mock_entry_points):
        """Core-shipped client keys win over entry-point keys."""
        # mock an EP that tries to register "openrouter"
        LLMFactory._discover()
        # core's OpenRouterClient should still be there

    def test_duplicate_entry_point_warning(self, mock_entry_points, caplog):
        """Duplicate EP keys log a warning."""
        LLMFactory._discover()
        assert "duplicate" in caplog.text.lower()

    def test_list_providers(self):
        """list_providers() returns installed provider→package mapping."""
        providers = LLMFactory.list_providers()
        assert isinstance(providers, dict)

    def test_create_missing_satellite(self):
        """create() with missing satellite raises actionable ImportError."""
        with pytest.raises(ImportError, match="ai-parrot-client"):
            LLMFactory.create("nonexistent-provider:model")
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/pep-420-llm-clients.spec.md` for full context
2. **Check dependencies** — this task has no dependencies
3. **Verify the Codebase Contract** — confirm all imports and line numbers
4. **Update status** in `sdd/tasks/index/pep-420-llm-clients.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2795-factory-refactor-metapathfinder.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
