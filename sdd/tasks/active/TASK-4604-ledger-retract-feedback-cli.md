# TASK-4604: `wikitoolkit ledger retract-feedback` CLI command

**Feature**: FEAT-723 — Retractable coder feedback (`insight.superseded` tombstones)
**Spec**: `sdd/specs/ledger-coder-feedback-fixes.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4603
**Assigned-to**: unassigned

---

## Context

`TASK-4603` adds `CoderFeedbackStore.retract()`, which withdraws a misattributed
coder-feedback lesson by appending an `insight.superseded` tombstone. Without a
CLI, the only way to retract one is to write Python by hand or hand-edit
`.parrot/ledger/events.jsonl` — the latter would corrupt an append-only log whose
integrity is the point of the feature.

This task exposes `retract()` as `wikitoolkit ledger retract-feedback`, so a human
who spots a misattribution (as happened in FEAT-589, where four
`gitignored-file-not-force-added` defects were charged to a codex model whose
sandbox cannot commit at all) can withdraw it with one command.

Completes the fix tracked as `issue:1c7d47068c4d`; `TASK-4603` carries the formal
`Discovered-from` link.

## Scope

Add a `@ledger.command("retract-feedback")` Click command: variadic feedback ids,
required `--reason`, optional `--actor`, one echo line per id, exit `1` if any id
could not be retracted.

**NOT in scope**: `retract()` itself (`TASK-4603`); a Click-runner test harness
for `ledger` subcommands (none exists in this repo, and adding one is a separate
concern); `--dry-run`; reading ids from stdin or a file; `remote_cli.remote_aware`
proxying (retraction is a local-ledger write, not a proxied read).

---

## Files to Create / Modify

| File | Action | Why |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | add the `retract-feedback` subcommand |

---

## Codebase Contract (Anti-Hallucination)

Verified against `02b8475ff`.

### Verified Imports

Already at module scope in `cli.py` — add neither:

```python
import click
from pathlib import Path, PurePosixPath   # :40 — `Path` is available at module scope
```

Added **inside** the command body (cli.py has 55 in-function `from parrot.`
imports — verified: `grep -c '^    from parrot\.' cli.py` → `55` — so this is the
module's established pattern, and it keeps CLI startup light):

```python
    from parrot.knowledge.wiki.ledger.coder_feedback import CoderFeedbackStore
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py
def _run(coro: Any) -> Any:                     # line 580 — returns asyncio.run(coro)
@click.group()  # the `ledger` group these subcommands hang off
# sibling command, the style to copy:
@ledger.command("unclaim")                      # line 3535
def ledger_unclaim(issue_id: str, reason: str, actor: str) -> None:   # line 3539
    #   service = LedgerService.from_root()
    #   if _run(service.unclaim(...)): click.echo(f"Unclaimed {issue_id}")
    #   else: click.echo("Could not unclaim ..."); raise SystemExit(1)
```

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_feedback.py
class CoderFeedbackStore:
    @classmethod
    def from_root(cls, root: Path) -> CoderFeedbackStore:   # line 92 — root is REQUIRED
    async def retract(self, feedback_id: str, reason: str, actor: str) -> bool:
        # created by TASK-4603; insert position: directly above _read() at line 114
```

### Does NOT Exist

- ~~`CoderFeedbackStore.from_root()` with no argument~~ — `root` is **required**
  (unlike `LedgerService.from_root(root: Path | None = None)` at `service.py:167`,
  which the neighbouring commands call bare). Pass `Path.cwd()`.
- ~~`service.retract_feedback(...)` on `LedgerService`~~ — retraction lives on
  `CoderFeedbackStore`, not on `LedgerService`.
- ~~`@ledger.command("retract")`~~ — the command name is `retract-feedback`;
  a bare `retract` would read as an *issue* operation.
- ~~`CoderFeedbackStore` at cli.py module scope~~ — not imported today
  (verified: `grep -n 'CoderFeedback' cli.py` → no match). Import it in-function.
- ~~`WikiStoreBusy` wrapping for this command~~ — `retract()` touches the
  append-only log, not the SQLite index, so there is no busy-index path to catch.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/cli.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#_run",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#ledger_unclaim",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_feedback.py#CoderFeedbackStore.from_root"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow

`ledger_unclaim` (`cli.py:3535-3550`) is the template: decorators, a `bool`-returning
async call wrapped in `_run(...)`, an echo on each branch, `raise SystemExit(1)` on
failure. Differences: this command is **variadic** (`nargs=-1`), so it must not exit
on the first failure — it reports every id and exits once at the end.

### Key Constraints

- `--actor` defaults to `agent:cli`, matching every sibling `ledger` command.
- Accumulate failures in a counter and `raise SystemExit(1)` *after* the loop, so a
  caller passing four ids sees all four outcomes. Exiting inside the loop would hide
  the rest.
- Do not add `@remote_cli.remote_aware` — that decorator is for proxied reads
  (`ledger context`), and a retraction must hit the local shared ledger.
- 120-column lines, `black`, Google-style docstring, strict type hints.

### References in Codebase

- `cli.py:3553` `ledger_context` — the insertion point sits directly above it.
- `cli.py:580` `_run` — the only sanctioned way to call an async store from Click here.

---

## Implementation Blueprint

### Steps (in order)

