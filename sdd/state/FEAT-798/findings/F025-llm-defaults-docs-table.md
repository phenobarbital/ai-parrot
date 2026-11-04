---
id: F025
query_id: Q006
type: wiki_page
intent: "User-facing docs for per-component defaults — which Gemini ids are documented as defaults (docs must change too)."
executed_at: 2026-11-04T01:39:28Z
duration_ms: 1200
parent_id: null
depth: 0
---

# F025 — docs/configuration/llm-defaults.md publishes five 2.5 builtin defaults

## Summary

Wiki page `file:docs/configuration/llm-defaults.md` (FEAT-796). The variables table documents the builtin defaults: `AGENT_LLM` → `google:gemini-2.5-pro`, `CREW_LLM` → `google:gemini-2.5-pro`, `EXPERT_JUDGMENT_LLM` → `google:gemini-2.5-pro`, `EXPERT_BALANCED_LLM` / `EXPERT_TEMPLATED_LLM` → `google:gemini-2.5-flash`; `DEFAULT_LLM` has no builtin. This table must be rewritten alongside the three code sites in F009. The same doc describes the `<COMPONENT>_GOOGLE_API_KEY` cascade and `CREW_AI_KEY` alias (unaffected).

## Citations

- path: `docs/configuration/llm-defaults.md`
  lines: 3-12
  symbol: Variables table
  excerpt: |
    | `DEFAULT_LLM` | Global fallback | `None` (falls back to builtin) |
    | `AGENT_LLM` | Agent | `google:gemini-2.5-pro` |
    | `CREW_LLM` | Crew | `google:gemini-2.5-pro` |
    | `EXPERT_JUDGMENT_LLM` | Expert (Judgment tier) | `google:gemini-2.5-pro` |
    | `EXPERT_BALANCED_LLM` | Expert (Balanced tier) | `google:gemini-2.5-flash` |
    | `EXPERT_TEMPLATED_LLM` | Expert (Templated tier) | `google:gemini-2.5-flash` |

## Notes

- Operators can already escape the 2.5 defaults today by setting `DEFAULT_LLM=google:gemini-4-argon` (or per-component vars) — a zero-code mitigation available before 2026-12-01.
