# F011 — Remaining wire-level gotchas

**Source**: `docs/reasoning.md`, `docs/token-counting.md`, `docs/prompt-caching.md`

- **`logprobs` unsupported**: `logprobs: true` (CC) and
  `include: ["message.output_text.logprobs"]` (Responses) both → **HTTP 400**.
  Muse Spark is a reasoning model.
- **`reasoning_content` is redacted to empty** for external API keys on Chat
  Completions — *"there is nothing to replay and each turn reasons from
  scratch."* Do not treat it as thinking output.
- **Output-token param**: `max_tokens` on Chat Completions (vs
  `max_output_tokens` on Responses). `openai_base.py:643/983` already sends
  `max_tokens` → correct. (Note: an in-flight spec,
  `sdd/specs/openai-max-completion-tokens.spec.md`, is currently modified in
  the working tree and concerns `max_completion_tokens` for reasoning models —
  worth checking for interaction before implementation.)
- **Prompt caching is automatic** — no key, no setup, nothing to implement.
  Observability only: `usage.prompt_tokens_details.cached_tokens` (CC).
  `prompt_cache_key` is accepted and replaces the deprecated `user` field.
- **Token counting is not a Chat Completions feature**: it is
  `POST /v1/responses/input_tokens` (or `/v1/messages/count_tokens` for the
  Anthropic shape). Reachable without full Responses generation support.
- **Tool-result turns**: the complete assistant message including its
  `tool_calls` array must precede the `tool` message, else HTTP 400.
