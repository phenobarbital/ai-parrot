# TASK-3663: Export Studio tooling models to TypeScript (pnpm generate)

**Feature**: FEAT-593 — Tool Configuration for Agent Studio
**Spec**: `sdd/specs/tool-configuration-agentstudio.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3645, TASK-3646, TASK-3659, TASK-3661
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 11; AC16. The SPA must import generated types (never hand-edit
`types/generated/`). `test_ts_codegen.py` enforces that the committed `ui/schemas/` snapshot
matches the models.

---

## Scope

- Add to the model map (next to `"AgentToolCall": AgentToolCall,`): `ToolkitSpec`,
  `AgentMCPServerSpec`, `ConfigOption`, `ToolkitSchemaEnvelope`, `ToolkitConfigPutRequest`,
  `AgentToolkitsResponse`, `ToolkitPersistResponse`, `AgentMcpServersPutRequest`,
  `AgentMcpServersResponse`, `ToolkitOptionsResponse`, `UserToolkitOverride`.
- Run `python scripts/generate_ts_types.py` then `pnpm generate` in `packages/ai-parrot-server/ui/`;
  commit both output trees.

**NOT in scope**: any UI code.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `scripts/generate_ts_types.py` | MODIFY | Add FEAT-593 models to the export map |
| `packages/ai-parrot-server/ui/schemas/ToolkitSpec.json` | CREATE | Generated JSON Schema |
| `packages/ai-parrot-server/ui/schemas/AgentMCPServerSpec.json` | CREATE | Generated JSON Schema |
| `packages/ai-parrot-server/ui/schemas/ConfigOption.json` | CREATE | Generated JSON Schema |
| `packages/ai-parrot-server/ui/schemas/ToolkitSchemaEnvelope.json` | CREATE | Generated JSON Schema |
| `packages/ai-parrot-server/ui/schemas/ToolkitConfigPutRequest.json` | CREATE | Generated JSON Schema |
| `packages/ai-parrot-server/ui/schemas/AgentToolkitsResponse.json` | CREATE | Generated JSON Schema |
| `packages/ai-parrot-server/ui/schemas/ToolkitPersistResponse.json` | CREATE | Generated JSON Schema |
| `packages/ai-parrot-server/ui/schemas/AgentMcpServersPutRequest.json` | CREATE | Generated JSON Schema |
| `packages/ai-parrot-server/ui/schemas/AgentMcpServersResponse.json` | CREATE | Generated JSON Schema |
| `packages/ai-parrot-server/ui/schemas/ToolkitOptionsResponse.json` | CREATE | Generated JSON Schema |
| `packages/ai-parrot-server/ui/schemas/UserToolkitOverride.json` | CREATE | Generated JSON Schema |
| `packages/ai-parrot-server/ui/src/lib/types/generated/ToolkitSpec.d.ts` | CREATE | Generated TS type (pnpm generate) |
| `packages/ai-parrot-server/ui/src/lib/types/generated/AgentMCPServerSpec.d.ts` | CREATE | Generated TS type (pnpm generate) |
| `packages/ai-parrot-server/ui/src/lib/types/generated/ConfigOption.d.ts` | CREATE | Generated TS type (pnpm generate) |
| `packages/ai-parrot-server/ui/src/lib/types/generated/ToolkitSchemaEnvelope.d.ts` | CREATE | Generated TS type (pnpm generate) |
| `packages/ai-parrot-server/ui/src/lib/types/generated/ToolkitConfigPutRequest.d.ts` | CREATE | Generated TS type (pnpm generate) |
| `packages/ai-parrot-server/ui/src/lib/types/generated/AgentToolkitsResponse.d.ts` | CREATE | Generated TS type (pnpm generate) |
| `packages/ai-parrot-server/ui/src/lib/types/generated/ToolkitPersistResponse.d.ts` | CREATE | Generated TS type (pnpm generate) |
| `packages/ai-parrot-server/ui/src/lib/types/generated/AgentMcpServersPutRequest.d.ts` | CREATE | Generated TS type (pnpm generate) |
| `packages/ai-parrot-server/ui/src/lib/types/generated/AgentMcpServersResponse.d.ts` | CREATE | Generated TS type (pnpm generate) |
| `packages/ai-parrot-server/ui/src/lib/types/generated/ToolkitOptionsResponse.d.ts` | CREATE | Generated TS type (pnpm generate) |
| `packages/ai-parrot-server/ui/src/lib/types/generated/UserToolkitOverride.d.ts` | CREATE | Generated TS type (pnpm generate) |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references (dev @ `ce602539c`, 2026-09-23). Use these exact imports,
> names and signatures. Anything not listed here must be verified with `grep`/`read` first.

### Verified Imports
```python
from parrot.tools.spec import AgentMCPServerSpec, ToolkitSpec  # TASK-3645
from parrot.tools.config_schema import ConfigOption, ToolkitSchemaEnvelope  # TASK-3646
from parrot.handlers.studio.models import (ToolkitConfigPutRequest, AgentToolkitsResponse, ToolkitPersistResponse,
    AgentMcpServersPutRequest, AgentMcpServersResponse, ToolkitOptionsResponse)  # TASK-3659
