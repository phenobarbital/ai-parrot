---
id: FC-001
query_id: Q010
type: grep
intent: "Inventory every literal gemini-2.5 id across the source and test trees of all distributions (the retirement blast radius)."
executed_at: 2026-11-04T01:39:51Z
duration_ms: 900
parent_id: null
depth: 0
---

# FC-001 — 65 files / 190 lines name a gemini-2.5 id; 32 of them are live `src/` sites

## Summary

Excluding `build/` and `node_modules/`, `gemini-2\.5` appears in 65 files (190 lines) under `packages/`. Live `src/` hits (non-test, non-UI) are ~45 lines across 22 files; the rest are tests (see FC-011) and the admin UI (ChatInput.svelte, regeneration-models.ts). The ids seen are `gemini-2.5-flash` (dominant), `gemini-2.5-pro`, `gemini-2.5-flash-lite`, plus media/voice variants (`-preview-tts`, `-flash-image`, `-native-audio-preview-*`, `-computer-use-preview-10-2025`). Several are *hardcoded defaults* (handlers, bots, loaders, image plugins, memory reflection, e2e budget), not merely docstring mentions.

## Citations

- path: `packages/ai-parrot-server/src/parrot/handlers/agents/abstract.py`
  lines: 182-182, 797-802
  symbol: `_use_model` / `resolve_component_llm("AGENT", builtin=...)`
  excerpt: |
    _use_model: Optional[str] = None  # None -> AGENT_LLM / DEFAULT_LLM / google:gemini-2.5-pro (FEAT-796)
    ...
    resolved = resolve_component_llm("AGENT", builtin="google:gemini-2.5-pro")
    ...
    model = self._use_model or ("gemini-2.5-pro" if llm == "google" else None)

- path: `packages/ai-parrot-server/src/parrot/handlers/google_generation.py`
  lines: 115-115
  symbol: `GoogleGenerationHandler.post`
  excerpt: |
    client = GoogleGenAIClient(model=data.get("model", "gemini-2.5-flash"))

- path: `packages/ai-parrot-server/src/parrot/autonomous/deploy/templates.py`
  lines: 188-199
  symbol: (deploy templates)
  excerpt: |
    llm="google:gemini-2.5-flash",

- path: `packages/ai-parrot-server/src/parrot/e2e/models.py`
  lines: 131-131
  symbol: `LiveBudget.model`
  excerpt: |
    model: str = "google:gemini-2.5-flash-lite"

- path: `packages/ai-parrot/src/parrot/loaders/abstract.py`
  lines: 984-1103
  symbol: `AbstractLoader` (summary/translation defaults)
  excerpt: |
    model="gemini-2.5-flash-lite",            # 984
    llm="google:gemini-2.5-flash-lite",       # 1012
    model="gemini-2.5-flash-lite",            # 1047
    translation_model = self.get_default_llm(model="gemini-2.5-flash-lite")  # 1103

- path: `packages/ai-parrot/src/parrot/interfaces/images/plugins/classifybase.py`
  lines: 26-26
  symbol: (image plugin ctor)
  excerpt: |
    self._model_name: str = kwargs.get("model_name", "gemini-2.5-flash")

- path: `packages/ai-parrot/src/parrot/interfaces/images/plugins/classify.py`
  lines: 55-55
  symbol: (image plugin ctor)
  excerpt: |
    self._model_name: str = kwargs.get("model_name", "gemini-2.5-flash")

- path: `packages/ai-parrot/src/parrot/interfaces/images/plugins/analisys.py`
  lines: 16-16
  symbol: (image plugin ctor)
  excerpt: |
    self._model_name: str = kwargs.get("model_name", "gemini-2.5-flash")

- path: `packages/ai-parrot/src/parrot/memory/episodic/reflection.py`
  lines: 94-94
  symbol: (reflection ctor)
  excerpt: |
    model: str = "gemini-2.5-flash",

- path: `packages/ai-parrot/src/parrot/setup/providers/google.py`
  lines: 16-16
  symbol: `default_model`
  excerpt: |
    default_model: str = "gemini-2.5-flash"

- path: `packages/ai-parrot/src/parrot/experts/policy.py`
  lines: 11-13
  symbol: `DEFAULT_TIER_POLICY`
  excerpt: |
    ExpertTier.JUDGMENT: {"provider": "google", "model": "gemini-2.5-pro", "temperature": 0.2},
    ExpertTier.BALANCED: {"provider": "google", "model": "gemini-2.5-flash", "temperature": 0.1},
    ExpertTier.TEMPLATED: {"provider": "google", "model": "gemini-2.5-flash", "temperature": 0.0},

- path: `packages/ai-parrot/src/parrot/knowledge/bookstore/_llm.py`
  lines: 6-6
  symbol: (module docstring)
  excerpt: |
    - ``PARROT_BOOKSTORE_LLM`` — heavy model, e.g. ``"google:gemini-2.5-flash"``

- path: `packages/ai-parrot-client-google/src/parrot/clients/google/analysis.py`
  lines: 914-914
  symbol: (analysis default)
  excerpt: |
    model="gemini-2.5-flash",

- path: `packages/ai-parrot-server/ui/src/lib/config/regeneration-models.ts`
  lines: 22-62
  symbol: `DEFAULT_MODEL`
  excerpt: |
    value: "google:gemini-2.5-flash",
    export const DEFAULT_MODEL = "google:gemini-2.5-flash";

- path: `packages/ai-parrot-server/ui/src/lib/components/agents/ChatInput.svelte`
  lines: 203-204
  symbol: (model picker options)
  excerpt: |
    { value: "google:gemini-2.5-flash", label: "Gemini 2.5 Flash" },
    { value: "google:gemini-2.5-pro", label: "Gemini 2.5 Pro" },

- path: `packages/parrot-formdesigner/scripts/calibrate_voice_postprocessors.py`
  lines: 6-6, 348-348
  symbol: (CLI help text)
  excerpt: |
    parser.add_argument("--llm", default=None, help="provider:model, e.g. google:gemini-2.5-flash")

- path: `packages/ai-parrot/src/parrot/clients/base.py`
  lines: 373-373, 2143-2143
  symbol: (comments only)
  excerpt: |
    # gemini-2.5-pro spent 1,011 on reasoning and finished cleanly at STOP.
    ``LLMFactory.create("google:gemini-2.5-pro")``). Substituting the cheap

## Notes

- Stale `packages/*/build/lib*/` copies also contain 2.5 ids (e.g. `conf.py` with `DEFAULT_LLM_MODEL_NAME fallback='gemini-2.5-pro'`); these are build artifacts, not source — ignore, but they explain why naive greps over-count.
- The bots/ hits are detailed in FC-006; the enum members in FC-003; tests in FC-011; UI files are a separate (TypeScript/Svelte) surface the request did not name.
- `[cross-lane: type=wiki_query, intent=confirm whether the admin UI model lists (regeneration-models.ts, ChatInput.svelte) are generated from the backend /models endpoint or hand-maintained]`
