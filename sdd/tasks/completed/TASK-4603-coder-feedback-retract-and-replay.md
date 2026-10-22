# TASK-4603: `CoderFeedbackStore.retract()` and tombstone-aware replay

**Feature**: FEAT-723 — Retractable coder feedback (`insight.superseded` tombstones)
**Spec**: `sdd/specs/ledger-coder-feedback-fixes.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:1c7d47068c4d`

---

## Context

`CoderFeedbackStore` cannot withdraw a recorded correction. `_read()`
(`coder_feedback.py:114-126`) replays every `insight.recorded` event whose
`category` is `coder_feedback` forever, so a lesson charged to the wrong party is
permanent and is re-injected by `context()` into every future dispatch for that
backend/model.

The retraction for the known case was **already performed and committed, but
never took effect**: `.parrot/ledger/events.jsonl` holds 4 `insight.superseded`
tombstones appended `2026-09-22T13:56:43` by `human:jesus`, whose subjects match
4 misattributed records exactly — yet the filter at `coder_feedback.py:118`
(`if event.kind != "insight.recorded" …: continue`) skips them entirely. The 4
bogus `gitignored-file-not-force-added` defects (FEAT-589,
TASK-3605/3611/3614/3616) are still live in replay a month on, while the audit
trail records them as retracted.

This task is the core of the fix (port of orphaned commit `cc5d1a6157`).
`TASK-4604` adds the CLI on top of the `retract()` this task creates.

## Scope

1. Add `CoderFeedbackStore.retract(feedback_id, reason, actor) -> bool`, which
   appends an `insight.superseded` tombstone, or returns `False` **without
   appending** when the id is unknown or already retracted.
2. Teach `_read()` to honour `coder_feedback` tombstones during replay.
3. Add `test_retracted_feedback_is_dropped_from_replay`.

**NOT in scope**: the CLI command (`TASK-4604`); retracting `coder_review` or
`coder_suspension` insights; any `LedgerIndex` reducer for `insight.superseded`
(`index.py:125` ignores unowned kinds on purpose — adding one is a defect);
changing `record()`, `context()`, or the `CoderFeedback` model; re-recording the
corrected feedback against the right party.

---

## Files to Create / Modify

| File | Action | Why |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_feedback.py` | MODIFY | add `retract()`; make `_read()` honour tombstones |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_feedback.py` | MODIFY | append the one new test |

---

## Codebase Contract (Anti-Hallucination)

Verified against `02b8475ff`.

### Verified Imports

Every symbol this task needs is **already imported** at the top of
`coder_feedback.py`. Add no import.

```python
import asyncio                                                                        # :5
from parrot.knowledge.wiki.ledger.events import InsightRecordedPayload, LedgerEvent   # :15
from parrot.knowledge.wiki.ledger.log import LedgerLog                                # :16
```

In the test file, already imported — add no import:

```python
from parrot.knowledge.wiki.ledger.coder_feedback import CoderFeedback, CoderFeedbackStore  # :13
from parrot.knowledge.wiki.ledger.log import LedgerLog                                     # :16
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_feedback.py
logger = logging.getLogger(__name__)                                        # line 20

class CoderFeedback(BaseModel):                                             # line 24
    def feedback_id(self) -> str:                                           # line 67
        """Returns "coder-feedback:<24 hex chars>"."""

class CoderFeedbackStore:                                                   # line 80
    def __init__(self, log: LedgerLog) -> None:                             # line 87
    @classmethod
    def from_root(cls, root: Path) -> CoderFeedbackStore:                   # line 92
    async def record(self, feedback: CoderFeedback) -> CoderFeedbackReceipt:  # line 96
        # appends via: await asyncio.to_thread(self.log.append, event)      # line 111
    def _read(self) -> list[tuple[str, CoderFeedback]]:                     # line 114
        # replays via: for event, _offset in self.log.iter_events():        # line 117
        # dedupes via: records.setdefault(feedback.feedback_id(), (event.ts, feedback))  # line 126
    async def context(self, backend: str, model: str, files: list[str],
                      max_tokens: int = 1800, max_age_days: int = 90) -> str:  # line 129
```

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py
class LedgerEvent(BaseModel):                       # line 103
    event_id: str = Field(default="")               # line 106
    kind: LedgerEventKind                           # line 107
    subject: str                                    # line 108
    actor: str                                      # line 109
    ts: str                                         # line 110
    payload: dict[str, Any]                         # line 111 — a PLAIN dict is valid

