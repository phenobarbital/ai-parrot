---
id: F024
query_id: Q004
type: wiki_page
intent: "Earlier spec that centralised the Google default model — learn the single source of truth for the Google default and whether it still names gemini-2.5-flash."
executed_at: 2026-11-04T01:39:28Z
duration_ms: 2000
parent_id: null
depth: 0
---

# F024 — FEAT-188 (draft, 2026-05) catalogued ~14 hardcoded gemini-2.5-flash fallbacks; GEMINI_FLASH_LATEST + DEFAULT_LLM_MODEL are the intended single source of truth

## Summary

Wiki page `file:sdd/specs/centralize-google-default-model.spec.md` (score 1.00 for Q009, 0.78 for conf orientation). FEAT-188, status **draft** (2026-05-19, author Juan2coder) — not evidently approved or implemented — documents the design rule: runtime/agent fallbacks read `parrot.conf.DEFAULT_LLM_MODEL` (env `LLM_MODEL` → `GoogleModel.GEMINI_FLASH_LATEST.value`), library-level defaults inside the Google client read `GEMINI_FLASH_LATEST.value` directly. It enumerated literal `'gemini-2.5-flash'` fallbacks in `conf.py:142` (`ONTOLOGY_AQL_MODEL`), `bots/base.py:342,344`, `bots/voice.py:249`, `bots/scraper/scraper.py:98`, plus client-internal fallbacks, and explicitly kept intentional 2.5 pins (`analysis.py:771` retry path, image plugins using `GEMINI_2_5_FLASH`) and the enum member itself. Line numbers are 5+ months old and pre-date FEAT-523/FEAT-796; treat as a map of *where to look*, not as current anchors.

## Citations

- path: `sdd/specs/centralize-google-default-model.spec.md`
  lines: 20-48
  symbol: Problem Statement / Goals
  excerpt: |
    ~14 code paths bypass that alias and hardcode the literal "gemini-2.5-flash" (or GoogleModel.GEMINI_2_5_FLASH) as a fallback default.
    - Make GoogleModel.GEMINI_FLASH_LATEST (and the env-driven DEFAULT_LLM_MODEL in parrot/conf.py) the **only** authoritative default
    - Preserve backward compatibility: existing env (LLM_MODEL) and DB (navigator.bots.model) overrides keep winning over the global.

- path: `sdd/specs/centralize-google-default-model.spec.md`
  lines: 50-62
  symbol: Non-Goals
  excerpt: |
    - Do **not** touch references that intentionally pin to a specific Gemini version for capability reasons
      (e.g. analysis.py:771 retry path that explicitly falls back to 2.5-flash on 5xx from Pro; image plugins that use GEMINI_2_5_FLASH)
    - Do **not** rename or remove GoogleModel.GEMINI_2_5_FLASH from the enum — it remains a valid explicit choice.

- path: `packages/ai-parrot/src/parrot/conf.py`
  lines: 142 (as of 2026-05)
  symbol: `ONTOLOGY_AQL_MODEL`
  excerpt: |
    ONTOLOGY_AQL_MODEL hardcoded 'gemini-2.5-flash' fallback → DEFAULT_LLM_MODEL

- path: `packages/ai-parrot/src/parrot/bots/base.py`
  lines: 342, 344 (as of 2026-05)
  symbol: agent-layer fallback literals
  excerpt: |
    Replace literal 'gemini-2.5-flash' with DEFAULT_LLM_MODEL import from parrot.conf

- path: `packages/ai-parrot/src/parrot/bots/voice.py`
  lines: 249 (as of 2026-05)
  symbol: voice fallback literal
  excerpt: |
    'gemini-2.5-flash' → DEFAULT_LLM_MODEL

- path: `packages/ai-parrot/src/parrot/bots/scraper/scraper.py`
  lines: 98 (as of 2026-05)
  symbol: scraper fallback literal
  excerpt: |
    'gemini-2.5-flash' → DEFAULT_LLM_MODEL

## Notes

- Whether FEAT-188 was ever implemented is unknown from the wiki (no task index page surfaced). The codebase lane's Q010/Q014/Q015 greps will show whether those literals survive today.
- The spec names the "intentional pin" exception class — image plugins and the 5xx retry fallback — which is exactly the class a 2.5 retirement cannot leave alone.
- [cross-lane: type=grep, intent=check whether sdd/tasks/index/centralize-google-default-model.json exists and its status]
- [citation-check: stale] conf.py:142, bots/base.py:342,344, voice.py:249, scraper.py:98 are the 2026-05 FEAT-188 line numbers (probes c140-c143 missing); current anchors are conf.py:166, base.py:487-495, voice.py:437-438, scraper.py:94-99 (F005/F006, probes c44/c50/c51 found).
