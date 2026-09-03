---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: PEP 420 LLM Client Satellite Packages

**Date**: 2026-09-03
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: Option A

---

## Problem Statement

Every LLM client (`parrot.clients`) ships inside the core `ai-parrot`
distribution, regardless of whether the user needs or installs the
corresponding SDK dependency. The `clients/` directory currently contains
**34,671 lines** across 34 files covering ~20 distinct LLM providers.

**Who is affected:** developers installing `ai-parrot` who only need a
subset of providers (the common case). They carry ~13 kLoC of unused client
code in their environment, and the `pyproject.toml` already lists per-provider
extras for the SDK dependencies (`ai-parrot[openai]`, `ai-parrot[groq]`, etc.)
— but those extras install only the *dependency*, not the *code*, because the
code is already always present.

**Why now:** the client roster keeps growing — Grok/xAI, Moonshot/Kimi, NVIDIA
NIM, BedrockMantle, OpenAI Codex, and Gemma4 were all added in the last 6
months. Each new provider adds ~500–2,000 lines to core. The
`ai-parrot-embeddings` refactor (FEAT-201) already proved the PEP 420
satellite pattern works well and reduces core install size. Applying the same
pattern to LLM clients is the natural next step.

**The unsolved question:** `SUPPORTED_CLIENTS` in `factory.py` is a static
dict that hard-codes every provider→class mapping. Moving client code to
satellite packages means the factory can no longer statically import them.
The discovery mechanism must become dynamic — specifically,
`importlib.metadata.entry_points`-based — so that each satellite registers its
clients at install time and the factory discovers them at runtime.

## Constraints & Requirements

- **Backward compatibility**: `from parrot.clients.openai import OpenAIClient`
  (and equivalent for every provider) must keep working when the satellite is
  installed. PEP 420 namespace merging provides this natively; a `sys.meta_path`
  finder acts as a fallback.
- **Core must remain self-sufficient**: Anthropic (Claude), Google
  (GenAI + VertexAI + Live), and Ollama (local/vLLM) stay in core because
  internal tools and defaults depend on them.
- **No import-time overhead**: the factory must not attempt to import all
  satellites eagerly. Entry points are metadata-only until explicitly loaded.
- **Existing extras pattern preserved**: `ai-parrot[openai]` must now pull in
  *both* the SDK (`openai==3.3.1`) and the satellite package
  (`ai-parrot-llm-openai`). A new `ai-parrot[llms]` meta-extra pulls all
  satellite LLM packages.
- **OpenAIBaseClient stays in core**: it is the shared base class for
  LocalLLMClient (core) and multiple satellite clients (Groq, NVIDIA, etc.).
  Satellites import from `parrot.clients.openai_base`.
- **One package per provider**: each satellite is independently versionable and
  installable, following the user's decision in discovery.

---

## Options Explored

### Option A: Per-Provider PEP 420 Satellites + Entry-Point Discovery

Each non-core LLM provider gets its own distribution under `packages/`. The
satellite contributes its client module(s) to the `parrot.clients` namespace
via PEP 420 implicit namespace packages (no `__init__.py` at `src/parrot/` or
`src/parrot/clients/`). Each satellite declares a
`[project.entry-points."parrot.llm_providers"]` group in its `pyproject.toml`
that maps provider keys to the client class.

**`factory.py` changes**: `SUPPORTED_CLIENTS` starts with only core clients
(Claude, Google, Ollama). At first access (lazy singleton), it merges clients
discovered via `importlib.metadata.entry_points(group="parrot.llm_providers")`.
Each entry point's `load()` returns the client class. The existing lazy-loader
closure pattern is replaced by the entry-point loader which is inherently lazy.

**Satellite packages (9 total):**

