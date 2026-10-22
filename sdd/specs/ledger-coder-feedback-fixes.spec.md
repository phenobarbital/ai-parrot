---
type: feature
base_branch: dev
projects: [ai-parrot, sdd-tooling, dev-loop]
tags: [ledger, coder-feedback, sdd-coder, append-only, audit]
---

# Feature Specification: Retractable coder feedback (`insight.superseded` tombstones)

**Feature ID**: FEAT-723
**Date**: 2026-10-22
**Author**: Jesus Lara
**Status**: approved
**Target version**: 1.2.5

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

`CoderFeedbackStore` has no way to withdraw a recorded correction. `_read()`
(`coder_feedback.py:114-126`) replays every `insight.recorded` event whose
`category` is `coder_feedback` forever, so a lesson charged to the wrong party is
permanent and is re-injected by `context()` into every future dispatch for that
backend/model.

The retraction for the known case was **already performed, but never took effect**:

- `.parrot/ledger/events.jsonl` holds **4 `insight.superseded` tombstones**,
  appended `2026-09-22T13:56:43` by `human:jesus`, reason *"Misattributed: codex
  seat runs with .git read-only and cannot git add; the engine extraction…"*.
- Their subjects match the 4 misattributed records exactly:
  `coder-feedback:298a2946b86d3c0a452654ca`, `:2dc3591d1159566f512e9174`,
  `:df08b552b9c7ec047a937236`, `:fb88c2ea4281dfbf093125c1`.
- But the replay filter at `coder_feedback.py:118` is
  `if event.kind != "insight.recorded" …: continue`, which skips
  `insight.superseded` entirely.

The tombstones are inert. The 4 bogus `gitignored-file-not-force-added` defects
(FEAT-589, TASK-3605/3611/3614/3616) are still live in replay and still rendered
into codex dispatches touching `artifacts/`, a month on, while the audit trail
records them as retracted.

The defects were never the model's fault: the codex seat runs with `.git`
read-only and **cannot commit at all**; the engine's extraction was the bug.
Affected dispatches are told "you forgot `git add -f`" and spend budget on a
correction they are structurally unable to perform.

Tracked as `issue:1c7d47068c4d` (bug / major). The implementation is a port of
orphaned commit `cc5d1a6157`, pushed to `fix/sdd-coder-ignored-declared-files`
*after* its PR #1460 merged, which never reached `dev`.

### Goals

- Give `CoderFeedbackStore` a first-class retraction that respects the
  append-only log: no event is ever rewritten or deleted.
- Make the 4 **already-committed** tombstones take effect on the next replay,
  with no new events appended and no migration.
- Expose retraction on the CLI so a human can withdraw a misattribution without
  hand-editing `events.jsonl`.

### Non-Goals (explicitly out of scope)

- Retracting `coder_review` or `coder_suspension` insights (separate categories,
  separate stores — `coder_reviews.py:97`, `coder_suspensions.py:318`).
- Fixing the FEAT-589 engine extraction bug that produced the misattribution;
  that is already retired (`dirty_task_worktree`, FEAT-587).
- Any change to issue lifecycle, claims, `ledger sync`, or the SQLite index.
- Re-recording corrected feedback against the right party.
- An `insight.superseded` reducer in `LedgerIndex` (§2 shows why none is needed).

---

## 2. Architectural Design

### Overview

Add a tombstone-emitting `retract()` to `CoderFeedbackStore` and teach `_read()`
to honour tombstones during replay. Ordering carries the semantics: a tombstone
drops every recording of its subject seen **before** it, so a later re-recording
of the same occurrence counts as a fresh confirmation again.

`insight.superseded` is already a declared event kind (`events.py:19`), so this
feature adds **no new kind** and needs no schema change.

### Component Diagram

```
wikitoolkit ledger retract-feedback <id>…
        │
        ▼
CoderFeedbackStore.retract(feedback_id, reason, actor)
        │  appends kind="insight.superseded", subject=<feedback_id>
        ▼
   LedgerLog (append-only)  ──replay──▶  CoderFeedbackStore._read()
                                              │  pops subject on tombstone
                                              ▼
                                        context() → coder dispatch prompt
```

