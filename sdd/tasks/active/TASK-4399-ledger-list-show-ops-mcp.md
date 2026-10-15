# TASK-4399: ledger_list / ledger_show operations, MCP tools and remote allowlist

**Feature**: FEAT-689 — wikitoolkit ledger list / show
**Spec**: `sdd/specs/wiki-ledger-show.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4398
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2. This task exposes the TASK-4398 service reads as framework-free operations
(`op_ledger_list`, `op_ledger_show`), as the MCP tools `ledger_list`/`ledger_show` (transport
`_SPECS` + dispatch, both adapter layers, the `parrot_tools` registry), and as `--remote` read-only
tools (`READ_ONLY_TOOLS`). Every edit mirrors the existing `ledger_context` entry in the same file.

---

## Scope

- Add `LedgerListInput`, `LedgerShowInput`, `op_ledger_list` and `op_ledger_show` to `ledger/operations.py`.
- Register `ledger_list`/`ledger_show` in `transport.py` (imports, `_SPECS` with `mount="ledger"`, `elif` dispatch).
- Add both names to `remote.READ_ONLY_TOOLS`.
- Re-export the new inputs/ops from core `wiki/tools.py` and map `LedgerListTool`/`LedgerShowTool` in `_EXPORTS`.
- Add `LedgerListTool`/`LedgerShowTool` to `parrot_tools/wiki/tools.py` and append them in `create_wiki_tools`.
- Re-export them from `parrot_tools/wiki/ledger.py` and register them in `parrot_tools/__init__.py`.
- Update the tool-count/surface tests and regenerate the MCP manifest goldens that list ledger tools.
- Add the M2 tests from spec §4 to `tests/knowledge/wiki/test_ledger_tools.py`.

**NOT in scope**: service methods (TASK-4398); CLI commands (TASK-4400); any change to the
existing `ledger_*` tool behaviour; moving `/sdd-fix` over to the new tools.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/operations.py` | MODIFY | inputs + `op_ledger_list` / `op_ledger_show` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/transport.py` | MODIFY | imports, `_SPECS`, dispatch |
| `packages/ai-parrot/src/parrot/knowledge/wiki/remote.py` | MODIFY | `READ_ONLY_TOOLS` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/tools.py` | MODIFY | re-exports + `_EXPORTS` |
| `packages/ai-parrot-tools/src/parrot_tools/wiki/tools.py` | MODIFY | `LedgerListTool`, `LedgerShowTool`, `create_wiki_tools` |
| `packages/ai-parrot-tools/src/parrot_tools/wiki/ledger.py` | MODIFY | re-export the two tools |
| `packages/ai-parrot-tools/src/parrot_tools/__init__.py` | MODIFY | tool registry entries |
| `tests/knowledge/wiki/test_ledger_tools.py` | MODIFY | M2 unit tests |
| `tests/knowledge/wiki/test_mcp_server_ledger.py` | MODIFY | 12 → 14 tools; new names present |
| `packages/ai-parrot/tests/knowledge/wiki/test_tool_surface_golden.py` | MODIFY | `LEDGER` list gains the two names |
| `packages/ai-parrot/tests/knowledge/wiki/golden/mcp_manifests/ledger.json` | MODIFY | regenerated golden |
| `packages/ai-parrot/tests/knowledge/wiki/golden/mcp_manifests/schema_absent.json` | MODIFY | regenerated golden |
| `packages/ai-parrot/tests/knowledge/wiki/golden/mcp_manifests/schema_present.json` | MODIFY | regenerated golden |

