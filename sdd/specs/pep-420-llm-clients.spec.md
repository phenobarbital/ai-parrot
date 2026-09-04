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
**Status**: approved
**Target version**: 5.1.0

> **v0.3 is a rewrite.** v0.1/v0.2 were drafted against a `dev` that predated
> FEAT-524 (memory-less clients) and FEAT-526 (MetaClient). Both changed the
> ground this spec stands on, and the original scope left the provider model
> enums in `parrot.models`, which defeats per-client isolation. The 13 tasks
> generated from v0.2 (TASK-2795..2807) are superseded and must be regenerated.

---

## 1. Motivation & Business Requirements

### Problem Statement

The core `ai-parrot` package bundles **all 20+ LLM client modules** (~34,700
lines, 3 MB of source) in `parrot/clients/`, alongside their SDK dependencies
(`anthropic`, `openai`, `google-genai`, `groq`, `aioboto3`, `xai-sdk`,
`zai-sdk`, `claude-agent-sdk`, `transformers`, …).

This causes four concrete pain points:

1. **Dependency bloat**: installing `ai-parrot` for one provider still ships
   the client code for every other provider in the wheel.

2. **SDK version conflicts**: providers ship breaking SDK changes at different
   cadences. Pinning `groq==0.33.0` in core means every downstream consumer
   inherits that pin even if they only use Claude.

3. **Third-party extensibility barrier**: adding a provider requires a PR to
   core and a manual entry in `factory.py`'s `SUPPORTED_CLIENTS`.

4. **Leaky encapsulation through `parrot.models`**: nine provider model enums
   (`GoogleModel`, `OpenAIModel`, `ClaudeModel`, `GroqModel`, `LocalLLMModel`,
   `MoonshotModel`, `NvidiaModel`, `OpenRouterModel`, `ZaiModel`) live in
   `parrot/models/`, three more (`GrokModel`, `Gemma4Model`,
   `TransformersModel`) live inside client files, and core modules (`conf.py`,
   `loaders/abstract.py`, `bots/agent.py`, image plugins) import them at module
   scope. A client cannot leave core while core imports its enum.

### Goals

- **G1**: Extract **every** concrete LLM client from core into **one satellite
  distribution per provider**. Core keeps only the abstract machinery.
- **G2**: Establish a single **folder convention** for a provider client —
  `parrot/clients/<provider>/{__init__,client,models}.py` — and move each
  provider's model enum into its own `models.py`. `parrot.models` stops owning
  provider enums.
- **G3**: Dynamic discovery via `importlib.metadata` entry points
  (`parrot.clients` group) plus a factory-level model catalogue
  (`list_providers()`, `list_models()`), so no core or server module needs to
  import a provider enum to enumerate models.
- **G4**: Client import paths whose module name is unchanged (`parrot.clients.google`,
  `.groq`, `.grok`, `.zai`, `.nvidia`, `.moonshot`, `.openrouter`, `.vllm`,
  `.gemma4`, `.hf`, `.meta`) keep working when the satellite is installed, via
  PEP 420 namespace merging. Paths that the convention **renames** are a hard
  cut with callers updated in-feature: `parrot.clients.gpt` → `.openai`,
  `.claude` → `.anthropic`, `.localllm` → `.local`, `.bedrock`/`.nova` →
  `.amazon`, `.live` → `.google.live`, and every `parrot.models.<provider>`
  enum → `parrot.clients.<provider>.models` (see Non-Goals).
- **G5**: Preserve `ai-parrot[llms]` as the single install command for all
  clients; each satellite has independent semver.

### Non-Goals (explicitly out of scope)

- Backward-compatibility shims for `from parrot.models.<provider> import
  <Provider>Model`. Project policy: no external consumers, hard cuts, update
  all callers in-feature.