LEDGER_EVENT_KINDS = (..., "insight.recorded", "insight.superseded", ...)   # :18-19
```

```python
# packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_feedback.py
def feedback(**overrides: object) -> CoderFeedback:   # line 22 — accepts pattern=, files=, model=
@pytest.fixture
def store(tmp_path: Path) -> CoderFeedbackStore:      # line 42 — tmp_path-backed store
```

### Does NOT Exist

- ~~`CoderFeedbackStore.retract()`~~ — this task adds it.
- ~~`InsightSupersededPayload`~~ — **no such model** anywhere in
  `parrot.knowledge.wiki.ledger`. `events.py` declares the *kind string* only;
  the tombstone payload is a plain `dict`. Do not import or invent it.
- ~~`CoderFeedbackStore.unrecord()` / `.delete()` / `.forget()` / `.supersede()`~~ — not real.
- ~~`LedgerLog.remove()` / `.rewrite()` / `.truncate()`~~ — the log is append-only.
- ~~`LedgerIndex._apply_insight_superseded`~~ — does not exist and must NOT be added.
- ~~`store.retracted_ids` / `_retractions` attribute~~ — not real; no state is cached.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_feedback.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_feedback.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_feedback.py#CoderFeedbackStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_feedback.py#CoderFeedbackStore._read",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_feedback.py#CoderFeedbackStore.record",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_feedback.py#CoderFeedback.feedback_id",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py#LedgerEvent"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow

`retract()` mirrors `record()` (`:96-112`) exactly: build a `LedgerEvent`, then
`await asyncio.to_thread(self.log.append, event)`. Keep blocking file I/O off the
event loop — that is why `to_thread` is used for both the `_read()` probe and the
append.

### Key Constraints

- **Ordering is the semantics.** The tombstone branch goes *before* the
  `insight.recorded` filter in `_read()`. Replay is one forward pass over
  `log.iter_events()`, so a tombstone drops only recordings already seen; a later
  re-record of the same occurrence legitimately counts again. Do **not**
  pre-collect retracted ids into a set and filter with it — that would also kill
  post-tombstone re-recordings, breaking AC-6.
- **Leave `records.setdefault` (`:126`) as is.** Retraction `pop`s the key
  entirely, so a re-record after a tombstone becomes the new first write.
- `payload["category"] = "coder_feedback"` is mandatory — it is how replay tells a
  coder-feedback tombstone from any other future `insight.superseded` producer.
- 120-column lines, `black` formatting, Google-style docstrings, strict hints.

### References in Codebase

- `coder_reviews.py:97` and `coder_suspensions.py:318` use the same
  `insight.recorded` + `category` filter idiom — do not touch them.
- `shared_log.py:27` — `SUPERSEDING_CLAIM_KINDS` does **not** contain
  `insight.superseded`, so this tombstone cannot supersede an issue claim.

---

## Implementation Blueprint

### Steps (in order)

1. Insert `retract()` immediately **above** `def _read(self)` — *why*: it is a
   public write method and belongs beside `record()`, before the private reader.
2. Add the tombstone branch as the **first** statement inside `_read()`'s
   `for` loop — *why*: it must be reached before the `insight.recorded` filter
   `continue`s past the event, and order encodes the before/after semantics.
3. Update `_read()`'s docstring — *why*: the dedupe rule now has a second half.
4. Append the new test at the end of the test file — *why*: it reuses the
   module-level `store` fixture and `feedback()` helper already defined there.
5. Run the Validation Commands, then `ruff check --fix` and `black` on both files.

### `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_feedback.py` (MODIFY — 1 of 2)

```python
# occurrences: 1 (verified: grep -c 'def _read(self) -> list\[tuple\[str, CoderFeedback\]\]:' packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_feedback.py)
# BEFORE — insert above `    def _read(self) -> list[tuple[str, CoderFeedback]]:` (verified: coder_feedback.py:114)
    async def retract(self, feedback_id: str, reason: str, actor: str) -> bool:
        """Withdraw a recorded correction by appending an ``insight.superseded`` tombstone.

        The event log is append-only, so a misattributed lesson is never rewritten
        out; replay simply drops every recording of ``feedback_id`` made before the
        tombstone. A later recording of the same occurrence counts again.

        Args:
            feedback_id: The ``coder-feedback:<digest>`` subject to withdraw.
            reason: Why the correction is wrong; kept for the audit trail.
            actor: Who withdraws it, e.g. ``human:jesus``.

        Returns:
            ``True`` when a live record was retracted; ``False`` (nothing appended)
            when ``feedback_id`` is unknown or already retracted.
        """
        live = {fb.feedback_id() for _ts, fb in await asyncio.to_thread(self._read)}
        if feedback_id not in live:
            return False
        event = LedgerEvent(
            kind="insight.superseded",
            subject=feedback_id,
            actor=actor,
            payload={"category": "coder_feedback", "reason": reason, "retracted_by": actor},
        )
        await asyncio.to_thread(self.log.append, event)
        return True
