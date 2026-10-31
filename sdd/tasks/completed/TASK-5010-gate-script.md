# TASK-5010: Gate script `check_spec_consequences.py` with exit matrix (M9c)

**Feature**: FEAT-784 — SDD Decision Audit
**Spec**: `sdd/specs/sdd-decision-audit.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5008
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 9 (gate script part) and G5/G8. `/sdd-spec` (gate before approval) and `/sdd-task`
(advisory warning) both call one deterministic, LLM-free script:
`python -m scripts.sdd.check_spec_consequences sdd/specs/<slug>.spec.md [--json] [--render] [--advisory]`.
It wraps the spec-audit wiring built by TASK-5008 (`spec_audit.is_configured`,
`spec_audit.open_consequence_service`) and the render/check functions of TASK-5006, and maps the
`ConsequenceReport` status to the frozen exit matrix:

| status | exit |
|---|---|
| `pass` | 0 |
| `skipped` (repo not configured, no `## Decisions` block) | 0 |
| `conflict` | 1 |
| `invalid` | 2 |
| `incomplete` | 3 |

Operational failures (exceptions, unbuilt wiki plane, unreadable spec) are **never 0** — except under
`--advisory`, which is the `/sdd-task` form (owner Q3, AC19): it never refuses, it only prints a warning.

---

## Scope

- Create `scripts/sdd/check_spec_consequences.py` with `main(argv: list[str] | None = None) -> int`,
  mirroring `scripts/sdd/check_task_graph.py:main` (argparse, `--json`, `print(... )  # noqa: T201`).
- Arguments: positional `spec` (Path), `--root` (Path, default `.`), `--base-branch` (default `dev`),
  `--json`, `--render`, `--advisory`, `--budget` (int, default `DEFAULT_BUDGET_TOKENS`).
- Short-circuit the unconfigured repository **before** opening any store (G8 — such a repo usually has no
  wiki plane): no block → print `decision audit not configured in this repository` and return 0;
  block present → status `invalid` with `AUDIT_NOT_CONFIGURED`, return 2.
- Default (check) mode: run `check_spec` (read-only). `current` → exit from `report.exit_code`;
  `stale` / `missing` → exit 3 with `consequences-stale` / `consequences-missing` message.
- `--render`: run `render_spec` (writes the two generated sections), then return the report's exit code.
- `--advisory`: never non-zero. Silent when the repo is unconfigured or the sections are `missing`;
  warning on stderr when the report is `conflict`/`invalid`/`incomplete` or the check is `stale`.
- `--json`: emit `report.model_dump(mode="json")` (plus `"check": <status>` in check mode) on stdout.
- Write `tests/sdd_scripts/test_check_spec_consequences.py`.

**NOT in scope**: the `ConsequenceService` itself (TASK-5005), rendering logic (TASK-5006), the wiring
module `spec_audit.py` (TASK-5008), CLI `wikitoolkit spec …` (TASK-5009), editing the `/sdd-spec` /
`/sdd-task` prompts (TASK-5011), CI wiring (spec §1 Non-Goals).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `scripts/sdd/check_spec_consequences.py` | CREATE | Gate script: exit matrix, check/render/advisory/json modes |
| `tests/sdd_scripts/test_check_spec_consequences.py` | CREATE | Exit-matrix, advisory, skipped and JSON-shape tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.decisions.render import DEFAULT_BUDGET_TOKENS          # verified: decisions/render.py:19
from parrot.knowledge.wiki.decisions.models import AUDIT_NOT_CONFIGURED            # added by TASK-4997 (models.py error vocabulary)
from parrot.knowledge.wiki.decisions.spec_entries import DECISIONS_HEADING, extract_block   # created by TASK-4999
from parrot.knowledge.wiki.decisions.consequences_render import check_spec, render_spec      # created by TASK-5006
from parrot.knowledge.wiki.decisions.spec_audit import is_configured, open_consequence_service  # created by TASK-5008
```

### Existing Signatures to Use
```python
# scripts/sdd/check_task_graph.py — the shape to copy
class Finding(BaseModel): level: str; code: str; tasks: list[str]; message: str        # line 77
def main(argv: list[str] | None = None) -> int:                                        # line 651
    parser = argparse.ArgumentParser(...)                                              # line 653
    parser.add_argument("--json", action="store_true", ...)                            # line 656
    print(json.dumps(...))  # noqa: T201 - CLI output                                  # line 660
if __name__ == "__main__":                                                             # line 667
    raise SystemExit(main())

