# TASK-3119: Fidelity check and in-memory job table

**Feature**: FEAT-549 — `sdd-worker` as Orchestrator of Parallel `sdd-coder` Sub-Agents
**Spec**: `sdd/specs/sdd-worker-subagents.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3115
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 (two pure helpers the engine composes). `fidelity.py` decides whether
a coder branch may be merged: committed changes must be a subset of the files listed
under the task's `## Files to Create / Modify` and must never touch `sdd/` (spec G7,
AC-7; design research S5 adds the clean-status gate in the engine). `jobs.py` is the
process-local registry behind `coder_run_chunk` / `coder_wait` / `coder_status`: jobs
are `asyncio.Task`s, `wait` returns a snapshot even on timeout (AC-12).

---

## Scope

- Implement `parse_task_files`, `check_fidelity`, `FidelityReport` in `sdd_coder/fidelity.py`.
- Implement `JobTable` in `sdd_coder/jobs.py` (create / get / snapshot / wait).
- Unit tests.

**NOT in scope**: git commands (the engine feeds `changed` lists), journaling to disk (engine, TASK-3120), dispatch.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/fidelity.py` | CREATE | task-file parser + set check |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/jobs.py` | CREATE | `JobTable` |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_fidelity.py` | CREATE | parser + check tests |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_jobs.py` | CREATE | job table tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import asyncio, re, time, uuid
from datetime import datetime, timezone
from typing import Awaitable, Callable, Dict, List
from pydantic import BaseModel, Field
from parrot.flows.dev_loop.sdd_coder.models import CoderJob, TaskResult   # TASK-3115
```

### Existing Signatures to Use
```markdown
<!-- sdd/templates/task.md:33 — the heading parse_task_files reads; bullets are a markdown table in the template: -->
## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/path/to/new_file.py` | CREATE | Main implementation |
```
```python
# CoderJob (TASK-3115): job_id, feature_id, chunk_task_ids, state: Literal["running","done","error"], started_at, ended_at="", tasks: List[TaskResult], error=""
```

### Does NOT Exist
- ~~`sdd/tasks/active/TASK-*.md` with a bulleted "Files to Create/Modify" list~~ — the template uses a **table** (`| \`path\` | CREATE | … |`); older tasks may use bullets — parse both: first backtick-quoted token per table row or bullet.
- ~~persistent job storage~~ — `JobTable` is in-memory; the on-disk journal is the engine's `_journal` (TASK-3120).
- ~~`asyncio.timeout`~~ for Python < 3.11 compatibility concerns — the repo is `>=3.11`; `asyncio.wait_for` is fine and is what the spec names.

---

## Implementation Notes

### Key Constraints
- `parse_task_files` returns repo-relative paths as written (strip backticks/whitespace), in file order, deduplicated.
- `check_fidelity`: `ok ⇔ set(changed) ⊆ set(expected) and not any(p.startswith("sdd/") for p in changed)`; `sdd_touched` lists offenders separately from `unexpected`.
- `JobTable.wait` never raises on timeout; it returns the current snapshot with `state="running"`.
- Snapshots are `CoderJob` copies (`model_copy(deep=True)`) so callers cannot mutate live state.

---

## Implementation Blueprint

### Steps (in order)
1. `fidelity.py` — *why*: AC-7 is a hard gate before every merge; keeping it pure makes it trivially testable.
2. `jobs.py` — *why*: AC-12/AC-21 need a job id that returns immediately and a bounded `wait`.
3. Tests, `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder -v`.

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/fidelity.py` (CREATE)
```python
"""File-fidelity gate for coder branches (spec G7/AC-7, design research S5)."""
from __future__ import annotations

import re
from typing import List

from pydantic import BaseModel, Field

_HEADING = re.compile(r"^## Files to Create ?/ ?Modify\s*$", re.M)      # sdd/templates/task.md:33
_NEXT_HEADING = re.compile(r"^## ", re.M)
_BACKTICK_PATH = re.compile(r"`([^`\s]+)`")


