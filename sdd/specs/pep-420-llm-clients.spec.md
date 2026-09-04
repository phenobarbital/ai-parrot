---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: PEP 420 LLM Client Extraction

**Feature ID**: FEAT-523
**Date**: 2026-09-04
**Author**: Jesus Lara
**Status**: draft
**Target version**: 5.1.0

---

## 1. Motivation & Business Requirements

### Problem Statement

The core `ai-parrot` package bundles **all 20+ LLM client modules** (~34,700
lines, 3 MB of source) in `parrot/clients/`, alongside their SDK dependencies
(`anthropic`, `openai`, `google-genai`, `groq`, `aioboto3`, `xai-sdk`,
`zai-sdk`, `claude-agent-sdk`, …).

This causes three concrete pain points:

1. **Dependency bloat**: installing `ai-parrot` for one provider still makes
   available the import machinery for every other provider. The `[llms]`
   extra already gates the *SDK* installs, but the *client code* — 34K
   lines — ships in every wheel.

2. **SDK version conflicts**: providers ship breaking SDK changes at different
   cadences. Pinning `openai==3.3.1` in the core package means every
   downstream consumer inherits that pin, even if they only use Claude.

3. **Third-party extensibility barrier**: adding a new provider requires a PR
   to the core package. There is no plugin mechanism for client contributions
   beyond manually registering in `factory.py`'s `SUPPORTED_CLIENTS` dict.

### Goals

- **G1**: Extract all concrete LLM client implementations from core into
  satellite distributions, grouped by SDK dependency family.
- **G2**: Zero breaking changes — all existing import paths continue to work
  when the corresponding satellite is installed.
- **G3**: Enable dynamic client discovery via `importlib.metadata` entry
  points, so third-party providers can register without core changes.
- **G4**: Preserve the `ai-parrot[llms]` meta-extra as the single install
  command for all LLM clients.
- **G5**: Each satellite package has independent semver versioning.

### Non-Goals (explicitly out of scope)

- Runtime fallback-on-failure across providers (was not considered in
  brainstorm — see `proposals/pep-420-llm-clients.brainstorm.md`).
- Migrating non-client code out of core (tools, embeddings, etc. are already
  satellite packages via FEAT-201 and other features).
- Changing the `AbstractClient` interface or `LLMFactory.create()` calling
  convention (signatures stay identical).
- Auto-installing missing satellites — users must explicitly install the
  packages they need.

---

## 2. Architectural Design

### Overview

Extract LLM client implementations from `parrot/clients/` into **10
family-based satellite packages** using PEP 420 implicit namespace packages
(the same pattern as `ai-parrot-embeddings` / FEAT-201). Each satellite:

- Lives at `packages/ai-parrot-client-<family>/src/parrot/clients/<module>.py`
- Has NO `__init__.py` at the `parrot/` level (PEP 420 namespace merging)
- Declares entry points in `[project.entry-points."parrot.clients"]`
- Depends on `ai-parrot` (imports `AbstractClient`, `OpenAIBaseClient`)

**What stays in core** (`packages/ai-parrot/src/parrot/clients/`):
- `AbstractClient` (base.py) — the abstract base class
- `OpenAIBaseClient` (openai_base.py) — shared base for OpenAI-compatible clients
- `OpenRouterClient` (openrouter.py) — thin wrapper, no new SDK (6.8K)
- `MoonshotClient` (moonshot.py) — thin wrapper, no new SDK (15.4K)
- `LLMFactory` (factory.py) — refactored with entry-point discovery
- `models.py`, `protocols.py` — shared types

**Discovery** uses a dual mechanism:
1. **Entry points** (primary): `importlib.metadata.entry_points(group="parrot.clients")`
   discovers installed satellites at first `LLMFactory.create()` call (lazy, cached).
2. **MetaPathFinder** (fallback): `_ParrotClientsRedirector` intercepts
   `parrot.clients.<x>` imports when namespace merging fails (editable
   installs, certain installer behaviors).

### Component Diagram

