# TASK-4566: InboxWatcher lifecycle: observer, debounced worker, startup scan, lock retry

**Feature**: FEAT-715 — FirefliesInsightsAgent
**Spec**: `sdd/specs/fireflies-insights-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4565
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 2**, second half — the one module the spec marks **not**
delegation-eligible: the debounce / coalesce / lock-retry interplay is the novel
design of the feature. It folds design-research **S1** (one asyncio owner), **S3**
(startup scan, final-path revalidation) and the C11 serialization rule.

**A constraint discovered at task time that shapes this design:**
`InboxProcessor.run(*, dry_run, limit, force, archive)` has **no file-list parameter**
and `discover()` picks up *every* safe file in the inbox. A run triggered because file
A is stable would therefore also ingest a file B that is still being written.
**Binding rule: a run starts only when EVERY current candidate in the inbox passes the
stability probe.** If any candidate is unstable, the whole run is deferred and
re-checked. (Continuous writes can defer indefinitely; log that at INFO — it is the
correct trade, because a partial ingest is unrecoverable and a delayed one is not.)

---

## Scope

- Add `InboxWatcher` to `packages/ai-parrot/src/parrot/knowledge/wiki/inbox/watcher.py` with the spec §3 M2 methods: `start()`,
  `stop(*, drain=True)`, `run_forever(*, stop_event=None)`, `_is_stable(path)`,
  `_drain_once()`, `_startup_scan()`, plus private `_enqueue` / `_worker` / `_Handler`.
- Constructor (spec skeleton extended with keyword-only test seams):
  `InboxWatcher(runtime, *, stats=None, probe=None, debounce=0.5, lock_retry_delay=2.0,
  force=False, archive=True, observer_factory=None, processor_factory=None)`.
- **asyncio ownership (S1, AC26) — binding**: `start()` captures the running loop;
  the watchdog handler runs on an observer thread and may ONLY call
  `loop.call_soon_threadsafe(self._enqueue, path)`; exactly **one** worker task owns
  every `InboxProcessor` call; `stop()` stops the observer, joins it with
  `asyncio.to_thread(observer.join)`, then awaits (drain) or cancels the worker.
  **No handler code may call `asyncio.run()` or touch `InboxProcessor`.**
- **Startup scan (S3, AC22)**: `start()` enqueues a wake-up after observing, so files
  that landed while the watcher was stopped are processed.
- **Lock retry (AC6)**: `InboxLockBusy` ⇒ `stats.lock_busy_retries += 1`, sleep
  `lock_retry_delay`, retry the same run; never drop the pending wake-up.
- **Runtime surface**: `InboxWatcher` reads only `runtime.root` and `runtime.config`;
  the full runtime is handed untouched to `processor_factory(runtime)` (default
  `InboxProcessor`). This keeps TASK-4568 able to use a lightweight stand-in.
- Re-export the three public names from `packages/ai-parrot/src/parrot/knowledge/wiki/inbox/__init__.py`.

**NOT in scope**: the CLI flag (TASK-4567), the real-watchdog integration test
(TASK-4568), changing `InboxProcessor` or its locking (spec Non-Goals),
overriding `stage_git` (C15 — never set it).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/inbox/watcher.py` | MODIFY | Add the `InboxWatcher` lifecycle class |
| `packages/ai-parrot/src/parrot/knowledge/wiki/inbox/__init__.py` | MODIFY | Re-export `InboxWatcher`, `WatcherStats`, `WatcherUnavailable` |
| `packages/ai-parrot/tests/knowledge/wiki/inbox/test_watcher.py` | MODIFY | Lifecycle tests with a fake observer and fake processor |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.inbox.processor import InboxLockBusy, InboxProcessor, InboxRuntime  # verified: packages/ai-parrot/src/parrot/knowledge/wiki/inbox/processor.py:64, :133, :43
from parrot.knowledge.wiki.inbox.models import InboxRunReport                                   # verified: inbox/models.py (re-exported inbox/__init__.py:3)
from parrot.knowledge.wiki.project import validate_inbox_paths                                  # verified: packages/ai-parrot/src/parrot/knowledge/wiki/project.py:315
# already in packages/ai-parrot/src/parrot/knowledge/wiki/inbox/watcher.py from TASK-4565:
#   StabilityProbe, WatcherStats, WatcherUnavailable, _require_watchdog, is_candidate
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/inbox/processor.py:136
class InboxProcessor:
    def __init__(self, runtime: InboxRuntime, *, today: date | None = None) -> None: ...
    async def run(self, *, dry_run: bool = False, limit: int | None = None,
                  force: bool = False, archive: bool = True) -> InboxRunReport: ...   # :202 — owns the sole writer lock
