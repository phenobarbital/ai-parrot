---
kind: brief
slug: e2e-explorer-write-scope
key: e009ded74983
base_branch: dev
source:
  type: ledger
  ref: issue:e009ded74983
  url: null
jira_issue_key: null
ledger_issue: issue:e009ded74983
created: '2026-10-30'
---

# Brief: Scope the Write tool of the E2E exploration subagents to their exploration directory

## Problem

Ledger `issue:e009ded74983` (tech_debt, major, from review:TASK-3544 / FEAT-581):

> `.claude/agents/e2e-api-tester.md` and `e2e-ui-tester.md` declare
> `tools: Read, Bash, Glob, Grep, Write` with no path restriction. AC12 requires
> "candidate tests are outside discovery and promotion requires human review" —
> nothing technically stops either agent from writing a candidate test directly
> into `tests/` ... enforced by prompt discipline only, not a hard control.

## Root cause

Both agent definitions grant `Write` unconditionally
(`.claude/agents/e2e-api-tester.md:26`, `.claude/agents/e2e-ui-tester.md:29`) and declare
no `hooks:` frontmatter. The only constraint on where they write is the prose
contract (`e2e-api-tester.md:111-157`, `e2e-ui-tester.md:162-207`), which says output goes
under `sdd/state/<FEAT-ID>/e2e/exploration/<run-id>/` (candidates under `.../candidates/`).
A model that drifts from the prompt can write anywhere.

## Research findings

- Precedent: `.claude/agents/sdd-coder.md:16-22` declares a frontmatter
  `hooks: PreToolUse` with matcher `Bash|Write|Edit|MultiEdit|NotebookEdit`, running a
  checker that exits 2 to block. The same mechanism fits here.
- `.claude/hooks/e2e-teardown.sh` already exists for these two agents (SubagentStop/Stop
  safety net); a sibling shell hook matches local style.
- Gate integrity is already safe: evidence.py never reads exploration output, and
  ScenarioSpec rejects `tier=exploratory` + `required=true` — so this is defense-in-depth.
- `Bash` is also granted and can write files (`cat >`, `tee`). A Write-only path guard
  does NOT close that channel; agents need Bash for `parrot e2e up/down` and curl probes.

## Assumptions

(No interview held. These are the defaults the implementer should use.)

1. Scope is the `Write` tool only. The hook matcher also covers `Edit|MultiEdit|NotebookEdit`
   so a later edit to the grant cannot widen it without anyone noticing. Bash stays unrestricted:
   parsing shell redirections is fragile, and the brief records that limit openly
   rather than claiming a hard control over Bash.
2. Allowed prefix: `<project>/sdd/state/FEAT-*/e2e/exploration/` (resolved, after
   symlinks and `..` are resolved). Every other path is blocked with exit 2 and a reason on stderr.
3. Implement as `.claude/hooks/e2e-exploration-write-guard.sh` (or a small python3 script),
   reading the PreToolUse JSON from stdin (`tool_input.file_path`).

## Fix plan

- HOTFIX-e009ded74983-1: add the guard hook, wire it into both agents' frontmatter,
  update their docs to say promotion is now hook-enforced for Write (and still prompt-only for Bash),
  add a pytest that feeds allowed/denied/traversal payloads to the hook.

## Validation commands

- `pytest tests/sdd/test_e2e_exploration_write_guard.py -q`
