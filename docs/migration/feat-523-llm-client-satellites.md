# Migration — FEAT-523: PEP 420 LLM Client Extraction

**Feature**: FEAT-523
**Status**: merged (target: next release after dev integration)
**Affects**: anyone installing or vendoring AI-Parrot, or importing
`parrot.clients.<provider>` directly.

## What changed

Every concrete LLM provider client moved from the `ai-parrot` core
distribution into its own sibling package, one per provider:

| Provider folder | Satellite distribution |
|---|---|
| `parrot.clients.openai` | `ai-parrot-client-openai` |
| `parrot.clients.meta` | `ai-parrot-client-meta` |
| `parrot.clients.anthropic` | `ai-parrot-client-anthropic` |
| `parrot.clients.amazon` | `ai-parrot-client-amazon` |
| `parrot.clients.google` | `ai-parrot-client-google` |
| `parrot.clients.gemma4` | `ai-parrot-client-gemma4` |
| `parrot.clients.hf` | `ai-parrot-client-hf` |
| `parrot.clients.groq` | `ai-parrot-client-groq` |
| `parrot.clients.grok` | `ai-parrot-client-grok` |
| `parrot.clients.zai` | `ai-parrot-client-zai` |
| `parrot.clients.nvidia` | `ai-parrot-client-nvidia` |
| `parrot.clients.moonshot` | `ai-parrot-client-moonshot` |
| `parrot.clients.openrouter` | `ai-parrot-client-openrouter` |
| `parrot.clients.local` | `ai-parrot-client-local` |
| `parrot.clients.vllm` | `ai-parrot-client-vllm` |

**Import paths are unchanged** — code such as
`from parrot.clients.anthropic import AnthropicClient` continues to work
without modification, but you must now install the relevant satellite
alongside `ai-parrot`.

The move uses **PEP 420 implicit namespace packages** (same pattern as
FEAT-201's `ai-parrot-embeddings`): each satellite ships no `__init__.py`
at the `parrot`/`parrot.clients` namespace levels, so Python merges every
installed distribution's directory automatically.

`LLMFactory` no longer knows about any provider by name. Each satellite
declares a `[project.entry-points."parrot.clients"]` table mapping its
provider key(s) to its client class; `LLMFactory._discover()` reads
`importlib.metadata.entry_points(group="parrot.clients")` to populate
`SUPPORTED_CLIENTS` lazily, on first use — with zero satellites
installed, `LLMFactory.list_providers()` returns `{}` and
`LLMFactory.create(...)` raises `ImportError` naming the satellite to
install, instead of silently failing or (previously) falling back to an
in-core implementation.

## Install command mapping

| Old | New |
|---|---|
| `pip install ai-parrot[anthropic]` | `pip install ai-parrot[anthropic]` (extra now installs `ai-parrot-client-anthropic`, unchanged command) |
| `pip install ai-parrot[bedrock]` | `pip install ai-parrot[bedrock]` (unchanged command; now installs `ai-parrot-client-anthropic`) |
| `pip install ai-parrot[bedrock-native]` | `pip install ai-parrot[bedrock-native]` (unchanged command; now installs `ai-parrot-client-amazon`) |
| `pip install ai-parrot[claude-agent]` | `pip install ai-parrot[claude-agent]` (unchanged command; now installs `ai-parrot-client-anthropic`) |
| `pip install ai-parrot[codex-agent]` | `pip install ai-parrot[codex-agent]` (unchanged command; now installs `ai-parrot-client-openai[bridge]`) |
| `pip install ai-parrot[openai]` | `pip install ai-parrot[openai]` (unchanged command; `openai==3.3.1` is now a base `ai-parrot` dependency — `OpenAIBaseClient` stays in core and is subclassed by 7 satellites) |
| `pip install ai-parrot[google]` | `pip install ai-parrot[google]` (unchanged command; now installs `ai-parrot-client-google` alongside the pre-existing `google-api-python-client`/`google-cloud-texttospeech`/`google-cloud-aiplatform` pins, which back unrelated core Google integrations, not the LLM client) |
| `pip install ai-parrot[groq]` / `[zai]` / `[xai]` | unchanged commands; now install the matching satellite |
| `pip install ai-parrot[llms]` | unchanged command — now installs all 15 satellites listed above instead of raw SDK pins |
| *(new)* | `pip install ai-parrot[grok]`, `[gemma4]`, `[hf]`, `[nvidia]`, `[moonshot]`, `[openrouter]`, `[local]`, `[vllm]`, `[meta]` — providers that previously had no dedicated core extra now each have one |

Each satellite can also be installed directly, independent of `ai-parrot`'s
own extras, e.g. `pip install ai-parrot ai-parrot-client-groq`.

## Code changes required

**None for import paths.** `from parrot.clients.<provider> import
<ClassName>` continues to work exactly as before, for every provider
listed above.

**If you called internal `factory.py` names directly** (not part of the
public API, but used by some tests before this feature): the
hand-written `_lazy_*` closures (`_lazy_claude_agent`, `_lazy_gemma4`,
`_lazy_bedrock_converse`, `_lazy_nova`, `_lazy_bedrock_mantle`,
`_lazy_openai_codex`) and the transitional `_IN_CORE_PROVIDERS` tuple no
longer exist — `SUPPORTED_CLIENTS` values are now always either a real
client class or an entry point's zero-arg loader
(`EntryPoint.load`), resolved the same way `LLMFactory.create()` always
has: `cls() if callable(cls) and not isinstance(cls, type) else cls`.

## What did NOT change

- Every public `LLMFactory` method (`create`, `parse_llm_string`) keeps
  its exact signature and behavior.
- `LLMFactory.list_providers()` / `LLMFactory.list_models()` (added in
  TASK-2847) are unaffected by this task beyond no longer ever returning
  `"ai-parrot"` as a distribution name (the transitional in-core registry
  that used that label is gone).
- `parrot.clients.factory.PROVIDER_BACKEND` (the AWS `backend=` injection
  table for `AnthropicClient`) is unchanged.
- `OpenAIBaseClient` (`parrot/clients/openai_base.py`) stays in core, as
  does `AbstractClient` (`parrot/clients/base.py`).

## See also

- `sdd/specs/pep-420-llm-clients.spec.md` — the full spec this migration
  implements.
- `docs/migration/feat-201-ai-parrot-embeddings.md` — the earlier,
  structurally identical satellite-extraction migration for embeddings.