class InboxLockBusy(RuntimeError): ...                                               # :64

# packages/ai-parrot/src/parrot/knowledge/wiki/project.py
class WikiProjectConfig(BaseModel):
    inbox: InboxConfig                                    # :721
    def inbox_path(self, root: Path) -> Path: ...         # :770
    def archive_path(self, root: Path) -> Path: ...       # :775
    def inbox_markdown_path(self, root: Path) -> Path: ...# :780
def validate_inbox_paths(root: Path, inbox: Path, archive: Path, markdown: Path) -> None: ...  # :315

# inbox/models.py
class InboxRunReport(BaseModel):
    counts: dict[str, int]
    documents: list[InboxDocResult]
```

### Does NOT Exist
- ~~`InboxProcessor.run(paths=...)`~~ / ~~`discover(paths=...)`~~ — no file-list
  parameter exists; hence the whole-inbox stability rule above.
- ~~`watchdog.events.FileSystemEventHandler` subclassing requirement~~ — watchdog
  calls `handler.dispatch(event)`; a duck-typed `_Handler` with `dispatch()` is enough
  and keeps `watchdog` out of import time.
- ~~`InboxWatcher` setting `runtime.config.inbox.stage_git`~~ — forbidden (C15, AC17).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/inbox/watcher.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/inbox/__init__.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/inbox/test_watcher.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/inbox/processor.py#InboxProcessor",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/inbox/processor.py#InboxProcessor.run",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/inbox/processor.py#InboxLockBusy",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/inbox/processor.py#InboxRuntime",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#validate_inbox_paths"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Every `await` on a filesystem walk uses `asyncio.to_thread` — never block the loop.
- `self.stats` is a public attribute so the CLI can report it even after a
  `KeyboardInterrupt` (TASK-4567).
- `start()` twice ⇒ `RuntimeError("InboxWatcher already started")`.
- Moved events: use `getattr(event, "dest_path", "") or event.src_path` — because an
  atomic `os.replace()` arrives as a *moved* event whose interesting path is the
  destination.

---

## Implementation Blueprint

### Steps (in order)
1. Append the class below to `packages/ai-parrot/src/parrot/knowledge/wiki/inbox/watcher.py` — *why*: fixes the public surface TASK-4567 uses.
2. Implement `_worker` with the whole-inbox stability rule — *why*: the only safe
   serialization given `run()` cannot take a file list.
3. Add the re-exports — *why*: spec §2 "New Public Interfaces".
4. Write the lifecycle tests with fakes — *why*: AC4/AC6/AC22/AC26 must be deterministic.

### `packages/ai-parrot/src/parrot/knowledge/wiki/inbox/watcher.py` (MODIFY — append at end of file)
```python
# AFTER — append below the last definition added by TASK-4565 (`class StabilityProbe`)
class _Handler:
    """Duck-typed watchdog handler: thread-side, hands paths to the loop only."""

    def __init__(self, loop: asyncio.AbstractEventLoop, enqueue: Callable[[Path], None]) -> None:
        self._loop = loop
        self._enqueue = enqueue

    def dispatch(self, event: Any) -> None:
        """Called on the observer thread; MUST NOT touch asyncio state directly."""
        raw = getattr(event, "dest_path", "") or getattr(event, "src_path", "")
        if raw:
            self._loop.call_soon_threadsafe(self._enqueue, Path(raw))