1. Confirm `TASK-4603` is `done` in the per-spec index and that
   `CoderFeedbackStore.retract` exists — *why*: this command is a thin wrapper and
   cannot be validated before the method it calls exists.
2. Insert the command block directly **above** `@ledger.command("context")` —
   *why*: it keeps the write commands (`claim`/`unclaim`/`retract-feedback`)
   grouped before the read commands, matching the file's existing order.
3. Run the Validation Commands, then `ruff check --fix` and `black` on `cli.py`.
4. Verify by hand: `wikitoolkit ledger retract-feedback --help` lists the command,
   and an unknown id exits `1` while appending no event — *why*: AC-4 and AC-5 have
   no automated harness, so they are evidence steps.

### `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -c '@ledger.command("context")' packages/ai-parrot/src/parrot/knowledge/wiki/cli.py)
# BEFORE — insert above `@ledger.command("context")` (verified: cli.py:3553)
@ledger.command("retract-feedback")
@click.argument("feedback_ids", nargs=-1, required=True)
@click.option("--reason", required=True, help="Why the recorded correction is wrong (kept in the audit trail).")
@click.option("--actor", default="agent:cli", help="Actor withdrawing the correction, e.g. human:jesus.")
def ledger_retract_feedback(feedback_ids: tuple[str, ...], reason: str, actor: str) -> None:
    """Withdraw misattributed coder feedback (`coder-feedback:<digest>` ids) from model lessons."""
    from parrot.knowledge.wiki.ledger.coder_feedback import CoderFeedbackStore

    store = CoderFeedbackStore.from_root(Path.cwd())
    missing = 0
    for feedback_id in feedback_ids:
        # FILL IN: call store.retract(...) through _run(...), echo the outcome for THIS id,
        # and increment `missing` on a False return — bounded by AC-1/AC-2/AC-3
    if missing:
        raise SystemExit(1)
```

**Why this shape**: the signature, command name, option names and defaults are fixed
by the spec and must not change. The loop body is the only decision left: it must
report every id rather than exiting early (AC-3), which is the one way this command
differs from `ledger_unclaim`. `Path.cwd()` is required because
`CoderFeedbackStore.from_root` takes no default root.

### FILL IN checklist

- [ ] `cli.py::ledger_retract_feedback` — the loop body: `_run(store.retract(...))`,
      a success echo (`f"Retracted {feedback_id}"`) and a failure echo naming the
      reason (`"unknown or already retracted"`), plus the `missing` increment;
      bounded by AC-1, AC-2, AC-3.

---

## Acceptance Criteria

- [ ] AC-1 `wikitoolkit ledger retract-feedback <live-id> --reason "..."` retracts it
      and echoes one success line per id.
- [ ] AC-2 An unknown or already-retracted id echoes a failure line naming the cause
      and does **not** append an event.
- [ ] AC-3 Given several ids where some fail, every id is reported and the process
      exits `1` **once**, after the loop — never on the first failure.
- [ ] AC-4 `wikitoolkit ledger retract-feedback --help` lists the command with its
      `--reason` and `--actor` options.
- [ ] AC-5 Exit code is `0` when every id was retracted, `1` when any failed.
- [ ] AC-6 `ruff check` and `black --check` clean on `cli.py`.
- [ ] AC-7 No existing `ledger` subcommand changes behaviour.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_cli_remote_push.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_feedback.py -q`

> `test_cli_remote_push.py` imports `parrot.knowledge.wiki.cli` directly
> (`:8 from parrot.knowledge.wiki.cli import wiki`) and drives it through
> `CliRunner`, so it fails if this task breaks the module's import or its Click
> wiring — verified green on this base (8 passed). It is the gate for AC-6/AC-7.
> AC-4 and AC-5 have no automated harness; record them as the manual `--help`
> and unknown-id evidence from step 4. Never substitute a directory-wide run.

---

## Test Specification

No new automated test. The command is a thin Click wrapper over
`CoderFeedbackStore.retract()`, which `TASK-4603` covers directly; this repo has no
Click-runner harness for `ledger` subcommands and building one is out of scope
(spec §4 "Integration Tests"). AC-4 and AC-5 are satisfied by the recorded manual
evidence from step 4, captured into
`artifacts/logs/feat-723-retraction-evidence.md`.

---

## Agent Instructions

1. **Work in the feature worktree** `.claude/worktrees/feat-FEAT-723-ledger-coder-feedback-fixes` — never on `dev`.
2. **Read the spec** at `sdd/specs/ledger-coder-feedback-fixes.spec.md` (§3 Module 2).
3. **Check dependencies** — `TASK-4603` must be `"done"` in
   `sdd/tasks/index/ledger-coder-feedback-fixes.json`. If it is not, stop.
4. **Verify the Codebase Contract** before writing code: re-run the blueprint's
   `# occurrences:` grep. A count of `0` means the anchor moved — stop and report.
5. **Update status** in the per-spec index → `"in-progress"` with `started_at`,
   and commit only that index file.
6. **Implement** from the blueprint; complete the one `# FILL IN:` marker.
7. **Verify** the acceptance criteria, including the manual `--help` and
   unknown-id checks.
8. **Commit the code** — stage only `cli.py`.
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4604 ledger-coder-feedback-fixes verified`.
10. **Fill in the Completion Note**, then commit the staged SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
