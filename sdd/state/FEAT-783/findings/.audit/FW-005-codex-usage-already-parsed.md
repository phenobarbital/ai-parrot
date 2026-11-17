---
id: FW-005
query_id: Q008
type: wiki_query
intent: "Orient: how codex is spawned as a coder backend and whether --json is parsed."
executed_at: 2026-10-30T22:39:16Z
duration_ms: 0
parent_id: null
depth: 1
---

# FW-005 — Codex usage events are ALREADY parsed: `OpenAICodexClient._usage_from_event` maps the Codex event stream onto `CompletionUsage`

## Summary

The source marks every Codex row in its seat table "**no** (unverified)" and makes spike S3
("find the usage event in `codex exec --json`") a gate. That spike is already closed in code:
`packages/ai-parrot-client-openai/src/parrot/clients/openai/codex_agent.py` defines
`OpenAICodexClient._usage_from_event` (L603-620) and `_usage_from_obj` (L622-632), both producing
`CompletionUsage` — i.e. the Codex event stream's token fields are already located, parsed and
normalised into the same model every other provider uses.

A `CodexCodeDispatcher` also already exists in the dev-loop (confirmed by a prior proposal's finding
F001, `sdd/state/FEAT-375/`), with its own test suite, and a prior finding records the installed CLI
surface (`-m`, `-c model_reasoning_effort`, `--output-schema`, `-o`, stdin prompt).

## Citations

- path: `packages/ai-parrot-client-openai/src/parrot/clients/openai/codex_agent.py`
  lines: 603-620
  symbol: `OpenAICodexClient._usage_from_event`
  excerpt: |
    # maps a Codex event-stream payload onto CompletionUsage
    # (wiki symbol index, extracted; sym:...codex_agent.py#OpenAICodexClient._usage_from_event)

- path: `packages/ai-parrot-client-openai/src/parrot/clients/openai/codex_agent.py`
  lines: 622-632
  symbol: `OpenAICodexClient._usage_from_obj`

- path: `packages/ai-parrot/src/parrot/models/basic.py`
  lines: 48-312
  symbol: `CompletionUsage`
  excerpt: |
    # the normalisation target shared with every other provider

- path: `packages/ai-parrot/tests/flows/dev_loop/test_codex_dispatcher.py`
  lines: 1-1
  symbol: test module
  excerpt: |
    # "Unit tests for the Codex-backed dev-loop dispatcher."

- path: `sdd/state/FEAT-375/findings/F001-codex-dispatcher-exists.md`
  lines: 1-1
  symbol: prior finding
  excerpt: |
    F001 — CodexCodeDispatcher already exists (queries Q001, Q004, Q010)

- path: `sdd/state/FEAT-545/findings/F009-codex-cli-flags-and-local-config.md`
  lines: 1-1
  symbol: prior finding
  excerpt: |
    F009 — codex-cli 0.153.4 installed; supports -m, -c model_reasoning_effort,
           --output-schema, -o, stdin prompt
    # NOTE: installed version TODAY is codex-cli 0.164.0 (probe X1, 2026-10-30)

## Notes

A known hard blocker on this seat is already in the ledger: `issue:c4d0e7a028ca` — "codex sdd-coder
seats can never commit: codex's workspace-write sandbox keeps .git read-only, so every codex attempt
ends as dirty_task_worktree". Relevant because a usage record for a Codex attempt will routinely be
an *abandoned* attempt, which the source's "cost is attributed to attempt_uid including abandoned
ones" rule depends on.

[cross-lane: type=read, intent=Read codex_agent.py L595-640 to list the exact Codex event field names and whether cached_input_tokens is among them]
[cross-lane: type=grep, intent=Determine whether the dev-loop CodexCodeDispatcher actually routes through OpenAICodexClient (and so inherits _usage_from_event) or spawns codex itself and drops usage]
