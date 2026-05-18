---
id: F009
query_id: Q017
type: git_log
intent: Recent commits on parrot/clients and parrot/bots — surfaces refactors that affect the design.
executed_at: 2026-05-18T00:00:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F009 — Clients recently homologated (ask_stream); lifecycle events integrated; API now stable

## Summary

Two large, recently-completed initiatives shape the integration surface:
(1) **FEAT "homologate-llm-clients-askstream" (TASK-1173..TASK-1180)**
unified `ask_stream` semantics across `AbstractClient`, ClaudeClient,
OpenAIClient, GroqClient, Gemma4Client, TransformersClient and
ClaudeAgentClient — `ask_stream` now yields a final `AIMessage`. (2)
**FEAT-176 lifecycle-events-system (TASK-1194)** integrated
`EventEmitterMixin` into `AbstractClient` with `BeforeClientCallEvent`,
`AfterClientCallEvent`, and `ClientCallFailedEvent`. On the bots side
GitHubReviewer was added very recently (commits d65f5073..30c92a37) plus
the FEAT-180 weekly-activity work. The clients surface is therefore in
its cleanest state in months: every subclass implements the same
interface, every call site emits lifecycle events, and there are no
in-flight refactors to fight against.

## Citations

- path: `packages/ai-parrot/src/parrot/clients/`
  lines: n/a (git log)
  symbol: recent commits (last 60 days)
  excerpt: |
    2b146f86 fix(lifecycle-events-system): address all code review issues
    47c68d22 feat(lifecycle-events-system): TASK-1194 — Integrate EventEmitterMixin into AbstractClient
    65701dc0 fix(homologate-llm-clients-askstream): address code-review issues
    04fb6df3 feat(homologate-llm-clients-askstream): TASK-1180 — ClaudeAgentClient ask_stream yields final AIMessage
    fb9dd4e4 feat(homologate-llm-clients-askstream): TASK-1179 — TransformersClient ...
    6e45f8d7 feat(homologate-llm-clients-askstream): TASK-1178 — Gemma4Client ...
    69f199a5 feat(homologate-llm-clients-askstream): TASK-1176 — GroqClient ...
    ba025671 feat(homologate-llm-clients-askstream): TASK-1175 — OpenAIClient ...
    9f67ccaf feat(homologate-llm-clients-askstream): TASK-1174 — ClaudeClient ...
    d965c701 feat(homologate-llm-clients-askstream): TASK-1173 — Update AbstractClient ask_stream Return Type

- path: `packages/ai-parrot/src/parrot/bots/`
  lines: n/a (git log)
  symbol: recent commits (last 60 days)
  excerpt: |
    30c92a37 new method: build weekly summary from reviewer
    9ae549fc add comment if github PR doenst have reference to jira ticket
    d3a4e761 Webhook route excluded from auth-middleware
    6edcd076 idempotent github reviewer for registering routes
    d65f5073 Github Reviewer
    95331871 refactor(github-reviewer): rename GitHubPRReviewer to GitHubReviewer
    f72eea31 feat(github-pr-reviewer): add autonomous PR reviewer agent
    2b146f86 fix(lifecycle-events-system): address all code review issues
    979aea5c Merge feat-176-lifecycle-events-system into dev

## Notes

The lifecycle events infrastructure is directly reusable: we can emit a
`PromptCacheEvent` (cacheable, hit, miss, threshold_not_met) without
inventing new telemetry plumbing. The recently-stabilized ask_stream
contract means cache-hint plumbing won't need to be re-done after a
streaming refactor.