| Package | Files Moved | Providers Registered | Lines |
|---|---|---|---|
| `ai-parrot-llm-openai` | `gpt.py`, `codex_agent.py`, `codex_tool_bridge.py` | `openai`, `codex-agent`, `openai-codex`, `codex-code` | ~3,250 |
| `ai-parrot-llm-groq` | `groq.py` | `groq` | ~1,522 |
| `ai-parrot-llm-grok` | `grok.py` | `grok`, `xai` | ~798 |
| `ai-parrot-llm-openrouter` | `openrouter.py` | `openrouter` | ~202 |
| `ai-parrot-llm-nvidia` | `nvidia.py` | `nvidia` | ~695 |
| `ai-parrot-llm-moonshot` | `moonshot.py` | `moonshot`, `kimi` | ~372 |
| `ai-parrot-llm-zai` | `zai.py` | `zai`, `z.ai` | ~1,098 |
| `ai-parrot-llm-bedrock` | `bedrock.py`, `nova/` | `bedrock-converse`, `nova`, `bedrock-mantle`, `mantle` | ~3,733 |
| `ai-parrot-llm-huggingface` | `hf.py`, `gemma4.py` | `transformers`, `gemma4` | ~1,538 |
| **Total** | **17 files** | **~20 keys** | **~13,208** |

**sys.meta_path fallback**: a `_ClientRedirector` (modeled on
`_ParrotToolsRedirector` in `parrot/tools/__init__.py`) intercepts
`parrot.clients.<name>` imports when namespace merging fails (editable installs,
mono-repo dev mode). It tries `import parrot_llm_<provider>.<name>` as a last
resort.

✅ **Pros:**
- Maximum granularity — install only what you need
- Independent versioning and release cycles per provider
- Mirrors the proven `ai-parrot-embeddings` pattern
- Entry points are the standard Python plugin mechanism
- Core shrinks by ~13 kLoC (38% of `clients/`)
- Each satellite can pin its own SDK version independently

❌ **Cons:**
- 9 new packages to maintain (pyproject.toml, CI, releases)
- uv workspace grows from 8 to 17 members
- Satellites that wrap a single ~200-line file (openrouter) have high
  packaging overhead relative to code
