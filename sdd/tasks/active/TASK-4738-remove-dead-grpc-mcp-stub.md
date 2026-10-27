# TASK-4738: M0b — delete the dead gRPC MCP stub and its reserved config fields

**Feature**: FEAT-746 — Squawk: typed binary inter-agent protocol
**Spec**: `sdd/specs/inter-agent-protocol.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 0 (U5): `packages/ai-parrot-server/src/parrot/mcp/transports/grpc_session.py` is an abandoned client-only gRPC stub (protobuf import commented out) next to an unused `mcp.proto`, and `MCPServerConfig` carries five reserved `grpc_*` fields "for future gRPC implementation". Squawk's native transport is Cap'n Proto, so this drift is removed in the same feature (AC17). Nothing imports the stub (verified: no hits in `packages/*/src`, `packages/*/tests`, `docs`).

---

## Scope

- Delete `grpc_session.py` and `mcp.proto` under `packages/ai-parrot-server/src/parrot/mcp/transports/`.
- Remove `grpc_host`, `grpc_port`, `grpc_use_tls`, `grpc_cert_path`, `grpc_use_protobuf` and their comment from `MCPServerConfig` (`mcp/config.py:202-207`).
- Add `packages/ai-parrot-server/tests/mcp/test_no_grpc_stub.py` asserting the module is gone and the dataclass has no `grpc_*` field.
- Grep docs for `grpc_session`/`grpc_use_protobuf` and remove stale mentions if any (none found at spec time).

**NOT in scope**: OTLP gRPC exporters (`observability/exporters.py` — unrelated), the `grpc = ["navigator-eventbus[grpc]"]` extra in core pyproject (stays).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/mcp/transports/grpc_session.py` | DELETE | dead stub |
| `packages/ai-parrot-server/src/parrot/mcp/transports/mcp.proto` | DELETE | unused proto |
| `packages/ai-parrot-server/src/parrot/mcp/config.py` | MODIFY | drop `grpc_*` fields |
| `packages/ai-parrot-server/tests/mcp/test_no_grpc_stub.py` | CREATE | regression |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.mcp.config import MCPServerConfig   # verified: packages/ai-parrot-server/src/parrot/mcp/config.py:131 (@dataclass at :130)
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/mcp/config.py
@dataclass                                   # line 130
class MCPServerConfig:                       # line 131
    transport: str = "stdio"                 # line 142 — documented values: stdio/http/streamable-http/sse/unix/quic (no "grpc")
    # For Future gRPC implementation (expected)   # line 202
    grpc_host: Optional[str] = None          # line 203
    grpc_port: Optional[int] = None          # line 204
    grpc_use_tls: bool = True                # line 205
    grpc_cert_path: Optional[str] = None     # line 206
    grpc_use_protobuf: bool = False          # line 207
    # QUIC transport settings                # line 209 (keep)
```

### Does NOT Exist
- ~~importers of `grpc_session` / `GrpcMCPSession` / `GrpcMCPConfig`~~ — none (verified repo-wide at spec time; re-grep before deleting).
- ~~`"grpc"` in `MCPServerConfig.transport`'s documented values or in `transports/__init__.py`~~ — none.
- ~~`extra="forbid"` on `MCPServerConfig`~~ — it is a plain dataclass; a YAML with stale `grpc_*` keys fails only if the loader passes unknown kwargs (document in the changelog line of the Completion Note).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-server/src/parrot/mcp/config.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/tests/mcp/test_no_grpc_stub.py", "action": "CREATE"}
  ],
  "contract_symbols": ["sym:packages/ai-parrot-server/src/parrot/mcp/config.py#MCPServerConfig"]
}
```
(DELETE targets are not expressible in the schema; the deletions are listed in the files table above.)

---

## Implementation Notes

### Key Constraints
- Re-run `grep -rn "grpc_session\|GrpcMCPSession\|grpc_use_protobuf\|grpc_host" packages docs --include=*.py --include=*.md --include=*.yaml` before deleting; stop and report if a new importer appeared.
- Hard cut is accepted project policy (no deprecation shims).

### References in Codebase
- `packages/ai-parrot-server/tests/mcp/test_agent_mount_config.py` — config test idiom in the same package.

---

## Implementation Blueprint

### Steps (in order)
1. `git rm` the two files — *why*: nothing imports them.
2. Remove lines 202-207 of `config.py` — *why*: reserved fields for a transport that will never exist here.
3. Add the regression test — *why*: AC17 needs a permanent check.

### `packages/ai-parrot-server/src/parrot/mcp/config.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    grpc_host: Optional\[str\] = None' packages/ai-parrot-server/src/parrot/mcp/config.py)
# REMOVE — the block starting at the comment `# For Future gRPC implementation (expected)` (config.py:202) through
# `    grpc_use_protobuf: bool = False  # Use native protobuf vs JSON-RPC wrapper` (config.py:207), plus the blank line after it.
# Keep `# QUIC transport settings` (config.py:209) and everything below unchanged.
```
**Why**: the five fields are the only remaining trace of the stub; `transport` never accepted `"grpc"`.

### `packages/ai-parrot-server/tests/mcp/test_no_grpc_stub.py` (CREATE)
```python
"""FEAT-746 M0b — the dead gRPC MCP stub and its config fields are gone (AC17)."""
from __future__ import annotations

import dataclasses
import importlib.util
import pathlib

from parrot.mcp.config import MCPServerConfig

TRANSPORTS = pathlib.Path(__file__).resolve().parents[2] / "src" / "parrot" / "mcp" / "transports"


def test_stub_files_removed():
    assert not (TRANSPORTS / "grpc_session.py").exists()
    assert not (TRANSPORTS / "mcp.proto").exists()
    assert importlib.util.find_spec("parrot.mcp.transports.grpc_session") is None


def test_config_has_no_grpc_fields():
    names = {f.name for f in dataclasses.fields(MCPServerConfig)}
    assert not {n for n in names if n.startswith("grpc_")}
```

### FILL IN checklist
- [ ] none — the task is fully mechanical; re-grep for importers is the only judgement

---

## Acceptance Criteria

- [ ] Both files deleted; `pytest packages/ai-parrot-server/tests/mcp/test_no_grpc_stub.py -q` passes
- [ ] `pytest packages/ai-parrot-server/tests/mcp/test_agent_mount_config.py -q` still passes
- [ ] `ruff check packages/ai-parrot-server/src/parrot/mcp/config.py` clean

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/mcp/test_no_grpc_stub.py -q`
- `pytest packages/ai-parrot-server/tests/mcp/test_agent_mount_config.py -q`

---

## Test Specification

See blueprint test file.

---

## Agent Instructions

1. **Work in the feature worktree** (`python -m scripts.sdd.ensure_worktree --slug inter-agent-protocol --feature-id FEAT-746`)
2. **Read the spec** §3 M0, §6 "Does NOT Exist" (stub importers)
3. **Check dependencies** — none
4. **Verify the Codebase Contract** — re-grep importers
5. **Update status** → `"in-progress"`, commit only the index
6. **Implement**
7. **Verify** — Validation Commands (`PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src` inside a worktree)
8. **Commit** — only the listed files
9. **Close** with `scripts/sdd/close_task.sh TASK-4738 inter-agent-protocol verified`
10. **Completion Note**

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