> The last four rows are additions not listed in spec §6. When `/sdd-task` re-verified the spec,
> `test_tool_surface_golden.py:30` and three manifest goldens (each containing 5 `ledger_*` entries)
> turned out to pin the ledger tool set, so they would fail without these updates.

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pydantic import BaseModel, Field                                         # verified: ledger/operations.py:15
from parrot.knowledge.wiki.ledger.events import IssueKind, IssueSeverity       # verified: ledger/operations.py:18 (add IssueStatus)
from parrot.knowledge.wiki.ledger.events import IssueStatus                   # verified: ledger/events.py:24
from parrot.knowledge.wiki.operations import OperationResult                  # verified: ledger/operations.py:19
from parrot.tools.abstract import AbstractTool, ToolResult                     # verified: parrot_tools/wiki/tools.py:20
from parrot.knowledge.wiki.ledger.service import LedgerService                 # TYPE_CHECKING only in operations.py:21-22
```
`typing.get_args` is stdlib; use it to expand `IssueStatus` for `all_statuses`.

### Existing Signatures to Use
```python
# ledger/operations.py
class LedgerContextInput(BaseModel):                                          # line 64
def _failed(exc: Exception) -> OperationResult:                               # line 69
async def op_ledger_ready(service, params, **context) -> OperationResult:     # line 91 — the comment at 93-94 explains why Literals are not called
async def op_ledger_context(service: LedgerService, params: LedgerContextInput, **context: Any) -> OperationResult:  # line 123
# OperationResult(data=..., text=..., is_error=...)

# TASK-4398 (must be merged first) — ledger/service.py
async def list_issues(self, statuses=("open","claimed"), *, kind=None, severity=None, about_prefix=None) -> list[dict]
async def get_issue(self, issue_id: str) -> dict[str, Any] | None              # _issue_dict + "body"
async def issue_history(self, issue_id: str) -> list[dict[str, Any]]
def normalize_issue_id(raw: str) -> str

# transport.py
#   import block lines 22-33 (LedgerContextInput line 25, op_ledger_context line 30)
#   _SPECS entry: "ledger_context": _Spec("ledger", LedgerContextInput, "...")  line 147
#   dispatch: elif name == "ledger_context": async def invoke(params) -> await op_ledger_context(ledger, params)  line 401

# remote.py — READ_ONLY_TOOLS frozenset, "ledger_context" at line 27

# core wiki/tools.py — import block lines 6-17 (op_ledger_context line 14), _EXPORTS "LedgerContextTool" line 79

