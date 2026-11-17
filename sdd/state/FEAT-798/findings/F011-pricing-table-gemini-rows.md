---
id: F011
query_id: Q020
type: grep
intent: "Pricing / cost tables: rows for gemini-2.5-* and gemini-4-* in the bundled pricing JSON (CostCalculator already warns the google table is stale)."
executed_at: 2026-11-04T01:42:07Z
duration_ms: 300
parent_id: null
depth: 0
---

# F011 — google.json pricing has only dated 2.5 *preview* rows, no gemini-2.5-flash/pro GA rows and no gemini-4-argon row; last_updated 2026-06-10

## Summary

`packages/ai-parrot/src/parrot/observability/cost/pricing/google.json` (`last_updated: 2026-06-10`, already flagged stale >90 days by `CostCalculator` at startup) carries rows for `gemini-3.1-pro-preview`, `-customtools`, `gemini-3.5-flash`, `gemini-3-flash-preview`, `gemini-3.1-flash-lite(-preview)`, `gemini-3.8-flash`, the 2.0/1.5/1.0 families, and two 2.5 rows keyed by *preview* ids (`gemini-2.5-flash-preview-05-20`, `gemini-2.5-pro-preview-05-06`). There is no GA `gemini-2.5-flash`/`gemini-2.5-pro` key and no `gemini-4-argon` key, so cost attribution for both the current defaults and the migration target is already a miss unless the calculator prefix-matches.

## Citations

- path: `packages/ai-parrot/src/parrot/observability/cost/pricing/google.json`
  lines: 3-3
  symbol: `last_updated`
  excerpt: |
    "last_updated": "2026-06-10",

- path: `packages/ai-parrot/src/parrot/observability/cost/pricing/google.json`
  lines: 57-63
  symbol: (2.5 preview rows)
  excerpt: |
    "gemini-2.5-flash-preview-05-20": {
    "gemini-2.5-pro-preview-05-06": {

- path: `packages/ai-parrot/src/parrot/observability/cost/pricing/google.json`
  lines: 9-50, 103-103
  symbol: (3.x rows)
  excerpt: |
    "gemini-3.1-pro-preview": {
    "gemini-3.5-flash": {
    "gemini-3.1-flash-lite": {
    "gemini-3.8-flash": [

## Notes

- Whether `CostCalculator` does prefix matching (so `gemini-2.5-flash` → `-preview-05-20`) was not read; out of this lane's query list.
- Argon pricing is not derivable from the repo — an external input for the spec.
