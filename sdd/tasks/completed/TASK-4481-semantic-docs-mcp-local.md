# TASK-4481: Local MCP configuration and semantic-layer documentation (M11b)

**Feature**: FEAT-704 — Semantic Layer — governed metric queries for agents
**Spec**: `sdd/specs/semantic-layer.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-4710
**Assigned-to**: unassigned
**Spec revision**: 0.4 (task amended 2026-10-26: operator config files dropped)

## Context

Spec rev 0.4, §3 M11; replaces the prior task text for this same reserved identity. The unmerged branch is a salvage reference only; no completion state is inherited.

## Amendment (2026-10-26)

`.parrot/mcp-toolkits.yaml` and `.mcp.json` are both git-ignored, operator-local files (`.gitignore:418` `.parrot/`, `.gitignore:399` `.mcp.json`) and do not exist in a worktree, so they cannot be MODIFY targets (engine: `complexity_contract_invalid`). By user decision they are **removed from this task**. Instead, `docs/tools/semantic-layer.md` carries the exact copyable `semantic-layer:` YAML section and `parrot-semantic-layer` MCP JSON entry (blocks below), and `test_mcp_local.py` writes those same blocks into `tmp_path` and loads/starts them from there. Scope items that say "add ... at verified anchors" now mean "document copyable blocks"; operators paste them into their own local configs.

## Scope

- Document clean-room model schema, aggregate/join examples, all tool signatures, policy schema, default governance, exact provenance, audit-required resolution and Postgres sink.
- Add semantic-layer YAML class LocalSemanticLayerToolkit with required host guard_factory/agent_id/static_subject; add matching MCP entry at verified anchors. Preserve all unrelated operator settings/secrets; never commit private values.
- Configs are operator-local if ignored: document identical copyable examples and test temporary files; do not force-add private config wholesale. The future implementation may edit local config only with safe placeholder values.
- Test actual server factory with governed fixture and explicit evaluator, not merely config parsing/listing. Document fail-closed startup, absent sink default, conformance requirements and no bare-manager hand-off.

**NOT in scope**: changes outside the target table; provider SDK calls; a third-party semantic engine; symmetric aggregates; reviving the removed M12 core RLS work. Blueprint gaps are planning instructions only and must not survive in implementation files.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/tools/semantic-layer.md` | CREATE | Scoped deliverable per blueprint |
| `packages/ai-parrot-semantic/tests/test_mcp_local.py` | CREATE | Focused regression evidence |

## Codebase Contract (Anti-Hallucination)

Verified against main-checkout `dev` at `c431642e2` on 2026-10-25. Existing source definitions below were re-read. Satellite imports are **planned contracts**, not claims that those files already exist on dev; their producer tasks must land first.

### Verified Imports

```python
from pathlib import Path
import pytest
```

Standard-library imports are built in; pydantic v2, sqlglot, PyYAML/jsonschema and pytest are governed by existing metadata and M1's explicit dependency/extra declarations. Reverify optional backend imports in the implementation environment. Relative satellite imports below resolve within the target package and are bounded by the listed dependency contracts.

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/mcp/toolkit_config.py:20
class ToolkitSection(BaseModel):
```

```python
# packages/ai-parrot/src/parrot/mcp/toolkit_config.py:90
def load_toolkits_config(root: Path, config_path: Path | None=None) -> MCPToolkitsConfig:
```

```python
# packages/ai-parrot/src/parrot/mcp/toolkit_server.py:137
def create_toolkit_mcp_server(name: str, root: Path=Path.cwd(), **overrides: Any) -> StdioMCPServer:
```

### Dependency Contracts and Parallelism Evidence

- TASK-4710: consumes packages/ai-parrot-semantic/src/parrot/semantic/bootstrap.py (MCP-local identity and configured PBAC bootstrap (M10c))

- Consumer-specific evidence: LocalSemanticLayerToolkit constructor and explicit fixture guard factory for actual MCP startup

### Does NOT Exist

- `parrot.semantic` on dev — the package and symbols are created by this graph, never imported from the salvage branch environment.
- A semantic engine selector, sidemantic adapter or sidemantic parity oracle — native SQL generation is the only path.
- `PermissionContext.session_id` or `.agent_id` — the satellite identity contract carries trusted scope; request_id is not a session id.
- Automatic semantic authorization in `DatasetManager.add_dataframe()` — retained snapshots require the guarded host-sink contract.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "docs/tools/semantic-layer.md",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-semantic/tests/test_mcp_local.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_config.py#ToolkitSection",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_config.py#load_toolkits_config",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_server.py#create_toolkit_mcp_server"
  ]
}
```

## Implementation Notes

- Keep the scope and signatures fixed by spec rev 0.4. Complete the bounded blueprint gaps, not a broad refactor. Preserve the clean-room rule: do not open sidemantic source/API glue.
- Use async I/O, Pydantic v2, strict types and Google-style docstrings. CPU SQL passes run off the event loop. Use logging, not print; black/ruff are the format/lint gates.
- Run in the feature worktree with the existing venv activated; never repair the shared environment. Write test logs to `artifacts/logs/`.
- The full-file snippets below are starting points. Recheck dependency-created MODIFY anchors after their tasks land; they cannot be falsely reported verified on dev today.