### Integration Points

Three properties of the surrounding ledger were **re-verified on this base
commit**, not assumed, because they are what make the tombstone safe:

| Concern | Finding | Verified at |
|---|---|---|
| Does the SQLite index break on the new event? | `apply_event` dispatches on `issue.*` only and documents that unknown kinds are ignored so replay never breaks on a kind it does not own | `ledger/index.py:103-125` |
| Can the tombstone clobber an issue claim? | **No** — `SUPERSEDING_CLAIM_KINDS` is `{issue.unclaimed, issue.closed, issue.superseded}`; `insight.superseded` is absent | `ledger/shared_log.py:27` |
| Is the kind legal to append? | Already declared | `ledger/events.py:19` |

> The claim check matters: FEAT-717 introduced `SUPERSEDING_CLAIM_KINDS` **after**
> `cc5d1a6157` was written, so the port is only safe because `insight.superseded`
> happens to fall outside that set. Re-check it if that set ever grows.

### Data Models

No new models. The tombstone payload is a plain dict, deliberately *not* an
`InsightRecordedPayload` (it carries no `fact`/`title`/`derived_from`):

```python
{"category": "coder_feedback", "reason": <str>, "retracted_by": <actor str>}
```

`category` is mandatory — it is how replay distinguishes a coder-feedback
tombstone from any other future `insight.superseded` producer.

### New Public Interfaces

```python
class CoderFeedbackStore:
    async def retract(self, feedback_id: str, reason: str, actor: str) -> bool:
        """True when a live record was retracted; False (nothing appended) when
        feedback_id is unknown or already retracted."""
```

CLI: `wikitoolkit ledger retract-feedback <id>... --reason <why> [--actor <who>]`

---

## 3. Module Breakdown

> Define the discrete modules that will be implemented.

#### Delegation-eligible modules

Both modules are small, fully specified, and touch one file plus its test —
suitable for a delegated coder seat.

### Module 1: Store retraction and tombstone-aware replay

**Files**: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_feedback.py`,
`packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_feedback.py`

1. Add `async def retract(self, feedback_id: str, reason: str, actor: str) -> bool`
   immediately **above** `_read()`. It reads the live set
   (`{fb.feedback_id() for _ts, fb in await asyncio.to_thread(self._read)}`),
   returns `False` without appending when `feedback_id` is not live, else appends
   a `LedgerEvent(kind="insight.superseded", subject=feedback_id, actor=actor,
   payload={...})` via `asyncio.to_thread(self.log.append, event)` and returns `True`.
2. In `_read()`, **before** the existing `insight.recorded` filter, add:
   on `event.kind == "insight.superseded"` and
   `event.payload.get("category") == "coder_feedback"`, do
   `records.pop(event.subject, None)` then `continue`.
3. Update `_read()`'s docstring to state that retractions drop earlier records.

Order is load-bearing: the `pop` must be reached before the `insight.recorded`
filter `continue`s past it, and replay is a single forward pass over
`log.iter_events()`, so a tombstone only affects recordings already seen.

### Module 2: `ledger retract-feedback` CLI command

**Files**: `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py`

Add a `@ledger.command("retract-feedback")` directly above
`@ledger.command("context")`: variadic `feedback_ids` (`nargs=-1, required=True`),
`--reason` required, `--actor` defaulting to `agent:cli`. Resolve the store with
`CoderFeedbackStore.from_root(Path.cwd())` imported **inside** the function (the
module's established pattern for ledger subcommands), echo one line per id, and
`raise SystemExit(1)` if any id could not be retracted.

---

## 4. Test Specification

### Unit Tests

`packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_feedback.py` —
one new test, `test_retracted_feedback_is_dropped_from_replay`, appended at the
end of the file, using the existing `store` fixture (`:42`) and `feedback(**overrides)`
helper (`:22`). It asserts, in one pass:

1. Retracting a live id returns `True`.
2. An unknown id returns `False`.
3. Re-retracting an already-retracted id returns `False`.
4. After reopening the log (`CoderFeedbackStore(LedgerLog(store.log.path))`),
   `context()` no longer mentions the retracted pattern but **does** still mention
   an unrelated pattern for the same model — a retraction is surgical.
5. The log holds `2` `insight.recorded` and `1` `insight.superseded` events —
   nothing was rewritten or deleted.
6. Re-recording the same occurrence after the tombstone makes it live again, at
   `confirmed deliveries: 1`.

### Integration Tests

None. The CLI command is a thin Click wrapper over `retract()`; the repo has no
Click-runner harness for `ledger` subcommands, and adding one is out of scope.
Module 2 is validated by the real-log evidence step in §5 instead.

### Validation Contract

```
packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_feedback.py
```

### Test Data / Fixtures

Existing only: the `store` fixture (`tmp_path`-backed `CoderFeedbackStore`) and
the `feedback()` builder. No new fixture, no `fakeredis`, no network.

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_feedback.py`
      passes, including `test_retracted_feedback_is_dropped_from_replay`.