# parrot_tools/wiki/tools.py
def _to_tool_result(result: OperationResult) -> ToolResult:                   # line 79
class LedgerContextTool(AbstractTool):                                        # line 395 — adapter pattern (name/description/args_schema/__init__/_execute)
#   create_wiki_tools ledger block: LedgerContextTool(ledger_service), at line 581
# parrot_tools/wiki/ledger.py — import list + __all__ ("LedgerContextTool" at lines 6 and 16)
# parrot_tools/__init__.py:155 — "ledger_context": "parrot_tools.wiki.tools.LedgerContextTool",
```

### Does NOT Exist
- ~~`op_ledger_list`~~, ~~`op_ledger_show`~~, ~~`LedgerListInput`~~, ~~`LedgerShowInput`~~, ~~`LedgerListTool`~~, ~~`LedgerShowTool`~~ — this task creates them
- ~~`LedgerService.show`~~ / ~~`LedgerService.history`~~ — the methods are named `get_issue` / `issue_history`
- ~~`IssueStatus(...)`~~ as a constructor — it is a `typing.Literal`; calling it raises `TypeError`
- ~~`parrot_tools.wiki.ledger.LedgerListTool` as the defining module~~ — tools are defined in `parrot_tools/wiki/tools.py`; `ledger.py` only re-exports

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/ledger/operations.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/transport.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/remote.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/tools.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-tools/src/parrot_tools/wiki/tools.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-tools/src/parrot_tools/wiki/ledger.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-tools/src/parrot_tools/__init__.py", "action": "MODIFY"},
    {"path": "tests/knowledge/wiki/test_ledger_tools.py", "action": "MODIFY"},
    {"path": "tests/knowledge/wiki/test_mcp_server_ledger.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/test_tool_surface_golden.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/golden/mcp_manifests/ledger.json", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/golden/mcp_manifests/schema_absent.json", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/golden/mcp_manifests/schema_present.json", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/operations.py#LedgerContextInput",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/operations.py#_failed",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/operations.py#op_ledger_context",
    "sym:packages/ai-parrot-tools/src/parrot_tools/wiki/tools.py#_to_tool_result",
    "sym:packages/ai-parrot-tools/src/parrot_tools/wiki/tools.py#LedgerContextTool",
    "sym:packages/ai-parrot-tools/src/parrot_tools/wiki/tools.py#create_wiki_tools"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Ops stay framework-free (operations.py module docstring): no tool-framework imports.
- Schemas mirror the CLI options one for one (spec §3 M3): `statuses`, `all_statuses`, `kind`, `severity`, `about_prefix`; `issue_id`, `include_history`.
- Status resolution: `all_statuses=True` → `get_args(IssueStatus)`; otherwise `params.statuses or ("open", "claimed")`.
- Unknown id → `OperationResult(text=f"Issue {normalize_issue_id(id)} not found", is_error=True)`.
- Adapters build params with `Model.model_construct(...)`, as `LedgerContextTool` does.
- The MCP surface golden: regenerate with `UPDATE_GOLDEN=1 pytest packages/ai-parrot/tests/knowledge/wiki/test_mcp_manifest_golden.py -q`
  (see `golden/mcp_manifests/README.md`), then **review the diff**. Only the three ledger-bearing manifests should change, and
  only by gaining the two tools. Any other drift means something else changed; stop and report it.

---

## Implementation Blueprint

### Steps (in order)
1. Add the inputs and ops to `operations.py`. *Why:* every other file imports them.
2. Wire `transport.py` (imports → `_SPECS` → dispatch) and `remote.py`. *Why:* without both, the MCP server and `--remote` won't see the tools.
3. Add the two adapters to `parrot_tools/wiki/tools.py` and append them in `create_wiki_tools`. Then update the re-exports in core `tools.py`, `parrot_tools/wiki/ledger.py` and `parrot_tools/__init__.py`. *Why:* this is the `ledger_context` pattern in each file.
4. Update the count and surface tests, regenerate the goldens, add the M2 tests, and run the validation.

### `ledger/operations.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cxF 'from parrot.knowledge.wiki.ledger.events import IssueKind, IssueSeverity' operations.py)
# REPLACE `from parrot.knowledge.wiki.ledger.events import IssueKind, IssueSeverity` (verified: operations.py:18) WITH:
from parrot.knowledge.wiki.ledger.events import IssueKind, IssueSeverity, IssueStatus
# and add `from typing import TYPE_CHECKING, Any, get_args` in place of the existing `from typing import TYPE_CHECKING, Any` (line 13)

# occurrences: 1 (verified: grep -c 'class LedgerContextInput(BaseModel):' operations.py)
# AFTER — insert below the LedgerContextInput class body (its last line is `    max_tokens: int = Field(default=3000, ...)`, operations.py:66)
class LedgerListInput(BaseModel):
    """Schema mirrors `wikitoolkit ledger list` options one for one."""

    statuses: list[IssueStatus] | None = Field(default=None, description="Statuses to include (default open+claimed)")
    all_statuses: bool = Field(default=False, description="Include every status; overrides statuses")
    kind: IssueKind | None = Field(default=None, description="Filter by issue kind")
    severity: IssueSeverity | None = Field(default=None, description="Filter by severity")
    about_prefix: str | None = Field(
        default=None, description="Keep issues with an about entry starting with this prefix"
    )


class LedgerShowInput(BaseModel):
    """Schema mirrors `wikitoolkit ledger show` one for one."""

    issue_id: str = Field(..., description="Issue id, with or without the issue: prefix")
    include_history: bool = Field(default=True, description="Include the issue's event history")

