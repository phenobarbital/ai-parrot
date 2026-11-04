# Gemini 2.5 retirement (FEAT-798)

Google shuts down `gemini-2.5-pro` and `gemini-2.5-flash` on 2026-12-01. The 2.5 TTS and
native-audio previews shut down on 2026-11-17.

## What changed

| Retired id | Replacement | Where used |
|---|---|---|
| `gemini-2.5-pro` | `gemini-4-argon` | Agent, Crew and Expert (Judgment tier) builtin defaults |
| `gemini-2.5-flash` | `gemini-3.8-flash` | Expert Balanced and Templated tier builtin defaults |

The builtin defaults for the per-component LLM settings (`AGENT_LLM`, `CREW_LLM`,
`EXPERT_JUDGMENT_LLM`, `EXPERT_BALANCED_LLM`, `EXPERT_TEMPLATED_LLM`) now point at the
replacements. See `docs/configuration/llm-defaults.md`. The `google-genai` floor is raised to
`2.34.0`.

## Breaking changes

- The retired members of the `GoogleModel`, `VertexAIModel` and `GoogleVoiceModel` enums are
  deleted.
- `GoogleModel("gemini-2.5-pro")` (and the other retired values) now raises `ValueError`.
- `GET /models` and `LLMFactory.list_models("google")` no longer list the retired ids.

Code that referenced the removed enum members must switch to the replacement ids.

## Explicit overrides are preserved

`DEFAULT_LLM`, `<COMPONENT>_LLM`, `LLM_MODEL` and persisted bot configurations are not
rewritten: the resolver returns an explicitly configured value as-is, even if it is a retired
id. After 2026-12-01 Google auto-routes `gemini-2.5-pro` to `gemini-3.8-flash` and
`gemini-2.5-flash` to `gemini-3.5-flash-lite`, billed at the new model's rate. Update such
overrides deliberately.

## Context caching

`gemini-4-argon` has no `createCachedContent` support. The client fails open (the request
proceeds without a cache) rather than raising. To keep context caching on a component, set its
override to a caching-capable model, for example `AGENT_LLM=google:gemini-3.8-flash` (or
`CREW_LLM`, `EXPERT_JUDGMENT_LLM`).
