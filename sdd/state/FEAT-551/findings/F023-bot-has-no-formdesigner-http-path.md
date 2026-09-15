---
id: F023
query_id: Q009
type: grep
intent: How the Teams bot reaches FormDesigner today (registry vs HTTP)
executed_at: 2026-09-10T22:35:04Z
duration_ms: 0
parent_id: F009
depth: 1
---

# F023 — The Teams bot has no FormRegistry, HTTP client or FormDesigner base URL today

## Summary
Neither `msteams/wrapper.py`, `dialogs/orchestrator.py` nor `msteams/models.py` reference `FormRegistry`/`form_registry`, an aiohttp `ClientSession`, or any `base_url`/`api_base` setting. The orchestrator uses FormDesigner only in-process via `RequestFormTool` / `ToolExtractor` (dialog flow). So a bot-side receiver that forwards a card submission to `POST .../forms/{uid}/data` must either (a) POST over HTTP to an absolute `submit_url` carried in the card envelope, or (b) gain a configured FormDesigner base URL / in-process registry access — neither exists yet.

## Citations
- path: `packages/ai-parrot-integrations/src/parrot/integrations/msteams/dialogs/orchestrator.py`
  lines: 17-19
  excerpt: |
    from parrot_formdesigner.tools import RequestFormTool
    from parrot_formdesigner.extractors.tool import ToolExtractor
- path: `packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py`
  symbol: (no FormRegistry / ClientSession / base_url matches — evidence of absence)
- path: `packages/ai-parrot-integrations/src/parrot/integrations/msteams/models.py`
  symbol: (no base_url / api_base config field — evidence of absence)