```

**Why this shape**: the live-set probe is what makes the return value meaningful —
an unknown or already-retracted id appends nothing, so the CLI in `TASK-4604` can
exit non-zero instead of silently piling up duplicate tombstones. The payload is a
plain dict (there is no `InsightSupersededPayload`), and `category` is what replay
keys on. Do not change the signature, the return type, or the payload keys.

### `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_feedback.py` (MODIFY — 2 of 2)

```python
# occurrences: 1 (verified: grep -c 'if event.kind != "insight.recorded" or event.payload.get("category") != "coder_feedback":' packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_feedback.py)
# BEFORE — insert above `            if event.kind != "insight.recorded" or event.payload.get("category") != "coder_feedback":` (verified: coder_feedback.py:118)
            if event.kind == "insight.superseded" and event.payload.get("category") == "coder_feedback":
                records.pop(event.subject, None)
                continue
```

Also replace `_read()`'s one-line docstring (`coder_feedback.py:115`) with:

```python
        """Replay this plane only; duplicate recordings count once; retractions drop earlier records."""
```

**Why**: the `pop` must run before the `insight.recorded` guard, or the guard
`continue`s and the tombstone is never seen — that single ordering is the whole
defect being fixed.

### `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_feedback.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -c 'async def test_review_and_feedback_coexist' packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_feedback.py)
# AFTER — append at end of file, below the last line of `async def test_review_and_feedback_coexist` (verified: test_feedback.py:488)


async def test_retracted_feedback_is_dropped_from_replay(store: CoderFeedbackStore) -> None:
    """A misattributed correction can be withdrawn without rewriting the append-only log.

    FEAT-589 recorded four "forgot `git add -f`" defects against a codex model whose
    sandbox cannot commit at all (the engine's extraction was the bug). Retraction
    appends an `insight.superseded` tombstone; replay drops the record, other
    patterns and other models are untouched, and a later re-recording of the same
    occurrence is a fresh confirmation again.
    """
    wrong = feedback(pattern="gitignored-file-not-force-added", files=["artifacts/x.py"], model="gpt-5.6-terra")
    real = feedback(pattern="unverified-fixture-schema-drift", model="gpt-5.6-terra")
    await store.record(wrong)
    await store.record(real)

    # FILL IN: assert retract() returns True for the live id, and False for both an
    # unknown id and a second retraction of `wrong` — bounded by AC-1/AC-2/AC-3

    restarted = CoderFeedbackStore(LedgerLog(store.log.path))
    # FILL IN: assert context("nova", "gpt-5.6-terra", ["artifacts/x.py"]) drops the
    # retracted pattern but still contains "unverified-fixture-schema-drift" — AC-4
    # FILL IN: assert the log holds 2 insight.recorded and 1 insight.superseded via
    # [event.kind for event, _offset in restarted.log.iter_events()] — AC-5
    # FILL IN: re-record `wrong`, then assert it is live again at
    # "confirmed deliveries: 1" — AC-6
```

**Why**: the fixture-and-helper preamble is mechanical and fixed; the assertions are
the task's real content and are left as bounded `FILL IN` stubs. `restarted` must be
a *fresh* store over the same path — that is what proves the behaviour comes from
replay and not from in-memory state.

### FILL IN checklist

- [ ] `test_feedback.py::test_retracted_feedback_is_dropped_from_replay` — the three
      `retract()` return-value assertions; bounded by AC-1, AC-2, AC-3.
- [ ] same test — the post-restart `context()` assertions (retracted pattern gone,
      unrelated pattern kept); bounded by AC-4.
- [ ] same test — the event-kind count assertion proving nothing was deleted;
      bounded by AC-5.
- [ ] same test — the re-record assertion proving a tombstone does not block a
      later confirmation; bounded by AC-6.

---

## Acceptance Criteria

- [ ] AC-1 `retract()` returns `True` for a live `feedback_id` and appends exactly
      one `insight.superseded` event.
- [ ] AC-2 `retract()` returns `False` and appends **nothing** for an unknown id.
- [ ] AC-3 `retract()` returns `False` and appends **nothing** when the id was
      already retracted.
- [ ] AC-4 After reopening the log, `context()` omits the retracted pattern and
      still renders an unrelated pattern for the same backend/model.
- [ ] AC-5 The log keeps every original event: 2 `insight.recorded` + 1
      `insight.superseded`; nothing is rewritten or deleted.
- [ ] AC-6 Re-recording the same occurrence after a tombstone makes it live again
      at `confirmed deliveries: 1`.
- [ ] AC-7 The new test **fails** against unmodified `coder_feedback.py` (proof it
      covers the defect), and passes after the change.
- [ ] AC-8 `ruff check` and `black --check` clean on both changed files.
- [ ] AC-9 No signature change to `record()`, `context()`, `_read()`'s return type,
      or the `CoderFeedback` model.

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_feedback.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_feedback.py::test_retracted_feedback_is_dropped_from_replay -q`