class FidelityReport(BaseModel):
    ok: bool
    expected: List[str] = Field(default_factory=list)
    changed: List[str] = Field(default_factory=list)
    unexpected: List[str] = Field(default_factory=list)
    sdd_touched: List[str] = Field(default_factory=list)


def parse_task_files(task_md: str) -> List[str]:
    """Paths listed under '## Files to Create / Modify' — first backticked token of each table row or bullet."""
    m = _HEADING.search(task_md)
    if not m:
        return []
    body = task_md[m.end():]
    n = _NEXT_HEADING.search(body)
    body = body[: n.start()] if n else body
    paths: List[str] = []
    # FILL IN: for each non-empty line starting with "|" or "-", take the first _BACKTICK_PATH match; skip the header row
    #          ("| File |") and the separator ("|---|"); dedupe preserving order — bounded by test_parse_task_files_from_template_section
    return paths


def check_fidelity(expected: List[str], changed: List[str]) -> FidelityReport:
    """ok ⇔ changed ⊆ expected and no changed path starts with 'sdd/'."""
    exp = set(expected)
    unexpected = [p for p in changed if p not in exp]
    sdd_touched = [p for p in changed if p.startswith("sdd/")]
    return FidelityReport(ok=not unexpected and not sdd_touched, expected=list(expected), changed=list(changed),
                          unexpected=unexpected, sdd_touched=sdd_touched)
```
**Why this shape**: the heading regex tolerates the template's `Create / Modify` spacing and the WORKFLOW.md variant `Create/Modify`; `sdd/` paths are reported separately so `sdd-worker` can tell "coder edited the index" from "coder touched an extra file".

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/jobs.py` (CREATE)
```python
"""In-memory job registry for the sdd_coder MCP server (spec §3 M4; AC-12, AC-21)."""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Awaitable, Callable, Dict, List

from parrot.flows.dev_loop.sdd_coder.models import CoderJob, TaskResult


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class JobTable:
    """Registry of running/finished ``CoderJob`` snapshots for ONE server process."""

    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)
        self._jobs: Dict[str, CoderJob] = {}
        self._tasks: Dict[str, "asyncio.Task[List[TaskResult]]"] = {}

    def create(self, feature_id: str, task_ids: List[str], runner: Callable[[], Awaitable[List[TaskResult]]]) -> CoderJob:
        """Register + schedule immediately (asyncio.create_task); return the initial snapshot."""
        job = CoderJob(job_id=f"job-{uuid.uuid4().hex[:12]}", feature_id=feature_id, chunk_task_ids=list(task_ids),
                       state="running", started_at=_now())
        self._jobs[job.job_id] = job
        self._tasks[job.job_id] = asyncio.create_task(self._run(job.job_id, runner))
        return job.model_copy(deep=True)

    async def _run(self, job_id: str, runner: Callable[[], Awaitable[List[TaskResult]]]) -> List[TaskResult]:
        # FILL IN: await runner(); on success set tasks/state="done"/ended_at; on exception set state="error", error=str(exc),
        #          log with self.logger.exception; always return the task list (possibly empty) — bounded by test_job_wait_returns_snapshot_on_timeout
        raise NotImplementedError

    def running_task_ids(self) -> set[str]:
        """Task ids owned by jobs still in state 'running' (engine uses it for task_already_running / orphan detection)."""
        return {t for j in self._jobs.values() if j.state == "running" for t in j.chunk_task_ids}

    def get(self, job_id: str) -> CoderJob:
        """Raises KeyError when unknown (toolkit maps it to job_not_found)."""
        return self._jobs[job_id].model_copy(deep=True)

    def snapshot(self, job_id: str) -> CoderJob:
        return self.get(job_id)

    async def wait(self, job_id: str, timeout_s: float) -> CoderJob:
        """Await completion up to timeout_s; ALWAYS returns a snapshot (state stays 'running' on timeout)."""
        task = self._tasks.get(job_id)
        if task is None:
            raise KeyError(job_id)
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=timeout_s)
        except asyncio.TimeoutError:
            pass
        return self.get(job_id)
```
**Why this shape**: `asyncio.shield` keeps the job alive when `wait` times out (a plain `wait_for` would cancel it); `running_task_ids()` is what TASK-3120's `plan` uses to exclude live branches from orphans and TASK-3121's `run_chunk` uses for `task_already_running`.