# Contracts from earlier tasks of this feature (spec §3 skeletons — not renegotiable)
# decisions/spec_entries.py (TASK-4999)
DECISIONS_HEADING = "## Decisions"
def extract_block(text: str, heading: str) -> tuple[str | None, int, int]
# decisions/consequences.py (TASK-5004)
class ConsequenceReport(_Strict):
    status: Literal["pass", "skipped", "conflict", "invalid", "incomplete"]; exit_code: int
    input_digest: str; evaluation_digest: str; snapshot: SnapshotManifest
    findings: list[Finding]; diagnostics: list[DecisionDiagnostic]; coverage: CoverageSummary
# decisions/consequences_render.py (TASK-5006)
class CheckResult(_Strict): status: Literal["current", "stale", "missing"]; report: ConsequenceReport
async def render_spec(service: ConsequenceService, spec_path: Path, *, budget_tokens: int) -> ConsequenceReport
async def check_spec(service: ConsequenceService, spec_path: Path) -> CheckResult
# decisions/spec_audit.py (TASK-5008, PLAN decision 8)
def is_configured(root: Path) -> bool
def open_consequence_service(root: Path, *, store: Any = None, config: Any = None, base_branch: str = "dev") -> Any   # TASK-5008; the script passes only root + base_branch
```

### Does NOT Exist
- ~~`scripts/sdd/check_spec_consequences.py`~~ — created by this task.
- ~~an exit code for `skipped` other than 0~~ — `skipped` is 0 by the matrix (G8).
- ~~`ConsequenceReport.passed` / `.ok`~~ — use `status` and `exit_code` only.
- ~~a CI workflow step for this gate~~ — deferred (spec §1 Non-Goals).
- ~~`scripts.sdd.check_task_graph.Finding` reuse~~ — the gate reports the feature's own `ConsequenceReport`; do not import task-graph models.
- ~~`ADR_UNSUPPORTED_SCHEMA`~~ — the code is `ADR_SCHEMA_UNSUPPORTED` (models.py:19).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "scripts/sdd/check_spec_consequences.py", "action": "CREATE"},
    {"path": "tests/sdd_scripts/test_check_spec_consequences.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:scripts/sdd/check_task_graph.py#main",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/render.py#DEFAULT_BUDGET_TOKENS"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Zero LLM calls** (AC1). The script imports no client; it only reads the plane.
- **Unconfigured short-circuit happens before `open_consequence_service`** — opening the store on a repo
  without a built wiki plane raises; a portable repo must still get exit 0 (AC19).
- Async work runs through one `asyncio.run(...)` call inside `main`; `main` itself is sync (argparse entry).
- `print` only in this entry-point module, each with `# noqa: T201`. Warnings for `--advisory` go to stderr.
- Exit code for `stale`/`missing` is 3: the persisted audit is not current evidence, which is the
  "incomplete" class of the matrix; never 0 outside `--advisory` (G5: "a stale persisted report fails check mode").
- Default `--root .` — `/sdd-spec` runs from the repo root; resolve `spec` relative to root when not absolute.

### References in Codebase
- `scripts/sdd/check_task_graph.py:651-667` — argparse / JSON / exit pattern.
- `tests/sdd_scripts/test_check_task_graph.py:9` — `from scripts.sdd.check_task_graph import ... main` import style.

---

## Implementation Blueprint

### Steps (in order)
1. Write the script skeleton below — *why*: fixes the CLI surface the three `/sdd-spec` and `/sdd-task` prompts call (TASK-5011).
2. Implement `_unconfigured(...)` first and test it in a bare `tmp_path` — *why*: it is the portability guarantee (AC19) and needs no plane.
3. Implement `_run(...)` with check / render branches — *why*: one async entry keeps `asyncio.run` single.
4. Implement the exit mapping in `_exit_for` and the advisory downgrade — *why*: the matrix is the public contract (AC11).
5. Write the tests with a fake service injected by monkeypatching `open_consequence_service` and `check_spec`/`render_spec` — *why*: exit-mapping tests must not depend on a built wiki plane.

