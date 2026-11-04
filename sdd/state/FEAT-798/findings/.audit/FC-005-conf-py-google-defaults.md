---
id: FC-005
query_id: Q014
type: grep
intent: "parrot.conf: every Google/Gemini-related setting and its default value (the 'default in parrot.conf' the request names)."
executed_at: 2026-11-04T01:39:51Z
duration_ms: 500
parent_id: null
depth: 0
---

# FC-005 — conf.py has one remaining 2.5 fallback (ONTOLOGY_AQL_MODEL); DEFAULT_LLM_MODEL is already gemini-flash-latest and DEFAULT_LLM is unset by design

## Summary

In `packages/ai-parrot/src/parrot/conf.py` the only literal 2.5 default is `ONTOLOGY_AQL_MODEL` (line 166, fallback `gemini-2.5-flash`). The global `DEFAULT_LLM_MODEL` (458) already falls back to `gemini-flash-latest` with a comment tying it to `GoogleModel.GEMINI_FLASH_LATEST`, and `DEFAULT_LLM` (250, FEAT-796) is `None` so each component keeps its *builtin* default — which is where the 2.5 defaults actually live (FC-009). Other Google settings are credentials/paths (`GOOGLE_API_KEY`, `VERTEX_PROJECT_ID`, `GITHUB_REVIEW_GOOGLE_API_KEY`), not model ids. A stale `build/lib*/parrot/conf.py` still has `DEFAULT_LLM_MODEL_NAME fallback='gemini-2.5-pro'`; that symbol no longer exists in src.

## Citations

- path: `packages/ai-parrot/src/parrot/conf.py`
  lines: 165-166
  symbol: `ONTOLOGY_AQL_MODEL`
  excerpt: |
    # LLM model for dynamic AQL generation and intent detection.
    ONTOLOGY_AQL_MODEL = config.get("ONTOLOGY_AQL_MODEL", fallback="gemini-2.5-flash")

- path: `packages/ai-parrot/src/parrot/conf.py`
  lines: 247-250
  symbol: `DEFAULT_LLM`
  excerpt: |
    # LLM Model
    # Opt-in global default for per-component LLM selection (FEAT-796), "provider:model".
    # Unset -> each component keeps its builtin default. Independent of LLM_MODEL below.
    DEFAULT_LLM: str | None = config.get("DEFAULT_LLM", fallback=None)

- path: `packages/ai-parrot/src/parrot/conf.py`
  lines: 456-459
  symbol: `DEFAULT_LLM_MODEL`
  excerpt: |
    # "gemini-flash-latest" is GoogleModel.GEMINI_FLASH_LATEST.value, verified
    # byte-identical in parrot/clients/google/models.py.
    DEFAULT_LLM_MODEL = config.get("LLM_MODEL", fallback="gemini-flash-latest")
    DEFAULT_LLM_TEMPERATURE = config.get("LLM_TEMPERATURE", fallback=0.1)

- path: `packages/ai-parrot/src/parrot/conf.py`
  lines: 391-393, 426-428, 439-444
  symbol: `GOOGLE_API_KEY` / `VERTEX_PROJECT_ID` / `GOOGLE_CREDENTIALS_FILE`
  excerpt: |
    GOOGLE_API_KEY = config.get("GOOGLE_API_KEY")
    VERTEX_PROJECT_ID = config.get("VERTEX_PROJECT_ID")
    VERTEX_REGION = config.get("VERTEX_REGION")

## Notes

- `docs/config.md:224-225,331` still documents `DEFAULT_LLM_MODEL` as `gemini-2.5-flash` and a `LLM_MODEL_NAME` alias defaulting to `gemini-2.5-pro` — the docs lag the code (see FC-008).
- The user's phrase "default en parrot.conf" most plausibly maps to the per-component builtins passed to `resolve_component_llm` (FC-009) plus `ONTOLOGY_AQL_MODEL`, not to a single conf constant.
