# TASK-5008: Spec-audit wiring, MCP operation and tool registration (M9a)

**Feature**: FEAT-784 — SDD Decision Audit
**Spec**: `sdd/specs/sdd-decision-audit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5006, TASK-5007
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 9 (first half). Three surfaces — MCP (`wiki_spec_consequences`), CLI (TASK-5009) and the gate script
(TASK-5010) — must emit the SAME `ConsequenceReport` (spec §4 `test_cli_mcp_json_equivalence`, S11). This task
creates the one shared wiring module (`spec_audit.py`: configured check + service construction with
`read_repair=False`), the framework-free operation `op_spec_consequences`, and registers the MCP tool in every
place the wiki surface enumerates tools. The task is **exclusive** (`parallel: false`): it regenerates the shared
golden MCP manifests other tasks' tests load.

---

## Scope

- Create `decisions/spec_audit.py`: `is_configured(root)`, `taxonomy_path(root)`, `approvals_path(root)`,
  `open_consequence_service(root, *, store=None, config=None, base_branch="dev")`.
- Add `SpecConsequencesInput` + `op_spec_consequences` to `decisions/operations.py`.
- Register `wiki_spec_consequences` in `transport.py` (`_SPECS`, `_operation_invoke` dispatch, `mounted_operation_names`
  when `ctx.root is not None`).
- Add the framework tool `WikiSpecConsequencesTool` to `parrot_tools/wiki/decisions.py` and append it in
  `create_decision_tools` when `root is not None` — **required**: `test_mcp_manifest_golden.py` (framework transport)
  asserts every mounted descriptor has a framework tool with an identical description and schema.
- Add lazy exports `ConsequenceService`, `ConsequenceReport`, `BatchPublisher` to `decisions/__init__.py`.
- Add `"wiki_spec_consequences"` to `LOCAL_NO_LEDGER` in `_tool_surface.py`.
- Regenerate the ten golden MCP manifests (`UPDATE_GOLDEN=1`) and review the diff: only the new tool may appear.
- Write `test_spec_consequences_op.py`.

**NOT in scope**: CLI commands (TASK-5009), the gate script (TASK-5010), `/sdd-spec` docs (TASK-5011),
`wikitoolkit decisions publish` (TASK-5009).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/spec_audit.py` | CREATE | Shared configured-check + service wiring |
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/operations.py` | MODIFY | `SpecConsequencesInput`, `op_spec_consequences` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/__init__.py` | MODIFY | Lazy exports |
| `packages/ai-parrot/src/parrot/knowledge/wiki/transport.py` | MODIFY | `_Spec`, dispatch, mount |
| `packages/ai-parrot-tools/src/parrot_tools/wiki/decisions.py` | MODIFY | `WikiSpecConsequencesTool` + registration |
| `packages/ai-parrot/tests/knowledge/wiki/_tool_surface.py` | MODIFY | Frozen tool inventory |
| `packages/ai-parrot/tests/knowledge/wiki/golden/mcp_manifests/minimal_local.json` | MODIFY | Regenerated (UPDATE_GOLDEN=1) |
| `packages/ai-parrot/tests/knowledge/wiki/golden/mcp_manifests/ledger.json` | MODIFY | Regenerated |
| `packages/ai-parrot/tests/knowledge/wiki/golden/mcp_manifests/decisions.json` | MODIFY | Regenerated |
| `packages/ai-parrot/tests/knowledge/wiki/golden/mcp_manifests/schema_present.json` | MODIFY | Regenerated |
| `packages/ai-parrot/tests/knowledge/wiki/golden/mcp_manifests/schema_absent.json` | MODIFY | Regenerated |
| `packages/ai-parrot/tests/knowledge/wiki/golden/mcp_manifests/federated.json` | MODIFY | Regenerated |
| `packages/ai-parrot/tests/knowledge/wiki/golden/mcp_manifests/bulk_on.json` | MODIFY | Regenerated |
| `packages/ai-parrot/tests/knowledge/wiki/golden/mcp_manifests/bulk_off.json` | MODIFY | Regenerated |
| `packages/ai-parrot/tests/knowledge/wiki/golden/mcp_manifests/vault.json` | MODIFY | Regenerated |
| `packages/ai-parrot/tests/knowledge/wiki/golden/mcp_manifests/remote_proxy.json` | MODIFY | Regenerated |
| `packages/ai-parrot/tests/knowledge/wiki/decisions/test_spec_consequences_op.py` | CREATE | Operation + registration tests |

