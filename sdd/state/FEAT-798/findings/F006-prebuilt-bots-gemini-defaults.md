---
id: F006
query_id: Q015
type: grep
intent: "Pre-built agents in parrot.bots: every hardcoded llm= / model= / 'google:' default (the 'agentes pre-hechos' the request names)."
executed_at: 2026-11-04T01:39:51Z
duration_ms: 800
parent_id: null
depth: 0
---

# F006 — Seven parrot.bots sites pin a 2.5 id; the other pre-built bots already sit on 3.x ids; parrot/agents/ has none

## Summary

Under `packages/ai-parrot/src/parrot/bots/` the 2.5 ids appear in: `base.py:493-495` (hard fallback `gemini-2.5-flash` for Google clients when no model is given), `flows/crew/crew.py:121` (`_CREW_BUILTIN_LLM = "google:gemini-2.5-pro"`, resolved through FEAT-796), `voice.py:438` (text LLM default `gemini-2.5-flash`), `scraper/scraper.py:98` (last-resort `gemini-2.5-flash`), `mixins/model_switching.py:30` (docstring example), `abstract.py:968` (docstring example), and the `factory/builders/{rag,tool_agent}_builder.py` LLM prompts (lines 29/31) that instruct the builder LLM to default to `gemini-2.5-flash`. Already-migrated pre-built bots: `search.py:71` (`google:gemini-3-flash`), `jira_specialist.py:210` (`gemini-3.5-flash`), `github_reviewer.py:583` (`gemini-3.7-flash`), `flows/agents/a2a_orchestrator.py:174` (`gemini-3.1-flash-lite-preview`), `flows/result_agent.py` (inherits `GEMINI_FLASH_LATEST`). `packages/ai-parrot/src/parrot/agents/` exists but has zero Gemini id references.

## Citations

- path: `packages/ai-parrot/src/parrot/bots/base.py`
  lines: 487-495
  symbol: `BasicBot` (model fallback in the ask path)
  excerpt: |
    # Ensure model is set, falling back to client default if needed
    try:
        if not kwargs.get("model"):
            if hasattr(llm, "default_model") and llm.default_model:
                kwargs["model"] = llm.default_model
            elif llm.client_type == "google":
                kwargs["model"] = "gemini-2.5-flash"
    except Exception:
        kwargs["model"] = "gemini-2.5-flash"

- path: `packages/ai-parrot/src/parrot/bots/flows/crew/crew.py`
  lines: 121-135
  symbol: `_CREW_BUILTIN_LLM` / `_build_crew_client`
  excerpt: |
    _CREW_BUILTIN_LLM = "google:gemini-2.5-pro"
    ...
    resolved = resolve_component_llm("CREW", builtin=_CREW_BUILTIN_LLM)

- path: `packages/ai-parrot/src/parrot/bots/voice.py`
  lines: 437-438
  symbol: (VoiceBot text LLM)
  excerpt: |
    text_llm = GoogleGenAIClient(
        model=kwargs.get("model", "gemini-2.5-flash"),

- path: `packages/ai-parrot/src/parrot/bots/scraper/scraper.py`
  lines: 94-99
  symbol: (scraper model resolution)
  excerpt: |
    model: str = (
        self._model
        or getattr(client, "model", None)
        or getattr(client, "default_model", None)
        or "gemini-2.5-flash"
    )

- path: `packages/ai-parrot/src/parrot/bots/factory/builders/rag_builder.py`
  lines: 29-29
  symbol: (builder prompt)
  excerpt: |
    - Default model: provider=`google`, model=`gemini-2.5-flash`,

- path: `packages/ai-parrot/src/parrot/bots/factory/builders/tool_agent_builder.py`
  lines: 31-31
  symbol: (builder prompt)
  excerpt: |
    5. Default model: provider=`google`, model=`gemini-2.5-flash`,

- path: `packages/ai-parrot/src/parrot/bots/mixins/model_switching.py`
  lines: 30-30
  symbol: `ModelSwitchingMixin` (docstring example)
  excerpt: |
    llm="google:gemini-2.5-flash",

- path: `packages/ai-parrot/src/parrot/bots/abstract.py`
  lines: 961-968
  symbol: `AbstractBot._parse_model_config` (docstring example)
  excerpt: |
    "model": "gemini-2.5-pro",

- path: `packages/ai-parrot/src/parrot/bots/search.py`
  lines: 71-71
  symbol: (SearchBot ctor default)
  excerpt: |
    llm: str = 'google:gemini-3-flash',

- path: `packages/ai-parrot/src/parrot/bots/jira_specialist.py`
  lines: 210-210
  symbol: `model`
  excerpt: |
    model = "gemini-3.5-flash"

- path: `packages/ai-parrot/src/parrot/bots/github_reviewer.py`
  lines: 583-583
  symbol: `model`
  excerpt: |
    model = "gemini-3.7-flash"

- path: `packages/ai-parrot/src/parrot/bots/flows/agents/a2a_orchestrator.py`
  lines: 174-174
  symbol: (orchestrator default)
  excerpt: |
    llm="google:gemini-3.1-flash-lite-preview"

## Notes

- `search.py:71` uses `google:gemini-3-flash`, which is not a catalogue value (the enum has `gemini-3-flash-preview` as a computer-use alias and `gemini-3.5-flash`); this may be a pre-existing drift worth a separate check, outside this lane's directive.
- The builders' 2.5 mention is inside an LLM *prompt* string, so it steers generated agent configs toward a soon-deprecated model.