```
                        ┌──────────────────────────────────────────┐
                        │         parrot/clients/ (CORE)           │
                        │                                          │
                        │  AbstractClient (base.py)                │
                        │  OpenAIBaseClient (openai_base.py)       │
                        │  OpenRouterClient (openrouter.py)        │
                        │  MoonshotClient (moonshot.py)            │
                        │  LLMFactory (factory.py)                 │
                        │    ├─ CORE_CLIENTS (static dict)         │
                        │    ├─ entry_points("parrot.clients")     │
                        │    └─ _ParrotClientsRedirector (finder)  │
                        └───────┬──────────────────────────────────┘
                                │
          ┌─────────────────────┼──────────────────────────┐
          │ PEP 420 namespace   │  entry point discovery    │
          │ merging             │  (importlib.metadata)     │
          ▼                     ▼                           ▼
  ┌──────────────┐  ┌──────────────────┐  ┌───────────────────┐
  │ ai-parrot-   │  │ ai-parrot-       │  │ ai-parrot-        │
  │ client-      │  │ client-          │  │ client-           │
  │ anthropic    │  │ openai           │  │ google            │
  │              │  │                  │  │                   │
  │ AnthropicCli │  │ OpenAIClient     │  │ GoogleGenAIClient │
  │ ClaudeAgent  │  │ OpenAICodexCli   │  │ Gemma4Client      │
  │ backends     │  │ codex_bridge     │  │ GeminiLiveClient  │
  └──────────────┘  └──────────────────┘  └───────────────────┘

  ┌──────────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐
  │ ai-parrot-   │  │ client-  │  │ client-  │  │ client-  │
  │ client-      │  │ groq     │  │ grok     │  │ zai      │
  │ amazon       │  │          │  │          │  │          │
  │              │  │ GroqCli  │  │ GrokCli  │  │ ZaiCli   │
  │ BedrockConv  │  └──────────┘  └──────────┘  └──────────┘
  │ Nova clients │
  │ BdrckMantle  │  ┌──────────┐  ┌──────────┐  ┌──────────┐
  └──────────────┘  │ client-  │  │ client-  │  │ client-  │
                    │ nvidia   │  │ local    │  │ hf       │
                    │          │  │          │  │          │
                    │ NvidiaCl │  │ LocalLLM │  │ Transfor │
                    └──────────┘  │ vLLMCli  │  │ mersCli  │
                                  └──────────┘  └──────────┘
```

### Satellite Package Map

