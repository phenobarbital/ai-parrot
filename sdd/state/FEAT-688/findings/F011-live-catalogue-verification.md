---
id: F011
query_id: Q014-retry
type: live_api
intent: "EXTERNAL (retry of Q014): confirm the Gemini 4.x ids, the deprecation list and the google-genai release by measurement"
executed_at: 2026-10-15T20:30:00Z
parent_id: F008
depth: 1
---

# F011 — Live catalogue, REST probes and PyPI metadata (supersedes F008)

## Summary

`WebSearch`/`WebFetch` stayed broken, but `curl` works. Q014 was re-run against primary
sources instead of documentation:

- `GET generativelanguage.googleapis.com/v1beta/models?pageSize=200` with the workspace
  `GOOGLE_API_KEY` (env/.env) → 63 models, no pagination.
- Raw REST `generateContent` probes against `gemini-4-argon`.
- `https://pypi.org/pypi/google-genai/{,2.24.0,2.31.0}/json`.

## Evidence

**4.x family** — exactly one id: `gemini-4-argon` (`displayName: Gemini 4 Argon`,
`inputTokenLimit: 1048576`, `outputTokenLimit: 32768`, `thinking: true`,
`supportedGenerationMethods: generateContent, countTokens, batchGenerateContent` — no
`createCachedContent`).

**Enum values not served** (diff of the 34 `GoogleModel` values vs the listing):
`gemini-3.7-pro`, `gemini-3.7-flash-thinking`, `gemini-3.7-flash-lite` (only
`gemini-3.7-flash` survives), `gemini-deep-research-preview-04-2026` (upstream:
`deep-research-preview-04-2026`, plus `deep-research-max-preview-04-2026` and
`deep-research-pro-preview-12-2025`), and the three `imagen-*` values — but the listing
contains **no** imagen model at all, so imagen absence is inconclusive.

**REST probes on `gemini-4-argon`** (all `200 OK`): `thinkingConfig.thinkingBudget: 0`;
`thinkingConfig.thinkingLevel: "LOW"`; no thinking config; `tools` (one
FunctionDeclaration) + `responseMimeType: application/json` + `responseSchema` in a single
request → returned a `functionCall`, same as `gemini-3.8-flash`.

**SDK** — PyPI latest `2.31.0`; `2.30.1` exists. `requires_dist` (non-extra) of `2.24.0` and
`2.31.0` is identical: anyio, google-auth[requests], httpx, pydantic>=2.12.5, requests,
tenacity<9.2.0, websockets<17.0, typing-extensions, distro, sniffio — no Google Cloud
packages. Installed `2.24.0` already exposes `ThinkingConfig.thinking_level`
(`Optional[ThinkingLevel]`) next to `thinking_budget`.

## Citations

- `packages/ai-parrot-client-google/src/parrot/clients/google/models.py:22-24,54-55`
- `packages/ai-parrot-client-google/src/parrot/clients/google/client.py:151,281,518`
- `packages/ai-parrot-client-google/pyproject.toml:17-27`
- `packages/ai-parrot-embeddings/pyproject.toml:47-55`

## Implications

U1 and U3 are resolved by measurement; C9–C12 rise to high/medium. Argon must enter
`_default_combined_call_prefixes` and must stay out of `_requires_thinking`.