### `scripts/sdd/check_spec_consequences.py` (CREATE)
```python
"""Decision-audit gate for SDD specs (FEAT-784 M9).

Exit matrix: 0 pass|skipped · 1 conflict · 2 invalid · 3 incomplete (also stale/missing generated
sections and any operational failure). ``--advisory`` (the /sdd-task form) always returns 0 and only
prints a warning when an existing report is contrary.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from parrot.knowledge.wiki.decisions.consequences_render import check_spec, render_spec
from parrot.knowledge.wiki.decisions.models import AUDIT_NOT_CONFIGURED
from parrot.knowledge.wiki.decisions.render import DEFAULT_BUDGET_TOKENS
from parrot.knowledge.wiki.decisions.spec_audit import is_configured, open_consequence_service
from parrot.knowledge.wiki.decisions.spec_entries import DECISIONS_HEADING, extract_block

EXIT_BY_STATUS = {"pass": 0, "skipped": 0, "conflict": 1, "invalid": 2, "incomplete": 3}
EXIT_OPERATIONAL = 3
NOT_CONFIGURED_LINE = "decision audit not configured in this repository"


def _unconfigured(spec_text: str) -> tuple[int, dict[str, Any]]:
    """Result for a repo with neither taxonomy nor approvals manifest (spec §2 portability)."""
    yaml_source, _start, _end = extract_block(spec_text, DECISIONS_HEADING)
    if yaml_source is None:
        return 0, {"status": "skipped", "exit_code": 0, "message": NOT_CONFIGURED_LINE}
    return 2, {
        "status": "invalid",
        "exit_code": 2,
        "diagnostics": [{"code": AUDIT_NOT_CONFIGURED, "message": "spec declares decisions but the repo is not configured"}],
    }


async def _run(spec: Path, root: Path, base_branch: str, *, render: bool, budget: int) -> tuple[int, dict[str, Any], str]:
    """Return ``(exit_code, json_payload, check_status)``; check_status is 'rendered' in render mode."""
    service = open_consequence_service(root, base_branch=base_branch)
    if render:
        report = await render_spec(service, spec, budget_tokens=budget)
        return EXIT_BY_STATUS[report.status], report.model_dump(mode="json"), "rendered"
    result = await check_spec(service, spec)
    payload = result.report.model_dump(mode="json") | {"check": result.status}
    # FILL IN: exit code — current ⇒ EXIT_BY_STATUS[result.report.status]; stale/missing ⇒ 3 and add a
    #   message "consequences-stale" / "consequences-missing" to payload — bounded by G5 / AC10 / AC15
    raise NotImplementedError


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; see module docstring for the exit matrix."""
    parser = argparse.ArgumentParser(description="Check a spec's declared decisions against the decision plane.")
    parser.add_argument("spec", type=Path)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--base-branch", default="dev")
    parser.add_argument("--json", action="store_true", help="Emit the ConsequenceReport as JSON.")
    parser.add_argument("--render", action="store_true", help="Write ## Governing Decisions and ## Consequences.")
    parser.add_argument("--advisory", action="store_true", help="Warn instead of failing (the /sdd-task form).")
    parser.add_argument("--budget", type=int, default=DEFAULT_BUDGET_TOKENS)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    spec = args.spec if args.spec.is_absolute() else root / args.spec
    # FILL IN: read spec text (unreadable ⇒ EXIT_OPERATIONAL, or 0 + stderr warning under --advisory);
    #   if not is_configured(root): code, payload = _unconfigured(text) — advisory stays silent and returns 0;
    #   else asyncio.run(_run(...)) inside try/except Exception ⇒ EXIT_OPERATIONAL (never 0 unless --advisory)
    #   — bounded by AC11 ("operational failure never 0") and AC19
    # FILL IN: output — --json ⇒ print(json.dumps(payload, indent=2, sort_keys=True))  # noqa: T201;
    #   otherwise one human line "<status>: <n> finding(s)" (or NOT_CONFIGURED_LINE)  # noqa: T201
    # FILL IN: advisory downgrade — if args.advisory: print a warning to sys.stderr only when the check
    #   status is "stale" or the report status is conflict/invalid/incomplete; silent when "missing"
    #   or unconfigured; return 0 — bounded by AC19 / owner Q3
    raise NotImplementedError


if __name__ == "__main__":
    raise SystemExit(main())
```
**Why this shape**: the exit table and the unconfigured short-circuit are the two public contracts
(G5, G8); everything else delegates to the shared wiring so CLI, MCP and script emit the same report
(spec §4 `test_cli_mcp_json_equivalence`). `sys` is imported for the stderr warning.