- [ ] The new test **fails** against the unmodified `coder_feedback.py` — proof it
      covers the defect rather than restating current behaviour.
- [ ] `ruff check` and `black --check` clean on both changed source files.
- [ ] **Real-log evidence (the point of the feature)**: with the fix in place, a
      replay of the repo's own `.parrot/ledger/events.jsonl` drops all 4
      pre-existing records —
      `context("nova", "gpt-5.6-terra", ["artifacts/x.py"])` no longer contains
      `gitignored-file-not-force-added` — while the event count on disk is
      **unchanged** (no new tombstone appended, nothing deleted). Captured to
      `artifacts/logs/feat-723-retraction-evidence.md`.
- [ ] `wikitoolkit ledger retract-feedback --help` lists the command, and a run
      against an unknown id exits `1` without appending an event.
- [ ] No change to issue lifecycle: `wikitoolkit ledger list` output and the
      SQLite index are unaffected by the tombstones.
- [ ] No breaking change to `record()`, `context()` or `CoderFeedback`.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**

Verified against base commit `02b8475ff`.

### Verified Imports

```python
# all already present at the top of coder_feedback.py — add NOTHING
from parrot.knowledge.wiki.ledger.events import InsightRecordedPayload, LedgerEvent  # :15
from parrot.knowledge.wiki.ledger.log import LedgerLog                               # :16
from parrot.knowledge.wiki.ledger.service import LedgerService                       # :17
import asyncio                                                                       # :5

# cli.py, imported INSIDE the command function (module pattern)
from parrot.knowledge.wiki.ledger.coder_feedback import CoderFeedbackStore

# test file — already imported, add NOTHING
from parrot.knowledge.wiki.ledger.coder_feedback import CoderFeedback, CoderFeedbackStore  # :13
from parrot.knowledge.wiki.ledger.log import LedgerLog                                     # :16
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_feedback.py
class CoderFeedbackStore:
    def __init__(self, log: LedgerLog) -> None:                                  # line 88
    @classmethod
    def from_root(cls, root: Path) -> CoderFeedbackStore:                        # line 93
    async def record(self, feedback: CoderFeedback) -> CoderFeedbackReceipt:     # line 96
    def _read(self) -> list[tuple[str, CoderFeedback]]:                          # line 114
    async def context(self, backend: str, model: str, files: list[str],
                      max_tokens: int = 1800, max_age_days: int = 90) -> str:    # line 129

class CoderFeedback(BaseModel):
    def feedback_id(self) -> str:        # "coder-feedback:<24-hex>"  # line 78 area
```

