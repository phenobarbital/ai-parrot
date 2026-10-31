# TASK-4995: `wikitoolkit usage report` CLI + paired MCP tool + AC-14 guard

**Feature**: FEAT-783 — Unified usage & cost metrics per SDD spec
**Spec**: `sdd/specs/unified-usage.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4994
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8 (CLI half), G7, AC-12/AC-14. Following TASK-4020's precedent, the CLI
subcommand and its MCP tool ship in one task. The MCP surface has golden manifests
(FEAT-540), so the new tool must appear in `transport._SPECS`, in the dispatch, and in the
`parrot_tools.wiki` wrapper (whose description must match exactly). The goldens are then regenerated.

---

## Scope

- In `knowledge/wiki/cli.py`, add a `@wiki.group(name="usage")` sibling of `ledger`, with `report --feat FEAT-NNN [--by task|model|seat] [--format markdown|json] [--root PATH]`. It reads rows via `read_spec_usage(root, feat)`, builds `build_spec_usage_report`, and renders with the existing renderer (markdown) or `model_dump_json` (json).
- Root default: the same durable-root resolution `SpecUsageRecorder` uses (main checkout `artifacts/logs/sdd-spec-usage`). No worktree check is needed for a reader, but reuse the resolver.
- MCP tool `usage_report` (input model `UsageReportInput{feat_id, by="task"}`): an `_Spec("core", ...)` entry, an `elif name == "usage_report":` dispatch branch, an op function `op_usage_report`, and a `parrot_tools.wiki` `AbstractTool` wrapper with an identical description.
- Regenerate the goldens: `UPDATE_GOLDEN=1 pytest packages/ai-parrot/tests/knowledge/wiki/test_mcp_manifest_golden.py -q`, then review the diff (only the new tool may appear).
- AC-14 guard test: no `usage`-prefixed value in `LedgerEventKind`, and no file under `knowledge/wiki/ledger/` changed by this feature (compare `git diff --name-only origin/dev...HEAD`).

**NOT in scope**: a remote/proxied variant (`remote_cli.remote_aware`); add it only if the golden test demands it.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | `usage` group + `report` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/transport.py` | MODIFY | `_SPECS` entry + dispatch branch |
| `packages/ai-parrot/src/parrot/knowledge/wiki/usage_operations.py` | CREATE | `UsageReportInput` + `op_usage_report` |
| `packages/ai-parrot-tools/src/parrot_tools/wiki/tools.py` | MODIFY | `UsageReportTool` wrapper + registration |
| `packages/ai-parrot/tests/knowledge/wiki/golden/mcp_manifests/*.json` | MODIFY | Regenerated goldens (core-mounted manifests) |
| `packages/ai-parrot/tests/knowledge/wiki/test_cli_usage_report.py` | CREATE | CLI + MCP + AC-14 tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import click                                                                   # cli.py:43
from parrot.flows.dev_loop.usage_report import build_spec_usage_report         # TASK-4994
from parrot.observability.recorders.spec_usage import read_spec_usage          # TASK-4990
```

### Existing Signatures to Use
```python
# knowledge/wiki/cli.py
@wiki.group(name="ledger")    # :3229 (1 occurrence) — anchor; commands use @ledger.command("open") + click.option + click.echo
def ledger() -> None: ...
# knowledge/wiki/transport.py
class _Spec: mount: str; input_model: type[BaseModel]; description: str     # :100
_SPECS: dict[str, _Spec] = {...}                                            # :112; e.g. "wiki_standup": _Spec("core", WikiStandupInput, "...") :142
    elif name == "wiki_standup":                                            # :337 — dispatch pattern:
        async def invoke(params: BaseModel) -> OperationResult:
            return await op_standup(store, params.model_dump(), root=ctx.root, config=ctx.config)
