# TASK-5248: G1 spike harness core (models, verdict, report, runner)

**Feature**: FEAT-824 — Ontology backend: PostgreSQL OntologyStore + SurrealDB programme
**Spec**: `sdd/specs/ontology-backend.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Phase 1 of FEAT-824 is a reproducible spike (G1) that decides whether SurrealDB 3.3.x and its
Python SDK can carry Phases 3–4. This task builds the harness skeleton: result models, the GO /
NO-GO rule, the Markdown report and the runner. The 13 checks themselves are TASK-5249; running
the harness against a real server is the host step TASK-5250. Spec §2 "Phase 1 — Spike G1",
Module 1.

---

## Scope

- Create `scripts/spikes/surrealdb_g1/harness.py` with `CheckResult`, `SpikeContext`, `Check`,
  `verdict`, `render_report`, `run`, `main` (signatures fixed by spec Module 1).
- Create `scripts/spikes/surrealdb_g1/docker-compose.yml` running one SurrealDB 3.3.x server
  pinned **by digest** (`surrealdb/surrealdb@sha256:<digest>`), in-memory or `surrealkv://`.
- Create `scripts/spikes/surrealdb_g1/README.md`: prerequisites (Docker, `uv`), how to start the
  server, the exact run command `uv run --no-project --with surrealdb==<pin> --with pydantic
  python scripts/spikes/surrealdb_g1/harness.py --report sdd/state/FEAT-824/g1/report.md`, the
  fallbacks (SDK 2.0.0, HTTP `/sql`) and how to read the verdict.
- Create `tests/spikes/test_surrealdb_g1_harness.py` (unit tests, no server, no SDK).

**NOT in scope**: the check implementations and `checks/__init__.py` (TASK-5249); running the
harness or writing `sdd/state/FEAT-824/g1/report.md` (TASK-5250); any `pyproject.toml` change.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `scripts/spikes/surrealdb_g1/harness.py` | CREATE | models, verdict, report, runner, CLI |
| `scripts/spikes/surrealdb_g1/docker-compose.yml` | CREATE | pinned SurrealDB server |
| `scripts/spikes/surrealdb_g1/README.md` | CREATE | how to reproduce the run |
| `tests/spikes/test_surrealdb_g1_harness.py` | CREATE | unit tests for verdict/report/run |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pydantic import BaseModel, Field   # pydantic v2 is a core dependency of ai-parrot
```

### Existing Signatures to Use
```python
# scripts/spikes/tool_call_delegate_spike.py — the only other spike in scripts/spikes/ (style reference only)
```

### Does NOT Exist
- ~~`scripts/spikes/surrealdb_g1/`~~ — this task creates it.
- ~~`tests/spikes/`~~ — does not exist at the repo root; this task creates it (no `__init__.py` needed).
- ~~`surrealdb`~~ — declared in no `pyproject.toml`; never import it at module level in `harness.py`.
- ~~`testcontainers`~~ — not available; the server comes from `docker-compose.yml`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "scripts/spikes/surrealdb_g1/harness.py", "action": "CREATE"},
    {"path": "scripts/spikes/surrealdb_g1/docker-compose.yml", "action": "CREATE"},
    {"path": "scripts/spikes/surrealdb_g1/README.md", "action": "CREATE"},
    {"path": "tests/spikes/test_surrealdb_g1_harness.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- The harness ships in no wheel and adds no dependency to any `pyproject.toml` (spec AC, Phase 1).
- `harness.py` imports only the standard library and pydantic at module level, so the unit test
  runs in the shared venv without the SDK.
- `main()` imports the check list lazily (`from checks import ALL_CHECKS` after putting the
  harness directory on `sys.path`) — `checks/` is created by TASK-5249.
- Check ids are `G1-01` … `G1-13`; blocking set: 01, 02, 03, 04, 05, 07, 08, 09, 10, 11, 12;
  informational: 06, 13 (spec §2 table).
- Use `logging`, never `print`, except that `main` writes the report to the `--report` path.

### References in Codebase
- `sdd/specs/ontology-backend.spec.md` §2 "Phase 1 — Spike G1" — check table and verdict rule.

---

## Implementation Blueprint

### Steps (in order)
1. Write `harness.py` from the block below — *why*: the signatures are fixed by spec Module 1.
2. Write `docker-compose.yml` with the image pinned by digest — *why*: AC requires the report to
   name the digest; `latest` or a bare tag is not reproducible.
3. Write `README.md` — *why*: AC "reproducible from its README on a host with Docker".
4. Write the unit tests and run them — *why*: verdict and report are the only logic testable
   without a server.

### `scripts/spikes/surrealdb_g1/harness.py` (CREATE)
```python
"""FEAT-824 Phase 1 — SurrealDB G1 spike harness.

Runs the G1 check list against a pinned SurrealDB server and SDK and writes a Markdown report
with a GO / NO-GO verdict. Not shipped in any wheel.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import traceback
from pathlib import Path
from typing import Awaitable, Callable, Literal, Sequence

from pydantic import BaseModel, Field

logger = logging.getLogger("parrot.spikes.surrealdb_g1")


class CheckResult(BaseModel):
    """Outcome of one G1 check."""

    check_id: str
    title: str
    blocking: bool
    status: Literal["pass", "fail", "skipped"]
    evidence: str
    measurements: dict[str, float] = Field(default_factory=dict)
    fallback: str | None = None


class SpikeContext(BaseModel):
    """Connection settings and pinned versions for one run."""

    url: str
    username: str
    password: str
    server_image: str
    sdk_version: str


Check = Callable[[SpikeContext], Awaitable[CheckResult]]


def verdict(results: Sequence[CheckResult]) -> Literal["GO", "NO-GO"]:
    """GO only when every blocking check has status 'pass'."""
    # FILL IN: GO iff every result with blocking=True has status == "pass"; an empty list is NO-GO
    #          — bounded by spec §2 "Verdict"; "skipped" on a blocking check is NO-GO.
    raise NotImplementedError


def render_report(ctx: SpikeContext, results: Sequence[CheckResult]) -> str:
    """Render the Markdown report: versions, one row per check, measurements, verdict."""
    # FILL IN: header with ctx.server_image (digest) and ctx.sdk_version; a table
    #          | ID | Check | Blocking | Status | Fallback | Evidence |; a measurements section;
    #          a final line "**Verdict: GO**" or "**Verdict: NO-GO**" — bounded by AC Phase 1 #1.
    raise NotImplementedError


async def run(ctx: SpikeContext, checks: Sequence[Check]) -> list[CheckResult]:
    """Run every check in order; a check that raises is recorded as 'fail' with the error."""
    results: list[CheckResult] = []
    for check in checks:
        try:
            results.append(await check(ctx))
        except Exception as exc:  # noqa: BLE001 — a crashing check is a failed check
            # FILL IN: append CheckResult(status="fail", evidence=traceback text) using the check's
            #          `check_id`/`title`/`blocking` attributes (TASK-5249 sets them on each check
            #          function); fall back to getattr(check, "__name__") when missing.
            raise NotImplementedError from exc
    return results


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry: run all checks, write the report, exit 0 on GO and 1 on NO-GO."""
    parser = argparse.ArgumentParser(description=__doc__)
    # FILL IN: --url, --username, --password, --server-image, --sdk-version, --report (Path);
    #          defaults from env SURREAL_URL / SURREAL_USER / SURREAL_PASS where sensible.
    args = parser.parse_args(argv)
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from checks import ALL_CHECKS  # created by TASK-5249

    # FILL IN: build SpikeContext from args, asyncio.run(run(ctx, ALL_CHECKS)), write
    #          render_report(...) to args.report (mkdir parents), log the verdict, return 0 / 1.
    raise NotImplementedError


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sys.exit(main())
```
**Why this shape**: mirrors spec Module 1's Interface Skeleton exactly; the lazy `checks` import
keeps the module importable without the SDK so the unit test runs in CI.

### `tests/spikes/test_surrealdb_g1_harness.py` (CREATE)
```python
"""Unit tests for the G1 harness (FEAT-824 TASK-5248). No server, no SDK."""
from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

