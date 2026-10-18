# /sdd-brief — Research-First Brief for a Hotfix or Single-Issue Fix

Turn one bug, alert, or ledger issue into a worktree holding an actionable
brief — research first, a short Q&A, no FEAT/TASK id reservation (FEAT-698).
Replaces `/sdd-spec --type hotfix`.

## Usage

```
/sdd-brief <source> [--base-branch main|dev|staging] [--no-interview] [--split] [--research full|light]
```

## Guardrails

- Never write or commit under the main checkout's `sdd/`; brief artifacts are
  written only after provisioning the target worktree.
- Never manually create a worktree; provision it only through
  `python -m scripts.sdd.ensure_worktree`.
- Never call `reserve_ids.py`; brief task IDs are local `HOTFIX-<KEY>-<N>` IDs.
- Never push to or merge into `main`.
- Never run `git checkout <base>` in the main checkout; it remains on its
  current branch.

## Steps

### 1. Parse Input

Parse `<source>` and the optional flags from the usage line. Accept only
`main`, `dev`, or `staging` for `--base-branch`, and only `full` or `light`
for `--research`. If questions cannot be asked, behave as though
`--no-interview` was supplied.

### 2. Detect and Fetch the Source

Detect the source before researching it and retain the fetched payload in the
draft. Use the following source-specific fetch operation:

| Source kind | Detection | Fetch operation |
| --- | --- | --- |
| Code-scanning alert | `cs:<n>` or a GitHub `/security/code-scanning/<n>` URL | `gh api repos/{owner}/{repo}/code-scanning/alerts/<n>` |
| GitHub issue | issue URL or `owner/repo#<n>` | `gh issue view <n> --repo <owner>/<repo> --json number,title,body,labels,state,url` |
| GitHub pull request | PR URL or `owner/repo!<n>` | `gh pr view <n> --repo <owner>/<repo> --json number,title,body,files,state,url` |
| Jira | Jira key | Fetch with `jiratoolkit` |
| Ledger | `issue:<hex>` or a bare hex id | `wikitoolkit ledger show <id>` and `wikitoolkit ledger plan-fix --json` |
| Text | any other non-file input | Record the supplied text verbatim |
| File | an existing local file path | Read the file and record its path and contents |

For a code-scanning alert, refuse to continue when the fetched alert has
`state` `dismissed` or `fixed`. Preserve the source type, reference, URL when
available, and fetched details for the brief frontmatter and body.

### 3. Resolve Base and Identity

For a ledger source, select `dev`. If the user explicitly supplied
`--base-branch main`, stop with this exact message:

```
⚠️  Ledger-sourced briefs always base on dev; --base-branch main is refused.
```

For every other source, default to `main` unless `--base-branch` overrides
it. Set `KEY` to the Jira key when present, the ledger short id for a ledger
source, or the slug otherwise. Derive a safe kebab-case `slug` from the
source title or text.

### 4. Claim a Ledger Source

For a ledger source only, claim the issue before research:

```bash
wikitoolkit ledger claim <id> --actor agent:sdd-brief
```

Record that claim. Every abort after this claim and before step 8 must release
it with the verified ledger subcommand:

```bash
wikitoolkit ledger unclaim <id> --reason "<why>" --actor agent:sdd-brief
```

If release fails, print that exact recovery command and the reason; do not
silently leave the issue claimed.

### 5. Research

Research wiki-first: run `wikitoolkit symbols lookup` for named code symbols,
then `wikitoolkit symbols blast` for their blast radius, then
`wikitoolkit query` for related repository knowledge. For affected files, run
`wikitoolkit ledger context <files>`. Use the fetched source to trace a
root cause and relevant tests. `--research light` may bound breadth, but never
the research floor in the next step.

### 6. Enforce the Research Floor

Before creating any worktree, inspect the draft and STOP unless it contains:

- the fetched or identified source;
- a root-cause statement; and
- at least one verified `path:line` anchor.

Verify every proposed anchor before accepting it:

```bash
test -e <path> && sed -n '<line>p' <path>
```

On a missing floor item, refuse to create the worktree, release any ledger
claim as required by step 4, and report which evidence is missing.

### 7. Run Bounded Q&A

Ask at most five questions, as one batch, and only for decisions that research
could not settle. With `--no-interview`, do not ask; record each unresolved
decision beneath `## Assumptions` in the draft instead.

### 8. Stage the Draft

Stage the validated draft at:

```text
sdd/state/.brief/<slug>-<RUN_ID>/
```

This location is git-ignored. It is staging only: do not write the committed
brief or task files into the main checkout.

### 9. Provision the Worktree

Provision exactly one target worktree through the shared CLI:

```bash
python -m scripts.sdd.ensure_worktree --json --slug <slug> --brief-key <KEY> --base-branch <base>
```

Capture the returned worktree path as `<wt>`. The new worktree has no
upstream; do not add one until step 11.

### 10. Write the Brief Artifacts Inside the Worktree

Inside `<wt>`, render `sdd/briefs/<slug>.brief.md` from
`sdd/templates/brief.md`, including `ledger_issue` in its frontmatter for a
ledger source. Materialize one task file for every fix chunk from
`sdd/templates/task.md` at:

```text
sdd/briefs/<slug>/tasks/HOTFIX-<KEY>-<N>-<task-slug>.md
```

Create several task files when `--split` was requested or research found more
than one independent chunk. Build the per-brief index with
`scripts.sdd.brief_meta.write_brief_index`, then validate its graph:

```bash
python -m scripts.sdd.check_task_graph <wt>/sdd/briefs/<slug>.index.json
```

### 11. Commit and Push from the Worktree

Stage only the generated brief, task files, and per-brief index in `<wt>`,
then commit and set the branch's upstream to itself:

```bash
git -C <wt> add sdd/briefs/<slug>.brief.md sdd/briefs/<slug>/tasks/ sdd/briefs/<slug>.index.json
git -C <wt> commit -m "sdd: add brief for <KEY> — <slug>"
git -C <wt> push -u origin <branch>
```

Do not push to or merge into `main`.

### 12. Hand Off

Report the worktree path, brief path, materialized task IDs, and the next
step. Offer either manual implementation or:

```bash
cd <wt> && claude --agent sdd-worker --model sonnet --verbose
```

Finish by directing the owner to run `/sdd-done <KEY>` after implementation.

## Output

Return:

- Worktree: `<wt>`
- Brief: `<wt>/sdd/briefs/<slug>.brief.md`
- Tasks: `HOTFIX-<KEY>-<N>` list
- Next step: `cd <wt> && claude --agent sdd-worker --model sonnet --verbose`,
  manual implementation, then `/sdd-done <KEY>`