```python
# packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_feedback.py
def feedback(**overrides: object) -> CoderFeedback:   # line 22
@pytest.fixture
def store(tmp_path: Path) -> CoderFeedbackStore:      # line 42
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `retract()` | `LedgerLog.append` | `asyncio.to_thread(self.log.append, event)` | mirrors `record()`, `coder_feedback.py:110` |
| `retract()` | `CoderFeedbackStore._read` | live-id set before appending | `coder_feedback.py:114` |
| `_read()` tombstone branch | `LedgerLog.iter_events` | single forward replay pass | `coder_feedback.py:116` |
| `ledger retract-feedback` | `CoderFeedbackStore.from_root` | `Path.cwd()` | `coder_feedback.py:93` |
| tombstone kind | `events.py` kind allowlist | `"insight.superseded"` | `events.py:19` |

### Does NOT Exist (Anti-Hallucination)

- ~~`CoderFeedbackStore.retract()`~~ — this feature adds it; absent on `dev`.
- ~~`wikitoolkit ledger retract-feedback`~~ — absent on `dev`.
- ~~`InsightSupersededPayload`~~ — **no such model**. `events.py` declares the
  *kind* string only; the payload is a plain dict.
- ~~`LedgerIndex._apply_insight_superseded`~~ — does not exist and must NOT be
  added (`index.py:125` deliberately ignores unowned kinds).
- ~~`CoderFeedbackStore.unrecord()` / `.delete()` / `.forget()`~~ — not real.
- ~~`LedgerLog.remove()` / `.rewrite()`~~ — the log is append-only.

### Edit Sites (Blueprint Anchors)

Verified against: `02b8475ff`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_feedback.py` | MODIFY | `    def _read(self) -> list[tuple[str, CoderFeedback]]:` | `coder_feedback.py:114` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_feedback.py` | MODIFY | `            if event.kind != "insight.recorded" or event.payload.get("category") != "coder_feedback":` | `coder_feedback.py:118` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | `@ledger.command("context")` | `cli.py:3553` | 1 |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_feedback.py` | MODIFY | append at end of file (after `async def test_review_and_feedback_coexist`) | `test_feedback.py:488` | 1 |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Async I/O off the event loop via `asyncio.to_thread`, exactly as `record()` does.
- Google-style docstrings, strict type hints, 120-column lines, `black` formatting.
- `logger` (module-level), never `print`.
- CLI subcommands import their store lazily inside the function body.

### Known Risks / Gotchas

- **Ordering is the semantics.** Put the tombstone branch *before* the
  `insight.recorded` filter. Replay is one forward pass, so a tombstone drops only
  recordings already seen; a later re-record legitimately counts again. Do not
  "optimize" this into a pre-collected set of retracted ids — that would also kill
  post-tombstone re-recordings.
- **`_read()` keeps first-write-wins** (`records.setdefault`, `:126`). Leave it:
  retraction removes the key entirely, so a re-record after a tombstone is the new
  first write.
- **Do not add an index reducer.** `index.py:125` ignores unowned kinds on purpose.
- **`SUPERSEDING_CLAIM_KINDS` (`shared_log.py:27`) must not contain
  `insight.superseded`.** It does not today; if that changes, this tombstone would
  start superseding issue *claims*.
- Worktree testing needs `PYTHONPATH=packages/ai-parrot/src`, and the Cython
  `parrot.utils.types` `.so` exists only in the main checkout — copy it in rather
  than running `uv sync`, which would repoint the shared venv.

### External Dependencies

None.

---

## 8. Open Questions

- [x] Should retraction delete the original event instead of tombstoning?
      **No** — the log is append-only and the audit trail is the point.
- [x] Should `retract()` be idempotent-true or false on a second call?
      **False, without appending** — so the CLI can report "unknown or already
      retracted" and exit non-zero, rather than silently appending duplicates.
- [ ] Should the other insight categories (`coder_review`, `coder_suspension`)
      get the same treatment? Out of scope here; open a separate issue if a
      misattribution ever lands there. — *Owner: Jesus*

---

## 9. Design Research Cross-Check

> Status: skipped (direct port of an already-reviewed commit, `cc5d1a6157`,
> whose design was settled when it was written; the three safety properties it
> depends on were independently re-verified against `02b8475ff` in §2).

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-22 | Jesus Lara | Initial draft — port of `cc5d1a6157` for `issue:1c7d47068c4d` |