class InboxWatcher:
    """Source-agnostic folder watcher that serializes InboxProcessor runs."""

    def __init__(
        self,
        runtime: InboxRuntime,
        *,
        stats: WatcherStats | None = None,
        probe: StabilityProbe | None = None,
        debounce: float = 0.5,
        lock_retry_delay: float = 2.0,
        force: bool = False,
        archive: bool = True,
        observer_factory: Callable[[], Any] | None = None,
        processor_factory: Callable[[Any], Any] | None = None,
    ) -> None:
        """Bind an already-built runtime; validates inbox paths before observing."""
        self.runtime = runtime
        self.stats = stats or WatcherStats()
        self.inbox_dir = runtime.config.inbox_path(runtime.root)
        validate_inbox_paths(
            runtime.root,
            self.inbox_dir,
            runtime.config.archive_path(runtime.root),
            runtime.config.inbox_markdown_path(runtime.root),
        )
        self._probe = probe or StabilityProbe.from_config(runtime.config.inbox)
        self._debounce = debounce
        self._lock_retry_delay = lock_retry_delay
        self._run_kwargs = {"force": force, "archive": archive}
        self._observer_factory = observer_factory
        self._processor_factory = processor_factory or InboxProcessor
        self._observer: Any = None
        self._worker_task: asyncio.Task[None] | None = None
        self._wake = asyncio.Event()
        self._stopping = False

    async def start(self) -> None:
        """Begin observing. Raises RuntimeError if already started, WatcherUnavailable without watchdog."""
        if self._observer is not None:
            raise RuntimeError("InboxWatcher already started")
        loop = asyncio.get_running_loop()
        factory = self._observer_factory or _require_watchdog().Observer
        self._observer = factory()
        self._observer.schedule(_Handler(loop, self._enqueue), str(self.inbox_dir), recursive=True)
        self._observer.start()
        self._worker_task = loop.create_task(self._worker())
        await self._startup_scan()

    def _enqueue(self, path: Path) -> None:
        """Loop-side: count the event and wake the single worker."""
        self.stats.events_seen += 1
        self._wake.set()

    async def _startup_scan(self) -> None:
        """Wake the worker once so files present before start() are processed (S3)."""
        self._wake.set()

    async def _is_stable(self, path: Path) -> bool:
        """Delegate to the injected StabilityProbe."""
        return await self._probe.is_stable(path)

    async def _worker(self) -> None:
        """The ONLY coroutine that calls InboxProcessor (S1)."""
        # FILL IN: loop until self._stopping:
        #   await self._wake.wait(); self._wake.clear(); await asyncio.sleep(self._debounce)
        #   candidates = await asyncio.to_thread(<rglob inbox_dir filtered by is_candidate>)
        #   if not candidates: continue
        #   if ANY candidate fails `await self._is_stable(p)`: log INFO "deferring", set
        #       self._wake again and continue   — bounded by the whole-inbox rule (Context)
        #   else: report = await self._drain_once();
        #         self.stats.documents_processed += len(report.documents)
        raise NotImplementedError

    async def _drain_once(self) -> InboxRunReport:
        """One serialized run; on InboxLockBusy back off and retry, never dropping the work."""
        # FILL IN: while True: self.stats.runs_started += 1; try: return await
        #   self._processor_factory(self.runtime).run(**self._run_kwargs)
        #   except InboxLockBusy: self.stats.lock_busy_retries += 1;
        #   await asyncio.sleep(self._lock_retry_delay)        — bounded by AC6
        raise NotImplementedError

    async def stop(self, *, drain: bool = True) -> WatcherStats:
        """Stop observing; when drain, await the in-flight run before returning."""
        # FILL IN: self._stopping = True; observer.stop(); await asyncio.to_thread(observer.join);
        #   drain -> self._wake.set() then await the worker; else cancel it and suppress
        #   CancelledError; reset self._observer = None; return self.stats   — AC26
        raise NotImplementedError

    async def run_forever(self, *, stop_event: asyncio.Event | None = None) -> WatcherStats:
        """start() → wait for stop_event or cancellation → stop(drain=True). Used by the CLI."""
        await self.start()
        try:
            if stop_event is None:
                await asyncio.Event().wait()
            else:
                await stop_event.wait()
        finally:
            await self.stop(drain=True)
        return self.stats
```
**Why this shape**: `_Handler` is duck-typed so `watchdog` is touched only inside
`start()` via `_require_watchdog()` (AC29). All counters live on `self.stats` so the CLI
can print them after Ctrl-C. Do not rename any public method — they are fixed by spec §3 M2.

### `packages/ai-parrot/src/parrot/knowledge/wiki/inbox/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF 'from parrot.knowledge.wiki.inbox.processor import InboxProcessor, InboxRuntime' packages/ai-parrot/src/parrot/knowledge/wiki/inbox/__init__.py)
# AFTER — insert below that line (verified: packages/ai-parrot/src/parrot/knowledge/wiki/inbox/__init__.py:4)
from parrot.knowledge.wiki.inbox.watcher import InboxWatcher, WatcherStats, WatcherUnavailable

