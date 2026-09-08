---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: PEP 420 LLM Client Extraction

**Date**: 2026-09-04
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: Option A

---

## Problem Statement

The core `ai-parrot` package bundles **all 20+ LLM client modules** (~34,700
lines, 3 MB of source) in `parrot/clients/`, alongside their SDK dependencies
(`anthropic`, `openai`, `google-genai`, `groq`, `aioboto3`, `xai-sdk`,
`zai-sdk`, `claude-agent-sdk`, …).

This causes three concrete pain points:

1. **Dependency bloat**: installing `ai-parrot` for one provider (e.g.
   Anthropic) still makes available the import machinery for every other
   provider. The `[llms]` extra already gates the *SDK* installs, but the
   *client code* — 34K lines of it — ships in every wheel.

2. **SDK version conflicts**: providers ship breaking SDK changes at different
   cadences. Pinning `openai==3.3.1` in the core package means every
   downstream consumer inherits that pin, even if they only use Claude.

3. **Third-party extensibility barrier**: adding a new provider requires a PR
   to the core package. There is no plugin mechanism for client contributions
   beyond manually registering in `factory.py`'s `SUPPORTED_CLIENTS` dict.

**Who is affected**: downstream application developers who install `ai-parrot`
as a dependency, CI pipelines that pull heavy SDK trees, and community
contributors wanting to add new LLM providers.

**Why now**: the client roster keeps growing — Grok/xAI, Moonshot/Kimi, NVIDIA
NIM, BedrockMantle, OpenAI Codex, and Gemma4 were all added in the last 6
months. The `ai-parrot-embeddings` refactor (FEAT-201) already proved the
PEP 420 satellite pattern works well. Applying the same pattern to LLM
clients is the natural next step.

## Constraints & Requirements

- **Zero breaking changes**: `from parrot.clients.claude import AnthropicClient`
  (and equivalent for every provider) MUST continue to work when the satellite
  is installed. PEP 420 namespace merging provides this natively; a
  `sys.meta_path` finder acts as a fallback.
- **OpenAI client stays in core**: as the reference implementation and base
  class for many OpenAI-compatible providers (`OpenAIBaseClient`). `OpenAIClient`
  (gpt.py) stays alongside `OpenAIBaseClient` (openai_base.py) in core.
- **`ai-parrot[llms]` meta-extra preserved**: the existing
  `pip install ai-parrot[llms]` must install all client packages (rewritten
  to pull satellite package dependencies).
- **Family-based grouping**: clients sharing the same SDK dependency family
  ship in the same satellite package (e.g. all Google clients share
  `google-genai`, all Amazon clients share `aioboto3`).
- **Dual discovery**: client registration via
  `[project.entry-points."parrot.clients"]` in `pyproject.toml` (primary),
  with a `sys.meta_path` finder as fallback for import-path compatibility.
- **uv workspace**: all new packages live under `packages/` and are declared
  as workspace members in the root `pyproject.toml`.

---

## Options Explored

### Option A: Family-Based Satellite Packages + Dual Discovery

Extract clients into **~9 satellite packages** grouped by SDK dependency
family, plus a handful of standalone single-provider packages.

**Satellite packages:**

| Package | Clients Moved | SDK Dependencies | ~Lines |
|---|---|---|---|
| **Core** (`ai-parrot`) | `AbstractClient`, `OpenAIBaseClient`, `OpenAIClient`, `OpenRouterClient`, `MoonshotClient`, `LLMFactory` | `openai` | stays |
| `ai-parrot-client-anthropic` | `AnthropicClient` (claude.py), `ClaudeAgentClient` (claude_agent.py), `ClaudeAgentBridge` (claude_agent_bridge.py), `anthropic_backends.py` | `anthropic[aiohttp]`, `claude-agent-sdk` | ~5,100 |
| `ai-parrot-client-google` | `GoogleGenAIClient` (google/), `Gemma4Client` (gemma4.py), `GeminiLiveClient` (live.py) | `google-genai`, `google-api-python-client`, `google-cloud-texttospeech` | ~16,000 |
| `ai-parrot-client-amazon` | `BedrockConverseClient` (bedrock.py), Nova clients (nova/), `BedrockMantleClient` (nova/mantle.py) | `aioboto3`, `anthropic[aiohttp,aws]` | ~4,400 |
| `ai-parrot-client-groq` | `GroqClient` (groq.py) | `groq` | ~1,500 |
| `ai-parrot-client-grok` | `GrokClient` (grok.py) | `xai-sdk` | ~800 |
| `ai-parrot-client-zai` | `ZaiClient` (zai.py) | `zai-sdk` | ~1,100 |
| `ai-parrot-client-nvidia` | `NvidiaClient` (nvidia.py) | (none — uses `openai`) | ~700 |
| `ai-parrot-client-local` | `LocalLLMClient` (localllm.py), `vLLMClient` (vllm.py) | (none — uses `openai`) | ~900 |
| `ai-parrot-client-hf` | `TransformersClient` (hf.py) | `transformers`, `sentence-transformers` | ~650 |