### `tests/sdd_scripts/test_check_spec_consequences.py` (CREATE)
```python
"""Exit matrix and portability tests for the decision-audit gate (FEAT-784 M9)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.sdd.check_spec_consequences as gate

_SPEC_NO_BLOCK = "# Feature Specification: demo\n\n## 2. Architectural Design\n\ntext\n"
_SPEC_WITH_BLOCK = _SPEC_NO_BLOCK + "\n## Decisions\n\n```yaml\nschema_version: 1\ndocument_id: demo\nentries: []\n```\n"


def _write(tmp_path: Path, text: str) -> Path:
    spec = tmp_path / "sdd/specs/demo.spec.md"
    spec.parent.mkdir(parents=True)
    spec.write_text(text, encoding="utf-8")
    return spec


def test_unconfigured_without_block_is_skipped(tmp_path, capsys):
    spec = _write(tmp_path, _SPEC_NO_BLOCK)
    assert gate.main([str(spec), "--root", str(tmp_path)]) == 0
    assert gate.NOT_CONFIGURED_LINE in capsys.readouterr().out


def test_unconfigured_with_block_is_invalid(tmp_path):
    spec = _write(tmp_path, _SPEC_WITH_BLOCK)
    assert gate.main([str(spec), "--root", str(tmp_path)]) == 2


@pytest.mark.parametrize("status,code", [("pass", 0), ("conflict", 1), ("invalid", 2), ("incomplete", 3)])
def test_exit_matrix(tmp_path, monkeypatch, status, code):
    # FILL IN: mark the repo configured (create sdd/taxonomy/subsystems.yaml), monkeypatch
    #   gate.open_consequence_service to return a sentinel and gate.check_spec to return a
    #   CheckResult(status="current", report=<ConsequenceReport with this status/exit_code>)
    #   — bounded by AC11
    raise NotImplementedError


def test_stale_and_missing_fail_check_mode(tmp_path, monkeypatch):
    # FILL IN: CheckResult(status="stale") ⇒ 3; status="missing" ⇒ 3 — bounded by G5 / AC15
    raise NotImplementedError


def test_advisory_never_fails(tmp_path, monkeypatch, capsys):
    # FILL IN: conflict ⇒ 0 + warning on stderr; missing ⇒ 0 + empty stderr; unconfigured ⇒ 0 silent — AC19
    raise NotImplementedError


def test_operational_failure_is_never_zero(tmp_path, monkeypatch):
    # FILL IN: open_consequence_service raises RuntimeError ⇒ 3 (and 0 under --advisory) — AC11
    raise NotImplementedError


def test_json_shape(tmp_path, monkeypatch, capsys):
    # FILL IN: --json emits a dict with keys status, exit_code, input_digest, evaluation_digest, findings,
    #   diagnostics, coverage, snapshot and "check" — bounded by spec §4 test_gate_exit_matrix
    raise NotImplementedError
```
**Why**: the matrix is tested with an injected fake so the test runs without a built wiki plane;
plane-backed parity across CLI/MCP/script is TASK-5015's job. `json` is used by the JSON-shape test.

### FILL IN checklist
- [ ] `_run` — stale/missing ⇒ 3 with message; current ⇒ status exit; bounded by G5/AC15
- [ ] `main` — spec read, unconfigured branch, exception ⇒ 3; bounded by AC11/AC19
- [ ] `main` — JSON / human output with `# noqa: T201`
- [ ] `main` — `--advisory` downgrade (silent on missing/unconfigured); bounded by AC19
- [ ] every test body above

---

## Acceptance Criteria

- [ ] `pass`=0, `skipped`=0, `conflict`=1, `invalid`=2, `incomplete`=3; stale/missing sections ⇒ 3 (AC11, AC15).
- [ ] Unconfigured repo + no `## Decisions` block ⇒ exit 0 with the one-line note, store never opened (AC19).
- [ ] Unconfigured repo + block ⇒ exit 2 with `AUDIT_NOT_CONFIGURED`.
- [ ] Operational failure ⇒ never 0, except under `--advisory` (AC11).
- [ ] `--advisory` returns 0 always; warns only on contrary/stale reports (AC19).
- [ ] `--json` emits the full `ConsequenceReport`.
- [ ] `ruff check scripts/sdd/check_spec_consequences.py tests/sdd_scripts/test_check_spec_consequences.py` clean.

---

## Validation Commands

- `pytest tests/sdd_scripts/test_check_spec_consequences.py -q`

---

## Test Specification

See the blueprint test module; required cases: `test_unconfigured_without_block_is_skipped`,
`test_unconfigured_with_block_is_invalid`, `test_exit_matrix` (4 params), `test_stale_and_missing_fail_check_mode`,
`test_advisory_never_fails`, `test_operational_failure_is_never_zero`, `test_json_shape`.

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug sdd-decision-audit --feature-id FEAT-784`).
2. Read the spec §2 (portability principle), §3 M9, AC11/AC19.
3. Confirm TASK-5008 is `done` in `sdd/tasks/index/sdd-decision-audit.json` and that `spec_audit.py`,
   `consequences_render.py`, `spec_entries.py` expose the signatures listed above — if a name differs,
   update this contract first.
4. Mark in-progress, implement from the blueprint, complete every `FILL IN`, run the Validation Commands
   with `PYTHONPATH=packages/ai-parrot/src`.
5. Commit only the two listed files; close with `scripts/sdd/close_task.sh TASK-5010 sdd-decision-audit verified`.

---

## Completion Note

Seat: gpt-5.6-terra · Backend: codex · Model: gpt-5.6-terra · Attempts: 1 · Duration: 185s · Tokens: n/a

- Delivered files match the task list.
- Merge-tier validation: tests/sdd_scripts/test_check_spec_consequences.py 10 passed; package 217 passed, 1 failed — pre-existing env-gated test_backend_parity_is_reported. No review fixes.
