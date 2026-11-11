# TASK-5539: `parrot finance` CLI

**Feature**: FEAT-713 — Accounting Metrics Layer
**Spec**: `sdd/specs/accounting-metrics-layer.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5537
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8 (CLI), AC14. A click group `finance` with `validate` and `explain`, registered lazily in the core
CLI. Snapshots are explicit (`--snapshot <manifest>` required); live validation of a dataframe-backed model needs
`--journal-arrow <IPC file>`; database-backed models use the existing `PARROT_SEMANTIC_CONN_*` resolver.

---

## Scope

- Create `accounting/cli.py`: group `finance` (module attribute **named `finance`**), commands
  `validate <path> [--live] [--models-dir] --snapshot <manifest> [--journal-arrow <file>]` and
  `explain <path> <metric> --snapshot <manifest>`.
  - Structural `validate`: `load_model(path, snapshot_from_manifest(snapshot))` with no journal columns; print the
    full problem list grouped by interval; print that live column checks were skipped; exit 1 on any problem.
  - `--live`: build an `AccountingToolkit` with `snapshot_manifests={tenant: {model: snapshot}}` and, for a
    dataframe source, a `frame_provider` reading the Arrow IPC file; call `live._validate_one` for that model;
    exit 1 on drift or a failed assertion. Missing `--journal-arrow` for a dataframe model ⇒ usage error.
- Core `parrot/cli/__init__.py`: add `"finance": "parrot.semantic.accounting.cli"` to `_lazy_commands` and
  `"finance": "ai-parrot-semantic[duckdb]: pip install ai-parrot-semantic[duckdb]"` to `_lazy_extras`.
- `tests/accounting/test_cli.py`: `test_cli_validate_exit_codes`, `test_cli_snapshot_inputs`,
  `test_cli_explain`, `test_cli_lazy_registration`.

**NOT in scope**: MCP-local config (documented by TASK-5541); scheduler (TASK-5538).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-semantic/src/parrot/semantic/accounting/cli.py` | CREATE | click group |
| `packages/ai-parrot/src/parrot/cli/__init__.py` | MODIFY | lazy registration + extras hint |
| `packages/ai-parrot-semantic/tests/accounting/test_cli.py` | CREATE | CLI tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import click
from parrot.semantic.accounting.loader import load_model                 # TASK-5529
from parrot.semantic.accounting.snapshot import snapshot_from_manifest   # TASK-5528
from parrot.semantic.accounting.errors import ModelValidationError       # TASK-5524
from parrot.semantic.accounting.toolkit import AccountingToolkit         # TASK-5536/5537 (inside --live only)
from parrot.semantic.accounting.live import _validate_one                # TASK-5537 (inside --live only)
from click.testing import CliRunner                                      # tests
```

### Existing Signatures to Use
```python
# CORE/cli/__init__.py
class LazyGroup(click.Group)                     # :19 — get_command: getattr(mod, cmd_name.replace("-", "_")) (:99-100)
cli._lazy_commands = {                           # :170 … last entry :214 `    "disconnect": "parrot.cli.connect",` (occurrences: 1); closes :215
cli._lazy_extras = {                             # :219 … last entry :230
#   `    "ontology": "ai-parrot[ontology-store]: pip install ai-parrot[ontology-store]",` (occurrences: 1); closes :231
# example lazy module: CORE/mcp/local_cli.py:259  @click.command("mcp-local") on a function `mcp_local`
```

### Does NOT Exist
- ~~a `finance` entry in `_lazy_commands`~~ — added here.
- ~~`ai-parrot[finance]` for this feature~~ — that extra is ta-lib; the hint names `ai-parrot-semantic[duckdb]`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-semantic/src/parrot/semantic/accounting/cli.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/cli/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-semantic/tests/accounting/test_cli.py", "action": "CREATE"}
  ],
  "contract_symbols": ["sym:packages/ai-parrot/src/parrot/cli/__init__.py#LazyGroup"]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Write `cli.py` (structural path first).
2. Add the two lazy-registry lines.
3. Add `--live`; tests with `CliRunner`.

### `packages/ai-parrot-semantic/src/parrot/semantic/accounting/cli.py` (CREATE)
```python
"""``parrot finance`` — validate and explain accounting models (FEAT-713 M8)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import click

from .errors import ModelValidationError
from .loader import load_model
from .snapshot import snapshot_from_manifest


@click.group("finance")
def finance() -> None:
    """Accounting metrics layer commands."""


@finance.command("validate")
@click.argument("path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--snapshot", "snapshot_path", required=True, type=click.Path(exists=True, path_type=Path))
@click.option("--live", is_flag=True, help="Refresh the snapshot and run last-closed-month assertions plus drift.")
@click.option("--models-dir", type=click.Path(file_okay=False, path_type=Path), default=None)
@click.option("--journal-arrow", type=click.Path(exists=True, path_type=Path), default=None)
def validate(path: Path, snapshot_path: Path, live: bool, models_dir: Path | None, journal_arrow: Path | None) -> None:
    """Exit 1 on any Problem; prints the full problem list, grouped by interval."""
    try:
        model = load_model(path, snapshot_from_manifest(snapshot_path))
    except ModelValidationError as exc:
        # FILL IN: group exc.problems by interval and echo each; raise SystemExit(1).
        raise SystemExit(1) from exc
    click.echo("structural validation passed; live column checks skipped")
    if live:
        # FILL IN: dataframe source without --journal-arrow ⇒ click.UsageError; build AccountingToolkit
        #   (models_dir default: path.parent.parent; snapshot_manifests={tenant: {model: snapshot_path}};
        #   frame_provider reading the Arrow IPC file); asyncio.run(_validate_one(...)); echo; exit 1 on drift
        #   or any failed assertion.
        ...


@finance.command("explain")
@click.argument("path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument("metric")
@click.option("--snapshot", "snapshot_path", required=True, type=click.Path(exists=True, path_type=Path))
def explain(path: Path, metric: str, snapshot_path: Path) -> None:
    """Print the formula, resolved accounts per set, and covering assertions."""
    # FILL IN: load_model; unknown metric ⇒ click.BadParameter; echo the explanation (same text shape as
    #   AccountingToolkit.explain_metric).
```

### `packages/ai-parrot/src/parrot/cli/__init__.py` (MODIFY)
```python
# AFTER `    "disconnect": "parrot.cli.connect",` (verified: cli/__init__.py:214) — occurrences: 1
    "finance": "parrot.semantic.accounting.cli",
# AFTER `    "ontology": "ai-parrot[ontology-store]: pip install ai-parrot[ontology-store]",` (verified: :230) — occurrences: 1
    "finance": "ai-parrot-semantic[duckdb]: pip install ai-parrot-semantic[duckdb]",
```

### `packages/ai-parrot-semantic/tests/accounting/test_cli.py` (CREATE)
```python
"""FEAT-713 M8 — parrot finance CLI."""

from __future__ import annotations

from click.testing import CliRunner

from parrot.semantic.accounting.cli import finance


def test_cli_validate_exit_codes(troc_pnl_yaml, chart_snapshot, tmp_path) -> None:
    # FILL IN: write chart_snapshot as a YAML manifest; clean model ⇒ exit 0; broken model ⇒ exit 1 with problems.


def test_cli_snapshot_inputs(troc_pnl_yaml, tmp_path) -> None:
    # FILL IN: missing --snapshot ⇒ usage error; --live on a dataframe model without --journal-arrow ⇒ usage error.


def test_cli_explain(troc_pnl_yaml, chart_snapshot, tmp_path) -> None:
    # FILL IN: output names the metric's sets.


def test_cli_lazy_registration() -> None:
    # FILL IN: from parrot.cli import cli; cli.get_command(ctx, "finance") resolves to the finance group.
```

### FILL IN checklist
- [ ] Problem printing, `--live` path, `explain` body; four tests.

---

## Acceptance Criteria

- [ ] `parrot finance validate` is lazily registered, requires `--snapshot`, exits non-zero on any problem (AC14).
- [ ] `--live` refreshes the manifest and runs assertions + drift; dataframe models need `--journal-arrow` (AC14).
- [ ] `ruff check` passes on every touched file.

## Validation Commands

- `pytest packages/ai-parrot-semantic/tests/accounting/test_cli.py -q`

---

## Test Specification

See blueprint.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug accounting-metrics-layer --feature-id FEAT-713`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/accounting-metrics-layer.json`
4. **Verify the Codebase Contract** before writing any code; update it first if anything moved
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`; never change a fixed signature or path
7. **Verify** — run the Validation Commands with absolute `PYTHONPATH` for both `packages/ai-parrot-semantic/src` and `packages/ai-parrot/src`
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `parrot sdd task close TASK-5539 accounting-metrics-layer verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
