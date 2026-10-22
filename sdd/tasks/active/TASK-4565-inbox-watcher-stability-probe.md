# TASK-4565: Inbox watcher stability probe and lazy watchdog gate

**Feature**: FEAT-715 — FirefliesInsightsAgent
**Spec**: `sdd/specs/fireflies-insights-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4564
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 2**, first half. Builds the deterministic, testable building blocks
the `InboxWatcher` lifecycle (TASK-4566) composes: the size+mtime stability probe
(C11, design-research **S4**: injectable timing policy, nanosecond mtime), the
candidate filter that mirrors `InboxProcessor.discover()`'s dot-prefix rule (**S3**),
and the lazy `watchdog` gate (**§8 Q1 route (a)**, AC29: `watchdog` lives only in
the `filesystem-transport-full` extra and must never be imported at module load).

---

## Scope

- Create `packages/ai-parrot/src/parrot/knowledge/wiki/inbox/watcher.py` with: `WatcherUnavailable`, `_require_watchdog()`, `WatcherStats`,
  `FileSample`, `StabilityProbe`, and `is_candidate()`.
- `StabilityProbe.is_stable()` takes samples at t=0 and then every `poll_interval`
  until at least `window` seconds have elapsed; **stable iff ≥ 2 samples were taken
  and every sample has identical `st_size` AND `st_mtime_ns`**. A missing file is
  unstable. `window == 0` ⇒ stable iff the file exists.
- Inject `stat`, `sleep` and `clock` so tests never sleep for real (AC27).
- Create `packages/ai-parrot/tests/knowledge/wiki/inbox/test_watcher.py` covering every rule above.

**NOT in scope**: the `InboxWatcher` class, observer, worker, startup scan, lock
retry (all TASK-4566); exporting from `inbox/__init__.py` (TASK-4566); CLI (TASK-4567).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/inbox/watcher.py` | CREATE | Stability probe, candidate filter, `WatcherStats`, lazy `watchdog` gate |
| `packages/ai-parrot/tests/knowledge/wiki/inbox/test_watcher.py` | CREATE | Deterministic stability / candidate / lazy-import tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.project import InboxConfig  # verified: packages/ai-parrot/src/parrot/knowledge/wiki/project.py:286 (fields added by TASK-4564)
from pydantic import BaseModel, Field                 # repo standard (Pydantic v2)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/project.py  (after TASK-4564)
class InboxConfig(BaseModel):
    stability_window: float        # default 3.0
    stability_poll_interval: float # default 1.5