---

## Test Specification

One new test, specified by the blueprint block above. Uses the existing
`store` fixture (`test_feedback.py:42`) and `feedback()` builder (`:22`). No new
fixture, no `fakeredis`, no network, no Redis.

Run inside the worktree with `PYTHONPATH=packages/ai-parrot/src`. The Cython
`parrot.utils.types` `.so` exists only in the main checkout — copy it in if the
import fails; never run `uv sync` inside a worktree.

---

## Agent Instructions

1. **Work in the feature worktree** `.claude/worktrees/feat-FEAT-723-ledger-coder-feedback-fixes` — never on `dev`.
2. **Read the spec** at `sdd/specs/ledger-coder-feedback-fixes.spec.md` (§2 and §7).
3. **Check dependencies** — none.
4. **Verify the Codebase Contract** before writing code: re-run each
   `grep -c` in the blueprint's `# occurrences:` comments. A count of `0` means
   the anchor moved — stop and report the drift, do not invent an attachment point.
5. **Update status** in `sdd/tasks/index/ledger-coder-feedback-fixes.json` →
   `"in-progress"` with `started_at`, and commit only that index file.
6. **Implement** from the blueprint; complete every `# FILL IN:` marker.
7. **Prove AC-7** before claiming it: run the new test against the unmodified
   source once, confirm it fails, then restore the change.
8. **Commit the code** — stage only the two files this task lists.
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4603 ledger-coder-feedback-fixes verified`.
10. **Fill in the Completion Note**, then commit the staged SDD state.

---

## Completion Note

**Completed by**: Claude Opus 5.5 (interactive session, `/sdd-fix issue:1c7d47068c4d`)
**Date**: 2026-10-22
**Notes**:

Implemented exactly as the blueprint specified — `retract()` inserted above
`_read()`, the tombstone branch as the first statement in `_read()`'s loop, and
the docstring updated. No signature changed; no import added. Port of orphaned
commit `cc5d1a6157`.

All 9 acceptance criteria met:

- AC-1…AC-6 — covered by `test_retracted_feedback_is_dropped_from_replay`;
  `pytest … test_feedback.py` is 24 passed (23 pre-existing + 1 new).
- AC-7 — the new test was run against the unmodified `coder_feedback.py` and
  **failed** (`1 failed in 0.62s`), then passed after restoring the change.
- AC-8 — `ruff check` and `black --check --line-length 120` clean on both files.
- AC-9 — no signature change to `record()`, `context()`, `_read()`'s return
  type, or `CoderFeedback`.

Real-log evidence for the feature's whole point (spec §5, AC-4) is in
`artifacts/logs/feat-723-retraction-evidence.md` (git-ignored by `.gitignore:286`
`artifacts/`, so committed with `git add -f`). Replaying a byte copy of the
repo's own 2436-event ledger:

| | misattributed live | `context()` mentions pattern | `context()` chars |
|---|---|---|---|
| `dev`'s code | **4** | **yes** | 7058 |
| FEAT-723 | **0** | no | 6725 |

Event counts identical in both (723 `insight.recorded`, 4 `insight.superseded`)
and the real ledger's sha256 is unchanged — the fix is pure replay semantics
over an untouched append-only log.

Two things worth knowing for the next task:

1. The four records' real identity is `backend="codex"`, `model="gpt-5.6-terra"`,
   files `artifacts/laya/*` — **not** the `nova` backend. A `context()` probe with
   the wrong backend returns `""` and looks like a false pass.
2. `python -I` **ignores `PYTHONPATH`**, so an isolated-mode script inside a
   worktree silently imports the main checkout's editable install. The first
   evidence run did that and reported a false FAIL. Run such scripts without
   `-I` and assert `module.__file__` before trusting the output. (The worktree
   also needs the Cython `.so` files copied from the main checkout —
   `parrot/utils/types` and `parrot/utils/parsers/toml` — or everything
   `ImportError`s at collection.)

**Deviations from spec**: none.