- Moving `OpenAIBaseClient` out of core. **Decision (2026-09-04)**: it stays
  in core and `openai` remains a core dependency (it is the wire base for eight
  clients and core's own tokenizer path already depends on `tiktoken`).
- Changing `AbstractClient`'s interface or `LLMFactory.create()`'s calling
  convention.
- Runtime fallback-on-failure across providers.
- Auto-installing missing satellites.
- Moving the non-LLM Google models (TTS voices, music, image/video-reel
  request models) out of `parrot/models/google.py` — they stay in core because
  server handlers, loaders and pipelines depend on them.

---

## 2. Architectural Design

### Overview

Two moves, in order:

1. **Convention first, in core.** Every provider that is still a flat module
   (`claude.py`, `gpt.py`, `groq.py`, …) is converted to the folder shape
   `parrot/clients/<provider>/` **inside core**, and its model enum is
   relocated from `parrot/models/<x>.py` (or from the client file) into
   `parrot/clients/<provider>/models.py`. `google/` and `nova/` already are
   folders; FEAT-526 lands `meta/` in this shape directly. Core call sites
   that imported provider enums switch to string literals / `provider:model`
   specs. After this step core is internally consistent and still a single
   wheel — a safe intermediate state that can ship on its own.

2. **Relocation.** Each `parrot/clients/<provider>/` folder is moved verbatim
   into `packages/ai-parrot-client-<provider>/src/parrot/clients/<provider>/`
   together with its tests, and the satellite declares entry points. Because
   step 1 already made every folder self-contained, each relocation is a pure
   `git mv` plus a `pyproject.toml`.

Namespace merging uses **`pkgutil.extend_path`** in core's
`parrot/clients/__init__.py` — the exact mechanism `parrot/__init__.py`,
`parrot/embeddings/__init__.py` and `parrot/stores/__init__.py` already use
(FEAT-201). Satellites ship `src/parrot/clients/<provider>/` with **no**
`__init__.py` at `src/parrot/` or `src/parrot/clients/`. The v0.2
`_ParrotClientsRedirector` MetaPathFinder is **dropped**: it solved a problem
`extend_path` does not have, and `parrot.embeddings` has run on `extend_path`
alone since FEAT-201.

### Folder convention (normative)

```
parrot/clients/<provider>/
├── __init__.py     # re-exports: the client class(es) + the model enum + __all__
├── client.py       # the AbstractClient / OpenAIBaseClient subclass(es)
└── models.py       # <Provider>Model(str, Enum), capability frozensets,
                    # DEPRECATIONS mapping (if any). Pure data, no I/O.
```

Rules:

- `models.py` imports nothing from `client.py` (no cycles); `client.py`
  imports its enum from `.models`.
- Extra modules are allowed when a provider genuinely has them (`google/`
  keeps `analysis.py`, `generation.py`; `nova/` keeps `audio.py`,
  `generation.py`, `mantle.py`) but the three canonical files are mandatory.
- Every client class exposes two class attributes read by the factory:

  ```python
  class GoogleGenAIClient(AbstractClient):
      provider_keys: tuple[str, ...] = ("google",)          # primary first
      models: type[Enum] = GoogleModel                        # the catalogue
      deprecated_models: Mapping[str, str] | None = None      # optional
  ```

  `provider_keys` lists **every** factory key the class answers to
  (`("moonshot", "kimi")`, `("grok", "xai")`, `("local", "localllm",
  "ollama", "llamacpp")`). Clients with more than one model family (Nova
  text/voice/image) may expose a single combined enum.

### Provider → distribution map (15 satellites)

| Distribution | `parrot/clients/<provider>/` | Today's sources (moved) | Enum(s) relocated | SDK deps |
|---|---|---|---|---|
| `ai-parrot-client-openai` | `openai/` | `gpt.py`, `codex_agent.py`, `codex_tool_bridge.py` | `OpenAIModel` + `DEPRECATIONS` (from `models/openai.py`) | `openai` (already core), `openai-codex` |
| `ai-parrot-client-anthropic` | `anthropic/` | `claude.py`, `claude_agent.py`, `claude_agent_bridge.py`, `anthropic_backends.py` | `ClaudeModel` (from `models/claude.py`) | `anthropic[aiohttp,aws]`, `claude-agent-sdk` |
| `ai-parrot-client-google` | `google/` | `google/` (as is) + `live.py` → `google/live.py` | `GoogleModel`, `VertexAIModel` (from `models/google.py`) | `google-genai`, `google-api-python-client`, `google-cloud-texttospeech` |
| `ai-parrot-client-gemma4` | `gemma4/` | `gemma4.py` | `Gemma4Model` (from `clients/gemma4.py`) | `transformers`, `torch` |
| `ai-parrot-client-hf` | `hf/` | `hf.py` | `TransformersModel` (from `clients/hf.py`) | `transformers`, `sentence-transformers` |
| `ai-parrot-client-amazon` | `amazon/` | `bedrock.py` → `amazon/bedrock.py`, `nova/` → `amazon/nova/` | Bedrock/Nova enums (from `models/bedrock_models.py`) | `aioboto3`, `anthropic[aiohttp,aws]`, `aws_sdk_bedrock_runtime` |
| `ai-parrot-client-groq` | `groq/` | `groq.py` | `GroqModel` (from `models/groq.py`) | `groq` |
| `ai-parrot-client-grok` | `grok/` | `grok.py` | `GrokModel` (from `clients/grok.py`) | `xai-sdk` |
| `ai-parrot-client-zai` | `zai/` | `zai.py` | `ZaiModel` (from `models/zai.py`) | `zai-sdk` |
| `ai-parrot-client-nvidia` | `nvidia/` | `nvidia.py` | `NvidiaModel` (from `models/nvidia.py`) | — (openai via core) |
| `ai-parrot-client-moonshot` | `moonshot/` | `moonshot.py` | `MoonshotModel` (from `models/moonshot.py`) | — |
| `ai-parrot-client-openrouter` | `openrouter/` | `openrouter.py` | `OpenRouterModel` (from `models/openrouter.py`) | — |
| `ai-parrot-client-local` | `local/` | `localllm.py` | `LocalLLMModel` (from `models/localllm.py`) | — |
| `ai-parrot-client-vllm` | `vllm/` | `vllm.py` | vLLM config models that are client-only (from `models/vllm.py`; shared request/response models stay in core, see §7) | — |
| `ai-parrot-client-meta` | `meta/` | `meta/` (landed by FEAT-526 in this shape) | `MetaModel` (already in `meta/models.py`) | — |

The `amazon/` folder is the one deliberate exception to "one client per
folder": Bedrock Converse, Nova and Mantle are one provider with three wire
protocols and share `bedrock_models.py`.

### What stays in core (`packages/ai-parrot/src/parrot/clients/`)

- `base.py` — `AbstractClient` (memory-less per FEAT-524; receives
  `history: Sequence[HistoryMessage]`, `_format_history()` is the
  per-provider override).
- `openai_base.py` — `OpenAIBaseClient` (wire base; `openai` stays a core dep).
- `factory.py` — `LLMFactory`, `SUPPORTED_CLIENTS` (now discovery-fed),
  `PROVIDER_BACKEND`.
- `models.py` — `LLMConfig` dataclass; `protocols.py` — `VoiceCapable`.
- `__init__.py` — `extend_path` + exports of `AbstractClient`,
  `OpenAIBaseClient`, `LLM_PRESETS`, `StreamingRetryConfig`. The `ZaiClient`
  export is removed (hard cut).

### Component Diagram

```
                 ┌──────────────────────────────────────────────────┐
                 │  parrot/clients/  (CORE, ai-parrot)              │
                 │  __init__.py  → __path__ = extend_path(...)      │
                 │  base.py          AbstractClient                 │
                 │  openai_base.py   OpenAIBaseClient  (openai SDK) │
                 │  factory.py       LLMFactory                     │
                 │     ├─ SUPPORTED_CLIENTS  ← entry_points()        │
                 │     ├─ list_providers()                          │
                 │     └─ list_models(provider)  ← cls.models       │
                 │  models.py / protocols.py                        │
                 └───────────────┬──────────────────────────────────┘
                                 │ PEP 420 (extend_path) + entry points
      ┌──────────┬──────────┬────┴─────┬──────────┬──────────┬──────────┐
      ▼          ▼          ▼          ▼          ▼          ▼          ▼
 clients/    clients/   clients/   clients/   clients/   clients/   clients/
 openai/     anthropic/ google/    amazon/    groq/      meta/      … (15)
 ├ client    ├ client   ├ client   ├ bedrock  ├ client   ├ client
 ├ models    ├ models   ├ models   ├ nova/    └ models   └ models
 └ codex_*   └ agent_*  └ live     └ models
```

### Integration Points

| Existing Component | Change | Notes |
|---|---|---|
| `parrot/clients/__init__.py` | modifies | `extend_path`; drop `ZaiClient` export |
| `parrot/clients/factory.py` | modifies | Remove all concrete imports and `_lazy_*` closures; `_discover()` from entry points; `list_providers()`, `list_models()` |
| `parrot/clients/protocols.py` | modifies | `LiveVoiceResponse` import from `.live` → `parrot.models.voice` (type moves to core models) |
| `parrot/models/__init__.py` | modifies | Drop `GoogleModel`, `NvidiaModel`, `ZaiModel` and vLLM client-only exports |
| `parrot/models/google.py` | modifies | Remove `GoogleModel`, `VertexAIModel`; keep media/voice/video-reel models |
| `parrot/models/{openai,claude,groq,localllm,moonshot,nvidia,openrouter,zai,bedrock_models}.py` | deletes | Content relocated to `clients/<provider>/models.py` |
| `parrot/conf.py:433-435` | modifies | `DEFAULT_LLM_MODEL` fallback becomes the literal `"gemini-flash-latest"`; no `GoogleModel` import |
| `parrot/loaders/abstract.py:27,1038,1073,1115,1180` | modifies | `GoogleModel.X` → string literal / `"google:<id>"` spec |
| `parrot/bots/agent.py`, `bots/jira_specialist.py`, `bots/github_reviewer.py`, `bots/flows/result_agent.py` | modifies | Same hard cut |
| `parrot/interfaces/images/plugins/{analisys,classify,classifybase}.py` | modifies | Same |
| `parrot_tools/code_toolkit.py` (ai-parrot-tools) | modifies | Same |
| `parrot_loaders/{imageunderstanding,videounderstanding}.py` | modifies | Same |
| `parrot_pipelines/abstract.py`, `planogram/**` | modifies | Same; `SUPPORTED_CLIENTS` validation unchanged |
| `parrot/handlers/llm.py` (ai-parrot-server) | modifies | Replace 4 try/except enum imports + per-provider `if` chain with `LLMFactory.list_models(provider)` |
| `parrot/handlers/{lyria_music,video_reel,google_generation,mediagen}.py`, `handlers/models/understanding.py` | verifies | Import only media models from `parrot.models.google` — must still resolve |
| `packages/ai-parrot/pyproject.toml` | modifies | Extras → satellites; remove extracted SDK pins (keep `openai`, `tiktoken`) |
| root `pyproject.toml` | modifies | 15 new workspace members |
| `packages/ai-parrot/tests/unit/clients/` | moves | Provider-specific tests move into their satellite's `tests/` |
| `packages/ai-parrot/tests/unit/models/test_openai_deprecations.py` | moves | → openai satellite |

### Data Models

No new Pydantic models. New class-level attributes on every client
(`provider_keys`, `models`, `deprecated_models`) — see Folder convention.
`LiveVoiceResponse` moves from `parrot/clients/live.py` to
`parrot/models/voice.py` unchanged.

### New Public Interfaces

```python
# parrot/clients/factory.py
class LLMFactory:
    @staticmethod
    def list_providers() -> dict[str, str]:
        """Installed provider key → distribution name (from entry-point metadata)."""

    @staticmethod
    def list_models(provider: str) -> dict[str, list[str]]:
        """{"active": [...], "deprecated": [...]} read from the resolved
        client class's ``models`` / ``deprecated_models`` attributes.
        Raises the same actionable ImportError as create() when the
        satellite is missing."""

    @staticmethod
    def _discover() -> None:
        """Merge entry_points(group="parrot.clients") into SUPPORTED_CLIENTS.
        Lazy on first create()/list_*(); idempotent; duplicate keys warn."""
```

Satellite entry-point contract (one line per key in `provider_keys`):

```toml
[project.entry-points."parrot.clients"]
moonshot = "parrot.clients.moonshot:MoonshotClient"
kimi     = "parrot.clients.moonshot:MoonshotClient"
```

---

## 3. Module Breakdown

### Module 1: Core folder convention + enum relocation (in core, no satellites yet)
- **Path**: `packages/ai-parrot/src/parrot/clients/**`, `parrot/models/**`
- **Responsibility**: Convert every flat client module to
  `clients/<provider>/{__init__,client,models}.py`; move each enum from
  `parrot/models/<x>.py` or from the client file into `models.py`; add
  `provider_keys` / `models` / `deprecated_models` class attributes; move
  `live.py` under `google/`, `bedrock.py` + `nova/` under `amazon/`;
  `LiveVoiceResponse` → `parrot/models/voice.py`; split
  `parrot/models/google.py`; delete the emptied `parrot/models/<provider>.py`
  files; update `parrot/models/__init__.py`. Keep `factory.py` imports
  working (path changes only) so the tree is green at the end of this module.
- **Depends on**: FEAT-526 merged (so `meta/` is already in shape).

### Module 2: Core call-site hard cut
- **Path**: `conf.py`, `loaders/abstract.py`, `bots/*`, `interfaces/images/plugins/*`,
  `parrot_tools/code_toolkit.py`, `parrot_loaders/*understanding.py`,
  `parrot_pipelines/**`
- **Responsibility**: Replace every provider-enum import outside
  `parrot/clients/` with string literals or `"provider:model"` specs. After
  this module `grep -rn "clients\.\w+\.models import" packages/*/src` outside
  `parrot/clients/` returns nothing, and no core module imports a
  `parrot.clients.<provider>` at module scope.
- **Depends on**: Module 1

### Module 3: Factory discovery + model catalogue
- **Path**: `parrot/clients/factory.py`, `parrot/clients/__init__.py`,
  `parrot/handlers/llm.py`
- **Responsibility**: `extend_path` in `__init__.py`; remove concrete imports
  and `_lazy_*` closures from `factory.py`; `_discover()` via
  `importlib.metadata.entry_points(group="parrot.clients")`;
  `list_providers()`, `list_models()`; actionable `ImportError` naming
  `ai-parrot-client-<provider>`; `PROVIDER_BACKEND` untouched; rewrite the
  server LLM handler's model listing on top of `list_models()`. Until
  Module 4 lands, a transitional in-core registry (the 15 `provider_keys`
  tuples read from the in-core folders) keeps `create()` working.
- **Depends on**: Module 1

### Module 4: Satellite scaffolds (15, embarrassingly parallel)
- **Path**: `packages/ai-parrot-client-<provider>/` for each row of the map
- **Responsibility**: `git mv` the folder and its tests; `pyproject.toml`
  (template in §7) with entry points for every key in `provider_keys`, own
  SDK pins, `dependencies = ["ai-parrot"]`; `.gitkeep` at `src/parrot/` and
  `src/parrot/clients/`; add to root workspace `members`. Each satellite
  touches a disjoint file set.
- **Depends on**: Modules 2, 3

### Module 5: Core extras & dependency cleanup
- **Path**: `packages/ai-parrot/pyproject.toml`, root `pyproject.toml`
- **Responsibility**: Rewrite extras (`anthropic = ["ai-parrot-client-anthropic"]`,
  …), `llms` pulls all 15, root `all` pulls `ai-parrot[llms]` transitively;
  drop extracted SDK pins from core (keep `openai`, `tiktoken`); remove the
  transitional in-core registry from Module 3.
- **Depends on**: Module 4 (all 15)

### Module 6: Tests & migration verification
- **Path**: `packages/ai-parrot/tests/unit/clients/`, each satellite `tests/`
- **Responsibility**: discovery, catalogue, namespace-merge, missing-satellite
  error, `PROVIDER_BACKEND` with discovered Anthropic, convention conformance
  test (every installed `parrot.clients.<provider>` has the three canonical
  files and the two class attributes), editable-install smoke.
- **Depends on**: Modules 3, 4

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_convention_three_files` | M1/M6 | Every `parrot/clients/<provider>/` has `__init__.py`, `client.py`, `models.py` |
| `test_convention_class_attrs` | M1/M6 | Every registered client class has `provider_keys` (non-empty, primary first) and `models` (Enum subclass) |
| `test_no_provider_enum_in_parrot_models` | M1 | `parrot.models` exposes none of the 12 provider enums |
| `test_google_media_models_intact` | M1 | `TTSVoice`, `MusicGenre`, `VideoReelRequest`, … still import from `parrot.models.google` |
| `test_core_has_no_module_scope_provider_import` | M2 | Import `parrot.conf`, `parrot.loaders.abstract`, `parrot.bots.agent` with all satellites blocked in `sys.modules` → no ImportError |
| `test_discover_entry_points` | M3 | `_discover()` merges EP keys into `SUPPORTED_CLIENTS` |
| `test_duplicate_entry_point_warning` | M3 | Duplicate EP keys log a warning, first wins |
| `test_create_missing_satellite` | M3 | `create("claude:...")` without satellite → `ImportError` naming `ai-parrot-client-anthropic` |
| `test_list_models_active_deprecated` | M3 | `list_models("openai")` returns active ids from the enum and deprecated ids from `deprecated_models` |
| `test_list_providers` | M3 | Returns installed key → distribution mapping |
| `test_provider_backend_discovered` | M3 | `bedrock` / `anthropic-aws` inject `backend=` on discovered `AnthropicClient` |
| `test_llm_handler_uses_catalogue` | M3 | Server handler lists models via `list_models`, no enum import |
| `test_extend_path_merges_satellite` | M6 | A tmp satellite dir on `sys.path` becomes importable as `parrot.clients.<x>` |

### Integration Tests

| Test | Description |
|---|---|
| `test_import_all_client_paths` | Every `from parrot.clients.<provider> import <Client>` resolves with satellites installed |
| `test_factory_create_all_keys` | `LLMFactory.create()` resolves a class for every key of every installed satellite |
| `test_editable_install` | Discovery + merging work under `uv pip install -e` for a satellite |
| `test_openai_base_parity` (existing) | Still green with `WIRE_SUBCLASSES` pointing at the new paths |

### Test Data / Fixtures

```python
@pytest.fixture
def mock_entry_points(monkeypatch):
    from importlib.metadata import EntryPoint
    eps = [EntryPoint(name="test-provider", value="test_pkg:TestClient", group="parrot.clients")]
    monkeypatch.setattr("importlib.metadata.entry_points", lambda group: eps)
    return eps

@pytest.fixture
def block_satellites(monkeypatch):
    """Make every parrot.clients.<provider> import fail, to prove core independence."""
    for name in PROVIDERS:
        monkeypatch.setitem(sys.modules, f"parrot.clients.{name}", None)
```

---

## 5. Acceptance Criteria

- [ ] **AC-1**: Every provider in the map exists as
  `parrot/clients/<provider>/{__init__,client,models}.py` (in its satellite
  after Module 4), and `client.py` classes expose `provider_keys` and `models`.
- [ ] **AC-2**: No provider model enum is importable from `parrot.models` or
  any `parrot/models/*.py`; `parrot/models/google.py` keeps its media models.
- [ ] **AC-3**: No module in core `ai-parrot` (outside `parrot/clients/<provider>/`)
  imports a `parrot.clients.<provider>` module or enum at module scope
  (`test_core_has_no_module_scope_provider_import`).
- [ ] **AC-4**: `from parrot.clients.<provider> import <Client>` works for every
  provider when its satellite is installed (PEP 420 via `extend_path`); the
  renamed legacy paths listed in G4 are gone and no caller in `packages/*`,
  `tests/`, `examples/` references them.
- [ ] **AC-5**: `LLMFactory.create("<key>:<model>")` works for every key of every
  installed satellite via entry-point discovery; without the satellite it
  raises `ImportError` naming `ai-parrot-client-<provider>`.
- [ ] **AC-6**: `LLMFactory.list_providers()` and `list_models(provider)` are
  public and the server LLM handler uses them (no enum imports left there).
- [ ] **AC-7**: `PROVIDER_BACKEND` injection for `bedrock` / `anthropic-aws`
  works with the discovered `AnthropicClient`.
- [ ] **AC-8**: `OpenAIBaseClient` stays in core, `openai` and `tiktoken` remain
  core dependencies; every other extracted SDK pin is gone from core.
- [ ] **AC-9**: `pip install ai-parrot[llms]` installs all 15 satellites; each
  has its own `version`.
- [ ] **AC-10**: `LLMFactory.create()` and `AbstractClient` signatures unchanged.
- [ ] **AC-11**: MetaClient (FEAT-526) relocates to `ai-parrot-client-meta` with
  zero source edits inside `meta/` (pure `git mv`).
- [ ] **AC-12**: `pytest packages/ai-parrot/tests/unit/clients/ -v` and every
  satellite's `tests/` pass; `ruff` clean on changed files.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** Read from `dev` at `d44045f51`
> (2026-09-04, after FEAT-524, before FEAT-526 code). Re-verify line numbers.

### Verified Imports

```python
from parrot.clients import AbstractClient, OpenAIBaseClient, LLM_PRESETS, StreamingRetryConfig  # clients/__init__.py:6-7
from parrot.clients.base import AbstractClient            # base.py
from parrot.clients.openai_base import OpenAIBaseClient   # openai_base.py:65
from parrot.clients.factory import LLMFactory, SUPPORTED_CLIENTS, PROVIDER_BACKEND  # factory.py:107,155
from parrot.clients.models import LLMConfig               # clients/models.py (dataclass)
from parrot.clients.protocols import VoiceCapable         # protocols.py:17 — imports .live:LiveVoiceResponse (must change)
from parrot.memory import HistoryMessage, render_history  # FEAT-524
from pkgutil import extend_path                           # used in parrot/__init__.py:9-12, embeddings/__init__.py:1-2, stores/__init__.py:1-2
```

### Existing Class Signatures

```python
# parrot/clients/base.py — FEAT-524 memory-less contract
class AbstractClient(EventEmitterMixin, ABC):
    client_type: str = "generic"
    client_name: str = "generic"
    # ask()/ask_stream() take history: Sequence[HistoryMessage]; NO user_id/session_id,
    # NO conversation_memory kwarg. _format_history() is the provider override
    # (currently overridden by Google and Bedrock only).

# parrot/clients/openai_base.py:65
class OpenAIBaseClient(AbstractClient):
    tool_format: ToolFormat = ToolFormat.OPENAI      # :76
    _default_timeout: float = 60.0                    # :87
    def __init__(self, api_key=None, base_url=None, **kwargs)  # :89
    # subclasses: OpenAIClient, GroqClient, NvidiaClient, ZaiClient, MoonshotClient,
    #             OpenRouterClient, LocalLLMClient, vLLMClient, BedrockMantleClient, MetaClient

# parrot/clients/factory.py:107
SUPPORTED_CLIENTS = { "claude": AnthropicClient, "anthropic": ..., "bedrock": AnthropicClient,
  "anthropic-aws": AnthropicClient, "bedrock-converse": _lazy_bedrock_converse, "nova": _lazy_nova,
  "bedrock-mantle": _lazy_bedrock_mantle, "mantle": ..., "google": GoogleGenAIClient,
  "openai": OpenAIClient, "groq": GroqClient, "grok": GrokClient, "xai": GrokClient,
  "zai": ZaiClient, "z.ai": ZaiClient, "openrouter": OpenRouterClient, "nvidia": NvidiaClient,
  "moonshot": MoonshotClient, "kimi": MoonshotClient, "local"/"localllm"/"ollama"/"llamacpp": LocalLLMClient,
  "vllm": vLLMClient, "gemma4": _lazy_gemma4, "claude-agent"/"claude-code": _lazy_claude_agent,
  "codex-agent"/"openai-codex"/"codex-code": _lazy_openai_codex }
PROVIDER_BACKEND = {"bedrock": "bedrock", "anthropic-aws": "aws"}   # :155
```

### Current file inventory (`parrot/clients/`)

Flat modules: `anthropic_backends.py bedrock.py claude.py claude_agent.py
claude_agent_bridge.py codex_agent.py codex_tool_bridge.py gemma4.py gpt.py
grok.py groq.py hf.py live.py localllm.py moonshot.py nvidia.py openrouter.py
vllm.py zai.py` + core `base.py openai_base.py factory.py models.py protocols.py`.
Folders: `google/{__init__,client,analysis,generation}.py`,
`nova/{__init__,client,audio,generation,mantle}.py`.

Module-scope SDK imports today: `claude.py`/`anthropic_backends.py` → `anthropic`;
`gpt.py`/`openai_base.py`/`localllm.py`/`moonshot.py`/`nvidia.py`/`openrouter.py` →
`openai`; `google/*`/`live.py` → `google.genai`; `groq.py` → `groq`; `grok.py` →
`xai_sdk`; `bedrock.py`/`nova/generation.py` → `aioboto3`; `nova/audio.py` →
`aws_sdk_bedrock_runtime`; `gemma4.py`/`hf.py` → `torch`, `transformers`;
`claude_agent*.py` → `claude_agent_sdk`; `zai.py` imports `zai` lazily (:81).

### Provider enums today

In `parrot/models/`: `google.py:11 GoogleModel`, `:280 VertexAIModel`;
`openai.py OpenAIModel + DEPRECATIONS`; `claude.py ClaudeModel`; `groq.py
GroqModel`; `localllm.py LocalLLMModel`; `moonshot.py MoonshotModel`;
`nvidia.py NvidiaModel`; `openrouter.py OpenRouterModel`; `zai.py ZaiModel`;
`bedrock_models.py` (Bedrock/Nova). In client files: `grok.py GrokModel`,
`gemma4.py Gemma4Model`, `hf.py TransformersModel`.
`parrot/models/__init__.py:76-108` re-exports `GoogleModel`, `NvidiaModel`,
`ZaiModel` and the vLLM models.

Non-client content that **stays** in `parrot/models/google.py`:
`GoogleVoiceModel`, `TTSVoice`, `MusicGenre`, `MusicMood`,
`MusicGenerationRequest`, `LyriaModel`, `MusicBatchRequest/Response`,
`AspectRatio`, `ImageResolution`, `FictionalSpeaker`,
`ConversationalScriptConfig`, `VoiceProfile`, `VoiceRegistry`,
`VideoReelScene`, `VideoReelRequest`.

### Enum consumers outside `parrot/clients/` (hard-cut list)

Core: `conf.py:433,435`, `loaders/abstract.py:27,1038,1073,1115,1180`,
`bots/agent.py`, `bots/jira_specialist.py`, `bots/github_reviewer.py`,
`bots/flows/result_agent.py`,
`interfaces/images/plugins/{analisys,classify,classifybase}.py`,
`models/__init__.py`. Satellites: `parrot_tools/code_toolkit.py`,
`parrot_loaders/{imageunderstanding,videounderstanding}.py`,
`parrot_pipelines/abstract.py`, `parrot_pipelines/planogram/{plan,legacy}.py`,
`parrot_pipelines/planogram/types/*.py`, `parrot/handlers/llm.py:19-39,72-81`.
Server handlers `lyria_music.py`, `video_reel.py`, `google_generation.py`,
`mediagen.py`, `handlers/models/understanding.py` import **media** models
from `parrot.models.google` — verify they need no change.

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.clients.registry`~~ — no registry module; registration is static.
- ~~`[project.entry-points."parrot.clients"]`~~ — introduced by this spec.
- ~~`_ParrotClientsRedirector`~~ — never existed; v0.2 proposed it, v0.3 drops it.
- ~~`AbstractClient.conversation_memory` / `create_conversation_memory()`~~ —
  removed by FEAT-524.
- ~~`provider_keys` / `models` class attributes~~ — introduced by this spec.
- ~~`LLMFactory.list_models()` / `list_providers()`~~ — introduced by this spec.
- ~~`parrot/clients/openai.py`~~ — the OpenAI client file is `gpt.py`.
- ~~`parrot/clients/ollama.py`, `parrot/clients/vertex.py`~~ — do not exist.
- ~~`parrot/clients/meta/`~~ — does not exist on `dev` yet; FEAT-526 creates it.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Namespace merging**: `parrot/clients/__init__.py` starts with
  `from pkgutil import extend_path; __path__ = extend_path(__path__, __name__)`
  exactly like `parrot/embeddings/__init__.py`. Satellites: `src/parrot/` and
  `src/parrot/clients/` contain only `.gitkeep`; `namespaces = true` in
  `[tool.setuptools.packages.find]` (copy `packages/ai-parrot-embeddings/pyproject.toml`).
- **Satellite `pyproject.toml` template**:
  ```toml
  [build-system]
  requires = ["setuptools>=77.0.0", "wheel>=0.44.0"]
  build-backend = "setuptools.build_meta"
  [project]
  name = "ai-parrot-client-<provider>"
  version = "0.1.0"
  dependencies = ["ai-parrot", "<sdk pins>"]
  [project.entry-points."parrot.clients"]
  <key> = "parrot.clients.<provider>:<ClassName>"   # one per provider_keys entry
  [tool.setuptools.packages.find]
  where = ["src"]
  include = ["parrot*"]
  namespaces = true
  ```
- **Enum relocation is a move, not a rewrite**: keep enum member names and
  values byte-identical; `DEPRECATIONS` moves next to `OpenAIModel` and is
  exposed as `OpenAIClient.deprecated_models`.
- **Hard cut of core call sites**: prefer the `"provider:model"` string spec
  (`llm="google:gemini-2.5-flash-lite"`) over bare model literals where the
  call already goes through `LLMFactory`, so the provider is explicit.
- **Entry-point loading**: `importlib.metadata.entry_points(group="parrot.clients")`
  (3.11+ API). Wrap `ep.load()` in a closure matching the existing `_lazy_*`
  shape so `create()` code stays the same.
- **Tests move with code**: `tests/unit/clients/test_{claude,grok,groq,openai,
  gemini,bedrock,codex}*` go to their satellites; core keeps the
  memory-less/lifecycle/signature tests that use a stub client.

### Known Risks / Gotchas

- **`protocols.py` → `live.py` cycle**: `VoiceCapable` imports
  `LiveVoiceResponse` from `.live`. Moving `live.py` into `google/` without
  first moving the type to `parrot/models/voice.py` makes core import a
  satellite. Do the type move in Module 1.
- **`parrot/models/vllm.py` is mixed**: `VLLMConfig`, `VLLMSamplingParams`,
  `VLLMBatchRequest/Response`, `VLLMServerInfo`, `pydantic_to_guided_json`
  are re-exported from `parrot.models` and may be used by server handlers.
  Inventory their consumers in Module 1; only client-private items move.
- **`bedrock_models.py` (17.5K)** is shared by Converse, Nova and Mantle — it
  becomes `amazon/models.py`; do not split it per wire protocol.
- **Amazon satellite depends on `anthropic[aws]`** independently of the
  anthropic satellite (Bedrock transport).
- **`handlers/llm.py` is in `ai-parrot-server`**: Module 3 crosses a package
  boundary; the server must not regain an enum import.
- **FEAT-525 (per-turn compaction)** is active in `parrot/memory` and `bots/`;
  it should not touch `parrot/clients/`, but Module 2 edits `bots/agent.py` —
  rebase-check before merging.
- **Editable installs**: `extend_path` relies on the satellite `src/` being on
  `sys.path`; uv's editable `.pth` does that. Covered by `test_editable_install`.
- **Two-step ordering is the safety net**: Module 1+2 leave core shippable
  with all clients still inside; if extraction stalls, `dev` is not broken.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `importlib.metadata` | stdlib (3.11+) | Entry-point discovery |
| `setuptools` | `>=77.0.0` | Namespace-aware build backend |
| `openai` | `==3.3.1` | **stays in core** (`OpenAIBaseClient`) |
| `anthropic[aiohttp,aws]` | `>=0.109.0,<1.0.0` | anthropic + amazon satellites |
| `claude-agent-sdk` | `>=0.1.68` | anthropic satellite |
| `openai-codex` | `>=0.1.0` | openai satellite |
| `google-genai` | `>=2.18.1` | google satellite |
| `aioboto3` | `>=13.2.0` | amazon satellite |
| `groq` | `==0.33.0` | groq satellite |
| `xai-sdk` | `>=1.12.0` | grok satellite |
| `zai-sdk` | `>=0.2.3` | zai satellite |
| `transformers` | `>=4.48.0,<5.0` | gemma4 + hf satellites |

---

## Worktree Strategy

- **Default isolation**: **per-spec** for Modules 1–3 (they rewrite the same
  core files sequentially), then **parallel** for Module 4's 15 satellites
  (disjoint file sets), then per-spec again for Modules 5–6.
- **Prerequisite**: FEAT-526 merged into `dev`. The existing worktree
  `feat-523-pep-420-llm-clients` (0 commits, 52 behind dev) must be removed
  and recreated from `origin/dev` after that merge.
- **Cross-feature dependencies**: FEAT-526 (blocking, lands `meta/` in the
  convention); FEAT-525 (non-blocking, watch `bots/agent.py`).

---

## 8. Open Questions

- [x] Which clients stay in core? — **v0.3: none.** All 15 providers leave;
  core keeps `AbstractClient`, `OpenAIBaseClient`, `LLMFactory`, shared types.
- [x] Distribution granularity? — **One per provider (15)**, not per SDK family.
- [x] Where do the provider model enums live? — `parrot/clients/<provider>/models.py`;
  `parrot.models` drops them (hard cut).
- [x] Where does `OpenAIBaseClient` live? — **Core**; `openai` stays a core dep.
- [x] Discovery mechanism? — `extend_path` + entry points. MetaPathFinder dropped.
- [x] How do UIs/server list models without importing enums? —
  `LLMFactory.list_models()` reading `cls.models` / `cls.deprecated_models`.
- [x] FEAT-526 sequencing? — MetaClient lands first, in core, already in the
  folder convention; FEAT-523 relocates it by `git mv`.
- [x] Gemma4: google, hf or its own? — **Own satellite** (`ai-parrot-client-gemma4`),
  consistent with one-per-provider; shares SDK pins with hf.
- [x] `ZaiClient` export in `parrot/clients/__init__.py`? — removed (hard cut).
- [x] `all` extra in root `pyproject.toml`? — transitive via `ai-parrot[llms]`.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-04 | Jesus Lara | Initial draft from brainstorm |
| 0.2 | 2026-09-04 | Jesus Lara | Resolve open questions: ZaiClient hard cut, list_providers() public, transitive all extra, GeminiLiveClient ships with Google |
| 0.3 | 2026-09-04 | Jesus Lara | Rewrite after FEAT-524/526: all clients leave core, one satellite per provider (15), `clients/<provider>/{__init__,client,models}.py` convention, provider enums leave `parrot.models`, `extend_path` replaces MetaPathFinder, `list_models()` catalogue, two-step (convention-in-core → relocate) plan. Supersedes TASK-2795..2807. |