# occurrences: 1 (verified: grep -c 'async def op_ledger_context(' operations.py)
# AFTER — append at end of file, below op_ledger_context (verified: operations.py:123-129)
async def op_ledger_list(service: LedgerService, params: LedgerListInput, **context: Any) -> OperationResult:
    """ledger_list — list issues by status/kind/severity/about prefix → data={"issues": [...]}."""
    try:
        statuses = get_args(IssueStatus) if params.all_statuses else (params.statuses or ("open", "claimed"))
        # FILL IN: issues = await service.list_issues(statuses, kind=..., severity=..., about_prefix=...) — bounded by spec §2 result shape
        return OperationResult(data={"issues": issues})
    except Exception as exc:
        return _failed(exc)


async def op_ledger_show(service: LedgerService, params: LedgerShowInput, **context: Any) -> OperationResult:
    """ledger_show — one issue with body (+ history) → data={"issue":…, "history":[…]}; is_error when unknown."""
    try:
        issue = await service.get_issue(params.issue_id)
        # FILL IN: when issue is None return OperationResult(text=f"Issue {normalize_issue_id(params.issue_id)} not found", is_error=True)
        #          (import normalize_issue_id inside the function from parrot.knowledge.wiki.ledger.service — the module-level import is TYPE_CHECKING-only);
        #          history = await service.issue_history(params.issue_id) if params.include_history else []
        #          — bounded by spec §2 / test_op_ledger_show_unknown_is_error
        return OperationResult(data={"issue": issue, "history": history})
    except Exception as exc:
        return _failed(exc)
```
**Why**: this mirrors `op_ledger_context` exactly. The service import stays deferred because
operations.py only imports `LedgerService` under `TYPE_CHECKING`, to avoid an import cycle.

### `transport.py` (MODIFY)
```python
# occurrences: 1 each (verified: grep -cxF '    LedgerContextInput,' / '    op_ledger_context,' transport.py)
# AFTER `    LedgerContextInput,` (transport.py:25) insert:
    LedgerListInput,
# AFTER `    LedgerReadyInput,` (transport.py:27) insert:
    LedgerShowInput,
# AFTER `    op_ledger_context,` (transport.py:30) insert:
    op_ledger_list,
# AFTER `    op_ledger_ready,` (transport.py:32) insert:
    op_ledger_show,

# occurrences: 1 (verified: grep -c '    "ledger_context": _Spec(' transport.py)
# AFTER — insert below the `"ledger_context": _Spec(...)` line (transport.py:147)
    "ledger_list": _Spec(
        "ledger", LedgerListInput, "List SDD ledger issues by status (or all), kind, severity or about prefix."
    ),
    "ledger_show": _Spec(
        "ledger", LedgerShowInput, "Show one SDD ledger issue in full: state, body and event history."
    ),

# occurrences: 1 (verified: grep -c '    elif name == "ledger_context":' transport.py)
# AFTER — insert below the ledger_context branch (its `return await op_ledger_context(ledger, params)` line, transport.py:404)
    elif name == "ledger_list":

        async def invoke(params: BaseModel) -> OperationResult:
            return await op_ledger_list(ledger, params)

    elif name == "ledger_show":

        async def invoke(params: BaseModel) -> OperationResult:
            return await op_ledger_show(ledger, params)
```

### `remote.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cxF '        "ledger_context",' remote.py)
# AFTER `        "ledger_context",` (remote.py:27) insert:
        "ledger_list",
        "ledger_show",
```

### core `wiki/tools.py` (MODIFY)
```python
# occurrences: 1 each (verified: grep -cxF '    LedgerContextInput,' / '    op_ledger_context,' tools.py)
# AFTER `    LedgerContextInput,` (tools.py:9): `    LedgerListInput,`; AFTER `    LedgerReadyInput,`: `    LedgerShowInput,`
# AFTER `    op_ledger_context,` (tools.py:14): `    op_ledger_list,`; AFTER `    op_ledger_ready,`: `    op_ledger_show,`
# occurrences: 1 (verified: grep -c '    "LedgerContextTool": "parrot_tools.wiki.ledger",' tools.py)
# AFTER `    "LedgerContextTool": "parrot_tools.wiki.ledger",` (tools.py:79) insert:
    "LedgerListTool": "parrot_tools.wiki.ledger",
    "LedgerShowTool": "parrot_tools.wiki.ledger",