- Entry-point discovery adds ~5–10ms at first factory call (one-time)

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `importlib.metadata` | Entry-point discovery | stdlib, Python 3.9+ |
| `setuptools` / `hatchling` | Build backend with entry-point support | already used |
| `uv` | Workspace member management | already used |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot-embeddings/` — full PEP 420 satellite template (directory structure, pyproject.toml, `.gitkeep` pattern)
- `parrot/tools/__init__.py:50-136` — `_ParrotToolsRedirector` sys.meta_path finder pattern
- `parrot/clients/factory.py:16-104` — lazy-loader closures (conceptual ancestor of entry-point loading)

---

### Option B: SDK-Grouped Satellites + Entry-Point Discovery

Instead of one package per provider, group clients by their underlying SDK
dependency. Providers sharing the same SDK ship together.

**Satellite packages (4 total):**

| Package | Clients | Shared SDK |
|---|---|---|
| `ai-parrot-llm-openai-compat` | OpenAI, Groq, NVIDIA, Moonshot, Zai, OpenRouter, Codex | `openai` SDK |
| `ai-parrot-llm-aws` | BedrockConverse, Nova, BedrockMantle | `aioboto3` / AWS SDK |
| `ai-parrot-llm-xai` | Grok | `xai-sdk` |
| `ai-parrot-llm-huggingface` | Transformers, Gemma4 | `torch`, `transformers` |

Same entry-point discovery mechanism as Option A. The only difference is
the packaging granularity.

✅ **Pros:**
- Only 4 packages instead of 9 — less CI/release overhead
- SDK version pinning is centralized per group
- Smaller providers (OpenRouter, Moonshot) don't carry packaging overhead

❌ **Cons:**
- Violates one-package-per-provider decision from discovery
- Installing `ai-parrot-llm-openai-compat` pulls in 7 client modules when
  you might only want one (defeats the purpose of reducing installed code)
- Groq and OpenRouter have different SDK-level deps despite sharing
  `OpenAIBaseClient` (Groq has `groq` SDK, not just `openai`)
- Adding a new OpenAI-compat provider forces a release of the umbrella package
- xAI alone as a satellite feels odd (single-file package)

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `importlib.metadata` | Entry-point discovery | stdlib |

🔗 **Existing Code to Reuse:**
- Same as Option A

---

### Option C: Single Satellite (ai-parrot-llm) with Per-Provider Extras

One satellite distribution (`ai-parrot-llm`) holds all non-core clients. Each
provider is exposed via an optional extra:
`pip install ai-parrot-llm[openai,groq]`.

All client code lives in a single `packages/ai-parrot-llm/` member. Extras
control only the SDK dependency, not which `.py` files are installed — all
client modules are always present in the satellite (same as the current
situation, but the code is in a separate distribution).

✅ **Pros:**
- Simplest packaging: 1 new package instead of 9
- Easiest migration: one `pyproject.toml`, one CI pipeline
- `ai-parrot[llms]` just depends on `ai-parrot-llm[all]`
- Single version to track

❌ **Cons:**
- Core size reduction is all-or-nothing: either you install the satellite
  (and get ALL client code) or you don't
- Does not achieve the stated goal of "install only what you need" at the
  code level — only at the SDK dependency level
- Adding a new provider still grows the satellite, approaching the same
  problem at a different level
- Cannot version providers independently

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `importlib.metadata` | Entry-point discovery | stdlib |

🔗 **Existing Code to Reuse:**
- Same as Option A, but only one satellite to scaffold

---

### Option D: Lazy-Import Guard Only (No Code Movement)

Do not move any code. Instead, wrap every non-core client in a try-import
guard that raises an actionable `ImportError` when the SDK is missing. Make
all non-core clients lazy-loaded in `factory.py` (extend the existing
`_lazy_*` pattern to ALL non-core clients).

This eliminates import-time failures and startup overhead from unused clients
without changing the package structure.

✅ **Pros:**
- Zero packaging changes — no new distributions
- No entry-point mechanism needed
- No risk of namespace-merging edge cases
- Trivially reversible
- Already partially implemented (6 of 20 clients use lazy loaders)

❌ **Cons:**
- Does NOT reduce installed code size (the stated goal)
- `parrot.clients` keeps growing with every new provider
- Not aligned with the PEP 420 satellite strategy established by FEAT-201
- Users still carry ~13 kLoC they cannot use

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| (none) | All stdlib | — |

🔗 **Existing Code to Reuse:**
- `parrot/clients/factory.py:16-104` — existing `_lazy_*` closures

---

## Recommendation

**Option A** is recommended because:

1. **It fully solves the stated problem**: code that is not needed is not
   installed. This is the only option that achieves true code-level
   modularity, not just dependency-level modularity.

2. **It follows the proven pattern**: `ai-parrot-embeddings` (FEAT-201)
   established PEP 420 satellites as the project's standard for decomposing
   the monolith. Doing the same for clients is a natural, predictable
   extension that developers already understand.

3. **Entry points are the right discovery mechanism**: they are the stdlib
   standard for plugin registration, metadata-only at rest (no import until
   `load()` is called), and supported by all modern build backends. This
   replaces the static `SUPPORTED_CLIENTS` dict with a discoverable,
   extensible registry — opening the door for third-party LLM client plugins
   in the future.

4. **The packaging overhead is manageable**: 9 packages sounds like a lot, but
   each satellite is a minimal `pyproject.toml` + 1-3 `.py` files + entry-point
   declarations. CI can use a matrix build. The uv workspace already manages 8
   members; 17 is routine for a workspace this size.

**What we're trading off**: release coordination complexity (9 satellites to
version) and slightly more CI infrastructure. This is acceptable because each
satellite changes infrequently (LLM client code is stable once written) and
can be released independently.

---

## Feature Description

### User-Facing Behavior

**Installing with specific providers:**
```bash
# Only need Claude and OpenAI
pip install ai-parrot ai-parrot-llm-openai

# Need everything
pip install ai-parrot[llms]

# Or the old way (still works — extras now pull satellite packages)
pip install ai-parrot[openai,groq]
```

**Import paths remain unchanged:**
```python
# These all work when ai-parrot-llm-openai is installed:
from parrot.clients.gpt import OpenAIClient          # PEP 420 namespace
from parrot.clients.factory import LLMFactory
client = LLMFactory.create("openai:gpt-5-mini")      # entry-point discovery
```

**Clear error when a satellite is not installed:**
```python
>>> from parrot.clients.gpt import OpenAIClient
ImportError: parrot.clients.gpt requires the 'ai-parrot-llm-openai' package.
Install with: pip install ai-parrot-llm-openai
  (or: pip install ai-parrot[openai])