**What stays in core:**
- `AbstractClient` (base.py) — the abstract base class
- `OpenAIBaseClient` (openai_base.py) — shared base for OpenAI-compatible clients
- `OpenAIClient` (gpt.py) — the reference implementation
- `OpenRouterClient` (openrouter.py, 6.8K) — thin wrapper, no new SDK
- `MoonshotClient` (moonshot.py, 15.4K) — thin wrapper, no new SDK
- `LLMFactory` (factory.py) — refactored with entry-point discovery
- `models.py`, `protocols.py` — shared types

**Discovery mechanism:**

Each satellite declares entry points in `pyproject.toml`:
```toml
# ai-parrot-client-anthropic/pyproject.toml
[project.entry-points."parrot.clients"]
claude = "parrot.clients.claude:AnthropicClient"
anthropic = "parrot.clients.claude:AnthropicClient"
claude-agent = "parrot.clients.claude_agent:ClaudeAgentClient"
```

`LLMFactory` discovers them via:
```python
# At first use (lazy, cached)
from importlib.metadata import entry_points
eps = entry_points(group="parrot.clients")
for ep in eps:
    SUPPORTED_CLIENTS[ep.name] = ep  # lazy — ep.load() on first use
```

A `_ParrotClientsRedirector` MetaPathFinder (modeled on
`_ParrotToolsRedirector`) provides import-path backward compatibility.

✅ **Pros:**
- Matches SDK dependency boundaries — install only the SDKs you need
- ~9 packages is manageable (vs. 12–15 for fully granular)
- Natural grouping: Google family shares `google-genai`, Amazon family
  shares `aioboto3`, Anthropic family shares `anthropic`
- Follows the proven `ai-parrot-embeddings` (FEAT-201) migration pattern
- Core package drops from 3 MB to ~600 KB of client code
- Third parties can add providers by publishing their own
  `ai-parrot-client-<provider>` package with an entry point
- Independent versioning per family

❌ **Cons:**
- 9 new packages to maintain (pyproject.toml, CI, releases)
- uv workspace grows from 12 to ~21 members
- Cross-family dependencies need care (e.g., Amazon Bedrock uses
  `anthropic[aws]` — pins `anthropic` independently from
  `ai-parrot-client-anthropic`)
