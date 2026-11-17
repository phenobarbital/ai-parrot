---
id: FW-005
query_id: Q005
type: wiki_page
intent: "Per-component LLM defaults module (FEAT-796) — how DEFAULT_LLM / component vars resolve, and which Google ids are hardcoded as fallbacks."
executed_at: 2026-11-04T01:39:28Z
duration_ms: 6000
parent_id: null
depth: 1
---

# FW-005 — llm_defaults.py carries no model id; the 2.5 builtins live at its three call sites (AgentHandler, crew, expert tiers)

## Summary

Wiki page `file:packages/ai-parrot/src/parrot/llm_defaults.py` (FEAT-796, merged in PR #1949 on 2026-11-03). `resolve_component_llm(component, *, builtin)` resolves `<COMPONENT>_LLM` → `conf.DEFAULT_LLM` → the caller-supplied `builtin` (`provider:model`); the module itself hardcodes nothing. Blast radius (`wikitoolkit symbols blast resolve_component_llm`) shows three production call sites, and each one's builtin is a **2.5** id: `AgentHandler._create_agent` → `"google:gemini-2.5-pro"` (plus a second literal `"gemini-2.5-pro"` fallback when `llm == "google"`), `crew._build_crew_client` → `_CREW_BUILTIN_LLM = "google:gemini-2.5-pro"` (crew.py:121), and `experts/policy.py` `DEFAULT_TIER_POLICY` → judgment `gemini-2.5-pro`, balanced/templated `gemini-2.5-flash`. These are the "defaults" the request wants retired; they were introduced two days ago by FEAT-796, so FEAT-796's tests pin them.

## Citations

- path: `packages/ai-parrot/src/parrot/llm_defaults.py`
  lines: 44-56
  symbol: `resolve_component_llm`
  excerpt: |
    def resolve_component_llm(component: str, *, builtin: str) -> ComponentLLM:
        """Resolve ``<COMPONENT>_LLM`` -> ``DEFAULT_LLM`` -> ``builtin``."""
        builtin_provider, builtin_model = builtin.split(":", 1)
        var = f"{component.upper()}_LLM"
        value = config.get(var)
        ...
        global_value = getattr(conf, "DEFAULT_LLM", None)
        ...
        return ComponentLLM(provider=builtin_provider, model=builtin_model, source="builtin")

- path: `packages/ai-parrot-server/src/parrot/handlers/agents/abstract.py`
  lines: 791-826
  symbol: `AgentHandler._create_agent`
  excerpt: |
    resolved = resolve_component_llm("AGENT", builtin="google:gemini-2.5-pro")
    # falls back to the builtin pair, never to env); env applies only when it sets neither.
    model = self._use_model or ("gemini-2.5-pro" if llm == "google" else None)

- path: `packages/ai-parrot/src/parrot/bots/flows/crew/crew.py`
  lines: 121, 124-147
  symbol: `_CREW_BUILTIN_LLM`, `_build_crew_client`
  excerpt: |
    _CREW_BUILTIN_LLM = "google:gemini-2.5-pro"
    ...
    resolved = resolve_component_llm("CREW", builtin=_CREW_BUILTIN_LLM)
    if resolved.source != "builtin":

- path: `packages/ai-parrot/src/parrot/experts/policy.py`
  lines: 24-28, 33-40
  symbol: `DEFAULT_TIER_POLICY`, `tier_policy`
  excerpt: |
    DEFAULT_TIER_POLICY: Final[dict[ExpertTier, dict[str, Any]]] = {
        ExpertTier.JUDGMENT: {"provider": "google", "model": "gemini-2.5-pro", "temperature": 0.2},
        ExpertTier.BALANCED: {"provider": "google", "model": "gemini-2.5-flash", "temperature": 0.1},
        ExpertTier.TEMPLATED: {"provider": "google", "model": "gemini-2.5-flash", "temperature": 0.0},
    }
    resolved = resolve_component_llm(f"EXPERT_{tier.name}", builtin=f"{base['provider']}:{base['model']}")

- path: `packages/ai-parrot/tests/unit/test_llm_defaults.py`
  lines: 19-60
  symbol: `test_resolve_builtin_when_unset` et al.
  excerpt: |
    Builtins are retained when no component or global default is set.

- path: `packages/ai-parrot/tests/experts/test_expert_llm_defaults.py`
  lines: 1
  symbol: module
  excerpt: |
    Tests for per-tier expert LLM defaults, credentials, and usage tags (FEAT-796).

- path: `packages/ai-parrot-server/tests/handlers/test_agent_handler_llm_defaults.py`
  lines: 55-56
  symbol: `_create`
  excerpt: |
    AgentHandler per-component LLM defaults (FEAT-796, TASK-5142).

## Notes

- `conf.DEFAULT_LLM` (provider:model, FEAT-796) is distinct from the older `conf.DEFAULT_LLM_MODEL` (bare model, FEAT-188 era); both exist and the codebase lane should list their current values (Q014).
- The retirement of 2.5 defaults is therefore three literals + the FEAT-796 tests that assert them, not a resolver change.
- [cross-lane: type=grep, intent=find which FEAT-796 tests assert the literal "gemini-2.5-pro"/"gemini-2.5-flash" builtins (test_llm_defaults.py, test_expert_llm_defaults.py, test_agent_handler_llm_defaults.py, test_crew_llm_defaults.py)]