# packages/ai-parrot/src/parrot/knowledge/wiki/inbox/processor.py:167 — the rule to mirror
#                 if name.startswith("."):      (inside discover(): dot-prefixed entries are skipped)
```

### Does NOT Exist
- ~~`watchdog` as a base dependency~~ — it is ONLY in the `filesystem-transport-full`
  extra of `packages/ai-parrot/pyproject.toml`. **Never `import watchdog` at module top
  level** — `_require_watchdog()` imports it lazily (AC29).
- ~~`InboxProcessor.discover(paths=...)`~~ — `discover()` takes only `limit`; it cannot
  be restricted to a file list. That is why the watcher gates whole runs (TASK-4566).
- ~~`parrot.knowledge.wiki.inbox.watcher`~~ — this task creates it.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/inbox/watcher.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/inbox/test_watcher.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#InboxConfig"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Async-first: `is_stable` awaits the injected `sleep` (default `asyncio.sleep`) and
  runs `stat` via `asyncio.to_thread` only for the default `os.stat` — because a slow
  network filesystem `stat` must not block the event loop.
- No `print`; module logger `logging.getLogger(__name__)`.
- `is_candidate` must reject a path if **any** component below the inbox root starts
  with `.` — because the processor skips dot-prefixed entries at every level, and the
  agent's atomic temp files (`.<name>.tmp`, TASK-4571) rely on that.

---

## Implementation Blueprint

### Steps (in order)
1. Write the module skeleton below — *why*: fixes the names TASK-4566 imports.
2. Implement `StabilityProbe.is_stable` per the rule in Scope — *why*: AC5/AC27.
3. Write `packages/ai-parrot/tests/knowledge/wiki/inbox/test_watcher.py` with injected fakes — *why*: no real sleeps (AC27).

### `packages/ai-parrot/src/parrot/knowledge/wiki/inbox/watcher.py` (CREATE)
```python
"""Source-agnostic folder watcher for the wiki inbox (FEAT-715).

This module must stay importable without ``watchdog`` installed: it lives only in
the ``filesystem-transport-full`` extra, so it is imported lazily by
:func:`_require_watchdog`.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, NamedTuple

from pydantic import BaseModel

logger = logging.getLogger(__name__)

WATCHDOG_EXTRA = "filesystem-transport-full"


class WatcherUnavailable(RuntimeError):
    """Raised when the optional ``watchdog`` dependency is not installed."""


def _require_watchdog() -> Any:
    """Import and return the ``watchdog.observers`` module, or raise WatcherUnavailable."""
    try:
        from watchdog import observers  # noqa: PLC0415 — lazy by design (spec §8 Q1)
    except ImportError as exc:
        raise WatcherUnavailable(
            "wikitoolkit inbox --watch needs the optional 'watchdog' package: "
            f"install ai-parrot[{WATCHDOG_EXTRA}]"
        ) from exc
    return observers


class WatcherStats(BaseModel):
    """Counters for one watcher lifetime; surfaced by the CLI on shutdown."""

    events_seen: int = 0
    runs_started: int = 0
    documents_processed: int = 0
    lock_busy_retries: int = 0


class FileSample(NamedTuple):
    """One stat observation of a candidate file."""

    size: int
    mtime_ns: int


def is_candidate(path: Path, inbox_dir: Path) -> bool:
    """Whether ``path`` is something InboxProcessor.discover() would pick up."""
    # FILL IN: False when `path` is not under `inbox_dir`, is a directory, or ANY
    #          component of path.relative_to(inbox_dir) starts with "." — bounded by
    #          processor.py:167 and the agent's `.tmp` convention (AC2).
    raise NotImplementedError


class StabilityProbe:
    """Decide whether a file stopped changing, with injectable time and stat."""

    def __init__(
        self,
        window: float,
        poll_interval: float,
        *,
        stat: Callable[[Path], os.stat_result] | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Bind the timing policy; ``stat=None`` means os.stat run in a worker thread."""
        self.window = window
        self.poll_interval = poll_interval
        self._stat = stat
        self._sleep = sleep
        self._clock = clock

    @classmethod
    def from_config(cls, config: InboxConfig, **overrides: Any) -> "StabilityProbe":
        """Build from InboxConfig.stability_window / stability_poll_interval."""
        return cls(config.stability_window, config.stability_poll_interval, **overrides)

    async def sample(self, path: Path) -> FileSample | None:
        """Return the current FileSample, or None when the file is gone."""
        # FILL IN: call self._stat(path) directly when injected, else
        #          await asyncio.to_thread(os.stat, path); FileNotFoundError -> None.
        raise NotImplementedError

    async def is_stable(self, path: Path) -> bool:
        """True iff >=2 samples spanning >= window seconds are all identical."""
        # FILL IN: window == 0 -> return (await self.sample(path)) is not None.
        #          Otherwise sample at start, then loop: await self._sleep(poll_interval),
        #          sample again; any None or any differing sample -> False; stop once
        #          self._clock() - start >= self.window AND >= 2 samples -> True.
        raise NotImplementedError