# OperationResult — imported in transport.py (grep its import line); op functions return OperationResult(data=...)
# parrot_tools/wiki/tools.py
class WikiLintTool(AbstractTool): name = "wiki_lint"; description = (...); args_schema = WikiLintInput   # :234 — wrapper pattern
#   async def _execute(...) -> ToolResult: return _to_tool_result(await op_lint(...))
# knowledge/wiki/ledger/events.py:7 — LedgerEventKind = Literal[...]
```

### Does NOT Exist
- ~~`@wiki.group(name="usage")`~~ — this task creates it
- ~~a `usage.*` LedgerEventKind~~ — must never exist (AC-14)
- ~~any edit under `knowledge/wiki/ledger/`~~ — forbidden (AC-14)
- ~~argparse in cli.py~~ — the CLI is click

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/cli.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/transport.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/usage_operations.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-tools/src/parrot_tools/wiki/tools.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/golden/mcp_manifests/*.json", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/test_cli_usage_report.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#ledger",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/transport.py#_Spec",
    "sym:packages/ai-parrot-tools/src/parrot_tools/wiki/tools.py#WikiLintTool"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `wikitoolkit` warm start is ~415 ms (`issue:f0a40d0853f2`). Import `flows.dev_loop` / `observability` **lazily** inside the command and op bodies, never at module top.
- The op is read-only, so mount it under `"core"`, not `"ledger"`: the ledger mount is the work-ledger surface, and AC-14 keeps usage out of it.
- Golden diffs: only the new tool's entry may change. Any other drift means a stale tree; stop and report.
- Two wiki test trees exist (`tests/knowledge/wiki` at the root is what CI runs for the wiki; this task's test lives in the package tree next to the golden test). If CI collects the root tree for CLI tests, mirror the test there too (see memory `two-wiki-test-trees`).

---

## Implementation Blueprint

### Steps (in order)
1. Create `usage_operations.py` (input model + op), so CLI and MCP share one code path.
2. Add the click group/command.
3. Add the `_SPECS` entry + dispatch branch.
4. Add the `parrot_tools` wrapper with an identical description, and register it wherever `WikiLintTool` is registered (FILL IN: `grep -n 'WikiLintTool' packages/ai-parrot-tools/src/parrot_tools/wiki/tools.py`).
5. Regenerate the goldens and review the diff.
6. Tests.

### `usage_operations.py` (CREATE)
```python
"""usage_report — per-spec token/cost report over SpecUsageRecorder rows (FEAT-783 M8)."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

USAGE_REPORT_DESCRIPTION = "Report tokens and cost for one SDD feature, grouped by task, model or seat."


class UsageReportInput(BaseModel):
    """Input for usage_report."""

    feat_id: str = Field(..., pattern=r"^FEAT-\d+$")
    by: Literal["task", "model", "seat"] = "task"


async def op_usage_report(params: UsageReportInput, *, root: Any = None) -> "Any":
    """Return OperationResult(data=UsageReport.model_dump(mode="json"))."""
    # FILL IN: lazy imports; resolve the default root like SpecUsageRecorder; read rows off the loop
    # (asyncio.to_thread); build_spec_usage_report; return OperationResult — import OperationResult from
    # the same module transport.py imports it from; on error return the module's failure shape
    raise NotImplementedError
```

### `cli.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '@wiki.group(name="ledger")' cli.py)
# BEFORE — insert above `@wiki.group(name="ledger")` (cli.py:3229)
@wiki.group(name="usage")
def usage() -> None:
    """Per-spec token and cost reporting."""


@usage.command("report")
@click.option("--feat", "feat_id", required=True, help="Feature id, e.g. FEAT-783.")
@click.option("--by", type=click.Choice(["task", "model", "seat"]), default="task")
@click.option("--format", "fmt", type=click.Choice(["markdown", "json"]), default="markdown")
@click.option("--root", type=click.Path(path_type=Path), default=None, help="Durable usage root (default: main checkout).")
def usage_report(feat_id: str, by: str, fmt: str, root: Path | None) -> None:
    """Render tokens and cost for one feature."""
    # FILL IN: delegate to op_usage_report via _run(...); markdown -> existing renderer from usage_report.py
    # (grep -n '^def render' usage_report.py); json -> json.dumps(data, indent=2) — bounded by AC-12
    raise NotImplementedError
```

### `transport.py` (MODIFY)
```python
# _SPECS — add after the "wiki_standup" entry (transport.py:142-146):
    "usage_report": _Spec("core", UsageReportInput, USAGE_REPORT_DESCRIPTION),
# dispatch — add after the `elif name == "wiki_standup":` branch (transport.py:337-340):
    elif name == "usage_report":

        async def invoke(params: BaseModel) -> OperationResult:
            return await op_usage_report(params, root=None)
# import: from parrot.knowledge.wiki.usage_operations import USAGE_REPORT_DESCRIPTION, UsageReportInput, op_usage_report
```

### `test_cli_usage_report.py` (CREATE)
```python
"""FEAT-783 AC-12 / AC-14 — usage CLI + MCP tool."""
import typing

from click.testing import CliRunner


def test_cli_renders_report_from_rows(tmp_path) -> None:
    # FILL IN: write rows with SpecUsageRecorder(root=tmp_path, ...) or raw JSONL, invoke `usage report --feat
    # FEAT-1 --root tmp_path --format json` via CliRunner on the wiki group, assert grouping
    ...


async def test_mcp_tool_matches_cli(tmp_path) -> None:
    # FILL IN: op_usage_report returns the same data as the CLI json
    ...


def test_no_usage_ledger_event_kind() -> None:
    from parrot.knowledge.wiki.ledger.events import LedgerEventKind

    assert not [k for k in typing.get_args(LedgerEventKind) if str(k).startswith("usage")]
```

### FILL IN checklist
- [ ] `op_usage_report` + the OperationResult import source
- [ ] CLI body + renderer choice
- [ ] Wrapper registration in `parrot_tools`
- [ ] Golden regeneration reviewed
- [ ] Test bodies (+ the git-diff part of AC-14 if CI has git history; otherwise note it in the Completion Note)

---

## Acceptance Criteria

- [ ] AC-12: `wikitoolkit usage report --feat FEAT-NNN` renders tokens and cost by task, model and seat; the paired MCP tool returns the same data.
- [ ] AC-14: no `usage.*` LedgerEventKind; no file under `knowledge/wiki/ledger/` modified.
- [ ] Golden manifests change only by the new tool.

## Validation Commands
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_cli_usage_report.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_mcp_manifest_golden.py -q`

## Test Specification
See blueprint.

## Agent Instructions
Six target entries (goldens are a glob). `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src`.

## Completion Note
_(filled at close)_