```

### Internal Behavior

1. **At install time**: each satellite's `pyproject.toml` declares entry points
   in the `parrot.llm_providers` group. `uv`/`pip` writes these to the
   distribution's `dist-info/entry_points.txt`.

2. **At first `LLMFactory.create()` call** (or explicit
   `LLMFactory.discover()`):
   - Start with core clients (hardcoded: claude, anthropic, bedrock,
     anthropic-aws, google, local, localllm, ollama, vllm, llamacpp).
   - Call `importlib.metadata.entry_points(group="parrot.llm_providers")`.
   - For each entry point, register its `name → entry_point` (not yet loaded)
     in the `SUPPORTED_CLIENTS` dict.
   - On first use of a discovered key, call `entry_point.load()` to import
     the class.

3. **At import time** (namespace merging):
   - When `ai-parrot-llm-openai` is installed, its
     `src/parrot/clients/gpt.py` is visible under the `parrot.clients`
     namespace because both core and satellite contribute to the same
     implicit namespace package.
   - The `_ClientRedirector` meta_path finder catches edge cases where
     namespace merging fails (editable mode, certain installer behaviors).

4. **PROVIDER_BACKEND mapping**: stays in core `factory.py` — it only
   applies to `AnthropicClient` backends (core).

### Edge Cases & Error Handling

- **Satellite not installed + direct import**: `ImportError` with actionable
  message (which package to install, which extra to use).
- **Satellite not installed + factory create**: `ValueError` listing only
  *installed* providers, plus a hint about available satellites.
- **Multiple satellites registering the same key**: last-installed wins (same
  as entry-point semantics). Log a warning.
- **Editable installs (uv workspace dev mode)**: PEP 420 namespace merging
  works with `uv pip install -e` because `uv` sets up `.pth` files. The
  meta_path finder is a safety net.
- **OpenAIBaseClient dependency**: satellites that extend `OpenAIBaseClient`
  import it from `parrot.clients.openai_base` (core). This is a cross-package
  dependency but it's stable and abstract — the base class changes rarely.
- **Circular import risk**: none — satellites import FROM core (base classes),
  core never imports FROM satellites (discovery is metadata-only until load).

---

## Capabilities

### New Capabilities
- `llm-client-satellites`: PEP 420 satellite packages for non-core LLM clients
- `llm-provider-entry-points`: entry-point-based dynamic discovery of LLM providers
- `client-namespace-redirector`: sys.meta_path fallback finder for `parrot.clients` namespace

### Modified Capabilities
- `parrot.clients.factory` — `SUPPORTED_CLIENTS` becomes a hybrid static+discovered dict
- `pyproject.toml` extras — `[openai]`, `[groq]`, etc. now pull satellite packages alongside SDK deps

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/clients/factory.py` | modifies | SUPPORTED_CLIENTS becomes dynamic; LLMFactory.create() calls discover() |
| `parrot/clients/__init__.py` | modifies | Add `_ClientRedirector` meta_path finder |
| `packages/ai-parrot/pyproject.toml` | modifies | Extras updated to include satellite packages; workspace gains 9 members |
| `parrot/server/ui/catalog.py` | modifies | `_dedup_llm_providers()` must handle discovered (not-yet-loaded) entries |
| `parrot/handlers/llm.py` | verifies | Uses `SUPPORTED_CLIENTS` — should work unchanged after discovery |
| `parrot/handlers/studio/catalog.py` | verifies | Same as above |
| `parrot/handlers/studio/byok.py` | verifies | Same as above |
| `parrot/advisors/mixin.py` | verifies | Lazy imports SUPPORTED_CLIENTS — should work unchanged |
| `parrot_pipelines/abstract.py` | verifies | Uses SUPPORTED_CLIENTS for validation |
| CI pipelines | extends | Matrix build for satellite packages |

---

## Code Context

### User-Provided Code