| Package | Clients Moved | SDK Dependencies | ~Lines |
|---|---|---|---|
| `ai-parrot-client-openai` | `OpenAIClient` (gpt.py), `OpenAICodexClient` (codex_agent.py), `codex_tool_bridge.py` | `openai`, `openai-codex` | ~3,250 |
| `ai-parrot-client-anthropic` | `AnthropicClient` (claude.py), `ClaudeAgentClient` (claude_agent.py), `ClaudeAgentBridge` (claude_agent_bridge.py), `anthropic_backends.py` | `anthropic[aiohttp]`, `claude-agent-sdk` | ~5,100 |
| `ai-parrot-client-google` | `GoogleGenAIClient` (google/), `Gemma4Client` (gemma4.py), `GeminiLiveClient` (live.py — WebSocket voice) | `google-genai`, `google-api-python-client`, `google-cloud-texttospeech` | ~16,000 |
| `ai-parrot-client-amazon` | `BedrockConverseClient` (bedrock.py), Nova clients (nova/), `BedrockMantleClient` | `aioboto3`, `anthropic[aiohttp,aws]` | ~4,400 |
| `ai-parrot-client-groq` | `GroqClient` (groq.py) | `groq` | ~1,500 |
| `ai-parrot-client-grok` | `GrokClient` (grok.py) | `xai-sdk` | ~800 |
| `ai-parrot-client-zai` | `ZaiClient` (zai.py) | `zai-sdk` | ~1,100 |
| `ai-parrot-client-nvidia` | `NvidiaClient` (nvidia.py) | (none — uses `openai` via `OpenAIBaseClient`) | ~700 |
| `ai-parrot-client-local` | `LocalLLMClient` (localllm.py), `vLLMClient` (vllm.py) | (none — uses `openai` via `OpenAIBaseClient`) | ~900 |
| `ai-parrot-client-hf` | `TransformersClient` (hf.py) | `transformers`, `sentence-transformers` | ~650 |
| **Total** | **~24 files** | | **~34,400** |

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot/clients/factory.py` | modifies | `SUPPORTED_CLIENTS` becomes hybrid static+discovered; `LLMFactory.create()` calls `_discover()` on first use |
| `parrot/clients/__init__.py` | modifies | Add `_ParrotClientsRedirector` MetaPathFinder |
| `pyproject.toml` (core) | modifies | Rewrite extras to pull satellite packages; remove extracted SDK deps |
| `pyproject.toml` (root) | modifies | Add 10 new workspace members |
| `parrot/bots/abstract.py` | verifies | `get_client()` uses `SUPPORTED_CLIENTS` — works unchanged after `_discover()` |
| `parrot/bots/voice.py` | verifies | Same |
| `parrot/bots/flows/crew/crew.py` | verifies | Same — client instantiation in crew |
| `parrot/interfaces/tools.py` | verifies | Same |
| `parrot/tools/execution_plan/planner.py` | verifies | Same |
| `parrot/server/ui/catalog.py` | verifies | Same |
| `parrot/handlers/llm.py` | verifies | Same |
| `parrot/handlers/studio/catalog.py` | verifies | Same |
| `parrot/handlers/studio/byok.py` | verifies | Same |
| `parrot/advisors/mixin.py` | verifies | Lazy imports `SUPPORTED_CLIENTS` |
| `parrot_pipelines/abstract.py` | verifies | Uses `SUPPORTED_CLIENTS` for validation |

### Data Models

No new Pydantic models. The existing `AbstractClient` interface and
`LLMFactory` API are unchanged.

### New Public Interfaces

```python
# parrot/clients/factory.py — new public discovery API
class LLMFactory:
    @staticmethod
    def list_providers() -> dict[str, str]:
        """Return installed provider keys → package name mapping.

        Useful for UIs, CLI help, and diagnostics.
        """
        ...

    @staticmethod
    def _discover() -> None:
        """Merge entry-point-discovered clients into SUPPORTED_CLIENTS.

        Called lazily on first create() call. Idempotent.
        """
        ...
