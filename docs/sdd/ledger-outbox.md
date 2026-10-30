# Ledger outbox (FEAT-758)

## Model

The local journal at `<ledger-dir>/events.jsonl` (resolved by `LedgerService.from_root`) is the source of pending events. `wikitoolkit ledger outbox prepare` seals a finite, complete prefix into `<ledger-dir>/outbox/pending/<uuid>/`; it does not alter a feature checkout. The integrator then uses a temporary checkout of `origin/dev` to merge the sealed events and regenerate the canonical snapshot. Only after remote content verification succeeds does it write `<ledger-dir>/outbox/receipts/<uuid>.json`.

Feature PRs contain code and task artifacts only. Canonical ledger data is delivered independently to `origin/dev`.

## Commands and exit codes

All commands require `--repo-root PATH`; `--ledger-dir PATH` explicitly selects the private local journal. Add `--json` for structured output.

| Command | Purpose |
| --- | --- |
| `wikitoolkit ledger outbox prepare --repo-root PATH [--ledger-dir PATH]` | Seal currently eligible local events. |
| `wikitoolkit ledger outbox status --repo-root PATH [--ledger-dir PATH]` | Show sealed batches, unsealed events, and legacy contamination without delivery. |
| `wikitoolkit ledger outbox integrate --repo-root PATH [--ledger-dir PATH] [--batch-id UUID]` | Deliver pending batches, or retry one named batch. |

| Exit code | Meaning |
| --- | --- |
| 0 | Prepared, delivered, already delivered, or no work remains. |
| 2 | Pending I/O, lock, or retry-exhaustion failure; retain the batch and retry. |
| 3 | Invalid content or semantic conflict requiring review. |
| 4 | Unsupported source/destination or legacy feature-diff contamination. |

## Recovery and migration

### Migrate installed hooks

Run `parrot claude install` to upgrade the managed `parrot-ledger` block. Seal existing local events with `wikitoolkit ledger outbox prepare --repo-root <worktree>`, then deliver with `wikitoolkit ledger outbox integrate --repo-root <worktree>`. Verify the remote `origin/dev` ledger content before considering migration complete.

### Legacy feature diff

If `outbox status` exits 4 and reports `contaminated_paths`, first back up the branch's ledger files. Import any missing committed events into the local journal with `wikitoolkit ledger import-log --repo-root <worktree>`, then prepare and deliver the local journal. After review, clean up only the two canonical files and commit that scoped cleanup:

```bash
git restore --source "$(git merge-base origin/dev HEAD)" -- sdd/ledger/events.jsonl sdd/ledger/issues.jsonl
git commit -am "chore: remove legacy ledger diff"
```

Never restore the whole `sdd/ledger/` directory: ID allocation and archives are outside this cleanup. Never rewrite already-published history automatically.

### Retry after a crash

Retry the immutable batch with `wikitoolkit ledger outbox integrate --repo-root <worktree> --batch-id <id>`. Remote verification makes a push that succeeded before a crash idempotent and writes its receipt only after the content is confirmed.

### Source machine unavailable

Undelivered events exist only in that machine's journal and outbox. Recover them from its backup of `<ledger-dir>/events.jsonl` and `<ledger-dir>/outbox/`; a feature PR is not a backup of unshipped ledger data.

## Limits

The outbox does not provide distributed claims; conflicts require review. Rotation is explicit maintenance via `wikitoolkit ledger rotate-log --older-than-days N` and is no longer run by `/sdd-done`. Server policy that blocks a push to `dev` leaves delivery pending; there is no fallback to `main`. Remote-only MCP ledgers are unsupported by this local outbox workflow. Back up `<ledger-dir>/` regularly.
