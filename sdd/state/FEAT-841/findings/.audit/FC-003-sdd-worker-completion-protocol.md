---
id: FC-003
query_id: Q017
type: read
intent: "Read sdd-worker's closing protocol: what it does after the last task (review, Completion Notes, notification, never push)."
executed_at: 2026-11-07T01:21:26Z
duration_ms: 3500
parent_id: null
depth: 0
---

# FC-003 — sdd-worker ends by self-reviewing, printing "✅ Feature completed" and telling the human to run /sdd-done

## Summary

`.claude/agents/sdd-worker.md` §Completion (lines 624-772) is the worker's end-of-feature protocol: (0) settle children and persist a durable review checkpoint (`parrot sdd task review prepare`, FEAT-584) whose `checkpoint_id` binds HEAD/branch/base SHA/spec/index hashes; (1) run its own `code-reviewer` agent with a neutral brief and file deferred findings in the ledger (a deferred 🔴 is filed `critical` and "blocks /sdd-done"); (2) never push (sandbox has no route to github); (2a) optionally record a desktop completion receipt via `worker_notification.py --complete`; (3) print a `✅ Feature FEAT-<ID> — <title> completed.` summary ending with "Run /sdd-done FEAT-<ID> from the host". The worker therefore **declares its own completion** today; the only artifacts it leaves are the per-spec index (all tasks `done`), the review checkpoint, ledger issues it filed, and the optional `notify-complete.json` receipt. No event tells the host "work completed" other than the printed summary.

## Citations

- path: `.claude/agents/sdd-worker.md`
  lines: 624-636
  symbol: null
  excerpt: |
    ## Completion
    After all tasks are done, at the development-to-review boundary:
    0. **Settle, checkpoint, compact-or-explicit-outcome, then a fresh reviewer.**
       `parrot sdd task review prepare --feature <FEAT-ID> --worktree <path> --execution-id <uuid>`.
       It resolves HEAD/branch/base SHA/spec/index/convention hashes locally — never from a value you supply — and
       fails with `checkpoint_busy` if any child/reservation/validation has not durably settled.

- path: `.claude/agents/sdd-worker.md`
  lines: 649-658
  symbol: null
  excerpt: |
     `parrot sdd task review validate --feature <FEAT-ID> --worktree <path> --execution-id <uuid>
     --checkpoint-id <id>`. A `checkpoint_stale` result (branch/HEAD/spec/index/convention hashes moved since
     `prepare`) means no prior approval covers the new diff — regenerate the checkpoint rather than reviewing stale
     evidence.
    1. **Code review** — invoke the `code-reviewer` agent with a neutral adversarial brief.

- path: `.claude/agents/sdd-worker.md`
  lines: 708-717
  symbol: null
  excerpt: |
    Map 🟠 → `major`, 🟡 → `minor`, 💡 → `low` (🔴 is always fixed; if you ever
    defer one, file it as `critical` — it blocks `/sdd-done`).
    2. **Do NOT push.** The sandbox has no route to `github.com` (no git-over-HTTPS, no SSH); `/sdd-done`
       on the host pushes.

- path: `.claude/agents/sdd-worker.md`
  lines: 719-727
  symbol: null
  excerpt: |
    2a. **Record optional desktop completion (feature scope only).** Only after all
        tasks are done, children have settled, review/deferred-finding handling is
        complete and step 2 pushed successfully, run from the feature worktree:
        if [ -n "${PARROT_SDD_NOTIFY_PYTHON:-}" ] && [ -n "${PARROT_SDD_NOTIFY_HELPER:-}" ]; then
          "$PARROT_SDD_NOTIFY_PYTHON" -S "$PARROT_SDD_NOTIFY_HELPER" --complete
        fi

- path: `.claude/agents/sdd-worker.md`
  lines: 735-772
  symbol: null
  excerpt: |
    3. **Print summary:**
       ✅ Feature FEAT-<ID> — <title> completed.
       Next:
         - Run /sdd-done FEAT-<ID> **from the host** (outside this sdd-worker
           session) — it pushes, opens the PR and cleans up.

- path: `.claude/agents/sdd-worker.md`
  lines: 596-615
  symbol: null
  excerpt: |
    ### g) Update SDD State (in worktree, alongside code — FEAT-145)
    # Move active → completed with `git mv`, stamp the index (status/completed_at/
    # verification/file), stage both, and HARD-VERIFY no active/ copy survives.
    # Fill in Completion Note in the moved task file (in completed/).
    # Stage and commit on the feature branch (NOT the main repo's BASE_BRANCH)

## Notes

- The worker's review checkpoint (FEAT-584) is already a "verdict bound to a head SHA" shape: `checkpoint_stale` when HEAD moves. An escrow verdict could reuse this binding semantic.
- The worker's `code-reviewer` is the "code-reviewer del worker" the user refers to — same session lineage, so not independent.
- [cross-lane: type=wiki_query, intent=FEAT-584 execution optimization spec / review checkpoint model (parrot.flows.dev_loop.sdd_coder.checkpoint)]
