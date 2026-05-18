---
kind: inline
jira_key: null
fetched_at: 2026-05-18T00:00:00Z
summary_oneline: Agnostic prompt-caching abstraction across LLM providers (Anthropic, OpenAI, Gemini)
---

Agnostic prompt caching abstraction across LLM providers.

Context from conversation:
- User wants a `prompt_caching=True` flag at the Agent level that each
  `AbstractClient` subclass (Anthropic, OpenAI, Gemini, possibly
  Groq/Vertex/HuggingFace) negotiates with its provider in its own way.
- Anthropic uses explicit `cache_control` blocks (5-min TTL, ~1024 token min).
- OpenAI uses automatic prompt caching on prefixes ≥1024 tokens (no API control).
- Gemini uses an explicit `CachedContent` resource with high minimum token
  thresholds (4096 min, 32k for some Flash models) and configurable TTL.
- The abstraction should live in a `PromptBuilder` (location TBD — investigate
  whether one already exists in `packages/ai-parrot/src/parrot/`).
- The `PromptBuilder` should ALSO load a repo-level context document
  (working name `AGENT_CONTEXT.md`) from a configuration directory, with
  in-memory caching invalidated by mtime, so it isn't re-read from disk on
  every agent invocation.
- This came up while designing the GithubReviewer agent
  (`packages/ai-parrot/src/parrot/bots/github_reviewer.py`), which needs
  repo-level context beyond just the PR diff + Jira ticket. The reviewer
  would inject the cached `AGENT_CONTEXT.md` as a "Repo Context" block
  alongside the per-PR data, and prompt caching makes this nearly free
  across repeated reviews.

Design constraints / known tradeoffs to investigate:
- Best-effort per provider: if a provider's minimum token threshold isn't
  met (Gemini especially), the abstraction must degrade gracefully (no
  error, just log at debug level that caching wasn't applied for that
  provider).
- Where exactly should `PromptBuilder` live? Investigate `parrot/clients/`,
  `parrot/bots/`, `parrot/template/`, or whether there's already a
  prompt-construction helper.
- API surface: flag on `Agent`, on `AbstractClient`, or both? Investigate
  current Agent/Chatbot init signatures.
- How do `AbstractClient` subclasses currently send the system prompt?
  Need to understand the current shape before designing the cache-marker
  injection.
