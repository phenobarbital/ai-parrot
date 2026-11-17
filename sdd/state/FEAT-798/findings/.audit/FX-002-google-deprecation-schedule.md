---
id: FX-002
query_id: Q010
type: read
intent: "External: Google's official Gemini deprecation schedule for the 2.5 family and the recommended replacements"
executed_at: 2026-11-04T01:36:55Z
duration_ms: 1800
parent_id: null
depth: 1
---

# FX-002 — Google's deprecation page: 2.5 Pro/Flash shut down 2026-12-01, but Google's replacements are 3.8-flash / 3.5-flash-lite, not Argon; 2.5-flash-lite is NOT deprecated

## Summary

`https://ai.google.dev/gemini-api/docs/deprecations` (fetched 2026-11-04T01:36:55Z) confirms the user's date and adds
material detail: (1) `gemini-2.5-pro` shutdown **2026-12-01**, API requests auto-route to `gemini-3.8-flash`
billed at 3.8 Flash rates; (2) `gemini-2.5-flash` shutdown **2026-12-01**, auto-routes to `gemini-3.5-flash-lite`;
(3) `gemini-2.5-flash-lite` is explicitly **not deprecated**; (4) `gemini-2.5-flash-preview-tts` and
`gemini-2.5-pro-preview-tts` shut down **2026-11-17** → `gemini-3.8-flash-tts` / `gemini-3.8-flash-lite-tts`;
(5) `gemini-2.5-flash-native-audio-preview-12-2025` (Live API) shuts down **2026-11-17** → `gemini-3.8-live`;
(6) `gemini-2.5-computer-use-preview-10-2025` already shut down **2026-07-28** → `gemini-3.8-flash`;
(7) `gemini-2.5-flash-image` lives until 2027-03-15. Access to 2.5 is already limited to prior users.

## Citations

- path: `https://ai.google.dev/gemini-api/docs/deprecations`
  lines: n/a
  symbol: `gemini-2.5-pro-models`
  excerpt: |
    gemini-2.5-pro | June 17, 2025 | December 1, 2026 | gemini-3.8-flash
    (effective December 1, 2026, API requests to gemini-2.5-pro automatically route to gemini-3.8-flash)
- path: `https://ai.google.dev/gemini-api/docs/deprecations`
  lines: n/a
  symbol: `gemini-2.5-flash-models`
  excerpt: |
    gemini-2.5-flash | June 17, 2025 | December 1, 2026 | gemini-3.5-flash-lite
    gemini-2.5-flash-lite | July 22, 2025 | No shutdown date announced
- path: `https://ai.google.dev/gemini-api/docs/deprecations`
  lines: n/a
  symbol: `audio-preview-models / live-api`
  excerpt: |
    gemini-2.5-flash-preview-tts | May 20, 2025 | November 17, 2026 | gemini-3.8-flash-tts or gemini-3.8-flash-lite-tts
    gemini-2.5-pro-preview-tts  | May 20, 2025 | November 17, 2026 | gemini-3.8-flash-tts
    gemini-2.5-flash-native-audio-preview-12-2025 | December 12, 2025 | November 17, 2026 | gemini-3.8-live
    gemini-2.5-computer-use-preview-10-2025 | October 7, 2025 | July 28, 2026 | gemini-3.8-flash

## Notes

External source. The TTS/Live 2.5 ids die two weeks BEFORE the chat models — if the repo's voice paths pin
them, that is the more urgent cut. Google's recommended replacements are 3.x models; choosing Argon as the
new default is a product decision, not Google's migration guidance.