- `LLMFactory` needs rewrite to support dynamic discovery
- Entry-point discovery adds ~5–10ms at first factory call (one-time)

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `importlib.metadata` | Entry-point discovery | stdlib, Python 3.11+ |
| `setuptools` | Build backend for satellites | existing build system |
| PEP 420 | Implicit namespace packages | no runtime dependency |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot-embeddings/` — complete PEP 420 satellite template
  (directory structure, pyproject.toml, workspace integration)
- `parrot/tools/__init__.py:50-136` — `_ParrotToolsRedirector` MetaPathFinder
  pattern (the template for `_ParrotClientsRedirector`)
- `parrot/clients/factory.py` — `LLMFactory` and `SUPPORTED_CLIENTS` dict
  to refactor

---

### Option B: Single Satellite Package (ai-parrot-clients)

Move ALL non-core client implementations into one `ai-parrot-clients`
satellite package, with per-provider optional extras.

```
packages/ai-parrot-clients/src/parrot/clients/
├── claude.py
├── google/
├── bedrock.py
├── groq.py
├── ...
```

Install: `pip install ai-parrot-clients[claude,google]`

✅ **Pros:**
- Simplest to maintain — one package, one release cycle
- Still achieves dependency isolation via per-provider extras
- `LLMFactory` can remain simpler (one import source)
- Lowest migration effort

❌ **Cons:**
- All client *code* still ships together (even if SDKs are optional)
- No independent versioning per provider — a Google-specific breaking
  change forces a version bump that affects Anthropic users
- Third-party providers would need to contribute to this one package
  (same friction as today, just moved)
- Doesn't match the user's stated goal of family-based packages

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| PEP 420 | Implicit namespace | same as Option A |
| `importlib.metadata` | Entry-point discovery | optional, could skip |

🔗 **Existing Code to Reuse:**
- Same as Option A, but simpler — one `pyproject.toml` with many extras

---

### Option C: Fully Granular — One Package Per Client Module

Every client file becomes its own package: `ai-parrot-client-claude`,
`ai-parrot-client-claude-agent`, `ai-parrot-client-google`,
`ai-parrot-client-gemma4`, `ai-parrot-client-live`,
`ai-parrot-client-groq`, `ai-parrot-client-grok`,
`ai-parrot-client-bedrock`, `ai-parrot-client-nova`,
`ai-parrot-client-mantle`, `ai-parrot-client-nvidia`,
`ai-parrot-client-zai`, `ai-parrot-client-hf`,
`ai-parrot-client-ollama`, `ai-parrot-client-vllm`,
`ai-parrot-client-codex` — ~15–17 packages total.

✅ **Pros:**
- Maximum isolation — each provider has its own version, release cycle
- Absolute minimum install for any given provider
- Third parties are on equal footing with built-in providers

❌ **Cons:**
- **Maintenance burden**: 15+ packages × (pyproject.toml + CI matrix +
  changelog + release) = significant overhead for a small team
- Packages sharing an SDK (Google family) duplicate the dep declaration
  or need inter-package dependencies
- `ai-parrot-client-gemma4` depends on `google-genai` just like
  `ai-parrot-client-google` — no real isolation gained by separating them
- Thin wrappers like `BedrockMantleClient` (200 lines) don't justify
  their own package

📊 **Effort:** Very High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| Same as A | Entry points + PEP 420 | More packages to declare |

🔗 **Existing Code to Reuse:**
- Same as Option A

---

## Recommendation

**Option A (Family-Based Satellite Packages)** is recommended because:

1. **Matches SDK dependency boundaries**: the grouping criterion is "which
   SDK do these clients share?" — Google clients share `google-genai`,
   Amazon clients share `aioboto3`, Anthropic clients share `anthropic`.
   Splitting within a family gains nothing: `Gemma4Client` and
   `GoogleGenAIClient` both require the same SDK.

2. **Manageable scope**: 9 new packages is a meaningful increase but stays
   well within what the existing workspace infrastructure supports (12
   packages today → ~21). Each package has a clear owner and boundary.

3. **Proven pattern**: `ai-parrot-embeddings` (FEAT-201) already demonstrated
   the PEP 420 migration path with zero breaking changes. The
   `_ParrotToolsRedirector` MetaPathFinder in `parrot/tools/__init__.py`
   is the exact template for import-path backward compatibility.

4. **Dual discovery for extensibility**: the `importlib.metadata` entry-point
   group (`parrot.clients`) allows third parties to publish
   `ai-parrot-client-<provider>` packages that are automatically discovered
   by `LLMFactory` — no PR to core required. The `sys.meta_path` fallback
   guarantees import-path compatibility.

The tradeoff is **higher initial migration effort** (9 new `pyproject.toml`
files, CI matrix updates, the `LLMFactory` refactor) vs. Option B's
simplicity. But Option B doesn't solve the "install only what you need"
goal at the code level or enable independent versioning per family.

---

## Feature Description

### User-Facing Behavior

**Before** (current state):
```bash
pip install ai-parrot         # gets ALL client code (3 MB)
pip install ai-parrot[llms]   # gates only SDK installs
```

**After** (this feature):
```bash
pip install ai-parrot                       # AbstractClient + OpenAI ref only
pip install ai-parrot-client-anthropic      # Claude + ClaudeAgent
pip install ai-parrot-client-google         # Google GenAI + Gemma4 + Live
pip install ai-parrot-client-amazon         # Bedrock + Nova + Mantle
pip install ai-parrot[llms]                 # meta-extra → all client packages
pip install ai-parrot[claude]               # alias → ai-parrot-client-anthropic
```

Import paths are **unchanged** — code that does
`from parrot.clients.claude import AnthropicClient` continues to work
via PEP 420 namespace merging and the MetaPathFinder fallback.

`LLMFactory.create("claude:claude-sonnet-4-20250514")` continues to work —
the factory discovers `AnthropicClient` via the `parrot.clients` entry-point
group at import time.

### Internal Behavior

1. **Build time**: each satellite declares
   `[project.entry-points."parrot.clients"]` in its `pyproject.toml`:
   ```toml
   [project.entry-points."parrot.clients"]
   claude = "parrot.clients.claude:AnthropicClient"
   anthropic = "parrot.clients.claude:AnthropicClient"
   claude-agent = "parrot.clients.claude_agent:ClaudeAgentClient"
   ```

2. **Import time**: `parrot/clients/__init__.py` installs a
   `_ParrotClientsRedirector` (modeled on `_ParrotToolsRedirector`) that
   redirects `parrot.clients.<x>` to the satellite's namespace-merged
   module when the standard namespace merge doesn't resolve it.

3. **Factory time**: `LLMFactory.create()` loads `SUPPORTED_CLIENTS` via
   `importlib.metadata.entry_points(group="parrot.clients")` at first use
   (lazy, cached). Core-shipped clients (OpenAI, OpenRouter, Moonshot)
   remain eagerly imported as today. Satellite clients are lazy-loaded
   via entry-point callables — `ep.load()` is called only on first use
   of that provider key.

4. **Fallback**: if a client name is not in `SUPPORTED_CLIENTS` (neither
   core nor entry-point-discovered), the factory raises `ValueError` with
   an actionable message listing available providers and suggesting
   `pip install ai-parrot-client-<provider>`.

### Edge Cases & Error Handling

- **Missing satellite**: `LLMFactory.create("claude:...")` when
  `ai-parrot-client-anthropic` is not installed → clear `ImportError`:
  `"AnthropicClient requires package 'ai-parrot-client-anthropic'. Install
  with: pip install ai-parrot-client-anthropic (or pip install ai-parrot[claude])"`