### FILL IN checklist
- [ ] `fidelity.py::parse_task_files` — table/bullet parsing; bounded by `test_parse_task_files_from_template_section`
- [ ] `jobs.py::JobTable._run` — state transitions + error capture; bounded by `test_job_wait_returns_snapshot_on_timeout`, `test_job_error_state`

---

## Acceptance Criteria

- [ ] `parse_task_files` on a template-shaped section returns the backticked paths in order, ignores header/separator rows, dedupes.
- [ ] `check_fidelity(["a.py"], ["a.py","b.py","sdd/x.json"])` ⇒ `ok=False`, `unexpected=["b.py","sdd/x.json"]`, `sdd_touched=["sdd/x.json"]`.
- [ ] `JobTable.wait(job, 0.01)` on a slow runner returns `state="running"` without raising; after the runner finishes, `get` shows `done` with tasks.
- [ ] A runner that raises ⇒ `state="error"`, `error` non-empty.
- [ ] `get("nope")` raises `KeyError`.
- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_fidelity.py test_jobs.py -v` passes; `ruff`/`mypy` clean.

---

## Test Specification

```python
# test_fidelity.py
from parrot.flows.dev_loop.sdd_coder.fidelity import check_fidelity, parse_task_files

SECTION = """## Scope
x
## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `pkg/a.py` | CREATE | a |
| `tests/test_a.py` | CREATE | t |
| `pkg/a.py` | MODIFY | dup |

## Codebase Contract
- `not/this.py`
"""

def test_parse_task_files_from_template_section():
    assert parse_task_files(SECTION) == ["pkg/a.py", "tests/test_a.py"]
    assert parse_task_files("no section") == []

def test_fidelity_rejects_unexpected_and_sdd():
    r = check_fidelity(["a.py"], ["a.py", "b.py", "sdd/x.json"])
    assert not r.ok and r.unexpected == ["b.py", "sdd/x.json"] and r.sdd_touched == ["sdd/x.json"]
    assert check_fidelity(["a.py"], ["a.py"]).ok

# test_jobs.py
import asyncio, pytest
from parrot.flows.dev_loop.sdd_coder.jobs import JobTable
from parrot.flows.dev_loop.sdd_coder.models import TaskResult

async def test_job_wait_returns_snapshot_on_timeout():
    gate = asyncio.Event()
    async def runner():
        await gate.wait(); return [TaskResult(task_id="TASK-1", outcome="merged")]
    table = JobTable(); job = table.create("FEAT-549", ["TASK-1"], runner)
    snap = await table.wait(job.job_id, 0.01)
    assert snap.state == "running" and table.running_task_ids() == {"TASK-1"}
    gate.set(); done = await table.wait(job.job_id, 1)
    assert done.state == "done" and done.tasks[0].outcome == "merged" and table.running_task_ids() == set()

async def test_job_error_state():
    async def runner(): raise RuntimeError("boom")
    table = JobTable(); job = table.create("F", ["TASK-2"], runner)
    done = await table.wait(job.job_id, 1)
    assert done.state == "error" and "boom" in done.error

def test_job_unknown_id():
    with pytest.raises(KeyError):
        JobTable().get("nope")
```

---

## Agent Instructions

1. **Read the spec** §3 Module 4 (fidelity/jobs skeletons) and §2 step 4.
2. **Check dependencies** — TASK-3115 completed.
3. **Verify the Codebase Contract** — `sed -n 33,42p sdd/templates/task.md`.
4. **Update status** in the per-spec index → `"in-progress"`.
5. **Implement** from the blueprint.
6. **Verify** all acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/TASK-3119-sdd-coder-fidelity-jobs.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
