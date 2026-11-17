---
id: FX-003
query_id: Q019
type: read
intent: "External: live Gemini API model list — which 2.5 / 3.x / 4.x ids exist today and which generation methods each supports"
executed_at: 2026-11-04T01:36:55Z
duration_ms: 1500
parent_id: null
depth: 1
---

# FX-003 — Live API (60 models): gemini-4-argon exists but has NO createCachedContent; 2.5 chat ids still resolve

## Summary

`GET v1beta/models` with the project key (fetched 2026-11-04T01:36:55Z) returns 60 models. `gemini-4-argon` is present
with `generateContent, countTokens, batchGenerateContent` — **no** `createCachedContent` (2.5 and every
3.x chat model has it). `gemini-2.5-flash` and `gemini-2.5-pro` still resolve today (shutdown 2026-12-01).
Other current chat ids: gemini-3-flash-preview, gemini-3.1-pro-preview(-customtools), gemini-3.1-flash-lite,
gemini-3.5-flash, gemini-3.5-flash-lite, gemini-3.6-flash, gemini-3.7-flash, gemini-3.8-flash. Live/bidi:
gemini-3.8-live, gemini-3.8-live-extended-thinking, gemini-3.5-transcribe-live, gemini-2.5-flash-native-audio-*.
TTS: gemini-3.8-flash-tts, gemini-3.8-flash-lite-tts, gemini-3.1-flash-tts-preview. No gemini-3.7-pro / 3.1-flash-lite-preview-era ids beyond those listed.

## Citations

- path: `https://generativelanguage.googleapis.com/v1beta/models`
  lines: n/a
  symbol: `gemini-4-argon`
  excerpt: |
    gemini-4-argon | 3.0 | generateContent,countTokens,batchGenerateContent
    gemini-3.8-flash | 3.0 | generateContent,countTokens,createCachedContent,batchGenerateContent
    gemini-2.5-flash | 001 | generateContent,countTokens,createCachedContent,batchGenerateContent
    gemini-2.5-pro | 2.5 | generateContent,countTokens,createCachedContent,batchGenerateContent
- path: `https://generativelanguage.googleapis.com/v1beta/models`
  lines: n/a
  symbol: `live / tts ids`
  excerpt: |
    gemini-3.8-live | bidiGenerateContent
    gemini-3.8-live-extended-thinking | bidiGenerateContent
    gemini-2.5-flash-native-audio-preview-12-2025 | countTokens,bidiGenerateContent
    gemini-3.8-flash-tts | generateContent,countTokens,batchGenerateContent

## Notes

External source. Argon's missing `createCachedContent` matters because FEAT-781 (PR #1890) added Gemini
context-cache handling in the client — making Argon the default may silently disable or break caching paths.