- **SDK missing but package installed**: satellite is installed but its
  SDK dependency is not (editable install without extras) → the existing
  `ImportError` from the SDK itself propagates, wrapped with a hint.
- **Version mismatch**: satellite depends on `ai-parrot>=X.Y` but an older
  core is installed → pip's dependency resolver catches this at install time.
- **Duplicate registration**: two packages declare the same entry-point
  key → first one wins (deterministic per `importlib.metadata` ordering),
  logged as a warning.
- **`SUPPORTED_CLIENTS` merge**: core-shipped clients take precedence over
  entry-point-discovered ones. An entry point that shadows a core client
  logs a warning and is skipped.
- **`PROVIDER_BACKEND` mapping**: stays in core `factory.py` — it only
  applies to `AnthropicClient` backends and will need to handle the case
  where `AnthropicClient` is not yet imported (lazy via entry point).
- **Editable installs (uv workspace dev mode)**: PEP 420 namespace merging
  works with `uv pip install -e` because `uv` sets up `.pth` files. The
  MetaPathFinder is a safety net.
- **Circular import risk**: none — satellites import FROM core (base classes),
  core never imports FROM satellites (discovery is metadata-only until load).

---

## Capabilities

### New Capabilities
- `pep-420-client-extraction`: extract LLM clients into PEP 420 satellite
  packages grouped by SDK family
- `client-entry-point-discovery`: `importlib.metadata` entry-point-based
  client auto-discovery in `LLMFactory`
- `client-metapath-finder`: `sys.meta_path` finder for backward-compatible
  import-path resolution of satellite client modules

