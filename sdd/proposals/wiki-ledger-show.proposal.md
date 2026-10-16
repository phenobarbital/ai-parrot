---
id: null  # FEAT-ID reserved by /sdd-spec via scripts.sdd.reserve_ids
title: wikitoolkit ledger list / show — read issues by status and by id
slug: wiki-ledger-show
type: feature
mode: enrichment
status: review
source:
  kind: inline
  jira_key: null
  jira_url: null
  fetched_at: 2026-10-16
  summary_oneline: wikitoolkit ledger doesn't have list or show commands
overall_confidence: high
base_branch: dev
projects: [ai-parrot, ai-parrot-tools, sdd-tooling]
tags: [wikitoolkit, ledger, cli, mcp]
research_state: sdd/state/wiki-ledger-show/
created: 2026-10-16
updated: 2026-10-16
---

# wikitoolkit ledger list / show

> **Mode**: enrichment
> **Confidence**: high
> **Status**: review

## 0. Origin

Inline request: *"wiki-ledger-show -- wikitoolkit ledger doesn't have list or show commands"*.

## 1. Synthesis Summary

The `wikitoolkit ledger` group has 15 subcommands but no way to **read an issue by id** or to
**list issues in any status other than `open`**. `ledger ready` prints only
`id [severity] title (kind)` for unclaimed open issues, so claimed and closed issues can't be seen
from the CLI, and an issue's `body` can't be seen anywhere. The service layer already does most of
the work: `LedgerService.list_issues()` filters by status, kind and `about` prefix (only the standup
collector calls it), and a private `_issue_state()` reads a single issue with its body. The feature
is mostly wiring: two CLI commands, two MCP tools, a remote read-only allowlist entry, and a small
per-issue event-history reader over `events.jsonl` [F001–F004].

## 2. Codebase Findings

### 2.1 Localization

| Path | Symbol | Role | Evidence |
|---|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:3221-3295` | `ledger` group, `ledger_ready` | add `list` and `show` beside `ready`; copy its remote/busy handling | F001 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py:278-308` | `LedgerService.list_issues` | reuse it as-is for `list` | F002 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py:336-341` | `LedgerService._issue_state` | promote to a public `get_issue()` that returns the dict including `body` | F002 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py:109-125` | `_issue_dict` | omits `body`; `show` needs it (`list` stays compact) | F002, F003 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/log.py:83` | `LedgerLog.iter_events` | filter by `subject == issue_id` for `issue_history()` | F003 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/operations.py:40-100` | `LedgerReadyInput`, `op_ledger_ready` | add `LedgerListInput`/`LedgerShowInput` + `op_ledger_list`/`op_ledger_show` | F004 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/transport.py:143-147,381-404` | `_SPECS`, dispatch | register `ledger_list`, `ledger_show` (mount `ledger`) | F004 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/remote.py:16-30` | `READ_ONLY_TOOLS` | add both, so `--remote` proxies them | F004 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/tools.py`, `packages/ai-parrot-tools/src/parrot_tools/wiki/tools.py:346-355` | `ledger_ready` tool class | add matching adapters | F004 |

### 2.2 Constraints Discovered

- Proxied CLI commands follow one pattern: `@remote_cli.remote_aware(proxied=True, tool=...)`, a
  `remote is not None` branch calling `remote_cli.call_remote_text`, and `WikiStoreBusy` reported
  as `index_pending` instead of a traceback [F001].
- Reads go through `_sync_best_effort()` and stay usable on a stale index while the writer lock is
  busy [F002].
- Issue ids are `issue:<12 hex>`. Events carry `subject`, `actor`, `ts`, `kind` and `payload` [F003].
- Any `--json` output must start at byte 0 with JSON. `plan-fix --json` already breaks this by
  printing the navconfig banner first, so the new commands must not repeat it [F005].
- `operations.py` is framework-free, and its input schemas mirror the CLI options one for one [F004].

### 2.3 Recent History

No recent churn in `ledger/service.py` or the ledger CLI section. The latest touches to `cli.py`
came from FEAT-540 (graphindex seams) and TASK-4353 (remote `wiki_sync_push`).

## 3. Probable Scope

### What's New
- `wikitoolkit ledger list [--status open|claimed|closed|superseded|all ...] [--kind K] [--severity S] [--about PREFIX] [--json]`
  - Default statuses are `open` and `claimed`, the same default as `list_issues`. Results are sorted
    by severity, then id. Each line shows `id [severity] status title (kind) claimed_by`.
- `wikitoolkit ledger show <issue_id> [--json] [--no-history]`
  - Prints every state field, including `body`, `about`, `discovered_from`, `claimed_by`,
    `closed_reason` and `resolved_by`, followed by a chronological event history
    (`ts actor kind` plus key payload fields).
  - Accepts the id with or without the `issue:` prefix. An unknown id exits with code 1.
- `LedgerService.get_issue(issue_id)` and `LedgerService.issue_history(issue_id)`, which scans the
  log off the event loop with `asyncio.to_thread`.
- MCP tools `ledger_list` and `ledger_show` (ops, transport spec, both tool adapters), added to
  `READ_ONLY_TOOLS`.

### What Changes
- `list_issues` gains an optional `severity` filter, unless the CLI filters after the call.

### What's Untouched (Non-Goals)
- `ready`, `plan-fix`, `context`: their output does not change.
- The ledger write path and event schema.
- Moving `/sdd-fix` or `/sdd-next` over to the new commands. That is a follow-up.

### Patterns to Follow
`ledger_ready` (CLI), `op_ledger_ready` (ops), the `ledger_ready` entry in `_SPECS`, and the
`ledger_ready` tool class.

### Integration Risks
- `issue_history` reads the whole `events.jsonl` (about 458 KB today), which is fine for now. If the
  log grows, an offset index is a later optimization.
- Adding tools changes the MCP tool list snapshot tests in `test_ledger_tools.py`, so those must be
  updated.

## 4. Confidence Map

- ✓ No `list` or `show` command exists [high, F001]
- ✓ `list_issues` and `_issue_state` already exist and are reusable [high, F002]
- ✓ Issue state stores `body`, but the public dict drops it [high, F002, F003]
- ✓ Wiring a new read tool touches ops, transport, remote and both adapter modules [high, F004]
- ◐ The history scan stays fast enough without an index [medium, F003]

## 5. Open Questions

### Resolved (during proposal phase)
- [x] U1 Surfaces → CLI, MCP and remote proxy (`READ_ONLY_TOOLS`).
- [x] U2 `show` depth → current state plus event history from `events.jsonl`.

### Unresolved (defer to spec)
- [ ] Should `ready` become an alias of `list --status open --unclaimed`, or stay separate? (Proposal: stay separate.)

## 6. Recommended Next Step

→ `/sdd-spec sdd/proposals/wiki-ledger-show.proposal.md`. The change is additive and well localized,
and every building block exists. Expect 2–3 tasks: service and ops, CLI, MCP/remote wiring with tests.

### Alternatives
- Single-task spec: the work could be done as one task with no worktree.

## 7. Research Audit

State: `sdd/state/wiki-ledger-show/`. Findings: F001–F005. Budget profile: default. Consumed: about
9 file reads, 12 greps, 3 git calls and 1 wiki query. Not truncated.

## 8. Provenance

Generated by `/sdd-proposal` on 2026-10-16 from the `dev` branch at `578f28c91` and later. The FEAT-ID
is deliberately unassigned, because per CLAUDE.md IDs are reserved through `scripts.sdd.reserve_ids`
at `/sdd-spec` time rather than by scanning.