from parrot.handlers.toolkit_persistence import UserToolkitOverride  # TASK-3661
```

### Existing Signatures to Use
```python
# scripts/generate_ts_types.py
#   model map built inside a function (:60-86): imports from parrot.server.ui.models + status, returns {name: Model}
#   `        "AgentToolCall": AgentToolCall,` (:85) ← anchor (last entry)
def export_schemas(output_dir: Path = SCHEMAS_DIR) -> dict[str, Path]:  # :89
# packages/ai-parrot-server/ui/package.json — "generate" script (:15) runs json-schema-to-typescript over ui/schemas
# packages/ai-parrot-server/tests/test_ts_codegen.py — drift test test_schemas_in_sync_with_committed (:34)
```

### Does NOT Exist
- ~~hand-edited files in `ui/src/lib/types/generated/`~~ — forbidden; regenerate.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "scripts/generate_ts_types.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/ui/schemas/ToolkitSpec.json",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/ui/schemas/AgentMCPServerSpec.json",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/ui/schemas/ConfigOption.json",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/ui/schemas/ToolkitSchemaEnvelope.json",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/ui/schemas/ToolkitConfigPutRequest.json",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/ui/schemas/AgentToolkitsResponse.json",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/ui/schemas/ToolkitPersistResponse.json",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/ui/schemas/AgentMcpServersPutRequest.json",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/ui/schemas/AgentMcpServersResponse.json",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/ui/schemas/ToolkitOptionsResponse.json",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/ui/schemas/UserToolkitOverride.json",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/ui/src/lib/types/generated/ToolkitSpec.d.ts",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/ui/src/lib/types/generated/AgentMCPServerSpec.d.ts",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/ui/src/lib/types/generated/ConfigOption.d.ts",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/ui/src/lib/types/generated/ToolkitSchemaEnvelope.d.ts",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/ui/src/lib/types/generated/ToolkitConfigPutRequest.d.ts",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/ui/src/lib/types/generated/AgentToolkitsResponse.d.ts",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/ui/src/lib/types/generated/ToolkitPersistResponse.d.ts",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/ui/src/lib/types/generated/AgentMcpServersPutRequest.d.ts",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/ui/src/lib/types/generated/AgentMcpServersResponse.d.ts",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/ui/src/lib/types/generated/ToolkitOptionsResponse.d.ts",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/ui/src/lib/types/generated/UserToolkitOverride.d.ts",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

`ToolkitSchemaEnvelope` uses an alias (`schema`) — confirm the exported JSON Schema uses the alias (`by_alias`); adjust `export_schemas` only if every model needs it (it probably already uses `model_json_schema()` whose default is by-alias).

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block to its declared path nearly
> verbatim, then complete every `# FILL IN:` marker. Blocks derive from the spec's Interface
> Skeletons (§3) and the §6 Edit Sites table, re-verified at task time. Never change a
> signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Extend the map with local imports inside the same function — *why*: keeps import cost lazy like existing entries.
2. Regenerate schemas + TS; commit — *why*: AC16 + drift test.

### `scripts/generate_ts_types.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        "AgentToolCall": AgentToolCall,' scripts/generate_ts_types.py)
# (1) inside the same function, next to the other imports (:60-69) add the imports from the Codebase Contract.
# (2) AFTER `        "AgentToolCall": AgentToolCall,` (verified: generate_ts_types.py:85) insert:
        # FEAT-593 — Agent Studio tool configuration
        "ToolkitSpec": ToolkitSpec,
        "AgentMCPServerSpec": AgentMCPServerSpec,
        "ConfigOption": ConfigOption,
        "ToolkitSchemaEnvelope": ToolkitSchemaEnvelope,
        "ToolkitConfigPutRequest": ToolkitConfigPutRequest,
        "AgentToolkitsResponse": AgentToolkitsResponse,
        "ToolkitPersistResponse": ToolkitPersistResponse,
        "AgentMcpServersPutRequest": AgentMcpServersPutRequest,
        "AgentMcpServersResponse": AgentMcpServersResponse,
        "ToolkitOptionsResponse": ToolkitOptionsResponse,
        "UserToolkitOverride": UserToolkitOverride,
```
Then: `python scripts/generate_ts_types.py && (cd packages/ai-parrot-server/ui && pnpm generate)`.

### FILL IN checklist
- [ ] Run both generators and commit the regenerated trees; bounded by test_ts_codegen drift test

---

## Acceptance Criteria

- [ ] `ui/schemas/` contains the 11 new JSON files; `ui/src/lib/types/generated/` the matching `.ts` files (AC16).
- [ ] `test_ts_codegen.py` passes.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-server/tests/test_ts_codegen.py -q`

---

## Test Specification

```python
# existing: packages/ai-parrot-server/tests/test_ts_codegen.py — no new test file; the drift test covers it.
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context (§2 Overview, §3 module, §7 risks).
2. **Check dependencies** — verify every `Depends-on` task is in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — before writing ANY code, confirm every import and
   signature listed still exists (`grep`/`read`). If anything moved, update the contract first.
4. **Update status** in `sdd/tasks/index/tool-configuration-agentstudio.json` → `"in-progress"`.
5. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:`
   marker, and never change a signature or path the blueprint fixes.
6. **Verify** all acceptance criteria; run the Validation Commands (in a worktree prefix with
   `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src:packages/ai-parrot-tools/src`).
7. **Move this file** to `sdd/tasks/completed/` and set the index entry to `"done"`.
8. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
