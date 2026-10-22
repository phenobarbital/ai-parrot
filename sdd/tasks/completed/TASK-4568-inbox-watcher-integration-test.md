# TASK-4568: InboxWatcher integration test with a real watchdog observer

**Feature**: FEAT-715 — FirefliesInsightsAgent
**Spec**: `sdd/specs/fireflies-insights-agent.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4566
**Assigned-to**: unassigned

---

## Context

Spec §4 Integration Tests, first row: prove that a file dropped into a real directory
reaches the processor through a **real** `watchdog` observer, end to end. The unit
tests (TASK-4565/4566) use fakes; this one is the only test that exercises the actual
thread → loop hand-off (S1) against real filesystem events.

---

## Scope

- Create `packages/ai-parrot/tests/knowledge/wiki/inbox/test_watcher_integration.py`; skip the module with `pytest.importorskip("watchdog")` because the
  dependency is optional (§8 Q1).
- Use a lightweight runtime stand-in (`SimpleNamespace(root=..., config=WikiProjectConfig(inbox=InboxConfig(stability_window=0.2, stability_poll_interval=0.1)))`)
  and a recording `processor_factory` — TASK-4566 guarantees `InboxWatcher` reads only
  `runtime.root` / `runtime.config`.
- Cases: (1) an atomic drop (`.x.tmp` then `os.replace`) is processed exactly once;
  (2) a dot-prefixed temp left in place is never seen by the processor;
  (3) two files dropped together → one run.
- Bound every wait with `asyncio.wait_for(..., timeout=10)` — no unbounded sleeps.

**NOT in scope**: building a real `InboxRuntime` / LLM adapters (the processor is
already covered by `test_end_to_end.py`); CLI (TASK-4567).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/knowledge/wiki/inbox/test_watcher_integration.py` | CREATE | Real-watchdog integration test of InboxWatcher over a temp inbox |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.inbox import InboxWatcher                       # re-exported by TASK-4566
from parrot.knowledge.wiki.project import InboxConfig, WikiProjectConfig  # verified: packages/ai-parrot/src/parrot/knowledge/wiki/project.py:286, :574
```

### Does NOT Exist
- ~~a shared real-`InboxRuntime` fixture~~ — `tests/knowledge/wiki/inbox/conftest.py`
  provides `tmp_repo`, `fake_adapters`, `seeded_store` only (lines 18, 33, 66); none
  builds an `InboxRuntime`. Use the stand-in.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/inbox/test_watcher_integration.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Write the module below — *why*: one real end-to-end proof of S1.
2. Fill the three cases — *why*: AC2, AC4, and the dot-prefix guarantee.

### `packages/ai-parrot/tests/knowledge/wiki/inbox/test_watcher_integration.py` (CREATE)
```python
"""Integration: real watchdog observer → InboxWatcher → recording processor (FEAT-715)."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("watchdog")

from parrot.knowledge.wiki.inbox import InboxWatcher  # noqa: E402
from parrot.knowledge.wiki.project import InboxConfig, WikiProjectConfig  # noqa: E402


class RecordingProcessor:
    """Records which inbox files existed at each run."""

    seen: list[list[str]] = []

    def __init__(self, runtime) -> None:
        self.inbox = runtime.config.inbox_path(runtime.root)

    async def run(self, **kwargs):
        names = sorted(p.name for p in self.inbox.iterdir() if p.is_file())
        type(self).seen.append(names)
        for p in self.inbox.iterdir():          # emulate archive=True: originals leave the inbox
            if p.is_file() and not p.name.startswith("."):
                p.unlink()
        return SimpleNamespace(documents=[object()] * len(names), counts={})


@pytest.fixture
def runtime(tmp_path: Path):
    (tmp_path / "inbox").mkdir()
    cfg = WikiProjectConfig(inbox=InboxConfig(stability_window=0.2, stability_poll_interval=0.1))
    return SimpleNamespace(root=tmp_path, config=cfg)


async def test_atomic_drop_is_processed_once(runtime) -> None:
    RecordingProcessor.seen = []
    w = InboxWatcher(runtime, debounce=0.1, processor_factory=RecordingProcessor)
    await w.start()
    inbox = runtime.root / "inbox"
    tmp = inbox / ".meeting.md.tmp"
    tmp.write_text("# meeting\nfireflies_id: abc123\n")
    os.replace(tmp, inbox / "meeting.md")
    # FILL IN: poll (bounded by asyncio.wait_for timeout=10) until RecordingProcessor.seen
    #   is non-empty, then stop(drain=True) and assert seen == [["meeting.md"]]  — AC2/AC4
    await w.stop(drain=True)
```
**Why this shape**: the startup scan (AC22) may trigger one empty-inbox wake before the
drop; the worker's "no candidates ⇒ continue" rule means it must NOT produce a run, so
`seen` must contain exactly one entry. Fix any flakiness in the watcher, never by
widening the assertion.

### FILL IN checklist
- [ ] case (1) bounded wait + assertion.
- [ ] case (2) a lingering `.x.tmp` never appears in `seen`.
- [ ] case (3) two files dropped back to back → exactly one run listing both.

---

## Acceptance Criteria

- [ ] The module is skipped cleanly when `watchdog` is absent.
- [ ] All three cases pass in under 10 s each, with no unbounded sleep.
- [ ] No case produces a run for an empty inbox.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot/tests/knowledge/wiki/inbox/test_watcher_integration.py -q`

---

## Test Specification

See the CREATE block above — it is the test module.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug fireflies-insights-agent --feature-id FEAT-715`).
2. **Read the spec** `sdd/specs/fireflies-insights-agent.spec.md` — §3 (the module this task implements) and §6.
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/fireflies-insights-agent.json`.
4. **Verify the Codebase Contract** before writing code. Anchors were verified at
   `f6a4dbfca`; re-run every `grep -c` in the blueprint and use the fresh count.
   A count of `0` means the anchor moved — stop and report, never invent one.
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`)
   and commit only that index file.
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`
   marker; never change a signature, class name or path the blueprint fixes.
7. **Run** the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`
   (plus `packages/ai-parrot-tools/src:packages/ai-parrot-integrations/src`
   when the task imports them) — the shared venv is installed against the main
   checkout. Then `ruff check --fix` on every file you touched.
8. **Commit** only the files this task lists (never `git add .` / `-A`):
   `feat(fireflies-insights-agent): TASK-4568 — <title>`.
9. **Close** with `scripts/sdd/close_task.sh TASK-4568 fireflies-insights-agent verified` — never move
   the file by hand.
10. **Fill in the Completion Note** below, then commit the staged SDD state.

---

## Completion Note

**Completed by**: sdd-worker (orchestrator manual — attempt 3 after fidelity_violation)
**Date**: 2026-10-22
**Notes**: Created test_watcher_integration.py with three cases: (1) atomic drop via
os.replace is processed exactly once, (2) dot-prefixed temps never reach the processor,
(3) two files dropped together coalesce into one run. Uses asyncio.Event signalling from
RecordingProcessor to avoid polling loops (ruff ASYNC110). All tests bounded by
asyncio.wait_for(timeout=10). Module skipped cleanly when watchdog is absent via
pytest.importorskip. Previous coder attempt (minimax seat) had a fidelity_violation
touching sdd/ledger/events.jsonl.

**Deviations from spec**: none
