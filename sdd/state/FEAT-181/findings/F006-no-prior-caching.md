---
id: F006
query_id: Q012
type: grep
intent: Detect existing prompt-caching work to avoid duplicate effort.
executed_at: 2026-05-18T00:00:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F006 — Zero pre-existing prompt-caching work in parrot/ (green field)

## Summary

A repo-wide grep for `prompt_cache|prompt_caching|cache_control|CachedContent|cached_content|cache_prompt`
inside `packages/ai-parrot/src/parrot/` returned **no matches**. There is
no half-finished implementation to coordinate with, no flag already on
clients, no Anthropic `cache_control` block construction anywhere, no
Gemini `CachedContent` resource creation, and no OpenAI `prompt_cache_key`
passing. The feature can land as a coherent new abstraction without
back-compat constraints from prior work. Search for
`AGENT_CONTEXT|CONTEXT\.md|context_file|context_path|load_context` in the
same package also returned no relevant loader pattern (only navconfig
logging imports), confirming the AGENT_CONTEXT.md loader is also green
field.

## Citations

- path: `packages/ai-parrot/src/parrot/**`
  lines: n/a
  symbol: absence
  excerpt: |
    $ grep -rnE "prompt_cache|prompt_caching|cache_control|CachedContent|cached_content|cache_prompt" packages/ai-parrot/src/parrot --include="*.py"
    (no output)

- path: `packages/ai-parrot/src/parrot/**`
  lines: n/a
  symbol: absence of AGENT_CONTEXT loader
  excerpt: |
    $ grep -rnE "AGENT_CONTEXT|CONTEXT\\.md|context_file|context_path" packages/ai-parrot/src/parrot --include="*.py"
    (no output)

## Notes

Absence is evidence: the design can pick the cleanest API surface
without worrying about migrating an existing half-built scheme. The
risk inverts — we must be careful to design well from the start since
there is no prior art in-repo to course-correct against.