```

---

## 3. Module Breakdown

### Module 1: Factory Refactor + MetaPathFinder
- **Path**: `packages/ai-parrot/src/parrot/clients/factory.py`,
  `packages/ai-parrot/src/parrot/clients/__init__.py`
- **Responsibility**:
  - Refactor `SUPPORTED_CLIENTS` into a two-tier dict: core clients
    (static, eagerly imported) + discovered clients (lazy, loaded via
    `entry_points("parrot.clients")`).
  - Add `LLMFactory._discover()` method that calls
    `importlib.metadata.entry_points(group="parrot.clients")` and merges
    results. Core keys take precedence; duplicate entry-point keys log a
    warning.
  - Add `_ParrotClientsRedirector` MetaPathFinder to `__init__.py`
    (modeled on `_ParrotToolsRedirector`).
  - `PROVIDER_BACKEND` stays in `factory.py` — it injects `backend=`
    kwargs for `bedrock`/`anthropic-aws` keys, which resolve to
    `AnthropicClient` via entry-point discovery.
  - Remove all non-core imports from `factory.py` (the satellite clients)
    and their `_lazy_*` closures.
  - Clean up `__init__.py` — remove the `ZaiClient` import entirely
    (hard cut, no deprecation shim — no external consumers).
- **Depends on**: nothing (this is the foundation)

### Module 2: Satellite Package — ai-parrot-client-openai
- **Path**: `packages/ai-parrot-client-openai/`
- **Responsibility**: Ship `OpenAIClient` (gpt.py), `OpenAICodexClient`
  (codex_agent.py), and `codex_tool_bridge.py`. Declare entry points:
  `openai`, `codex-agent`, `openai-codex`, `codex-code`.
- **Depends on**: Module 1

### Module 3: Satellite Package — ai-parrot-client-anthropic
- **Path**: `packages/ai-parrot-client-anthropic/`
- **Responsibility**: Ship `AnthropicClient` (claude.py),
  `ClaudeAgentClient` (claude_agent.py), `ClaudeAgentBridge`
  (claude_agent_bridge.py), `anthropic_backends.py`. Declare entry points:
  `claude`, `anthropic`, `bedrock`, `anthropic-aws`, `claude-agent`,
  `claude-code`.
- **Depends on**: Module 1

### Module 4: Satellite Package — ai-parrot-client-google
- **Path**: `packages/ai-parrot-client-google/`
- **Responsibility**: Ship `GoogleGenAIClient` (google/ subpackage),
  `Gemma4Client` (gemma4.py), `GeminiLiveClient` (live.py — WebSocket-based
  voice; ships with Google family since it depends on `google-genai`).
  Declare entry points: `google`, `gemma4`, `gemini-live`.
- **Depends on**: Module 1

### Module 5: Satellite Package — ai-parrot-client-amazon
- **Path**: `packages/ai-parrot-client-amazon/`
- **Responsibility**: Ship `BedrockConverseClient` (bedrock.py), Nova
  clients (nova/ subpackage including `BedrockMantleClient`). Declare
  entry points: `bedrock-converse`, `nova`, `bedrock-mantle`, `mantle`.
- **Depends on**: Module 1

### Module 6: Satellite Packages — Standalone Providers
- **Paths**: `packages/ai-parrot-client-groq/`,
  `packages/ai-parrot-client-grok/`, `packages/ai-parrot-client-zai/`,
  `packages/ai-parrot-client-nvidia/`, `packages/ai-parrot-client-local/`,
  `packages/ai-parrot-client-hf/`
- **Responsibility**: Each ships one or two client modules with their
  respective entry points.
- **Depends on**: Module 1

### Module 7: Core Extras & Workspace Update
- **Path**: `packages/ai-parrot/pyproject.toml`, root `pyproject.toml`
- **Responsibility**:
  - Rewrite core extras to pull satellite packages alongside SDK deps:
    `openai = ["ai-parrot-client-openai"]`,
    `anthropic = ["ai-parrot-client-anthropic"]`, etc.
  - Rewrite `llms` to pull all 10 satellites.
  - Root `pyproject.toml`'s `all` extra pulls `ai-parrot[llms]`
    transitively (not each satellite individually).
  - Add new packages to workspace `members` list.
  - Each satellite gets its own `pyproject.toml` with independent version.
- **Depends on**: Modules 2–6

### Module 8: Tests & Migration Verification
- **Path**: `packages/ai-parrot/tests/clients/`
- **Responsibility**:
  - Test entry-point discovery: mock satellites register via entry points,
    `LLMFactory._discover()` finds them.
  - Test MetaPathFinder: `parrot.clients.<x>` import resolves via
    namespace merging and finder fallback.
  - Test backward compatibility: all existing import paths work.
  - Test error messages: clear `ImportError` when satellite not installed.
  - Test `PROVIDER_BACKEND` injection works with lazy-loaded entry-point
    clients.
  - Test `LLMFactory.list_providers()` returns installed providers.
- **Depends on**: Module 1, one satellite (Module 2 or 3) for integration

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_discover_entry_points` | M1 | `_discover()` loads entry points and merges into `SUPPORTED_CLIENTS` |
| `test_core_precedence` | M1 | Core-shipped client keys win over entry-point keys |
| `test_duplicate_entry_point_warning` | M1 | Duplicate EP keys log a warning |
| `test_lazy_load` | M1 | Entry-point client class is loaded only on first `create()` |
| `test_create_missing_satellite` | M1 | `create("claude:...")` without satellite → actionable `ImportError` |
| `test_metapath_finder_redirect` | M1 | `from parrot.clients.claude import AnthropicClient` works via finder |
| `test_metapath_finder_skips_core` | M1 | Finder does NOT redirect core modules (base.py, openai_base.py) |
| `test_provider_backend_lazy` | M1 | `bedrock`/`anthropic-aws` backend injection works with lazy client |
| `test_list_providers` | M1 | Returns installed provider→package mapping |

### Integration Tests

| Test | Description |
|---|---|
| `test_import_all_paths` | All documented import paths resolve when satellites installed |
| `test_factory_create_all` | `LLMFactory.create()` works for every registered provider key |
| `test_pep420_namespace` | Satellite modules are visible under `parrot.clients` namespace |
| `test_editable_install` | Entry points + namespace merging work in `uv pip install -e` mode |