All ten manifests change because every `CONFIGS` entry in `test_mcp_manifest_golden.py:21-32` builds the bundle with
a local `root` (`build_wiki_tools(root, ...)`, line 122), so the new root-gated tool mounts in all of them. If any
manifest does NOT change after regeneration, that is fine — do not hand-edit it; note it in the Completion Note.

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.operations import OperationResult                        # verified: decisions/operations.py:13
from parrot.knowledge.wiki.decisions.render import DEFAULT_BUDGET_TOKENS            # verified: decisions/operations.py:12, render.py:19
from parrot.knowledge.wiki.decisions.models import DecisionError                    # verified: models.py:47
from parrot.knowledge.wiki.structural.service import StructuralService              # verified: structural/service.py:130
from parrot.knowledge.wiki.project import WikiProjectConfig                         # verified: imported by decisions/cli.py and parrot_tools/wiki/decisions.py:25
from parrot.tools.abstract import AbstractTool, ToolResult                          # verified: parrot_tools/wiki/decisions.py:36-39
# Deferred (inside functions only — import cycle, see decisions/cli.py:95-100 and decisions/__init__.py:13-22):
from parrot.knowledge.wiki.cli import _resolve_project, _require_built              # verified: wiki/cli.py:394, :484
# FEAT-784 earlier tasks:
from parrot.knowledge.wiki.decisions.consequences import ConsequenceService, ConsequenceReport, audit_configured   # TASK-5004/P09
from parrot.knowledge.wiki.decisions.consequences_render import check_spec, render_governing, render_consequences  # TASK-5006
from parrot.knowledge.wiki.decisions.approvals import GitCommitApprovalAdapter       # TASK-5001
from parrot.knowledge.wiki.decisions.publish import BatchPublisher                   # TASK-5007
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/decisions/operations.py
def _error_result(exc: DecisionError) -> OperationResult                             # line 62
async def op_decision_generate(store: Any, params: DecisionGenerateInput, **context: Any) -> OperationResult:   # line 103 (anchor, occurrences 1)

