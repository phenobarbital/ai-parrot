---
name: sdd-brief
description: Research a bug, code-scanning alert, Jira/GitHub issue, or ledger issue to a root cause and provision a worktree holding an actionable brief — no FEAT/TASK ids; replaces sdd-spec --type hotfix.
---

# SDD Brief

## Full procedure and Codex adaptations

Before executing, read the [full sdd-brief procedure](../../../.claude/commands/sdd-brief.md)
and the [Codex adaptation contract](../../../docs/sdd/CODEX.md#codex-adaptation-contract).
The full procedure holds the detail omitted here; the adaptation contract
overrides Claude runtime syntax. Retain every gate below.

Codex invocation: `$sdd-brief <source> [--base-branch main|dev|staging] [--no-interview] [--split] [--research full|light]`.

## Purpose

Turn one bug, alert, or ledger issue into a worktree holding an actionable
brief — research first, a short Q&A, no FEAT/TASK id reservation.

## Guardrails

- Write nothing under the main checkout's `sdd/`; artifacts go in the provisioned worktree.
- Provision the worktree only through `python -m scripts.sdd.ensure_worktree`.
- Brief task IDs are local `HOTFIX-<KEY>-<N>` IDs; never allocate global IDs.
- Never push to or merge into `main`; never check out a base branch in the main checkout.

## Procedure

1. **Parse** `<source>` and flags. `--base-branch` accepts `main|dev|staging`; `--research` accepts `full|light`. If questions cannot be asked, act as `--no-interview`.
2. **Detect and fetch** the source: `cs:<n>` code-scanning alert (`gh api repos/{owner}/{repo}/code-scanning/alerts/<n>`; refuse when `dismissed` or `fixed`), GitHub issue/PR (`gh issue view` / `gh pr view`), Jira key (`jiratoolkit`), ledger (`wikitoolkit ledger show <id>`, `wikitoolkit ledger plan-fix --json`), free text, or a local file.
3. **Resolve base and identity.** Ledger sources base on dev; if `--base-branch main` was supplied stop with: `⚠️  Ledger-sourced briefs always base on dev; --base-branch main is refused.` Other sources default to `main`. `KEY` is the Jira key, the ledger short id, or the slug.
4. **Claim a ledger source** with `wikitoolkit ledger claim <id> --actor agent:sdd-brief`; release any abort before step 8 with `wikitoolkit ledger unclaim <id> --reason "<why>" --actor agent:sdd-brief`, printing the recovery command if release fails.
5. **Research wiki-first**: `wikitoolkit symbols lookup`, `symbols blast`, `wikitoolkit query`, and `wikitoolkit ledger context <files>`. `--research light` may bound breadth, never the floor.
6. **Research floor.** Before any worktree exists, STOP unless the draft has the fetched source, a root-cause statement, and at least one verified `path:line` anchor (`test -e <path> && sed -n '<line>p' <path>`). Release any ledger claim and report what is missing.
7. **Bounded Q&A**: at most five questions in one batch, only for decisions research could not settle; under `--no-interview` record them in `## Assumptions`.
8. **Stage the draft** under `sdd/state/.brief/<slug>-<RUN_ID>/` (git-ignored).
9. **Provision**: `python -m scripts.sdd.ensure_worktree --json --slug <slug> --brief-key <KEY> --base-branch <base>`; capture `<wt>`.
10. **Write artifacts inside `<wt>`**: `sdd/briefs/<slug>.brief.md` from `sdd/templates/brief.md` (with `ledger_issue` for ledger sources), task files `sdd/briefs/<slug>/tasks/HOTFIX-<KEY>-<N>-<task-slug>.md`, the per-brief index via `scripts.sdd.brief_meta.write_brief_index`, then `python -m scripts.sdd.check_task_graph <wt>/sdd/briefs/<slug>.index.json`.
11. **Commit and push from `<wt>`**: stage only the brief, tasks and index; commit `sdd: add brief for <KEY> — <slug>`; `git -C <wt> push -u origin <branch>`.
12. **Hand off**: report worktree, brief path, task IDs; offer manual implementation or `cd <wt> && claude --agent sdd-worker --model sonnet --verbose`; finish with `/sdd-done <KEY>`.
