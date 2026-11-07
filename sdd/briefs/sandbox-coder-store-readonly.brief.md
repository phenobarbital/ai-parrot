---
kind: brief
slug: sandbox-coder-store-readonly
key: c61e28722cca
base_branch: dev
source:
  type: ledger
  ref: "issue:c61e28722cca"
  url: null
jira_issue_key: null
ledger_issue: "issue:c61e28722cca"
created: "2026-11-07"
---

# Brief: Bind the sdd-coder durable store writable from a linked worktree

<!-- FEAT-698. One brief = one fix. Task files live in sdd/briefs/<slug>/tasks/. -->

## Problem

An `sdd-worker` running inside a linked worktree reached its
development-to-review boundary and

```
parrot sdd task review prepare --feature <FEAT-ID> --worktree <path> --execution-id <uuid>
```

failed on a read-only filesystem. The worker continued straight to code review
with no persisted checkpoint and recorded, in its completion summary:

> Review checkpoint: `parrot sdd task review prepare` failed because the
> sandbox mounts `artifacts/` read-only. I went straight to code review without
> a persisted checkpoint (`checkpoint: unsupported_host`).

Two things are wrong there. The checkpoint — the neutral, durable evidence the
fresh reviewer is supposed to start from (FEAT-584 R5) — never got written, so
the review ran on the worker's own reasoning instead. And the condition was
reported under a label that means something else entirely.

## Root cause

Two deliberate designs collide, and neither is wrong on its own.

`parrot.flows.dev_loop.sdd_coder.telemetry.resolve_durable_root` resolves the
**main** checkout via `git rev-parse --path-format=absolute --git-common-dir`
and returns `<main checkout>/artifacts/logs/sdd-coder-usage`
(`packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/telemetry.py:150`).
Its docstring states the reason it lives outside the worktree: *"the dataset
must outlive `git worktree remove`"*.

The SDD sandbox binds **writable** only five things: the cwd checkout, the
common `.git`, the primary checkout's worktree root (`worktree_admin_dirs`),
the primary checkout's `.parrot/ledger`
(`shared_ledger_dirs`, `worktree_environment.py:205`, bound at
`worktree_environment.py:308`), and Claude's scratchpad root
`/tmp/claude-<uid>`. The native backend builds the same set at
`native_claude_sandbox.py:402-403`. The rest of the primary checkout —
`artifacts/` included — is read-only *on purpose*.

So from inside a linked worktree the store is readable but not writable, and
every write to it fails.

### Why the obvious workarounds do not apply

- **Writing to a `tempfile` and moving it later.** The store is *shared* with
  the host-side MCP engine, which runs unsandboxed and publishes
  `executions/<id>/artifacts/*.json`. `prepare` **reads** that settlement
  snapshot from the same root and writes the checkpoint beside it; `validate`
  reloads it from there. A write root that differs from the read root breaks
  `validate`.
- **A plain `/tmp` directory.** The bwrap sandbox mounts a private `tmpfs`
  over `/tmp` on every Bash call, so anything outside `/tmp/claude-<uid>`
  (which is explicitly bound back after the tmpfs) is gone by the next command.
- **Moving the files in `/sdd-done`.** That runs later, from the host. The
  checkpoint exists precisely so the *same session's* reviewer starts from
  neutral evidence; arriving after the review is worthless.

## Research findings

**Blast radius.** Both sandboxed CLIs that resolve this root are affected,
because they share the `SDD_CODER_TELEMETRY_DIR` contract:

| Call site | Write |
|---|---|
| `review_checkpoint.py:59` `_build_store` | `executions/<id>/review/<checkpoint_id>.json` |
| `finalize_task.py:512` → `_journal_paths` (`finalize_task.py:286`) | task journal + its lock file |

`parrot sdd task finalize` therefore has the same hole; the same fix closes it,
since both resolve the identical root.

**Three enforcement points, one source list.** `wiki_blast_radius` on
`shared_ledger_dirs` returns `protected_argv` (bwrap) and
`native_sandbox_settings` (native) at distance 1. A third, `validate_native_write_path`
(`native_claude_sandbox.py:501-520`), is the Write/Edit file-tool guard — but it
re-reads `native_sandbox_settings(root)["sandbox"]["filesystem"]["allowWrite"]`,
so extending `allow_paths` covers it automatically with no separate change.
`_we.validate_write_path` (`worktree_environment.py:96-100`) only rejects shared
Python environments and does not touch `artifacts/`.

**`worktree_environment.py` is stdlib-only by contract.** Its module docstring:
*"This file deliberately uses only the standard library and can run directly as
a Claude hook, even when importing the rest of Parrot is unavailable."* It
therefore **cannot** import `telemetry.py` to share the path constant. The
constant must be duplicated, and a test must guard the two against drift.

**Precedent for the narrow bind.** `shared_ledger_dirs` binds exactly
`.parrot/ledger`, not `.parrot/`, and says why in its own comment: *"Only that
directory [is writable] … so the wiki plane and the rest of `.parrot` stay"*
read-only. The same shape applies here.

**Why not all of `artifacts/`.** It is git-ignored, but git-ignored is not the
same as inert. It holds Python the host executes: `artifacts/laya/` (a sub-project
with `runtime.py`, `evaluate.py`, `reporting.py`, `routing.py` and its own
`pyproject.toml`), plus `build_feat627_tasks.py`, `generate_feat804_tasks.py`
and several probe scripts. Making it writable would let a sandboxed seat rewrite
code the unsandboxed host later runs — exactly the escalation the read-only
mount exists to prevent.

**Related ledger issues** (`ledger context` on the touched files returns only
this issue): `issue:cb467a1f6ade` ("Managed runtime: sdd helpers finalize_task /
review_checkpoint crash without navconfig env/ tree") touches the same two CLIs
but is a separate defect — not fixed here.

## Assumptions

`--no-interview` behaviour: every decision below was settled during research, so
no question was asked. Recorded as assumptions:

1. **The store stays where it is.** `resolve_durable_root` is not changed. The
   path keeps its "outlives `git worktree remove`" property; only the sandbox
   learns to allow it.
2. **The bind is the store directory, not `artifacts/`.** A narrow twin of
   `shared_ledger_dirs`, so `artifacts/laya/` and the generator scripts stay
   read-only.
3. **A custom `SDD_CODER_TELEMETRY_DIR` is explicitly out of scope.** The
   sandbox will **not** read that env var and bind whatever it names: an
   env-controlled writable bind is a sandbox-escape surface
   (`SDD_CODER_TELEMETRY_DIR=/` would bind `/` writable). An operator who
   relocates the store must relocate it somewhere already writable; the failure
   stays loud rather than being silently papered over.
4. **`coder_evidence_dirs` creates the directory on the host.** Unlike the
   ledger dir, the store may not exist before the first execution, and bwrap
   cannot bind a missing path. `claude_scratch_root()`
   (`worktree_environment.py:234`) already documents and performs exactly this
   host-side `mkdir` for the same reason.
5. **The mislabel is fixed in the same brief.** Owner confirmed.

## Fix plan

1. **HOTFIX-c61e28722cca-1** — Bind `<primary>/artifacts/logs/sdd-coder-usage`
   writable from a linked worktree, in both sandbox backends, with tests.
2. **HOTFIX-c61e28722cca-2** — Give the engine-path store-write failure its own
   label in the `sdd-worker` prompt, freeing `unsupported_host` for the
   no-engine path it actually means.

The two are independent and may land in either order.

## Validation commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_worker_prompt_orchestrator.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_start_optimization_contract.py -q`
