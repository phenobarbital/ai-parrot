# TASK-3392: `wikitoolkit ledger plan-fix`, `ledger unclaim`, `ledger close --resolved-by`

**Feature**: FEAT-572 — `/sdd-fix` Ledger-Driven Fix Lane
**Spec**: `sdd/specs/sdd-fix-ledger-lane.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3390, TASK-3391
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 (CLI half) and §8 resolved questions on `parents` / slug uniqueness. The
three `/sdd-fix` twins (TASK-3394) never re-implement ordering, grouping or lane logic — they
run `wikitoolkit ledger plan-fix --json` and parse the `FixPlan`. This command is therefore
the purity boundary's other side: it owns the **two filesystem lookups the pure planner
cannot do** — resolving each `spec:FEAT-<NNN>` parent's `completed_at` through
`LedgerService.feature_index_status()`, and de-duplicating `suggested_slug` against existing
`sdd/specs/*.spec.md` stems. Neither lookup is fatal.

`ledger unclaim` and `ledger close --resolved-by` expose the TASK-3391 service methods.

---

## Scope

- Add `plan-fix` to the `ledger` click group: `--kind`, `--severity`, `--lane fast|sdd`,
  `--json`. Mirrors `ledger ready`'s `LedgerService.from_root()` + `_run()` + `WikiStoreBusy`
  guard; on busy, plan from the committed snapshot `sdd/ledger/issues.jsonl` (status `open`
  rows) instead of failing.
- Module-level helpers in `cli.py`: `_load_ledger_snapshot(root) -> list[dict]`,
  `_spec_parent_ids(rows) -> set[str]`, `_dedupe_slugs(plan, specs_dir) -> None`.
- Add `unclaim <issue-id> --reason --actor`.
- Add `--resolved-by` to `close` and forward it.
- CREATE `tests/knowledge/wiki/test_cli_plan_fix.py`.

**NOT in scope**: the MCP `LedgerCloseTool` (TASK-3393); the twins (TASK-3394); any change
to the planner or service.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | import planner; `plan-fix`, `unclaim`, `close --resolved-by`; 3 helpers |
| `tests/knowledge/wiki/test_cli_plan_fix.py` | CREATE | CLI tests for the three surfaces |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.ledger.fix_planner import FixPlan, Lane, plan_fix_batch   # TASK-3389/3390
from parrot.knowledge.wiki.ledger.service import LedgerService                       # verified: cli.py:95 already imports it
from parrot.knowledge.wiki.ledger.events import IssueKind, IssueSeverity             # cli.py:94 imports IssueKind; add IssueSeverity
from parrot.knowledge.wiki.store import WikiStoreBusy                                # verified: cli.py:91
from parrot.knowledge.wiki.cli import ledger                                          # verified: tests/knowledge/wiki/test_cli_ledger.py:17
from click.testing import CliRunner                                                   # verified: test_cli_ledger.py:15
from unittest.mock import AsyncMock, MagicMock, patch                                 # verified: test_cli_ledger.py:12
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py
import errno                                                          # 28
from typing import Any, Optional, cast                                # 38
from parrot.knowledge.wiki.ledger.events import IssueKind             # 94
from parrot.knowledge.wiki.ledger.service import LedgerService        # 95  ← add the fix_planner import right below
def _run(coro: Any) -> Any:  return asyncio.run(coro)                 # 494
@wiki.group(name="ledger") def ledger() -> None                        # 2638-2640
@ledger.command("ready")  def ledger_ready(kind: str | None) -> None:  # 2681-2695 — THE pattern:
    service = LedgerService.from_root()
    try:
        kind_enum = cast(IssueKind, kind) if kind else None
        issues = _run(service.ready_work(kind=kind_enum))
        for issue in issues: click.echo(f"{issue['issue_id']} [{issue['severity']}] {issue['title']} ({issue['kind']})")
        if not issues: click.echo("No ready issues.")
    except WikiStoreBusy as exc: click.echo(f"Ledger index is busy ({exc.operation}); no ready issues available (index_pending)")
@ledger.command("claim") … exit 1 on False, exit 2 on busy             # 2697-2712
@ledger.command("close")                                               # 2730
@click.argument("issue_id")
@click.option("--reason", required=True, help="Reason for closing.")
@click.option("--actor", default="agent:cli", help="Actor closing the issue.")   # 2733 ← add --resolved-by below this
def ledger_close(issue_id: str, reason: str, actor: str) -> None:      # 2734
        success = _run(service.close_issue(issue_id, reason, actor))   # 2738
@ledger.command("context")                                             # 2748 ← insert plan-fix + unclaim ABOVE this decorator
# ledger_open (2650-2678) shows the EROFS pattern: `except OSError as exc: if exc.errno != errno.EROFS: raise`

# service (TASK-3391): service.shared_root: Path; async unclaim(issue_id, reason, actor) -> bool;
#   async close_issue(issue_id, reason, actor, resolved_by=None) -> bool; async feature_index_status(ids) -> dict[str, str|None]
# planner (TASK-3390): plan_fix_batch(rows, *, kind, severity, lane_override, parent_index_status, generated_at) -> FixPlan
#   FixPlan.groups[i].suggested_slug (mutable Pydantic field), FixPlan.model_dump_json(indent=2), FixPlan.model_validate_json(...)
#   FixGroup.issues[i].discovered_from — parents come from rows' "discovered_from" matching ^spec:(FEAT-\d+)$
# sdd/ledger/issues.jsonl — one _issue_dict JSON object per line; "status" key present.

# tests/knowledge/wiki/test_cli_ledger.py — patterns to copy (do NOT modify that file here):
#   patch("parrot.knowledge.wiki.cli.LedgerService.from_root", return_value=service); runner.invoke(ledger, ["ready"])
#   mock: MagicMock(spec=LedgerService) with AsyncMock attributes (28-58). NOTE spec=LedgerService only knows methods that
#   exist at import time — TASK-3391 must be merged for `unclaim`/`feature_index_status` to pass the spec check.
```

### Does NOT Exist
- ~~`ledger plan-fix` / `ledger unclaim`~~ — this task adds them. The group today has exactly: `open`, `ready`, `claim`, `acknowledge`, `close`, `context`, `blockers`, `export`, `sync`, `rebuild`, `ingest-sdd`, `compact`, `audit`.
- ~~`ledger close --resolved-by`~~ — added here.
- ~~`ledger related`~~ — deliberately absent (FEAT-566); do not add.
- ~~parsing `ledger ready` text output~~ — `plan-fix` calls `service.ready_work()` and gets dicts.
- ~~slug/parents logic inside `fix_planner.py`~~ — de-dupe and index lookup live HERE, in `cli.py` helpers.
- ~~`LedgerService.from_root()` raising on a read-only root~~ — it `mkdir`s; only writes fail with `EROFS`. `plan-fix` is read-only and needs no EROFS branch; `unclaim`/`close` mirror `ledger_open`'s pattern if you add one.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/cli.py", "action": "MODIFY"},
    {"path": "tests/knowledge/wiki/test_cli_plan_fix.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#ledger",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#ledger_ready",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#ledger_close",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#ledger_open",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#_run",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#LedgerService",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/fix_planner.py#plan_fix_batch",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/fix_planner.py#FixPlan"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `--json` prints **only** `plan.model_dump_json(indent=2)` on stdout; any busy/degradation
  notice goes to stderr (`click.echo(..., err=True)`) so the twins can parse stdout.
- Slug de-dupe is deterministic **in group order**: walk `plan.groups`, keep a `seen` set
  seeded with existing spec stems; on collision append `-2`, `-3`, … until free; add the
  final slug to `seen`. Collisions *between two groups of the same plan* are handled by the
  same walk.
- Unreadable index dir → `feature_index_status` raising `OSError` → catch → `{}` (every
  parent `open=False`). Unreadable specs dir → skip de-dupe. Never fail the plan.
- FEAT-570 (`expose-local-mcp-tools`) may touch `cli.py`; if it lands first, re-verify the
  `@ledger.command("context")` anchor before inserting.
- `black -l 120`, `ruff check`.

### References in Codebase
- `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:2681-2712` — `ready`/`claim` bodies.
- `tests/knowledge/wiki/test_cli_ledger.py:93-139` — busy and EROFS test patterns.

---

## Implementation Blueprint

### Steps (in order)
1. Import `plan_fix_batch`, `FixPlan`, `Lane`, `IssueSeverity` — *why*: the CLI is the only non-test consumer of the planner.
2. Add the three helpers above the `ledger` group — *why*: they are the I/O the planner refuses to do; keeping them module-level makes them unit-testable.
3. Insert `plan-fix` and `unclaim` above `@ledger.command("context")` — *why*: keeps the group's source order aligned with the lifecycle (open → ready → plan → claim → … → close → unclaim → context).
4. Add `--resolved-by` to `close` — *why*: S4 on the CLI surface.
5. Write the tests; run the new file AND `test_cli_ledger.py` (regression).

### `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF 'from parrot.knowledge.wiki.ledger.service import LedgerService' packages/ai-parrot/src/parrot/knowledge/wiki/cli.py)
# AFTER — insert below that import (verified: cli.py:95); also change line 94 to `from parrot.knowledge.wiki.ledger.events import IssueKind, IssueSeverity`
from parrot.knowledge.wiki.ledger.fix_planner import FixPlan, Lane, plan_fix_batch
```
```python
# occurrences: 1 (verified: grep -cF '@wiki.group(name="ledger")' packages/ai-parrot/src/parrot/knowledge/wiki/cli.py)
# BEFORE — insert ABOVE `@wiki.group(name="ledger")` (verified: cli.py:2638)
_SPEC_PARENT_RE = re.compile(r"^spec:(FEAT-\d+)$")  # add `import re` at the top if absent


def _load_ledger_snapshot(root: Path) -> list[dict[str, Any]]:
    """Open rows from the committed ``sdd/ledger/issues.jsonl`` — the busy-index fallback for plan-fix."""
    # FILL IN: read <root>/sdd/ledger/issues.jsonl line by line (json.loads), keep rows with status == "open";
    #          missing file / bad JSON → [] — bounded by test_cli_plan_fix_busy_falls_back_to_snapshot


def _spec_parent_ids(rows: list[dict[str, Any]]) -> set[str]:
    """``FEAT-<NNN>`` ids from rows whose ``discovered_from`` is ``spec:FEAT-<NNN>`` (other forms yield nothing)."""
    return {m.group(1) for row in rows if (m := _SPEC_PARENT_RE.match(str(row.get("discovered_from") or "")))}


def _dedupe_slugs(plan: FixPlan, specs_dir: Path) -> None:
    """Suffix colliding ``suggested_slug`` values with ``-2``, ``-3``… in group order (deterministic, I/O lives here)."""
    try:
        seen = {p.name[: -len(".spec.md")] for p in specs_dir.glob("*.spec.md")} if specs_dir.exists() else set()
    except OSError:
        return
    # FILL IN: for group in plan.groups — base = group.suggested_slug; n = 2; while slug in seen: slug = f"{base}-{n}"; n += 1;
    #          group.suggested_slug = slug; seen.add(slug) — bounded by test_cli_plan_fix_dedupes_slug_against_existing_specs
```
```python
# occurrences: 1 (verified: grep -cF '@ledger.command("context")' packages/ai-parrot/src/parrot/knowledge/wiki/cli.py)
# BEFORE — insert ABOVE `@ledger.command("context")` (verified: cli.py:2748)
@ledger.command("plan-fix")
@click.option("--kind", type=click.Choice(["bug", "tech_debt", "feature_gap", "vulnerability"]), default=None)
@click.option("--severity", type=click.Choice(["critical", "major", "minor", "low"]), default=None)
@click.option("--lane", type=click.Choice(["fast", "sdd"]), default=None, help="Force the lane for every group.")
@click.option("--json", "as_json", is_flag=True, help="Emit the FixPlan as JSON (stdout only).")
def ledger_plan_fix(kind: str | None, severity: str | None, lane: str | None, as_json: bool) -> None:
    """Plan a fix batch: severity-ordered, file-grouped, lane-labelled (FEAT-572)."""
    service = LedgerService.from_root()
    try:
        rows = _run(service.ready_work(kind=cast(IssueKind, kind) if kind else None))
    except WikiStoreBusy as exc:
        click.echo(f"Ledger index is busy ({exc.operation}); planning from committed snapshot", err=True)
        rows = _load_ledger_snapshot(service.shared_root)
    parents = _spec_parent_ids(rows)
    try:
        status = _run(service.feature_index_status(parents)) if parents else {}
    except OSError as exc:
        click.echo(f"Index directory unreadable ({exc}); parents reported as not open", err=True)
        status = {}
    try:
        plan = plan_fix_batch(
            rows,
            kind=cast(IssueKind, kind) if kind else None,
            severity=cast(IssueSeverity, severity) if severity else None,
            lane_override=cast(Lane, lane) if lane else None,
            parent_index_status=status,
        )
    except ValueError as exc:  # S7: --lane fast on a critical/vulnerability group
        click.echo(f"Refused: {exc}", err=True)
        raise SystemExit(1)
    _dedupe_slugs(plan, service.shared_root / "sdd" / "specs")
    if as_json:
        click.echo(plan.model_dump_json(indent=2))
        return
    # FILL IN: human table — one header line per group: f"{g.group_id} [{g.max_severity}] lane={g.lane} slug={g.suggested_slug} ({g.lane_reason})"
    #          then one indented line per issue like ledger_ready's format; "No ready issues." when plan.groups is empty


@ledger.command("unclaim")
@click.argument("issue_id")
@click.option("--reason", required=True, help="Why the claim is being released.")
@click.option("--actor", default="agent:cli", help="Actor releasing the claim.")
def ledger_unclaim(issue_id: str, reason: str, actor: str) -> None:
    """Release a claim so the issue returns to `ledger ready`."""
    service = LedgerService.from_root()
    try:
        if _run(service.unclaim(issue_id, reason, actor)):
            click.echo(f"Unclaimed {issue_id}")
        else:
            click.echo(f"Could not unclaim {issue_id} (not claimed or unknown)")
            raise SystemExit(1)
    except WikiStoreBusy as exc:
        click.echo(f"Ledger index is busy ({exc.operation}); cannot unclaim")
        raise SystemExit(2)
```
```python
# occurrences: 1 (verified: grep -cF '@click.option("--actor", default="agent:cli", help="Actor closing the issue.")' …/cli.py)
# AFTER — insert below that decorator (verified: cli.py:2733):
@click.option("--resolved-by", default=None, help="Evidence ref: commit:<sha> or task:TASK-<NNN>.")
# occurrences: 1 — REPLACE `def ledger_close(issue_id: str, reason: str, actor: str) -> None:` (cli.py:2734) with:
def ledger_close(issue_id: str, reason: str, actor: str, resolved_by: str | None) -> None:
# occurrences: 1 — REPLACE `success = _run(service.close_issue(issue_id, reason, actor))` (cli.py:2738) with:
        success = _run(service.close_issue(issue_id, reason, actor, resolved_by=resolved_by))
```
**Why this shape**: `plan-fix` is a copy of `ledger ready`'s control flow with the two
CLI-owned lookups bolted on and every degradation reported on stderr, so `--json` stdout is
always a parseable `FixPlan`. `unclaim` copies `claim`'s exit codes (1 refused, 2 busy) so the
twins treat both symmetrically. Passing `resolved_by=` as a keyword keeps existing
`test_ledger_close_command` valid.

### `tests/knowledge/wiki/test_cli_plan_fix.py` (CREATE)
```python
"""CLI tests for `ledger plan-fix`, `ledger unclaim` and `ledger close --resolved-by` (FEAT-572 Module 4)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from parrot.knowledge.wiki.cli import _dedupe_slugs, _spec_parent_ids, ledger
from parrot.knowledge.wiki.ledger.fix_planner import FixPlan
from parrot.knowledge.wiki.ledger.index import LedgerIndex
from parrot.knowledge.wiki.ledger.log import LedgerLog
from parrot.knowledge.wiki.ledger.service import LedgerService
from parrot.knowledge.wiki.ledger.store import LedgerStore
from parrot.knowledge.wiki.store import SQLitePragmaPolicy, WikiStoreBusy

_REPO_ROOT = Path(__file__).resolve().parents[3]
_FROM_ROOT = "parrot.knowledge.wiki.cli.LedgerService.from_root"


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def snapshot_rows() -> list[dict]:
    path = _REPO_ROOT / "sdd" / "ledger" / "issues.jsonl"
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


@pytest.fixture
def mock_service(tmp_path: Path, snapshot_rows) -> MagicMock:
    service = MagicMock(spec=LedgerService)
    service.shared_root = tmp_path
    service.ready_work = AsyncMock(return_value=snapshot_rows)
    service.feature_index_status = AsyncMock(return_value={"FEAT-551": "2026-09-15T13:46:35Z", "FEAT-559": "2026-09-16T09:21:54Z", "FEAT-560": "2026-09-15T23:44:12Z"})
    service.close_issue = AsyncMock(return_value=True)
    service.unclaim = AsyncMock(return_value=True)
    return service


def _real_service(tmp_path: Path) -> LedgerService:
    ledger_dir = tmp_path / ".parrot" / "ledger"; ledger_dir.mkdir(parents=True)
    store = LedgerStore(ledger_dir / "ledger.db", wiki_name="ledger", sqlite_policy=SQLitePragmaPolicy(busy_timeout_s=1.0))
    log = LedgerLog(str(ledger_dir / "events.jsonl"))
    return LedgerService(LedgerIndex(store, log), store, log, tmp_path)


def test_cli_plan_fix_json_matches_fixplan_schema(runner, mock_service):
    with patch(_FROM_ROOT, return_value=mock_service):
        result = runner.invoke(ledger, ["plan-fix", "--json"])
    assert result.exit_code == 0, result.output
    plan = FixPlan.model_validate_json(result.output)
    assert len(plan.groups) == 7 and plan.groups[0].max_severity == "major"
    # FILL IN: every group's parents have open is False (all three FEATs are stamped) — bounded by AC "parents resolved by the CLI"

def test_cli_plan_fix_busy_falls_back_to_snapshot(runner, mock_service, tmp_path, snapshot_rows):
    # FILL IN: write tmp_path/sdd/ledger/issues.jsonl from snapshot_rows; ready_work.side_effect = WikiStoreBusy("ledger.sync");
    #          exit 0, stdout parses as FixPlan with 7 groups — bounded by AC busy→snapshot

def test_cli_plan_fix_dedupes_slug_against_existing_specs(runner, mock_service, tmp_path):
    # FILL IN: first run to learn groups[0].suggested_slug; create tmp_path/sdd/specs/<slug>.spec.md; second run → f"{slug}-2"

def test_cli_plan_fix_survives_unreadable_index_dir(runner, mock_service):
    # FILL IN: feature_index_status.side_effect = OSError("denied"); exit 0; all parents open is False

def test_cli_plan_fix_refuses_fast_override_on_vulnerability(runner, mock_service):
    # FILL IN: ["plan-fix", "--lane", "fast"] over the snapshot (has issue:bcd04b2170a0) → exit 1, "Refused" in output (S7)

def test_cli_close_accepts_resolved_by(runner, mock_service):
    with patch(_FROM_ROOT, return_value=mock_service):
        result = runner.invoke(ledger, ["close", "issue:abc", "--reason", "fixed", "--resolved-by", "commit:deadbeef"])
    assert result.exit_code == 0
    mock_service.close_issue.assert_awaited_once_with("issue:abc", "fixed", "agent:cli", resolved_by="commit:deadbeef")

def test_cli_unclaim_roundtrip(runner, tmp_path):
    service = _real_service(tmp_path)
    issue_id = asyncio.run(service.open_issue(title="Round trip", body="b", discovered_from="task:TASK-1"))
    assert asyncio.run(service.claim(issue_id, "agent:test")) is True
    with patch(_FROM_ROOT, return_value=service):
        assert runner.invoke(ledger, ["unclaim", issue_id, "--reason", "released"]).exit_code == 0
        ready = runner.invoke(ledger, ["ready"])
    assert issue_id in ready.output

def test_spec_parent_ids_only_feat_form():
    rows = [{"discovered_from": "spec:FEAT-551"}, {"discovered_from": "spec:codex-dispatch-stdin-isolation"}, {"discovered_from": "task:TASK-1"}]
    assert _spec_parent_ids(rows) == {"FEAT-551"}
```
**Why**: the mock-backed tests pin the CLI's own logic (parents wiring, de-dupe, degradation);
the two real-service tests prove the claim/unclaim/ready cycle end-to-end through the CLI.

### FILL IN checklist
- [ ] `cli.py::_load_ledger_snapshot` — body; bounded by busy test
- [ ] `cli.py::_dedupe_slugs` — loop; bounded by de-dupe test
- [ ] `cli.py::ledger_plan_fix` — human table branch; bounded by "mirrors `ledger ready` format"
- [ ] `test_cli_plan_fix.py` — 5 test bodies marked FILL IN

---

## Acceptance Criteria

- [ ] `wikitoolkit ledger plan-fix --json` over the snapshot emits a `FixPlan` with exactly 7 groups, the two `major` groups first.
- [ ] `--json` stdout is pure JSON (`FixPlan.model_validate_json` succeeds); notices go to stderr.
- [ ] `WikiStoreBusy` ⇒ plan from `sdd/ledger/issues.jsonl`, exit 0.
- [ ] Parents resolved via `feature_index_status`; an unreadable index dir ⇒ all `open=False`, plan still emitted.
- [ ] Slug collisions against `sdd/specs/*.spec.md` get `-2`, `-3` deterministically in group order.
- [ ] `--lane fast` on a critical/vulnerability group exits 1 with "Refused" (S7).
- [ ] `ledger close --resolved-by` reaches `close_issue(..., resolved_by=)`; omitting it is unchanged.
- [ ] `ledger unclaim` returns an issue to `ledger ready`; exit 1 when refused, 2 when busy.
- [ ] `plan-fix` never parses `ledger ready` text.
- [ ] All tests pass: `pytest tests/knowledge/wiki/test_cli_plan_fix.py tests/knowledge/wiki/test_cli_ledger.py -v`
- [ ] `ruff check` and `black --check -l 120` clean on `cli.py`.

---

## Validation Commands

- `pytest tests/knowledge/wiki/test_cli_plan_fix.py -q`
- `pytest tests/knowledge/wiki/test_cli_ledger.py -q`

---

## Test Specification

```python
def test_cli_plan_fix_json_matches_fixplan_schema(runner, mock_service): ...
def test_cli_plan_fix_busy_falls_back_to_snapshot(...): ...
def test_cli_plan_fix_dedupes_slug_against_existing_specs(...): ...
def test_cli_plan_fix_survives_unreadable_index_dir(...): ...
def test_cli_plan_fix_refuses_fast_override_on_vulnerability(...): ...
def test_cli_close_accepts_resolved_by(...): ...
def test_cli_unclaim_roundtrip(runner, tmp_path): ...
def test_spec_parent_ids_only_feat_form(): ...
```

---

## Agent Instructions

1. **Read the spec** (§3 Module 4 CLI skeleton, §7 "`WikiStoreBusy`", "Read-only ledger", §8 last three resolved questions).
2. **Check dependencies** — TASK-3390 and TASK-3391 completed.
3. **Verify the Codebase Contract** — anchors occur once; `plan_fix_batch` / `unclaim` / `feature_index_status` importable.
4. **Update status** in `sdd/tasks/index/sdd-fix-ledger-lane.json` → `"in-progress"`.
5. **Implement** from the blueprint; option names and exit codes are fixed.
6. **Verify** both Validation Commands (`PYTHONPATH=packages/ai-parrot/src` in a worktree).
7. **Move this file** to `sdd/tasks/completed/TASK-3392-cli-plan-fix-unclaim-resolved-by.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note**.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