# REPLACE the __all__ line (verified: packages/ai-parrot/src/parrot/knowledge/wiki/inbox/__init__.py:6, occurrences: 1) with:
__all__ = [
    "InboxProcessor",
    "InboxRuntime",
    "InboxRunReport",
    "InboxDocResult",
    "InboxWatcher",
    "WatcherStats",
    "WatcherUnavailable",
]
```
**Why**: safe to import eagerly — `watcher.py` has no top-level `watchdog` import.

### FILL IN checklist
- [ ] `InboxWatcher._worker` — whole-inbox stability rule; bounded by Context + AC4/AC5.
- [ ] `InboxWatcher._drain_once` — retry loop; bounded by AC6.
- [ ] `InboxWatcher.stop` — join/drain/cancel; bounded by AC26.
- [ ] `packages/ai-parrot/tests/knowledge/wiki/inbox/test_watcher.py` — the lifecycle cases below.

---

## Acceptance Criteria

- [ ] **AC4** A burst of 3 events produces exactly one processor run.
- [ ] **AC5** A still-changing candidate defers the whole run; it runs once stable.
- [ ] **AC6** `InboxLockBusy` on the first attempt is retried; `lock_busy_retries == 1`; nothing dropped.
- [ ] **AC22** A file present before `start()` is processed without any event.
- [ ] **AC26** An event fired from a non-loop thread is delivered; `stop(drain=True)` joins the observer and awaits the worker; the handler never calls `asyncio.run` or the processor.
- [ ] **AC17** The watcher never assigns `stage_git`.
- [ ] `from parrot.knowledge.wiki.inbox import InboxWatcher` works without `watchdog` installed.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot/tests/knowledge/wiki/inbox/test_watcher.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/wiki/inbox/test_watcher.py  (append)
import asyncio, threading
from types import SimpleNamespace
from pathlib import Path
import pytest
from parrot.knowledge.wiki.inbox.processor import InboxLockBusy
from parrot.knowledge.wiki.inbox.watcher import InboxWatcher, StabilityProbe
from parrot.knowledge.wiki.project import InboxConfig, WikiProjectConfig


class FakeObserver:
    def __init__(self) -> None:
        self.handler = None; self.started = self.stopped = self.joined = False
    def schedule(self, handler, path, recursive=True):
        self.handler = handler
    def start(self): self.started = True
    def stop(self): self.stopped = True
    def join(self): self.joined = True


class CountingProcessor:
    runs = 0
    fail_first_with_lock = False
    def __init__(self, runtime): pass
    async def run(self, **kwargs):
        type(self).runs += 1
        if type(self).fail_first_with_lock and type(self).runs == 1:
            raise InboxLockBusy("busy")
        return SimpleNamespace(documents=[], counts={})


class AlwaysStable(StabilityProbe):
    def __init__(self): super().__init__(0.0, 0.1)
    async def is_stable(self, path): return True


@pytest.fixture
def runtime(tmp_path: Path):
    (tmp_path / "inbox").mkdir()
    return SimpleNamespace(root=tmp_path, config=WikiProjectConfig(inbox=InboxConfig()))


async def test_burst_coalesces_into_one_run(runtime) -> None:
    CountingProcessor.runs = 0
    obs = FakeObserver()
    (runtime.root / "inbox" / "a.md").write_text("a")
    w = InboxWatcher(runtime, probe=AlwaysStable(), debounce=0.05,
                     observer_factory=lambda: obs, processor_factory=CountingProcessor)
    await w.start()
    for name in ("a.md", "b.md", "c.md"):
        threading.Thread(target=obs.handler.dispatch,
                         args=(SimpleNamespace(src_path=str(runtime.root / "inbox" / name)),)).start()
    await asyncio.sleep(0.3)
    await w.stop(drain=True)
    assert CountingProcessor.runs == 1
    assert obs.joined is True
```
> FILL IN: add `test_unstable_candidate_defers_run` (probe stable only after N calls),
> `test_lock_busy_is_retried` (`fail_first_with_lock = True`, `lock_retry_delay=0.01`),
> `test_startup_scan_processes_preexisting_file` (no events fired), and
> `test_start_twice_raises`. Reset `CountingProcessor` class state in each test.
> If `WikiProjectConfig(inbox=...)` needs more required fields, build it the way
> `tests/knowledge/wiki/inbox/test_inbox_config.py` does — do not invent fields.

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
   `feat(fireflies-insights-agent): TASK-4566 — <title>`.
9. **Close** with `scripts/sdd/close_task.sh TASK-4566 fireflies-insights-agent verified` — never move
   the file by hand.
10. **Fill in the Completion Note** below, then commit the staged SDD state.

---

## Completion Note

**Completed by**: sdd-worker; coder seat gpt-5.6-terra (codex, attempt 1, 698.4s)
**Date**: 2026-10-22
**Notes**: Extended watcher.py with InboxWatcher (watchdog observer + debounce), WatcherConfig, run_watcher. Extended __init__.py exports. 90 passed merge-tier validation. No review fixes needed.

**Deviations from spec**: none