```

### `parrot_tools/wiki/tools.py` (MODIFY)
```python
# events import (occurrences: 1, tools.py:17): `from parrot.knowledge.wiki.ledger.events import IssueKind, IssueSeverity, IssueStatus`
# ledger operations import block (tools.py:21-32): add LedgerListInput, LedgerShowInput, op_ledger_list, op_ledger_show (same placement as core tools.py)

# occurrences: 1 (verified: grep -c 'class LedgerContextTool(AbstractTool):' tools.py)
# AFTER — insert below the whole LedgerContextTool class (ends at `return _to_tool_result(await op_ledger_context(...))`, tools.py:409)
class LedgerListTool(AbstractTool):
    """List SDD ledger issues by status, kind, severity or about prefix."""

    name = "ledger_list"
    description = "List SDD ledger issues by status (or all), kind, severity or about prefix."
    args_schema = LedgerListInput

    def __init__(self, ledger_service: "LedgerService"):
        super().__init__(name=self.name, description=self.description)
        self._ledger_service = ledger_service

    async def _execute(
        self,
        statuses: list[IssueStatus] | None = None,
        all_statuses: bool = False,
        kind: IssueKind | None = None,
        severity: IssueSeverity | None = None,
        about_prefix: str | None = None,
    ) -> ToolResult:
        """List ledger issues matching the filters."""
        params = LedgerListInput.model_construct(
            statuses=statuses, all_statuses=all_statuses, kind=kind, severity=severity, about_prefix=about_prefix
        )
        return _to_tool_result(await op_ledger_list(self._ledger_service, params))


class LedgerShowTool(AbstractTool):
    """Show one SDD ledger issue in full, including body and event history."""

    name = "ledger_show"
    description = "Show one SDD ledger issue in full: state, body and event history."
    args_schema = LedgerShowInput

    def __init__(self, ledger_service: "LedgerService"):
        super().__init__(name=self.name, description=self.description)
        self._ledger_service = ledger_service

    async def _execute(self, issue_id: str, include_history: bool = True) -> ToolResult:
        """Show one ledger issue."""
        params = LedgerShowInput.model_construct(issue_id=issue_id, include_history=include_history)
        return _to_tool_result(await op_ledger_show(self._ledger_service, params))

# occurrences: 1 (verified: grep -cxF '                LedgerContextTool(ledger_service),' tools.py)
# AFTER `                LedgerContextTool(ledger_service),` (tools.py:581) insert:
                LedgerListTool(ledger_service),
                LedgerShowTool(ledger_service),
```

### `parrot_tools/wiki/ledger.py` and `parrot_tools/__init__.py` (MODIFY)
```python
# ledger.py — occurrences: 1 each (verified: grep -cxF '    LedgerContextTool,' / '    "LedgerContextTool",' ledger.py)
# AFTER `    LedgerContextTool,` (ledger.py:6): `    LedgerListTool,` ; then `    LedgerShowTool,` after `    LedgerReadyTool,`
# AFTER `    "LedgerContextTool",` (ledger.py:16): `    "LedgerListTool",` and `    "LedgerShowTool",`

# __init__.py — occurrences: 1 (verified: grep -c '"ledger_context": "parrot_tools.wiki.tools.LedgerContextTool",' __init__.py)
# AFTER line 155 insert:
    "ledger_list": "parrot_tools.wiki.tools.LedgerListTool",
    "ledger_show": "parrot_tools.wiki.tools.LedgerShowTool",
```

### Tests (MODIFY)
```python
# tests/knowledge/wiki/test_mcp_server_ledger.py — occurrences: 1 (verified: grep -cxF '        assert len(tools) == 12' …, line 52)
# REPLACE `        assert len(tools) == 12` WITH `        assert len(tools) == 14` and fix the comment above it to "+ 7 ledger tools";
# AFTER `        assert "ledger_context" in tool_names` (line 60) insert:
        assert "ledger_list" in tool_names
        assert "ledger_show" in tool_names