No code snippets provided by the user during discovery.

### Verified Codebase References

#### Classes & Signatures
```python
# From parrot/clients/base.py:230
class AbstractClient(EventEmitterMixin, ABC):
    client_type: str = "generic"      # line 233
    client_name: str = "generic"      # line 234
    def __init__(self, conversation_memory=None, preset=None, tools=None,
                 use_tools=False, debug=True, tool_manager=None, **kwargs):  # line 360

# From parrot/clients/openai_base.py (base for satellite clients)
class OpenAIBaseClient(AbstractClient):
    # Extended by: OpenAIClient, GroqClient, NvidiaClient, ZaiClient,
    #              MoonshotClient, OpenRouterClient, LocalLLMClient, BedrockMantleClient

# From parrot/clients/factory.py:161
class LLMFactory:
    @staticmethod
    def parse_llm_string(llm: str) -> Tuple[str, Optional[str]]:  # line 171
    @staticmethod
    def create(llm: str, model_args=None, tool_manager=None, **kwargs) -> AbstractClient:  # line 193
```

#### SUPPORTED_CLIENTS (factory.py:107-149)
```python
SUPPORTED_CLIENTS = {
    # Core (stays):
    "claude": AnthropicClient,
    "anthropic": AnthropicClient,
    "bedrock": AnthropicClient,
    "anthropic-aws": AnthropicClient,
    "google": GoogleGenAIClient,
    "local": LocalLLMClient,
    "localllm": LocalLLMClient,
    "ollama": LocalLLMClient,
    "vllm": vLLMClient,
    "llamacpp": LocalLLMClient,
    # Lazy-loaded core (stays):
    "claude-agent": _lazy_claude_agent,
    "claude-code": _lazy_claude_agent,
    # Move to satellites:
    "bedrock-converse": _lazy_bedrock_converse,
    "nova": _lazy_nova,
    "bedrock-mantle": _lazy_bedrock_mantle,
    "mantle": _lazy_bedrock_mantle,
    "openai": OpenAIClient,
    "groq": GroqClient,
    "grok": GrokClient,
    "xai": GrokClient,
    "zai": ZaiClient,
    "z.ai": ZaiClient,
    "openrouter": OpenRouterClient,
    "nvidia": NvidiaClient,
    "moonshot": MoonshotClient,
    "kimi": MoonshotClient,
    "gemma4": _lazy_gemma4,
    "codex-agent": _lazy_openai_codex,
    "openai-codex": _lazy_openai_codex,
    "codex-code": _lazy_openai_codex,
}
```

#### PROVIDER_BACKEND (factory.py:155-158)
```python
PROVIDER_BACKEND: Dict[str, str] = {
    "bedrock": "bedrock",
    "anthropic-aws": "aws",
}
```

#### Meta_path Finder Pattern (parrot/tools/__init__.py:50-136)
```python
class _ParrotToolsRedirector(importlib.abc.MetaPathFinder):
    # Intercepts parrot.tools.<name> → parrot_tools.<name>
    # Uses _AliasLoader (line 31) to alias sys.modules entries
    # Synchronizes parrot_tools.* → parrot.tools.* in sys.modules
```

#### PEP 420 Pattern (ai-parrot-embeddings)
```
packages/ai-parrot-embeddings/src/parrot/          # NO __init__.py (only .gitkeep)
packages/ai-parrot-embeddings/src/parrot/stores/   # NO __init__.py (only .gitkeep)
packages/ai-parrot-embeddings/src/parrot/embeddings/  # NO __init__.py
# pyproject.toml:
[tool.setuptools.packages.find]
where = ["src"]
include = ["parrot*"]
namespaces = true
```

#### Existing Extras (pyproject.toml)
```toml
# Already exist — will be updated to include satellite packages:
openai = ["openai==3.3.1", "tiktoken==0.9.0"]          # line 527
groq = ["groq==0.33.0"]                                 # line 539
zai = ["zai-sdk>=0.2.3"]                                # line 543
llms = ["google-genai>=2.18.1", "openai==3.3.1", ...]   # line 547
claude-agent = ["claude-agent-sdk>=0.1.68"]              # line 516
codex-agent = ["openai-codex>=0.1.0", ...]               # line 520
google = ["google-genai>=2.18.1", ...]                   # line 532
```