```
**Why this shape**: `WatcherStats` and `WatcherUnavailable` are the names TASK-4566 and
TASK-4567 import — they are fixed here. The `from config import InboxConfig` line must
be added at the top (it is in Verified Imports). `NotImplementedError` lines are
blueprint markers: the finished file must not contain them.

### FILL IN checklist
- [ ] `is_candidate` — dot-component and containment rules; bounded by processor.py:167, AC2.
- [ ] `StabilityProbe.sample` — injected vs threaded `os.stat`; missing file → `None`.
- [ ] `StabilityProbe.is_stable` — the sampling loop exactly as Scope defines; AC5, AC27.
- [ ] `packages/ai-parrot/tests/knowledge/wiki/inbox/test_watcher.py` — the cases in Test Specification.

---

## Acceptance Criteria

- [ ] `import parrot.knowledge.wiki.inbox.watcher` succeeds with `watchdog` absent
  (`sys.modules["watchdog"] = None`), and `_require_watchdog()` then raises
  `WatcherUnavailable` naming `filesystem-transport-full` (AC29).
- [ ] Same size with a changed `st_mtime_ns` is **unstable** (S10).
- [ ] No test sleeps for real (AC27).
- [ ] `ruff check packages/ai-parrot/src/parrot/knowledge/wiki/inbox/watcher.py packages/ai-parrot/tests/knowledge/wiki/inbox/test_watcher.py` clean; no top-level `watchdog` import.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot/tests/knowledge/wiki/inbox/test_watcher.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/wiki/inbox/test_watcher.py
import sys
from dataclasses import dataclass
from pathlib import Path
import pytest
from parrot.knowledge.wiki.inbox.watcher import (
    StabilityProbe, WatcherUnavailable, _require_watchdog, is_candidate,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
    def __call__(self) -> float:
        return self.now
    async def sleep(self, seconds: float) -> None:
        self.now += seconds


@dataclass
class FakeStat:
    st_size: int
    st_mtime_ns: int


def scripted_stat(samples):          # list[tuple[size, mtime_ns] | None], consumed in order
    it = iter(samples)
    def _stat(path: Path) -> FakeStat:
        s = next(it)
        if s is None:
            raise FileNotFoundError(path)
        return FakeStat(*s)
    return _stat


async def test_identical_samples_are_stable(tmp_path: Path) -> None:
    clock = FakeClock()
    probe = StabilityProbe(3.0, 1.5, stat=scripted_stat([(10, 1)] * 3), sleep=clock.sleep, clock=clock)
    assert await probe.is_stable(tmp_path / "a.md") is True


async def test_same_size_changed_mtime_is_unstable(tmp_path: Path) -> None:
    clock = FakeClock()
    probe = StabilityProbe(3.0, 1.5, stat=scripted_stat([(10, 1), (10, 2), (10, 2)]), sleep=clock.sleep, clock=clock)
    assert await probe.is_stable(tmp_path / "a.md") is False


async def test_missing_file_is_unstable(tmp_path: Path) -> None:
    clock = FakeClock()
    probe = StabilityProbe(3.0, 1.5, stat=scripted_stat([None]), sleep=clock.sleep, clock=clock)
    assert await probe.is_stable(tmp_path / "gone.md") is False


def test_dot_prefixed_temp_is_not_a_candidate(tmp_path: Path) -> None:
    assert is_candidate(tmp_path / ".meeting.md.tmp", tmp_path) is False
    assert is_candidate(tmp_path / ".hidden" / "x.md", tmp_path) is False


def test_watchdog_absent_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "watchdog", None)
    with pytest.raises(WatcherUnavailable, match="filesystem-transport-full"):
        _require_watchdog()
```
> The probe must read only `st_size` and `st_mtime_ns` from a stat result — that is
> what lets `FakeStat` stand in for `os.stat_result`.

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
   `feat(fireflies-insights-agent): TASK-4565 — <title>`.
9. **Close** with `scripts/sdd/close_task.sh TASK-4565 fireflies-insights-agent verified` — never move
   the file by hand.
10. **Fill in the Completion Note** below, then commit the staged SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