### Modified Capabilities
- `llm-factory`: refactored to merge core `SUPPORTED_CLIENTS` with
  entry-point-discovered clients
- `ai-parrot-extras`: `[llms]`, `[claude]`, `[google]`, `[bedrock]`,
  `[groq]` extras rewritten to pull satellite package dependencies

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/clients/__init__.py` | modifies | Add `_ParrotClientsRedirector` MetaPathFinder |
| `parrot/clients/factory.py` | modifies | Merge entry-point discovery into `SUPPORTED_CLIENTS` |
| `pyproject.toml` (core) | modifies | Rewrite extras, remove extracted client deps |
| `pyproject.toml` (root) | modifies | Add new workspace members |
| `packages/ai-parrot-client-*` | new | 9 new satellite packages |
| `parrot/server/ui/catalog.py` | verifies | `_dedup_llm_providers()` uses `SUPPORTED_CLIENTS` |
| `parrot/handlers/llm.py` | verifies | Uses `SUPPORTED_CLIENTS` — should work after discovery |
| `parrot/handlers/studio/catalog.py` | verifies | Same as above |
| `parrot/handlers/studio/byok.py` | verifies | Same as above |
| `parrot/advisors/mixin.py` | verifies | Lazy imports `SUPPORTED_CLIENTS` |
| `parrot_pipelines/abstract.py` | verifies | Uses `SUPPORTED_CLIENTS` for validation |
| CI/CD | extends | Build matrix for satellite packages |
| Docs | extends | Installation guide update |

---

## Code Context

### User-Provided Code

No code snippets provided by the user during discovery.

### Verified Codebase References

#### Client Hierarchy
```python
# From packages/ai-parrot/src/parrot/clients/base.py:230
class AbstractClient(EventEmitterMixin, ABC):
    ...

# From packages/ai-parrot/src/parrot/clients/openai_base.py:59
class OpenAIBaseClient(AbstractClient):
    ...

# From packages/ai-parrot/src/parrot/clients/gpt.py:81
class OpenAIClient(OpenAIBaseClient):
    ...
```

#### All Concrete Client Classes
```python
# CORE (stays):
# packages/ai-parrot/src/parrot/clients/gpt.py:81
class OpenAIClient(OpenAIBaseClient):        # reference implementation

# packages/ai-parrot/src/parrot/clients/openrouter.py:26
class OpenRouterClient(OpenAIBaseClient):     # thin wrapper, stays

# packages/ai-parrot/src/parrot/clients/moonshot.py:74
class MoonshotClient(OpenAIBaseClient):       # thin wrapper, stays

# ANTHROPIC FAMILY (→ ai-parrot-client-anthropic):
# packages/ai-parrot/src/parrot/clients/claude.py:69
class AnthropicClient(AbstractClient):

# packages/ai-parrot/src/parrot/clients/claude_agent.py:265
class ClaudeAgentClient(AbstractClient):

# packages/ai-parrot/src/parrot/clients/claude_agent_bridge.py (bridge)
# packages/ai-parrot/src/parrot/clients/anthropic_backends.py (backend selection)

# GOOGLE FAMILY (→ ai-parrot-client-google):
# packages/ai-parrot/src/parrot/clients/google/client.py:95
class GoogleGenAIClient(AbstractClient, GoogleGeneration, GoogleAnalysis):

# packages/ai-parrot/src/parrot/clients/gemma4.py:48
class Gemma4Client(AbstractClient):

# packages/ai-parrot/src/parrot/clients/live.py:498
class GeminiLiveClient(AbstractClient):

# AMAZON FAMILY (→ ai-parrot-client-amazon):
# packages/ai-parrot/src/parrot/clients/bedrock.py:138
class BedrockConverseBase(AbstractClient):

# packages/ai-parrot/src/parrot/clients/bedrock.py:1647
class BedrockConverseClient(BedrockConverseBase):

# packages/ai-parrot/src/parrot/clients/nova/ (client.py, audio.py, generation.py, mantle.py)

# STANDALONE (→ individual packages):
# packages/ai-parrot/src/parrot/clients/groq.py:50
class GroqClient(OpenAIBaseClient):