# packages/ai-parrot/tests/knowledge/wiki/test_tool_surface_golden.py — occurrences: 1 (line 30)
# REPLACE the `LEDGER = sorted([...])` line WITH:
LEDGER = sorted(
    ["ledger_open", "ledger_ready", "ledger_claim", "ledger_close", "ledger_context", "ledger_list", "ledger_show"]
)

# tests/knowledge/wiki/test_ledger_tools.py — extend the import from parrot.knowledge.wiki.tools with
# LedgerListInput, LedgerListTool, LedgerShowInput, LedgerShowTool, op_ledger_list, op_ledger_show; then append:
@pytest.mark.asyncio
async def test_op_ledger_list_all_statuses(mock_ledger_service):
    """all_statuses=True passes every IssueStatus to list_issues."""
    # FILL IN: mock list_issues return; await op_ledger_list(svc, LedgerListInput(all_statuses=True));
    #          assert the statuses argument == ("open","claimed","closed","superseded") and data == {"issues": [...]}


@pytest.mark.asyncio
async def test_op_ledger_show_unknown_is_error(mock_ledger_service):
    """Unknown id → is_error=True and the text names the normalized id."""
    # FILL IN: get_issue returns None; result.is_error and "issue:abc123" in result.text for issue_id="abc123"


def test_ledger_list_show_tool_names():
    """Adapter names are fixed by the spec."""
    assert LedgerListTool.name == "ledger_list"
    assert LedgerShowTool.name == "ledger_show"


def test_read_only_tools_include_list_show():
    """Both reads are proxied by --remote."""
    from parrot.knowledge.wiki.remote import READ_ONLY_TOOLS

    assert {"ledger_list", "ledger_show"} <= READ_ONLY_TOOLS
```

### FILL IN checklist
- [ ] `op_ledger_list` — pass the resolved statuses and the three filters through; bounded by spec §2
- [ ] `op_ledger_show` — unknown-id error text and the `include_history` branch; bounded by spec §2
- [ ] the two async test bodies
- [ ] regenerate the goldens and review the diff (only the three ledger-bearing manifests change)

---

## Acceptance Criteria

- [ ] `ledger_list` and `ledger_show` are listed by the MCP server when a ledger is mounted and return the spec §2 data shapes
- [ ] both are in `remote.READ_ONLY_TOOLS`
- [ ] existing `ledger_*` tool tests are unchanged and green
- [ ] the MCP manifest goldens are regenerated, and the diff only adds the two tools
- [ ] `ruff check` is clean on every touched `.py` file

## Validation Commands
- `pytest tests/knowledge/wiki/test_ledger_tools.py -q`
- `pytest tests/knowledge/wiki/test_mcp_server_ledger.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_tool_surface_golden.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_mcp_manifest_golden.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_ledger_bulk_operations.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_remote_client.py -q`

---

## Test Specification

See the Tests block. Spec §4 rows covered: `test_op_ledger_list_all_statuses`, `test_op_ledger_show_unknown_is_error`,
`test_ledger_list_show_tool_names`, `test_read_only_tools_include_list_show`, plus the `test_mcp_server_ledger` integration update.

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug wiki-ledger-show --feature-id FEAT-689`).
2. TASK-4398 must be `done`. Confirm that `LedgerService.get_issue`/`issue_history` and `normalize_issue_id` exist.
3. Verify the Codebase Contract and mark the task `in-progress` in `sdd/tasks/index/wiki-ledger-show.json`.
4. Implement from the blueprint and complete every `FILL IN`.
5. Run the validation with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src`, then commit only the listed files.
6. Close with `scripts/sdd/close_task.sh TASK-4399 wiki-ledger-show verified` and fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: added the golden surface/manifest updates that spec §6 missed (see Files table note).
