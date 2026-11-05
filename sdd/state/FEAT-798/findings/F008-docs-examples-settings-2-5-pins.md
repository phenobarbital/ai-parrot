---
id: F008
query_id: Q018
type: grep
intent: "Gemini ids outside packages/: settings templates, env examples, docs, examples, plugins and agent YAML/TOML definitions that pin gemini-2.5 as a default."
executed_at: 2026-11-04T01:42:07Z
duration_ms: 700
parent_id: null
depth: 0
---

# F008 — ~75 gemini-2.5 mentions in docs/ and examples/; docs/configuration/llm-defaults.md and docs/config.md document 2.5 as the shipped defaults

## Summary

Outside `packages/` (and excluding `sdd/`), `gemini-2.5` appears in ~40 files: 25+ example scripts/configs (`examples/orchestration/messaging.py` ×10, `examples/crew/product_research_crew.json` ×8, `examples/matrix_swarm/agents.yaml`, `.env.example`, …), one plugin agent (`plugins/agents/epson.py`), and ~15 docs. Distinct ids: `gemini-2.5-flash` ×47, `gemini-2.5-pro` ×23, `gemini-2.5-flash-lite` ×2, native-audio ×3. Two docs are normative: `docs/configuration/llm-defaults.md:8-12` lists `google:gemini-2.5-pro`/`-flash` as the builtin for AGENT, CREW and the three EXPERT tiers (matches F009), and `docs/config.md:224-225,331` documents `DEFAULT_LLM_MODEL=gemini-2.5-flash` and a `LLM_MODEL_NAME` alias (`gemini-2.5-pro`) that no longer exists in `conf.py` (F005). No `settings/` or `env/` file in the repo root pins a 2.5 id.

## Citations

- path: `docs/configuration/llm-defaults.md`
  lines: 8-12
  symbol: (builtin defaults table)
  excerpt: |
    | `AGENT_LLM` | Agent | `google:gemini-2.5-pro` |
    | `CREW_LLM` | Crew | `google:gemini-2.5-pro` |
    | `EXPERT_JUDGMENT_LLM` | Expert (Judgment tier) | `google:gemini-2.5-pro` |
    | `EXPERT_BALANCED_LLM` | Expert (Balanced tier) | `google:gemini-2.5-flash` |
    | `EXPERT_TEMPLATED_LLM` | Expert (Templated tier) | `google:gemini-2.5-flash` |

- path: `docs/config.md`
  lines: 224-225, 331-331
  symbol: (configuration reference)
  excerpt: |
    - **`DEFAULT_LLM_MODEL`**: Default model across the application (default: `gemini-2.5-flash`)
    - **`LLM_MODEL_NAME`**: Alias for model name (default: `gemini-2.5-pro`)
    DEFAULT_LLM_MODEL=gemini-2.5-flash

- path: `examples/orchestration/messaging.py`
  lines: (10 hits)
  symbol: (example)
  excerpt: |
    gemini-2.5-* (10 occurrences)

- path: `examples/crew/product_research_crew.json`
  lines: (8 hits)
  symbol: (crew definition)
  excerpt: |
    gemini-2.5-* (8 occurrences)

- path: `examples/matrix_swarm/agents.yaml`
  lines: (1 hit)
  symbol: (agent definition)
  excerpt: |
    gemini-2.5-flash

- path: `plugins/agents/epson.py`
  lines: (1 hit)
  symbol: (plugin agent)
  excerpt: |
    gemini-2.5-*

## Notes

- Line numbers for example files were not individually read (budget); the counts come from the grep file tally.
- Whether examples/ and docs/ are in scope for the "retiro" is a product decision; the normative docs (llm-defaults.md, config.md) must change with the code regardless.