# packages/ai-parrot/src/parrot/clients/grok.py:53
class GrokClient(AbstractClient):

# packages/ai-parrot/src/parrot/clients/zai.py:22
class ZaiClient(OpenAIBaseClient):

# packages/ai-parrot/src/parrot/clients/nvidia.py:222
class NvidiaClient(OpenAIBaseClient):

# packages/ai-parrot/src/parrot/clients/localllm.py:26
class LocalLLMClient(OpenAIBaseClient):

# packages/ai-parrot/src/parrot/clients/vllm.py:52
class vLLMClient(LocalLLMClient):

# packages/ai-parrot/src/parrot/clients/hf.py:53
class TransformersClient(AbstractClient):

# packages/ai-parrot/src/parrot/clients/codex_agent.py:69
class OpenAICodexClient(AbstractClient):
```

#### Factory and Registration
```python
# From packages/ai-parrot/src/parrot/clients/factory.py (SUPPORTED_CLIENTS, line ~107)
SUPPORTED_CLIENTS = {
    "claude": AnthropicClient,
    "anthropic": AnthropicClient,
    "bedrock": AnthropicClient,         # FEAT-232 backend injection
    "anthropic-aws": AnthropicClient,
    "bedrock-converse": _lazy_bedrock_converse,
    "nova": _lazy_nova,
    "bedrock-mantle": _lazy_bedrock_mantle,
    "mantle": _lazy_bedrock_mantle,
    "google": GoogleGenAIClient,
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
    "local": LocalLLMClient,
    "localllm": LocalLLMClient,
    "ollama": LocalLLMClient,
    "vllm": vLLMClient,
    "llamacpp": LocalLLMClient,
    "gemma4": _lazy_gemma4,
    "claude-agent": _lazy_claude_agent,
    "claude-code": _lazy_claude_agent,
    "codex-agent": _lazy_openai_codex,
    "openai-codex": _lazy_openai_codex,
    "codex-code": _lazy_openai_codex,
}

PROVIDER_BACKEND: Dict[str, str] = {   # line ~155
    "bedrock": "bedrock",
    "anthropic-aws": "aws",
}

class LLMFactory:                        # line ~161
    @staticmethod
    def parse_llm_string(llm: str) -> Tuple[str, Optional[str]]:  # line 171
    @staticmethod
    def create(llm: str, model_args=None, tool_manager=None, **kwargs) -> AbstractClient:  # line 193
```

#### MetaPathFinder Pattern (existing reference)
```python
# From packages/ai-parrot/src/parrot/tools/__init__.py:50-136
class _ParrotToolsRedirector(importlib.abc.MetaPathFinder):
    _PREFIX = "parrot.tools."
    _RESOLVING: set = set()
    _loader = _AliasLoader()

    def find_spec(self, fullname, path, target=None):
        # Redirects parrot.tools.<x> → parrot_tools.<x> → plugins.tools.<x>
        # Guards: skips core submodules, prevents recursion
        # Synchronizes all parrot_tools.* aliases in sys.modules
        ...
```

#### PEP 420 Pattern (ai-parrot-embeddings reference)
```
packages/ai-parrot-embeddings/src/parrot/          # NO __init__.py (PEP 420)
packages/ai-parrot-embeddings/src/parrot/stores/   # has .gitkeep, no __init__.py
packages/ai-parrot-embeddings/src/parrot/embeddings/  # has .gitkeep, no __init__.py
```
```toml
# packages/ai-parrot-embeddings/pyproject.toml
[build-system]
requires = ["setuptools>=77.0.0", "wheel>=0.44.0"]

[project]
name = "ai-parrot-embeddings"
dependencies = ["ai-parrot"]