# packages/ai-parrot/src/parrot/knowledge/wiki/transport.py
from parrot.knowledge.wiki.decisions.operations import (... op_decision_why, ...)     # lines 14-21 (`    op_decision_why,` line 19, occurrences 1)
class _Spec: mount: str; input_model: type[BaseModel]; description: str              # line 100
"wiki_decision_generate": _Spec(                                                     # line 202 (occurrences 1)
def _operation_invoke(name: str, ctx: WikiOperationContext) -> ...                   # line 282 — store = ctx.read_store (295)
    elif name == "wiki_decision_generate":                                           # line 367 (occurrences 1)
def mounted_operation_names(ctx: WikiOperationContext) -> list[str]:                 # line 457
    names += ["wiki_decisions_for_symbol", "wiki_decision_why"]                      # line 472 (occurrences 1)
class WikiOperationContext: store; read_store; root: Path; config; ... read_repair   # line 233

# packages/ai-parrot/src/parrot/knowledge/wiki/decisions/__init__.py
if TYPE_CHECKING:                                                                    # line 29
    from parrot.knowledge.wiki.decisions.service import DecisionService              # line 42 (occurrences 1)
__all__ = [ ... "DecisionService", ... ]                                             # `    "DecisionService",` line 58 (occurrences 1)
_LAZY_SOURCES = { ... "DecisionService": "parrot.knowledge.wiki.decisions.service", ... }   # line 82 (occurrences 1)
# NOTE: TASK-4998 also edits this file (DecisionRef/DecisionTarget exports) — line numbers may have shifted by a few; the anchors stay unique.

# packages/ai-parrot-tools/src/parrot_tools/wiki/decisions.py
class WikiDecisionWhyTool(AbstractTool): name, description, args_schema; __init__(service_factory); async _execute(...) -> ToolResult   # line 96 (pattern)
def create_decision_tools(store, root: Path | None, config: WikiProjectConfig) -> list[AbstractTool]:   # line 164 (occurrences 1)
        tools.append(WikiDecisionGenerateTool(service_factory))                      # line 184 (occurrences 1)
    return tools                                                                     # line 185 (occurrences 1)

# packages/ai-parrot/tests/knowledge/wiki/_tool_surface.py
LOCAL_NO_LEDGER: list[str] = sorted([... "wiki_decisions_for_symbol", ...])          # `        "wiki_decisions_for_symbol",` line 21 (occurrences 1)

# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py
def _resolve_project(path: str | None) -> tuple[Path, WikiProjectConfig]             # line 394
def _require_built(root: Path, config: WikiProjectConfig) -> BaseWikiStore           # line 484 — raises click.ClickException when not built

# TASK-5006: check_spec(service, spec_path) -> CheckResult(status, report); render_governing(dossier, *, budget_tokens, report)
# TASK-5005: ConsequenceService(store, root, config: DecisionConfig, structural, *, taxonomy_path, approvals_path, adapter); .governing(...)
# TASK-5001: GitCommitApprovalAdapter(root: Path, base_branch: str)
```

### Does NOT Exist
- ~~`parrot.knowledge.wiki.decisions.tools.WikiSpecConsequencesTool`~~ — `decisions/tools.py` is a lazy shim onto `parrot_tools.wiki.decisions` (`_TARGET`, line 5); the real class goes in `parrot_tools/wiki/decisions.py`. Do not add it to the shim's `_NAMES` unless a test needs it.
- ~~a `decisions`/`spec` key in `WikiOperationContext`~~ — wiring is built per call from `ctx.root`, `ctx.store`, `ctx.config`.
- ~~`DecisionService.consequences()`~~ — the decision service factory (`decisions/factory.py:18`) builds `DecisionService`, not `ConsequenceService`; do not route through it.
- ~~`_tool_surface.DECISIONS`~~ — only `LOCAL_NO_LEDGER`, `LEDGER`, `BULK` exist.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/decisions/spec_audit.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/decisions/operations.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/decisions/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/transport.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-tools/src/parrot_tools/wiki/decisions.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/_tool_surface.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/golden/mcp_manifests/minimal_local.json", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/golden/mcp_manifests/ledger.json", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/golden/mcp_manifests/decisions.json", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/golden/mcp_manifests/schema_present.json", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/golden/mcp_manifests/schema_absent.json", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/golden/mcp_manifests/federated.json", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/golden/mcp_manifests/bulk_on.json", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/golden/mcp_manifests/bulk_off.json", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/golden/mcp_manifests/vault.json", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/golden/mcp_manifests/remote_proxy.json", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/decisions/test_spec_consequences_op.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/operations.py#_error_result",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/operations.py#op_decision_generate",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/transport.py#_Spec",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/transport.py#_operation_invoke",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/transport.py#mounted_operation_names",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/transport.py#WikiOperationContext",
    "sym:packages/ai-parrot-tools/src/parrot_tools/wiki/decisions.py#create_decision_tools",
    "sym:packages/ai-parrot-tools/src/parrot_tools/wiki/decisions.py#WikiDecisionWhyTool",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#_resolve_project",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#_require_built",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/structural/service.py#StructuralService"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `operations.py` must stay framework-free (`test_plane_operations.py::test_operations_framework_free`) and cheap to
  import (transport imports it eagerly at module top, transport.py:14-21): import `spec_audit`/`consequences*` INSIDE
  `op_spec_consequences`, never at module scope.
- `spec_audit.is_configured(root)` must not open a store or import the structural plane — the gate script calls it
  first in unconfigured repos (G8, AC19).
- `open_consequence_service` builds `StructuralService(store, root, config, read_repair=False)` (spec S6) and
  `GitCommitApprovalAdapter(root, base_branch)`; it reuses `store`/`config` when given (MCP) and otherwise resolves
  them with the deferred `_resolve_project` + `_require_built` (CLI, script). `_require_built` raises
  `click.ClickException` on an unbuilt wiki — catch it and raise `DecisionError(ADR_SOURCE_UNAVAILABLE, ...)`
  (existing code, models.py:36) so callers map it to `incomplete` (exit 3).
- Operation text = rendered Markdown, `data` = `report.model_dump(mode="json")` (JSON equivalence with CLI/script, S11).
- MCP tool mounted only when `ctx.root is not None` (needs a local spec file).

---

## Implementation Blueprint

### Steps (in order)
1. Create `spec_audit.py` — *why*: one wiring for three surfaces is the S11 equivalence guarantee.
2. Add the operation to `operations.py` — *why*: transport and the framework tool both call it.
3. Wire transport (three edits) and the framework tool — *why*: the golden test requires descriptor/tool parity.
4. Update `__init__.py` and `_tool_surface.py`.
5. Run `UPDATE_GOLDEN=1 pytest packages/ai-parrot/tests/knowledge/wiki/test_mcp_manifest_golden.py -q`, then
   `git diff --stat` the golden dir and inspect: the only change per file must be the added `wiki_spec_consequences` entry.
6. Write tests; run validation.

### `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/spec_audit.py` (CREATE)
```python
"""One wiring for every decision-audit surface: MCP, CLI and gate script (FEAT-784 M9)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from parrot.knowledge.wiki.decisions.models import ADR_SOURCE_UNAVAILABLE, DecisionError

TAXONOMY_REL = "sdd/taxonomy/subsystems.yaml"
APPROVALS_REL = "sdd/decisions/approvals.jsonl"


def taxonomy_path(root: Path) -> Path:
    return root / TAXONOMY_REL


def approvals_path(root: Path) -> Path:
    return root / APPROVALS_REL


def is_configured(root: Path) -> bool:
    """Configured when the taxonomy OR the approvals manifest exists (spec §2 portability). No store access."""
    return taxonomy_path(root).is_file() or approvals_path(root).is_file()


def open_consequence_service(root: Path, *, store: Any = None, config: Any = None, base_branch: str = "dev") -> Any:
    """Build a ``ConsequenceService`` with a non-repairing structural plane (spec S6).

    Raises:
        DecisionError: ``ADR_SOURCE_UNAVAILABLE`` when the wiki plane was never built.
    """
    import click

    from parrot.knowledge.wiki.decisions.approvals import GitCommitApprovalAdapter
    from parrot.knowledge.wiki.decisions.consequences import ConsequenceService
    from parrot.knowledge.wiki.structural.service import StructuralService

    if store is None or config is None:
        from parrot.knowledge.wiki.cli import _require_built, _resolve_project

        root, config = _resolve_project(str(root))
        try:
            store = _require_built(root, config)
        except click.ClickException as exc:
            raise DecisionError(ADR_SOURCE_UNAVAILABLE, exc.format_message()) from exc
    structural = StructuralService(store, root, config, read_repair=False)
    return ConsequenceService(
        store, root, config.decisions, structural,
        taxonomy_path=taxonomy_path(root), approvals_path=approvals_path(root),
        adapter=GitCommitApprovalAdapter(root, base_branch),
    )
```
**Why**: keeping `is_configured` import-free is what lets the gate script return `skipped` in a repo that has no
wiki at all. `audit_configured` (TASK-5005) and `is_configured` must agree — both test the same two paths.

### `operations.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'async def op_decision_generate(store: Any, params: DecisionGenerateInput, \*\*context: Any) -> OperationResult:' packages/ai-parrot/src/parrot/knowledge/wiki/decisions/operations.py)
# AFTER — append below the end of `op_decision_generate` (verified: operations.py:103-111, end of file)


class SpecConsequencesInput(BaseModel):
    """Arguments for ``wiki_spec_consequences``."""

    spec_path: str = Field(..., description="Repository-relative path of the spec, e.g. sdd/specs/<slug>.spec.md")
    mode: Literal["check", "governing"] = Field(default="check", description="check: evaluate (read-only); governing: the governing-decisions dossier")
    budget_tokens: int = Field(default=DEFAULT_BUDGET_TOKENS, ge=256, description="Estimated output budget for the dossier text")


async def op_spec_consequences(store: Any, params: SpecConsequencesInput, **context: Any) -> OperationResult:
    """Evaluate a spec's declared decisions (read-only); never writes the spec."""
    from parrot.knowledge.wiki.decisions.spec_audit import open_consequence_service

    root = context.get("root")
    if root is None:
        return OperationResult(text="wiki_spec_consequences requires a local project root", is_error=True)
    try:
        service = open_consequence_service(Path(root), store=context.get("store"), config=context.get("config"))
        # FILL IN: mode "check" ⇒ result = await check_spec(service, Path(params.spec_path)) (TASK-5006);
        #   text = render_consequences(result.report) + f"\ncheck: {result.status}"; data = {**report.model_dump(mode="json"), "check": result.status}.
        #   mode "governing" ⇒ dossier = await service.governing(...); report = await service.evaluate(...);
        #   text = render_governing(dossier, budget_tokens=params.budget_tokens, report=report); data = dossier.model_dump(mode="json").
        #   Path must stay confined under root — reject absolute or `..` spec_path with is_error=True.
        raise NotImplementedError
    except DecisionError as exc:
        return _error_result(exc)
```
**Why**: `data` carries the full report so MCP JSON == CLI `--json` == script `--json` (S11). Add `Literal` to the
`typing` import and `from pathlib import Path` at the top of `operations.py` (stdlib only).

### `transport.py` (MODIFY — four edits)
```python
# (a) occurrences: 1 (verified: grep -c '    op_decision_why,' packages/ai-parrot/src/parrot/knowledge/wiki/transport.py) — line 19
# AFTER `    op_decision_why,` add, and add `    SpecConsequencesInput,` alphabetically in the same import block:
    op_spec_consequences,
# (b) occurrences: 1 (verified: grep -c '    "wiki_decision_generate": _Spec(' ...transport.py) — line 202
# BEFORE `    "wiki_decision_generate": _Spec(` insert:
    "wiki_spec_consequences": _Spec(
        "decisions",
        SpecConsequencesInput,
        "Evaluate a spec's declared decisions against the accepted decision plane, or return the governing-decisions dossier for its subsystems. Read-only; blocking only on an explicit unresolved contradiction.",
    ),
# (c) occurrences: 1 (verified: grep -c '    elif name == "wiki_decision_generate":' ...transport.py) — line 367
# BEFORE `    elif name == "wiki_decision_generate":` insert:
    elif name == "wiki_spec_consequences":

        async def invoke(params: BaseModel) -> OperationResult:
            return await op_spec_consequences(None, params, root=ctx.root, store=ctx.store, config=ctx.config)

# (d) occurrences: 1 (verified: grep -c '    names += \["wiki_decisions_for_symbol", "wiki_decision_why"\]' ...transport.py) — line 472
# AFTER that line insert:
    if ctx.root is not None:
        names.append("wiki_spec_consequences")
```
**Why**: the description string must be byte-identical to the framework tool's `description` (golden parity
assert in `test_mcp_manifest_golden.py:_manifest_for_transport`). `ctx.store` (local, non-federated) — decisions
target the local plane only.

### `parrot_tools/wiki/decisions.py` (MODIFY — two edits)
```python
# (a) occurrences: 1 (verified: grep -c 'def create_decision_tools(' packages/ai-parrot-tools/src/parrot_tools/wiki/decisions.py) — line 164
# BEFORE `def create_decision_tools(` insert:
class WikiSpecConsequencesTool(AbstractTool):
    """Evaluate a spec's declared decisions, or return its governing-decisions dossier."""

    name = "wiki_spec_consequences"
    description = (
        "Evaluate a spec's declared decisions against the accepted decision plane, or return the governing-decisions "
        "dossier for its subsystems. Read-only; blocking only on an explicit unresolved contradiction."
    )
    args_schema = SpecConsequencesInput

    def __init__(self, store: BaseWikiStore, root: Path, config: WikiProjectConfig):
        super().__init__(name=self.name, description=self.description)
        self._store, self._root, self._config = store, root, config

    async def _execute(self, spec_path: str, mode: str = "check", budget_tokens: int = DEFAULT_BUDGET_TOKENS) -> ToolResult:
        result = await op_spec_consequences(
            None, SpecConsequencesInput(spec_path=spec_path, mode=mode, budget_tokens=budget_tokens),
            root=self._root, store=self._store, config=self._config,
        )
        if result.is_error:
            return ToolResult(success=False, status="error", result=None, error=result.text)
        return ToolResult(result=result.text, metadata=result.data)


# (b) occurrences: 1 (verified: grep -c '        tools.append(WikiDecisionGenerateTool(service_factory))' ...) — line 184
# AFTER it (still before `    return tools`, line 185) insert:
    if root is not None:
        tools.append(WikiSpecConsequencesTool(store, root, config))
# Also add `SpecConsequencesInput, op_spec_consequences` to the `from parrot.knowledge.wiki.decisions.operations import (...)` block (lines 11-18).
```
**Why**: verify the description string equals transport (b) character-for-character — the parenthesised string
concatenation must produce the same text.

### `__init__.py` and `_tool_surface.py` (MODIFY)
```python
# decisions/__init__.py — occurrences 1 each (verified: grep -c on each anchor):
#  after `    from parrot.knowledge.wiki.decisions.service import DecisionService` (line ~42):
    from parrot.knowledge.wiki.decisions.consequences import ConsequenceReport, ConsequenceService
    from parrot.knowledge.wiki.decisions.publish import BatchPublisher
#  in __all__, keep sorted: add "BatchPublisher", "ConsequenceReport", "ConsequenceService"
#  after `    "DecisionService": "parrot.knowledge.wiki.decisions.service",` (line ~82):
    "ConsequenceService": "parrot.knowledge.wiki.decisions.consequences",
    "ConsequenceReport": "parrot.knowledge.wiki.decisions.consequences",
    "BatchPublisher": "parrot.knowledge.wiki.decisions.publish",
# _tool_surface.py — occurrences: 1 (verified: grep -c '        "wiki_decisions_for_symbol",' .../_tool_surface.py) — line 21
#  AFTER `        "wiki_decisions_for_symbol",` insert:
        "wiki_spec_consequences",
```
**Why**: `LOCAL_NO_LEDGER` is `sorted(...)`, so insertion position does not matter for equality, but keep it
next to its siblings for review. Lazy map entries keep `decisions.models` importable standalone (`__init__.py:13-22`).

### FILL IN checklist
- [ ] `operations.op_spec_consequences` — check/governing branches + path confinement; bounded by S11, AC1
- [ ] Golden regeneration reviewed: only `wiki_spec_consequences` added in each manifest; bounded by `test_mcp_manifest_golden.py`

---

## Acceptance Criteria

- [ ] `_tool_surface.LOCAL_NO_LEDGER` lists `wiki_spec_consequences` (spec §4 `test_mcp_tool_registered`, AC16).
- [ ] MCP framework and SDK manifests match the regenerated goldens; diff shows only the new tool.
- [ ] `op_spec_consequences(mode="check")` returns `data` equal to the report the evaluator produced; an unconfigured repo returns status `skipped`.
- [ ] Unbuilt wiki in a configured repo ⇒ error/`incomplete` path, never a crash.
- [ ] `import parrot.knowledge.wiki.transport` does not import `consequences` / `structural.service` eagerly.
- [ ] `ruff check` clean on all touched Python files.

---

## Validation Commands
- `pytest packages/ai-parrot/tests/knowledge/wiki/decisions/test_spec_consequences_op.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_mcp_manifest_golden.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_tool_surface_golden.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_mcp_server.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_transport_descriptors.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_plane_operations.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/decisions/test_tools.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/wiki/decisions/test_spec_consequences_op.py
from pathlib import Path
from parrot.knowledge.wiki.decisions.operations import SpecConsequencesInput, op_spec_consequences
from parrot.knowledge.wiki.decisions.spec_audit import is_configured

from .._tool_surface import LOCAL_NO_LEDGER

def test_mcp_tool_registered():
    assert "wiki_spec_consequences" in LOCAL_NO_LEDGER

def test_is_configured(tmp_path: Path):
    assert not is_configured(tmp_path)
    (tmp_path / "sdd/taxonomy").mkdir(parents=True)
    (tmp_path / "sdd/taxonomy/subsystems.yaml").write_text("subsystems: []\n")
    assert is_configured(tmp_path)

async def test_unconfigured_spec_is_skipped(tmp_path, adr_store, adr_config): ...   # FILL IN — WikiProjectConfig + adr_store passed as store/config
async def test_rejects_path_outside_root(tmp_path, adr_store): ...                  # FILL IN
async def test_operation_never_constructs_llm(tmp_path, adr_store, monkeypatch): ... # FILL IN — LLMFactory.create guard (AC1)
def test_transport_import_is_lazy(): ...                                              # FILL IN — subprocess `python -c "import parrot.knowledge.wiki.transport, sys; assert 'parrot.knowledge.wiki.decisions.consequences' not in sys.modules"`
```

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug sdd-decision-audit --feature-id FEAT-784`).
2. Read spec §3 Module 9, §4 (test_mcp_tool_registered, test_cli_mcp_json_equivalence), §7 "Exact-set MCP tests".
3. Confirm TASK-5006 and TASK-5007 (and transitively P02) are `done`.
4. Verify the Codebase Contract (re-run every `grep -c`); update first on drift.
5. This task is EXCLUSIVE — no other task may run concurrently (shared golden files).
6. Implement; regenerate goldens with `UPDATE_GOLDEN=1`; review the diff before committing.
7. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src`.
8. Commit only the listed files; close with `scripts/sdd/close_task.sh TASK-5008 sdd-decision-audit verified`.

---

## Completion Note

*(Agent fills this in when done)*