#### Consumers of SUPPORTED_CLIENTS
```python
# parrot/server/ui/catalog.py:21 → _dedup_llm_providers()
# parrot/handlers/llm.py:14
# parrot/handlers/studio/catalog.py:25
# parrot/handlers/studio/byok.py:18
# parrot/advisors/mixin.py:145 (lazy import)
# parrot_pipelines/abstract.py:14
```

### Does NOT Exist (Anti-Hallucination)

- ~~`LLM_PROVIDERS`~~ — does not exist anywhere in the codebase. The concept
  is called `SUPPORTED_CLIENTS` in `factory.py`.
- ~~`parrot.clients.registry`~~ — no registry module exists; registration is
  purely static in `SUPPORTED_CLIENTS`.
- ~~`AbstractClient.__init_subclass__`~~ — no auto-registration metaclass or
  hook exists on `AbstractClient`.
- ~~`[project.entry-points]`~~ — no entry-point declarations exist in any
  current package's `pyproject.toml`.
- ~~`parrot/clients/vertexai.py`~~ — VertexAI is NOT a separate client file;
  it is handled inside `parrot/clients/google/client.py` via the
  `google-cloud-aiplatform` SDK.
- ~~`parrot/clients/openai.py`~~ — the OpenAI client file is named `gpt.py`,
  not `openai.py`.

---

## Parallelism Assessment

- **Internal parallelism**: **High**. Each satellite package is completely
  independent — different files, different `pyproject.toml`, different entry
  points. All 9 satellites can be scaffolded in parallel worktrees. The only
  serial dependency is the factory.py refactor (must land first so satellites
  have an entry-point group to register into).

- **Cross-feature independence**: The factory.py changes touch
  `SUPPORTED_CLIENTS` which is consumed by 6 other modules (listed above).
  However, the change is additive (discovery merges INTO the dict), so
  existing consumers work without modification. No conflicts with in-flight
  specs expected.

- **Recommended isolation**: **mixed** — the factory refactor + meta_path
  finder is one task in the main worktree. Each satellite package can be
  developed independently (even in parallel worktrees if desired, though
  sequential is fine given the mechanical nature of the scaffolding).

- **Rationale**: The factory refactor is the architectural core — it must be
  correct and tested before satellites make sense. But the satellite packages
  are purely mechanical (copy file, scaffold pyproject.toml, add entry point,
  verify import). After the factory task, the 9 satellites are embarrassingly
  parallel.

---

## Open Questions

- [ ] Should `GeminiLiveClient` (live.py, 1,776 lines) stay in core alongside the other Google clients, or move to its own satellite since it has specialized voice dependencies? — *Owner: Jesus*
- [ ] How should the `all` extra in root `pyproject.toml` be updated — should it transitively pull `ai-parrot[llms]` which pulls all satellites, or list each satellite explicitly? — *Owner: Jesus*
- [ ] Should we provide a `parrot.clients.discover()` public API that users can call to get a list of installed providers (useful for UIs, CLI help, etc.)? — *Owner: Jesus*
- [ ] For the meta_path fallback: should satellites have a top-level `parrot_llm_<provider>` package name (like `parrot_tools`) or rely purely on PEP 420 namespace contribution? — *Owner: Jesus*
- [x] How should `SUPPORTED_CLIENTS` / LLM_PROVIDERS work with dynamic discovery? — *Owner: Jesus*: Entry-point group `parrot.llm_providers`; factory discovers at first use via `importlib.metadata.entry_points()`, merges into the core-only static dict.
- [x] Which clients stay in core? — *Owner: Jesus*: Claude/Anthropic (+ ClaudeAgent), Google (GenAI + VertexAI + Live), Ollama/local (+ vLLM).
- [x] Naming convention? — *Owner: Jesus*: `ai-parrot-llm-{provider}`, one per provider.
- [x] Backward compatibility strategy? — *Owner: Jesus*: PEP 420 namespace primary, sys.meta_path fallback.
