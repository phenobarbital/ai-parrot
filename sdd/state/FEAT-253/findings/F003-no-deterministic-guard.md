---
id: F003
slug: no-deterministic-guard
query: "DeterministicGuard / mandate pattern search"
type: grep
---

## Finding: No DeterministicGuard exists — use confirming_tools instead

### Existing guard patterns:
1. **GrantGuard (FEAT-211)** — bounded approval windows via `ToolManager.set_grant_guard(guard)`
2. **ConfirmationGuard (FEAT-235)** — per-call HITL review via `confirming_tools` frozenset
3. **QueryValidator** — DDL/DML guard for database toolkit

### How confirming_tools works:
```python
class SomeToolkit(AbstractToolkit):
    confirming_tools: frozenset[str] = frozenset({"dangerous_method"})
```
This auto-sets `routing_meta["requires_confirmation"] = True` on the tool.

### Correction to SPEC:
- SPEC proposes `DeterministicGuard` with `MutationMandate` — this does NOT exist in codebase
- Replace with `confirming_tools` for HITL gating on write mutations
- Cost-cap and idempotency logic should be custom validation in `_pre_execute()` or method-level