### Test Data / Fixtures

```python
@pytest.fixture
def mock_entry_points(monkeypatch):
    """Mock entry_points() to return test client registrations."""
    from importlib.metadata import EntryPoint
    eps = [
        EntryPoint(name="test-provider", value="test_pkg:TestClient", group="parrot.clients"),
    ]
    monkeypatch.setattr("importlib.metadata.entry_points", lambda group: eps)
    return eps
```

---

## 5. Acceptance Criteria

- [ ] **AC-1**: All existing import paths (`from parrot.clients.claude import AnthropicClient`, etc.) continue to work when the corresponding satellite package is installed
- [ ] **AC-2**: `LLMFactory.create("claude:claude-sonnet-4-20250514")` works via entry-point discovery when `ai-parrot-client-anthropic` is installed
- [ ] **AC-3**: `LLMFactory.create("claude:...")` without `ai-parrot-client-anthropic` installed raises `ImportError` with an actionable message naming the missing package
- [ ] **AC-4**: Core package (`ai-parrot`) no longer imports any satellite client code at module scope — only via entry-point `load()` or MetaPathFinder redirect
- [ ] **AC-5**: `pip install ai-parrot[llms]` installs all 10 satellite packages
- [ ] **AC-6**: Each satellite package has its own independent `version` in `pyproject.toml` (not lock-step with core)
- [ ] **AC-7**: `PROVIDER_BACKEND` injection for `bedrock`/`anthropic-aws` works correctly with lazy-loaded `AnthropicClient`
- [ ] **AC-8**: `OpenAIBaseClient` stays in core and is importable by all satellite packages that extend it (`GroqClient`, `NvidiaClient`, etc.)
- [ ] **AC-9**: No breaking changes to `LLMFactory.create()` calling convention
- [ ] **AC-10**: All unit tests pass (`pytest packages/ai-parrot/tests/clients/ -v`)
- [ ] **AC-11**: The `_ParrotClientsRedirector` MetaPathFinder does not redirect core submodules (`base`, `openai_base`, `factory`, `models`, `protocols`, `openrouter`, `moonshot`)
- [ ] **AC-12**: Each satellite `pyproject.toml` declares `[project.entry-points."parrot.clients"]` with the correct provider keys

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.

### Verified Imports

```python
# Core base classes (always available — stay in core):
from parrot.clients import AbstractClient         # clients/__init__.py
from parrot.clients import OpenAIBaseClient       # clients/__init__.py
from parrot.clients.base import AbstractClient    # clients/base.py:230
from parrot.clients.openai_base import OpenAIBaseClient  # clients/openai_base.py:59
from parrot.clients.factory import LLMFactory     # clients/factory.py:161

# These imports CURRENTLY work but will require satellite after extraction:
from parrot.clients.claude import AnthropicClient       # clients/claude.py:69
from parrot.clients.gpt import OpenAIClient             # clients/gpt.py:81
from parrot.clients.google import GoogleGenAIClient     # clients/google/client.py:95
from parrot.clients.groq import GroqClient              # clients/groq.py:50
from parrot.clients.grok import GrokClient              # clients/grok.py:53
from parrot.clients.zai import ZaiClient                # clients/zai.py:22
from parrot.clients.nvidia import NvidiaClient          # clients/nvidia.py:222
from parrot.clients.bedrock import BedrockConverseClient  # clients/bedrock.py:1647
```

### Existing Class Signatures

```python
# parrot/clients/base.py:230
class AbstractClient(EventEmitterMixin, ABC):
    client_type: str = "generic"      # line 237
    client_name: str = "generic"      # line 238
    def __init__(self, conversation_memory=None, preset=None, tools=None,
                 use_tools=False, debug=True, tool_manager=None, **kwargs): ...  # line ~360

# parrot/clients/openai_base.py:59
class OpenAIBaseClient(AbstractClient):
    # Shared base for: OpenAIClient, GroqClient, NvidiaClient, ZaiClient,
    #   MoonshotClient, OpenRouterClient, LocalLLMClient, BedrockMantleClient

# parrot/clients/gpt.py:81
class OpenAIClient(OpenAIBaseClient):
    ...

# parrot/clients/factory.py:161
class LLMFactory:
    @staticmethod
    def parse_llm_string(llm: str) -> Tuple[str, Optional[str]]: ...  # line ~171
    @staticmethod
    def create(llm: str, model_args=None, tool_manager=None,
               **kwargs) -> AbstractClient: ...  # line ~193
```

