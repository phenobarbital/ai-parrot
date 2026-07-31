---
type: Wiki Overview
title: 'TASK-1669: Core tool-loop credential seam + ContextVar injection'
id: doc:sdd-tasks-completed-task-1669-tool-loop-seam-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec §3 Module 3 — the spine. Inserts the single, surface-agnostic credential-resolution
relates_to:
- concept: mod:parrot.auth.broker
  rel: mentions
- concept: mod:parrot.auth.credentials
  rel: mentions
---

# TASK-1669: Core tool-loop credential seam + ContextVar injection

**Feature**: FEAT-264 — Unified Credential Broker
**Spec**: `sdd/specs/unified-credential-broker.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1667
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 — the spine. Inserts the single, surface-agnostic credential-resolution
seam into the core tool-execution path so chat, A2A, and CLI all gate uniformly. This is
what fixes the uncabled chat path.

---

## Scope

- Formalize `credential_provider: Optional[str] = None` on `AbstractTool` (subclasses
  already set it: `WorkIQTool`, `stub_credentialed_tool`).
- In `AbstractTool.execute()`, between arg validation (:563) and the `_execute()` call
  (:589): if `credential_provider` is set and a broker is available, call
  `broker.resolve(provider, channel, user_id, **ctx)`. On `ResolvedCredential`, set a
  per-call ContextVar and run `_execute()`; on `NeedsAuth`, raise the canonical
  `CredentialRequired(provider, auth_url, auth_kind)`.
- Add `current_credential()` helper that reads the ContextVar; reset it in `finally`.
- Propagate the broker + identity/channel context from `ToolManager.execute_tool` via
  `exec_kwargs` (mirror the existing `_permission_context`/`_resolver` pop pattern); carry
  the broker on `ToolManager.clone()`.
- **Tools without `credential_provider` must be byte-for-byte unchanged.**
- Unit tests: seam resolves+injects; no-op without provider; secret never in args; fail
  closed without identity.

**NOT in scope**: building the broker (1667), agent config (1670), surface rendering of
`CredentialRequired` (1672–1674).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/abstract.py` | MODIFY | `credential_provider` attr, seam, ContextVar, `current_credential()` |
| `packages/ai-parrot/src/parrot/tools/manager.py` | MODIFY | broker hold + `exec_kwargs` propagation + `clone()` carry |
| `packages/ai-parrot/tests/unit/test_tool_credential_seam.py` | CREATE | seam tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.auth.broker import CredentialBroker            # created in TASK-1667
from parrot.auth.credentials import CredentialRequired, ResolvedCredential, NeedsAuth  # TASK-1667
```

### Existing Signatures to Use
```python
# parrot/tools/abstract.py
class AbstractToolArgsSchema(BaseModel):
    _context_fields: ClassVar[frozenset[str]] = frozenset()   # :50  injected runtime fields
class AbstractTool:
    args_schema: Type[BaseModel] = AbstractToolArgsSchema      # :115
    @abstractmethod
    async def _execute(self, **kwargs) -> Any                  # :256
    async def execute(self, *args, **kwargs) -> ToolResult:    # :490
        # :506 pctx = kwargs.pop('_permission_context', None)
        # :507 resolver = kwargs.pop('_resolver', None)        # PERMISSION resolver (NOT credential)
        # :536 self._current_pctx = pctx
        # :563 arg validation  ── INSERT CREDENTIAL SEAM HERE ──  :589 raw_result = await self._execute(*args, **resolved_kwargs)
        # :622-651 OutputScrubber.scrub(...)                    # sole egress redaction

# parrot/tools/manager.py
async def execute_tool(self, tool_name, parameters, permission_context=None) -> Any  # :1189
    # :1277 exec_kwargs = dict(parameters)
    # :1281 exec_kwargs['_resolver'] = self._resolver          # AbstractPermissionResolver
    # :1283 result = await tool.execute(**exec_kwargs)
def clone(self, *, include_search_tool=False) -> "ToolManager"  # :1490 (:1522 copies resolver)
```

### Does NOT Exist
- ~~`credential_provider` on the `AbstractTool` BASE~~ — only subclasses declare it; formalize on the base (default `None`).
- ~~any credential-resolution hook in `execute()`/`execute_tool` today~~ — only `_permission_context` + `_resolver` (permission) flow in.
- ~~`current_credential()`~~ — create it in this task.

---

## Implementation Notes
- Inject the credential the same way runtime context already flows: pop broker/identity
  from `kwargs` in `execute()` (do NOT add them to the LLM-visible `args_schema`).
- Mirror `self._current_pctx` for the ContextVar lifecycle (set before `_execute`, reset
  in `finally`).
- Channel + canonical `user_id` come from the caller (surface) via `exec_kwargs`; the seam
  must fail closed when `credential_provider` is set but no identity is present.

## Acceptance Criteria
- [ ] A tool declaring `credential_provider` receives its credential via `current_credential()`.
- [ ] A tool without `credential_provider` runs unchanged (regression test).
- [ ] Secret never appears in tool args/schema; egress still scrubbed by `OutputScrubber`.
- [ ] Missing identity + gated tool → fail closed (no service identity).
- [ ] `pytest packages/ai-parrot/tests/unit/test_tool_credential_seam.py -v` passes; `ruff` clean.

## Agent Instructions
Standard SDD flow. Verify `abstract.py` line anchors before editing (code may have shifted).

## Completion Note
*(Agent fills this in when done)*
