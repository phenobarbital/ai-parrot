# FEAT-723 — AC-4 real-log retraction evidence

**Date**: 2026-10-22
**Issue**: `issue:1c7d47068c4d`
**Task**: TASK-4603
**Base commit**: `02b8475ff`
**Ledger replayed**: a byte copy of `/home/jesuslara/proyectos/ai-parrot/.parrot/ledger/events.jsonl`
(2436 events). The real log was **never opened for writing** — sha256 before and
after the run is identical: `45a086877d739903168042062923d1fb28835376df396ae16b491e524e016406`.

The only difference between the two runs below is which `coder_feedback.py` is on
`PYTHONPATH`. The log file is the same bytes in both.

> **Harness gotcha worth recording**: `python -I` *ignores* `PYTHONPATH`, so an
> isolated-mode run inside a worktree silently imports the main checkout's
> editable install. The first attempt at this evidence did exactly that and
> reported a false FAIL. Run evidence scripts without `-I` and assert
> `module.__file__` before trusting the result.

## BEFORE — `dev`'s code (no tombstone handling)

```
log events total           : 2436
  insight.recorded         : 723
  insight.superseded       : 4
misattributed records      : 4
    coder-feedback:298a2946b86d3c0a452654ca
    coder-feedback:2dc3591d1159566f512e9174
    coder-feedback:df08b552b9c7ec047a937236
    coder-feedback:fb88c2ea4281dfbf093125c1
coder_feedback tombstones  : 4
tombstones match records   : True
misattributed STILL live   : 4
context() mentions pattern : True
context() length (chars)   : 7058

AC-4 VERDICT               : FAIL
```

All four tombstones were already in the log (appended `2026-09-22T13:56:43` by
`human:jesus`) and their subjects match the four recordings exactly — yet every
record is still live, and `context("codex", "gpt-5.6-terra", ["artifacts/laya/models.py"])`
renders the `gitignored-file-not-force-added` lesson. **The retraction was inert
for a month while the audit trail recorded it as done.**

## AFTER — FEAT-723 (`CoderFeedbackStore.retract` + tombstone-aware `_read`)

```
log events total           : 2436
  insight.recorded         : 723
  insight.superseded       : 4
misattributed records      : 4
coder_feedback tombstones  : 4
tombstones match records   : True
misattributed STILL live   : 0
context() mentions pattern : False
context() length (chars)   : 6725

AC-4 VERDICT               : PASS
```

- All 4 records dropped from replay.
- `context()` no longer renders the pattern; it shrank 7058 → 6725 chars, the
  removed lesson block.
- **Event counts are identical** (2436 total, 723 `insight.recorded`,
  4 `insight.superseded`) — nothing was rewritten, deleted or appended. The fix
  is pure replay semantics over an untouched append-only log.

## The affected records

| subject (tail) | task | backend / model | files |
|---|---|---|---|
| `…ec047a937236` | TASK-3605 | `codex` / `gpt-5.6-terra` | `artifacts/laya/__init__.py`, `artifacts/laya/models.py` |
| `…dfbf093125c1` | TASK-3611 | `codex` / `gpt-5.6-terra` | `artifacts/laya/routing.py` |
| `…566f512e9174` | TASK-3614 | `codex` / `gpt-5.6-terra` | `artifacts/laya/scenarios.py` |
| `…3c0a452654ca` | TASK-3616 | `codex` / `gpt-5.6-terra` | `artifacts/laya/evaluate.py` |

Retraction reason recorded in each tombstone: *"Misattributed: codex seat runs
with .git read-only and cannot git add; the engine extraction could not see
gitignored declared files (fixed in PR #1460)"*.

## AC-7 — the new test covers the defect

`test_retracted_feedback_is_dropped_from_replay` was run against the unmodified
`coder_feedback.py` and **failed**; it passes after the change.

```
1 failed, 7 warnings in 0.62s      # base coder_feedback.py
24 passed, 15 warnings in 4.86s    # patched (23 pre-existing + 1 new)
```

---

# TASK-4604 — `ledger retract-feedback` CLI evidence

**Date**: 2026-10-22

`.parrot/ledger/events.jsonl` sha256 was identical before and after every probe
below (`b310499aa6d9269a240402c470866c00667114c31c941f4d8c9c849940166601`,
2437 lines) — the failure path appends nothing.

> Only **deliberately fake** ids were used. The success path is *not* exercised
> against the live ledger, because that would append a real tombstone to shared
> state; `test_retracted_feedback_is_dropped_from_replay` covers the `True`
> branch against a `tmp_path` store instead.

## AC-4 — the command is registered

```
$ wikitoolkit ledger retract-feedback --help
Usage: wikitoolkit ledger retract-feedback [OPTIONS] FEEDBACK_IDS...

  Withdraw misattributed coder feedback (`coder-feedback:<digest>` ids) from
  model lessons.

Options:
  --reason TEXT  Why the recorded correction is wrong (kept in the audit
                 trail).  [required]
  --actor TEXT   Actor withdrawing the correction, e.g. human:jesus.
  --help         Show this message and exit.

$ wikitoolkit ledger --help | grep retract-feedback
  retract-feedback  Withdraw misattributed coder feedback...
```

## AC-2 / AC-5 — unknown id reports and exits 1

```
$ wikitoolkit ledger retract-feedback coder-feedback:000000000000000000000000 --reason "..."
Could not retract coder-feedback:000000000000000000000000 (unknown or already retracted)
exit=1
```

## AC-3 — every id is reported, with a single exit after the loop

```
$ wikitoolkit ledger retract-feedback coder-feedback:0000... coder-feedback:1111... --reason "..."
Could not retract coder-feedback:000000000000000000000000 (unknown or already retracted)
Could not retract coder-feedback:111111111111111111111111 (unknown or already retracted)
exit=1
```

Both ids are reported — the loop does not exit on the first failure, which is the
one behavioural difference from the `ledger_unclaim` template it was modelled on.

## AC-6 / AC-7

`ruff check` and `black --check --line-length 120` clean on `cli.py`;
`test_cli_remote_push.py` 8 passed (it imports `parrot.knowledge.wiki.cli` and
drives it through `CliRunner`, so it gates the module's import and Click wiring);
`test_feedback.py` 24 passed.