### Factory Registration (factory.py)

```python
# SUPPORTED_CLIENTS dict — line ~107
# Contains ~30 key→class mappings, eagerly imported or lazy-loaded
# After refactor: only core keys remain static; satellites are entry-point-discovered

# PROVIDER_BACKEND — line ~155
PROVIDER_BACKEND: Dict[str, str] = {
    "bedrock": "bedrock",
    "anthropic-aws": "aws",
}
# Stays in core. Injects backend= kwarg into AnthropicClient init.
```

### MetaPathFinder Pattern (template)

```python
# parrot/tools/__init__.py:50
class _ParrotToolsRedirector(importlib.abc.MetaPathFinder):
    _PREFIX = "parrot.tools."
    _RESOLVING: set = set()  # recursion guard
    _loader = _AliasLoader()  # line 31

    def find_spec(self, fullname, path, target=None):
        # 1. Skip if not parrot.tools.*
        # 2. Skip core submodules (_CORE_SUBMODULES frozenset)
        # 3. Try parrot_tools.<rest>, then plugins.tools.<rest>
        # 4. Synchronize all aliases in sys.modules
        ...
```

### PEP 420 Pattern (ai-parrot-embeddings reference)

```
# Directory structure — NO __init__.py at parrot/ level:
packages/ai-parrot-embeddings/src/parrot/           # .gitkeep only
packages/ai-parrot-embeddings/src/parrot/stores/    # .gitkeep only
packages/ai-parrot-embeddings/src/parrot/embeddings/  # .gitkeep only
```

```toml
# pyproject.toml pattern:
[build-system]
requires = ["setuptools>=77.0.0", "wheel>=0.44.0"]
build-backend = "setuptools.build_meta"

[project]
name = "ai-parrot-embeddings"
dependencies = ["ai-parrot"]

[tool.setuptools.packages.find]
where = ["src"]
include = ["parrot*"]
namespaces = true
```

### Consumers of SUPPORTED_CLIENTS

These files import or reference `SUPPORTED_CLIENTS` — they must be verified
to work unchanged after the refactor (the dict still exists and has the same
keys once `_discover()` runs):

- `parrot/clients/factory.py` — definition (line 107) + usage (lines 234, 237, 241)
- `parrot/bots/abstract.py` — `get_client()` resolution (lines 875, 881, 884, 887, 896, 900, 927, 932, 974, 976, 979, 984)
- `parrot/bots/voice.py` — voice bot client lookup (lines 378, 380)
- `parrot/bots/flows/crew/crew.py` — crew client instantiation (lines 42, 209, 214, 4633)
- `parrot/interfaces/tools.py` — tool interface client lookup (lines 12, 340)
- `parrot/tools/execution_plan/planner.py` — plan validation (lines 34, 108, 111, 113)
- `parrot/advisors/mixin.py` — lazy import (lines 145, 157)
- `parrot_pipelines/abstract.py` — pipeline validation (lines 14, 76, 81)
- `parrot/server/ui/catalog.py` — `_dedup_llm_providers()` (line 54)
- `parrot/handlers/llm.py` — handler (lines 14, 95, 105, 115, 190)
- `parrot/handlers/studio/byok.py` — BYOK handler (lines 18, 172, 174)
- `parrot/handlers/studio/catalog.py` — catalog handler (lines 25, 148)
- `parrot/handlers/studio/models.py` — docstring only (line 102)

### Google Client Subpackage Structure

```
parrot/clients/google/
├── __init__.py  (177B) — exports GoogleGenAIClient
├── analysis.py  (76.7K) — GoogleAnalysis mixin
├── client.py    (278.2K) — GoogleGenAIClient class (line 95)
└── generation.py (111.5K) — GoogleGeneration mixin
```

### Nova Client Subpackage Structure

```
parrot/clients/nova/
├── __init__.py   (351B)
├── audio.py      (61.6K)
├── client.py     (8.5K)
├── generation.py (15.4K)
└── mantle.py     (5.6K) — BedrockMantleClient
```