[tool.setuptools.packages.find]
where = ["src"]
include = ["parrot*"]
namespaces = true
```

#### Google Client Subpackage
```
packages/ai-parrot/src/parrot/clients/google/
├── __init__.py  (177B)
├── analysis.py  (76.7K)
├── client.py    (278.2K) — GoogleGenAIClient
└── generation.py (111.5K)
```

#### Nova Client Subpackage
```
packages/ai-parrot/src/parrot/clients/nova/
├── __init__.py   (351B)
├── audio.py      (61.6K)
├── client.py     (8.5K)
├── generation.py (15.4K)
└── mantle.py     (5.6K)
```

#### Existing Extras in Core pyproject.toml
```toml
anthropic = ["anthropic[aiohttp]>=0.109.0,<1.0.0"]
bedrock = ["anthropic[aiohttp,aws]>=0.109.0,<1.0.0"]
claude-agent = ["claude-agent-sdk>=0.1.68"]
openai = ["openai==3.3.1", "tiktoken==0.9.0"]
google = ["google-api-python-client>=2.166.0,<=2.177.0",
          "google-cloud-texttospeech==2.27.0", "google-genai>=2.18.1"]
groq = ["groq==0.33.0"]
llms = ["google-genai>=2.18.1", "openai==3.3.1", "groq==0.33.0",
        "ai-parrot[anthropic,bedrock]", "claude-agent-sdk>=0.1.68",
        "xai-sdk>=1.12.0", "zai-sdk>=0.2.3"]
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

#### __init__.py Exports (stays in core)
```python
# From packages/ai-parrot/src/parrot/clients/__init__.py
from .base import LLM_PRESETS, AbstractClient, StreamingRetryConfig
from .openai_base import OpenAIBaseClient
from .zai import ZaiClient  # TODO: will move to satellite
```

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.clients.registry`~~ — no client registry module exists;
  registration is purely static in `SUPPORTED_CLIENTS`
- ~~`[project.entry-points."parrot.clients"]`~~ — no entry points are
  used for client discovery anywhere in the project today
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
  NOT use entry points today; it relies solely on PEP 420 namespace merging

---

## Parallelism Assessment

- **Internal parallelism**: **High**. Each satellite package is completely
  independent — different files, different `pyproject.toml`, different entry
  points. All 9 satellites can be scaffolded in parallel worktrees. The only
  serial dependency is the `factory.py` + `__init__.py` refactor (must land
  first so satellites have an entry-point group to register into and a
  MetaPathFinder to fall back on).

- **Cross-feature independence**: The factory.py changes touch
  `SUPPORTED_CLIENTS` which is consumed by 6 other modules (listed above).
  However, the change is additive (discovery merges INTO the dict), so
  existing consumers work without modification. No conflicts with in-flight
  specs expected.

- **Recommended isolation**: **mixed** — the factory refactor + MetaPathFinder
  is one sequential task in the main worktree. Each satellite package can be
  developed in parallel worktrees (the scaffolding is mechanical: move file,
  create pyproject.toml, add entry point, verify import).

- **Rationale**: The factory refactor is the architectural core — it must be
  correct and tested before satellites make sense. But the satellite packages
  are purely mechanical (copy file, scaffold pyproject.toml, add entry point,
  verify import). After the factory task, the 9 satellites are embarrassingly
  parallel.

---

## Open Questions

- [ ] Where does `OpenAICodexClient` (codex_agent.py + codex_tool_bridge.py) go — into `ai-parrot-client-anthropic` (it's a code-agent tool), its own `ai-parrot-client-codex`, or stays in core? — *Owner: Jesus*
- [ ] Should `PROVIDER_BACKEND` (bedrock/anthropic-aws backend injection) move to `ai-parrot-client-anthropic` or stay in core's `LLMFactory`? If it stays in core, the factory needs to handle the case where `AnthropicClient` is an unresolved entry point — *Owner: Jesus*
- [ ] What's the versioning strategy for satellite packages — lock-step with core (`ai-parrot`), or independent semver? — *Owner: Jesus*
- [ ] Should the `ZaiClient` import in `parrot/clients/__init__.py` be removed or replaced with a lazy import when `zai` moves to a satellite? — *Owner: Jesus*
- [ ] Should we provide a `LLMFactory.list_providers()` public API that returns installed+available providers (useful for UIs, CLI help)? — *Owner: Jesus*
- [ ] How should the `all` extra in root `pyproject.toml` be updated — should it transitively pull `ai-parrot[llms]` (which pulls all satellites), or list each satellite explicitly? — *Owner: Jesus*