## Implementation Blueprint

### Steps (in order)

1. Verify existing anchors and dependency contracts — because stale signatures invalidate a mechanical implementation.
2. Implement the listed targets in their blueprint order — because each target has one explicit owner and the graph orders shared writers.
3. Complete all scope-specific validation branches and regression scenarios — because success-path-only tests cannot establish the required fail-closed behavior.
4. Run this task's validation commands and focused lint — because only evidence from its declared files closes this task.

### `docs/tools/semantic-layer.md` (CREATE)

```markdown
# Governed semantic layer

## Installation and clean-room format
<!-- FILL IN: native-only compiler, dependencies/extras, graph examples with
aggregate inputs/composite keys, supported grains and fan-out rejection. -->
## Authorization and identity
<!-- FILL IN: governed defaults, trusted host binding, local-only operator
identity, configured guard factory, no caller-supplied credentials. -->
## Tools and audit
<!-- FILL IN: tool contracts, saved queries, raw SQL opt-in, limits, signed
ledger, audit_required and Postgres storage wiring. -->
## Guarded dataset hand-off
<!-- FILL IN: M9H protocol, conformance tests and every-read authorization;
plain DatasetManager factory rejected, absent by default, expiry/revocation. -->
## MCP-local configuration
<!-- FILL IN: exact local subclass + guard_factory YAML and MCP JSON blocks;
temporary-config startup command, explicit allow/deny validation. -->
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### Copyable `mcp-toolkits.yaml` section (documented in `docs/tools/semantic-layer.md`, NOT a file target)

```yaml
# BEFORE verified database-query sibling under toolkits: (count below).
  semantic-layer:
    class: parrot.semantic.bootstrap.LocalSemanticLayerToolkit
    kwargs:
      models_dir: /path/to/models
      dialect: duckdb
      agent_id: local-semantic
      static_subject: {user_id: operator, tenant_id: local, roles: [admin]}
      guard_factory: myapp.semantic_auth.build_guard
      guard_factory_kwargs: {policy_dir: /path/to/policies}
    env: {}
# Host must supply the factory; missing configuration fails closed.
# Never force-add unrelated private config; document/test the same block.
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### Copyable `.mcp.json` entry (documented in `docs/tools/semantic-layer.md`, NOT a file target)

```json
{
  "parrot-semantic-layer": {
    "command": "parrot",
    "args": ["mcp-local", "semantic-layer"]
  }
}
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### `packages/ai-parrot-semantic/tests/test_mcp_local.py` (CREATE)

```python
"""Regression contract: Local MCP configuration and semantic-layer documentation (M11b)."""
from pathlib import Path
import pytest


def test_yaml_and_json_example_contract(tmp_path: Path) -> None:
    """Verify yaml and json example contract."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...


def test_actual_mcp_factory_governed_startup(tmp_path: Path) -> None:
    """Verify actual mcp factory governed startup."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...


def test_explicit_allow_and_deny_calls(tmp_path: Path) -> None:
    """Verify explicit allow and deny calls."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### FILL IN checklist

- [ ] `docs/tools/semantic-layer.md` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.
- [ ] `packages/ai-parrot-semantic/tests/test_mcp_local.py` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.

## Acceptance Criteria

- [ ] Document clean-room model schema, aggregate/join examples, all tool signatures, policy schema, default governance, exact provenance, audit-required resolution and Postgres sink.
- [ ] Document a copyable semantic-layer YAML section (class LocalSemanticLayerToolkit with required host guard_factory/agent_id/static_subject) and the matching `parrot-semantic-layer` MCP JSON entry in `docs/tools/semantic-layer.md`, with placeholder values only. The git-ignored operator files `.parrot/mcp-toolkits.yaml` and `.mcp.json` are NOT modified (amendment 2026-10-26).
- [ ] Configs are operator-local if ignored: document identical copyable examples and test temporary files; do not force-add private config wholesale. The future implementation may edit local config only with safe placeholder values.
- [ ] Test actual server factory with governed fixture and explicit evaluator, not merely config parsing/listing. Document fail-closed startup, absent sink default, conformance requirements and no bare-manager hand-off.
- [ ] The task-specific regression cases below pass; focused black/ruff checks pass on changed code. No unrelated target is modified.

## Validation Commands

- `pytest packages/ai-parrot-semantic/tests/test_mcp_local.py -q`

## Test Specification

- `test_yaml_and_json_example_contract`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.
- `test_actual_mcp_factory_governed_startup`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.
- `test_explicit_allow_and_deny_calls`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.

## Agent Instructions

Use `$sdd-start TASK-4481` in the feature worktree; it provisions isolation. Read spec/dependencies, reverify contracts, implement only declared targets, run validation and commit code. Use `scripts.sdd.finalize_task` with real TaskCompletionEvidence and the exact implementation HEAD; do not use close_task.sh or manually move/stamp completion artifacts.

## Completion Note


- Task: TASK-4481
- Feature: semantic-layer
- Implementation SHA: eae881f3691d8d0a82ddae8a395469bcb7d5916b
- Closed at (UTC): 2026-10-26T22:44:10+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: gpt-5.6-terra · Backend: codex · Model: gpt-5.6-terra · Attempts: 1 · Duration: 89.5s · Tokens: n/a |