### Core __init__.py (current state — needs cleanup)

```python
# parrot/clients/__init__.py (current):
from .base import LLM_PRESETS, AbstractClient, StreamingRetryConfig
from .openai_base import OpenAIBaseClient
from .zai import ZaiClient  # ← REMOVE: moves to satellite
```

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.clients.registry`~~ — no client registry module exists;
  registration is purely static in `SUPPORTED_CLIENTS`
- ~~`[project.entry-points."parrot.clients"]`~~ — no entry points are
  used for client discovery anywhere in the project today (this spec
  introduces them)
- ~~`parrot.clients.vertex`~~ — there is no standalone Vertex AI client;
  Vertex support is handled through `GoogleGenAIClient` (the `google-genai`
  SDK supports both AI Studio and Vertex natively)
- ~~`parrot.clients.ollama`~~ — there is no `ollama.py` module; Ollama
  support is handled by `LocalLLMClient` in `localllm.py` via
  OpenAI-compatible API
- ~~`parrot/clients/openai.py`~~ — the OpenAI client file is named `gpt.py`,
  not `openai.py`
- ~~`AbstractClient.__init_subclass__`~~ — no auto-registration metaclass
  or hook exists on `AbstractClient`
- ~~`ai-parrot-embeddings` entry points~~ — the embeddings satellite does
  NOT use entry points; it relies solely on PEP 420 namespace merging

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **PEP 420 satellite structure**: follow `ai-parrot-embeddings` exactly —
  `src/parrot/` with no `__init__.py`, `.gitkeep` at each namespace
  directory, `namespaces = true` in setuptools config.
- **MetaPathFinder**: model `_ParrotClientsRedirector` on
  `_ParrotToolsRedirector` (parrot/tools/__init__.py:50–136). Key
  behaviors to replicate:
  - `_CORE_SUBMODULES` frozenset guards core modules from redirect
  - `_RESOLVING` set prevents recursion
  - `sys.modules` synchronization after successful redirect
- **Entry-point loading**: use `importlib.metadata.entry_points(group=...)`
  (Python 3.11+ API — no `importlib_metadata` backport needed). Each
  entry point's `load()` call returns the class; wrap in a lazy closure
  matching the existing `_lazy_*` pattern.
- **Satellite pyproject.toml template**:
  ```toml
  [build-system]
  requires = ["setuptools>=77.0.0", "wheel>=0.44.0"]
  build-backend = "setuptools.build_meta"

  [project]
  name = "ai-parrot-client-<family>"
  version = "0.1.0"
  dependencies = ["ai-parrot"]

  [project.entry-points."parrot.clients"]
  <key1> = "parrot.clients.<module>:<ClassName>"
  <key2> = "parrot.clients.<module>:<ClassName>"

  [tool.setuptools.packages.find]
  where = ["src"]
  include = ["parrot*"]
  namespaces = true
  ```

### Known Risks / Gotchas

- **Namespace merging in editable mode**: PEP 420 namespace packages work
  with `uv pip install -e` but can be fragile with some installer versions.
  The MetaPathFinder is the defense in depth.
- **Entry-point staleness**: entry points are metadata-only — if a user
  uninstalls a satellite but the dist-info lingers (broken uninstall),
  `load()` will raise `ImportError`. The factory wraps this with an
  actionable error.
- **PROVIDER_BACKEND with lazy Anthropic**: when `bedrock` or
  `anthropic-aws` is used, the factory injects `backend=` before creating
  the client. Since `AnthropicClient` is now lazy (entry-point), the
  `PROVIDER_BACKEND` dict references keys that resolve to entry points,
  not classes. The factory must `load()` the entry point before
  constructing the client — the existing `create()` flow already does
  this (it resolves the client class from `SUPPORTED_CLIENTS` before
  calling `client_class(**init_params)`).
- **Amazon satellite depends on `anthropic[aws]`**: `BedrockConverseBase`
  and the `bedrock` PROVIDER_BACKEND both use the Anthropic SDK's AWS
  transport. `ai-parrot-client-amazon` must declare
  `anthropic[aiohttp,aws]` in its own dependencies, independently from
  `ai-parrot-client-anthropic`.
- **Google client size**: the `google/` subpackage is 466 KB of source
  (client.py alone is 278 KB). Moving this as-is to a satellite works
  fine — PEP 420 handles subpackages within namespace packages.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `importlib.metadata` | stdlib (3.11+) | Entry-point discovery |
| `setuptools` | `>=77.0.0` | Build backend with namespace support |
| `anthropic[aiohttp]` | `>=0.109.0,<1.0.0` | Anthropic satellite |
| `claude-agent-sdk` | `>=0.1.68` | Anthropic satellite (ClaudeAgent) |
| `openai` | `==3.3.1` | OpenAI satellite |
| `openai-codex` | `>=0.1.0` | OpenAI satellite (Codex) |
| `google-genai` | `>=2.18.1` | Google satellite |
| `aioboto3` | `>=13.2.0` | Amazon satellite |
| `groq` | `==0.33.0` | Groq satellite |
| `xai-sdk` | `>=1.12.0` | Grok satellite |
| `zai-sdk` | `>=0.2.3` | Zai satellite |
| `transformers` | `>=4.48.0,<5.0` | HuggingFace satellite |

---

## Worktree Strategy

- **Default isolation**: **mixed** (per-spec core + parallel satellites)
- **Sequential dependency**: Module 1 (factory refactor + MetaPathFinder)
  must land first — all satellites depend on it.
- **After Module 1**: Modules 2–6 are embarrassingly parallel. Each
  satellite moves a disjoint set of files into its own `packages/`
  directory with its own `pyproject.toml`. No two satellites touch the
  same file.
- **Module 7** (extras & workspace) depends on all satellites being
  scaffolded (needs their package names for dependency declarations).
- **Module 8** (tests) can start after Module 1 + one satellite.
- **Cross-feature dependencies**: none — no in-flight specs touch
  `parrot/clients/` directly.

---

## 8. Open Questions

- [x] Which clients stay in core? — *Resolved in brainstorm*: `AbstractClient`,
  `OpenAIBaseClient` (abstract base for OpenAI-compatible), thin wrappers
  (`OpenRouterClient`, `MoonshotClient`), `LLMFactory`.
- [x] Where does `OpenAICodexClient` go? — *Resolved in spec*:
  `ai-parrot-client-openai` (with `OpenAIClient`). The user clarified that
  "OpenAI-compatible" refers to `OpenAIBaseClient` (abstract base), not
  `OpenAIClient` (concrete). Both `OpenAIClient` and `OpenAICodexClient`
  move to the OpenAI satellite.
- [x] Should `PROVIDER_BACKEND` stay in core or move to satellite? —
  *Resolved in spec*: stays in core `factory.py`. It's a routing concern.
- [x] Versioning strategy? — *Resolved in spec*: independent semver per
  satellite package.
- [x] Discovery mechanism? — *Resolved in brainstorm*: entry points
  (`parrot.clients` group) as primary, `_ParrotClientsRedirector`
  MetaPathFinder as fallback.
- [x] Package naming convention? — *Resolved in brainstorm*:
  `ai-parrot-client-{family}`.
- [x] Should the `ZaiClient` import in `parrot/clients/__init__.py` be
  removed entirely or replaced with a lazy-import that emits a
  `DeprecationWarning`? — *Resolved*: removed cleanly (no external
  consumers — hard cut per project policy).
- [x] Should `LLMFactory.list_providers()` be a public API? — *Resolved*:
  yes, public method.
- [x] How should the `all` extra in root `pyproject.toml` be updated —
  transitively via `ai-parrot[llms]`, or list each satellite explicitly?
  — *Resolved*: transitive via `ai-parrot[llms]`.
- [x] Should `GeminiLiveClient` (live.py) move with the Google family or
  stay in core given its distinct use pattern (WebSocket-based voice)?
  — *Resolved*: ship with the Google satellite (`ai-parrot-client-google`).

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-04 | Jesus Lara | Initial draft from brainstorm |
| 0.2 | 2026-09-04 | Jesus Lara | Resolve all open questions: ZaiClient hard cut, list_providers() public, transitive all extra, GeminiLiveClient ships with Google |