HARNESS = Path(__file__).resolve().parents[2] / "scripts" / "spikes" / "surrealdb_g1" / "harness.py"


def _load():
    spec = importlib.util.spec_from_file_location("g1_harness", HARNESS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_verdict_requires_all_blocking() -> None:
    """NO-GO when one blocking check fails; informational failures do not block."""
    # FILL IN: build CheckResults; assert GO when only an informational one fails, NO-GO otherwise.


def test_report_lists_every_check() -> None:
    """Report has one row per check, the pinned versions and the verdict."""
    # FILL IN


def test_run_records_crashing_check_as_fail() -> None:
    """A check that raises becomes status 'fail' and the run continues."""
    # FILL IN: use asyncio.run(h.run(ctx, [crashing, passing])).
```
**Why**: sync tests with `asyncio.run` because the repo root has no pytest asyncio config.

### FILL IN checklist
- [ ] `verdict` — GO rule; bounded by spec §2 "Verdict".
- [ ] `render_report` — table, measurements, verdict line; bounded by AC Phase 1 #1.
- [ ] `run` — failure record for a raising check.
- [ ] `main` — arguments, report write, exit code.
- [ ] `docker-compose.yml` — real digest of a SurrealDB 3.3.x image (`docker buildx imagetools
      inspect surrealdb/surrealdb:v3.3.<x>` on the host); if the sandbox cannot resolve it, leave
      `# FILL IN: digest` and say so in the Completion Note — TASK-5250 fills it on the host.
- [ ] three test bodies.

---

## Acceptance Criteria

- [ ] `harness.py` imports without `surrealdb` installed.
- [ ] `verdict` returns NO-GO when any blocking check is not `pass`.
- [ ] `render_report` output has one row per result, the image digest, the SDK version and the verdict.
- [ ] No `pyproject.toml` is modified.
- [ ] `ruff check scripts/spikes/surrealdb_g1 tests/spikes` passes.

---

## Validation Commands

- `pytest tests/spikes/test_surrealdb_g1_harness.py -q`

---

## Agent Instructions

1. Work in the feature worktree (`parrot sdd worktree ensure --slug ontology-backend --feature-id FEAT-824`).
2. Read the spec; confirm every `Depends-on` task is `done` in `sdd/tasks/index/ontology-backend.json`.
3. Verify the Codebase Contract before writing code; fix it here first if it drifted.
4. Mark the task `in-progress` in the index, implement from the blueprint, complete every `FILL IN`.
5. Run the Validation Commands; commit only the files listed above.
6. Close with `parrot sdd task close TASK-5248 ontology-backend verified`; fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
