# TASK-4724: Squawk bridge — lazy satellite probe, codec/envelope selection, degraded mount, authority (M11a)

**Feature**: FEAT-747 — Roost — local inter-agent sub-protocol over Squawk
**Spec**: `sdd/specs/local-inter-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4715, TASK-4722
**Assigned-to**: unassigned

---

## Context

Implements the bridge part of spec §3 **Module 11**. Resolved Q1: the Squawk envelope, codec and catalog tools
live **only** in the FEAT-746 satellite (`ai-parrot-squawk`, namespace `parrot.squawk`); this file is the ONLY Roost
file allowed to name it, and every satellite import happens inside a function body. Without the satellite Roost
degrades, never fails: `LocalEnvelope`, `JsonEnvelopeCodec`, and `mount_capabilities` → `[]` with one warning per
process. Resolved Q3: `resolve_authority` prefers a verified Biscuit token over the serialized `PermissionContext`.

---

## Scope

- Create `parrot/roost/squawk_bridge.py` per the spec M11 skeleton (`SQUAWK_MODULE`, `SquawkUnavailable`, `squawk_available`, `SquawkCodecAdapter`, `load_codec`, `new_envelope`, `mount_capabilities`, `resolve_authority`).
- Write `tests/roost/test_squawk_bridge.py` covering both modes (absent, and a stub module injected into `sys.modules` under `SQUAWK_MODULE`).

**NOT in scope**: implementing any Squawk symbol (FEAT-746); adding `parrot.squawk` to any pyproject

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/roost/squawk_bridge.py` | CREATE | The only satellite seam |
| `packages/ai-parrot/tests/roost/test_squawk_bridge.py` | CREATE | Both-mode tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against `dev` @ `6cbd94131` (2026-10-26). Use these exact imports and
> signatures. Do NOT invent any import, attribute or method not listed here — verify first.

### Verified Imports
```python
import importlib, importlib.util
from parrot.roost.codec import EnvelopeCodec, JsonEnvelopeCodec          # TASK-4722
from parrot.roost.messages import LocalEnvelope, RoostMessage           # TASK-4711
from parrot.roost.directory import CapabilityMatch                      # TASK-4715
from parrot.core.events.lifecycle import TraceContext                   # verified: core/events/lifecycle/__init__.py:18
```

### Existing Signatures to Use
```python
# Specified by FEAT-746 (sdd/specs/inter-agent-protocol.spec.md, approved rev 0.3) — NOT in code yet; import lazily only:
#   parrot.squawk.schema.messages.CallMessage(envelope_id, cap_id, contract_hash, args: bytes, out_hints, budget,
#       trace_id, correlation_id, idempotency_key, reply_to=None, caller=None)  + properties trace / budget_ms / token_budget
#   parrot.squawk.schema.codec   (M3 codec)      parrot.squawk.transport.bus.BusPayloadSerializer.to_payload/from_payload (M11)
#   parrot.squawk.client.toolkit.SquawkRemoteToolkit(*, remote, tool_manager, landing, registry=None, ...).catalog_mount(target) -> str
#   parrot.squawk.security.biscuit.BiscuitVerifier (M10)

# parrot/roost/messages.py (TASK-4711)
class AgentAddress(BaseModel): name: str; carrier: CarrierKind = IN_PROCESS; endpoint: Optional[str] = None
class RoostMessage(BaseModel):
    message_id; performative; protocol; conversation_id; in_reply_to; sender: AgentAddress; receivers: list[AgentAddress]
    capability_filter: Optional[str]; content: Any; content_type: Optional[str]; body: Optional[str]; envelope: Any
    failure: Optional[FailureInfo]; permission_context: Any; auth_token: Optional[str]; created_at: datetime
    def reply(self, performative, *, content=None, body=None, failure=None) -> RoostMessage
    def is_addressed_to(self, name: str) -> bool
    def trace_id(self) -> Optional[str]
```

### Does NOT Exist
- ~~`parrot.squawk` in the installed environment — the satellite does not exist yet; tests must stub it~~
- ~~importing `parrot.squawk` at module level anywhere in Roost — forbidden (AC-33)~~
- ~~a FEAT-746 `CapnpEnvelopeCodec` class name — FEAT-746 exposes `schema.codec` + `BusPayloadSerializer`; the adapter wraps those~~

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/roost/squawk_bridge.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/roost/test_squawk_bridge.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- `squawk_available()` uses `importlib.util.find_spec(SQUAWK_MODULE)` inside try/except (`ModuleNotFoundError`, `ValueError`) and caches with `functools.lru_cache(maxsize=1)`; tests call `squawk_available.cache_clear()`.
- Each satellite-touching function first checks `squawk_available()`; on an ImportError of a specific submodule it logs once and degrades exactly as if the satellite were absent.
- `mount_capabilities` warning: a module-level `_WARNED` flag; `logger.warning('Squawk satellite not installed — capability mount skipped (FEAT-747 Q1)')` once per process.
- `resolve_authority`: token present + verifier importable ⇒ build the context from the verified scope (FILL IN, keep it behind the satellite check); else `msg.permission_context`; neither ⇒ `None` (PBAC then fails closed in `execute_tool`).
- `SquawkCodecAdapter.content_type = 'application/x-squawk'`.
- Async-first; Pydantic v2 models; `self.logger` / module `logger`, never `print`; Google docstrings; type hints everywhere; 120-column lines.

### References in Codebase
- spec §3 M11 `squawk_bridge.py` skeleton
- FEAT-746 spec M3/M7/M10/M11 sections

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared path nearly
> verbatim, then complete every `# FILL IN:` marker. Never change a signature, class name or file
> path the blueprint fixes (they come from the spec's §3 Interface Skeletons).

### Steps (in order)
1. Write the module with all satellite imports inside functions.
2. Tests: absent ⇒ JSON codec/LocalEnvelope/[] + exactly one warning; stub module ⇒ adapter selected.

### `packages/ai-parrot/src/parrot/roost/squawk_bridge.py` (CREATE)
```python
"""The ONLY Roost module that names the Squawk satellite (FEAT-747 M11, resolved Q1).

Every satellite import is inside a function body; without the satellite Roost degrades, never fails.
"""
from __future__ import annotations

import functools
import importlib
import importlib.util
import logging
from typing import TYPE_CHECKING, Any, Final, Optional, Sequence

from parrot.core.events.lifecycle import TraceContext

from .codec import EnvelopeCodec, JsonEnvelopeCodec
from .directory import CapabilityMatch
from .messages import LocalEnvelope, RoostMessage

if TYPE_CHECKING:
    from parrot.tools.manager import ToolManager

logger = logging.getLogger(__name__)

SQUAWK_MODULE: Final[str] = "parrot.squawk"  # confirmed by the FEAT-746 spec (M0)
_WARNED = False


class SquawkUnavailable(RuntimeError):
    """A satellite feature was required but ``parrot.squawk`` is not installed."""


@functools.lru_cache(maxsize=1)
def squawk_available() -> bool:
    """True when the satellite namespace resolves; cached per process."""
    raise NotImplementedError  # FILL IN — Key Constraints bullet 1


class SquawkCodecAdapter:
    """EnvelopeCodec over parrot.squawk.schema.codec + parrot.squawk.transport.bus.BusPayloadSerializer."""

    content_type = "application/x-squawk"

    def __init__(self) -> None:
        raise NotImplementedError  # FILL IN — lazy imports; raise SquawkUnavailable when missing

    def encode(self, msg: RoostMessage) -> bytes:
        raise NotImplementedError  # FILL IN

    def decode(self, data: bytes) -> RoostMessage:
        raise NotImplementedError  # FILL IN


def load_codec() -> EnvelopeCodec:
    """SquawkCodecAdapter when available, else JsonEnvelopeCodec (Q2)."""
    if squawk_available():
        try:
            return SquawkCodecAdapter()
        except (ImportError, SquawkUnavailable):
            logger.warning("Squawk codec unavailable; falling back to JSON envelope codec")
    return JsonEnvelopeCodec()


def new_envelope(*, correlation_id: str, caller: str, trace: Optional[TraceContext] = None,
                 budget_ms: Optional[int] = None, token_budget: Optional[int] = None,
                 idempotency_key: Optional[str] = None) -> Any:
    """CallMessage when available (satisfies EnvelopeLike), else LocalEnvelope."""
    # FILL IN: satellite branch (CallMessage needs cap_id/contract_hash/args — use "" / b"" for Roost-only messages)
    return LocalEnvelope(correlation_id=correlation_id, caller=caller, trace=trace, budget_ms=budget_ms,
                         token_budget=token_budget, idempotency_key=idempotency_key)


async def mount_capabilities(tool_manager: "ToolManager", matches: Sequence[CapabilityMatch]) -> list[str]:
    """Satellite catalog_mount per match → tool names; [] after one warning without the satellite (Q1)."""
    raise NotImplementedError  # FILL IN — bullets 2-3


def resolve_authority(msg: RoostMessage) -> Any:
    """Q3: token-derived PermissionContext when verifiable, else msg.permission_context; None ⇒ fail-closed."""
    raise NotImplementedError  # FILL IN — bullet 4
```
**Why**: The function names are the spec contract used by TASK-4725 and TASK-4722; keep the degrade paths total — no function here may raise because the satellite is missing.

### FILL IN checklist
- [ ] `squawk_available`
- [ ] `SquawkCodecAdapter`
- [ ] `new_envelope` satellite branch
- [ ] `mount_capabilities`
- [ ] `resolve_authority`
- [ ] tests

---

## Acceptance Criteria

- [ ] Without the satellite: `load_codec()` is `JsonEnvelopeCodec`, `new_envelope` is `LocalEnvelope`, `mount_capabilities` returns `[]` and logs exactly one warning across two calls (AC-33)
- [ ] With a stub `parrot.squawk` in `sys.modules`: `squawk_available()` is True and the adapter path is taken
- [ ] `resolve_authority` returns `permission_context` when no token, `None` when neither (AC-35)
- [ ] `grep -rn 'parrot.squawk' packages/ai-parrot/src/parrot/roost` matches only this file
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/roost/squawk_bridge.py packages/ai-parrot/tests/roost/test_squawk_bridge.py`

---

## Validation Commands

> File-level pytest only — no directories, no package roots. In a worktree prefix with
> `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-integrations/src`.

- `pytest packages/ai-parrot/tests/roost/test_squawk_bridge.py -q`

---

## Test Specification

```python
import logging

from parrot.roost import squawk_bridge as sb
from parrot.roost.codec import JsonEnvelopeCodec
from parrot.roost.messages import LocalEnvelope


async def test_degrades_without_squawk(caplog):
    sb.squawk_available.cache_clear()
    sb._WARNED = False
    assert not sb.squawk_available()
    assert isinstance(sb.load_codec(), JsonEnvelopeCodec)
    assert isinstance(sb.new_envelope(correlation_id="c", caller="a"), LocalEnvelope)
    with caplog.at_level(logging.WARNING):
        assert await sb.mount_capabilities(None, []) == [] and await sb.mount_capabilities(None, []) == []
    assert sum("satellite not installed" in r.message for r in caplog.records) == 1
# FILL IN: stub-module test (monkeypatch sys.modules / importlib.util.find_spec), resolve_authority cases
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug local-inter-agent --feature-id FEAT-747 --spec sdd/specs/local-inter-agent.spec.md --index sdd/tasks/index/local-inter-agent.json`)
2. **Read the spec** at `sdd/specs/local-inter-agent.spec.md` (§2 Data Models and the §3 module this task implements)
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/local-inter-agent.json`
4. **Verify the Codebase Contract** — re-run `grep -c` on every MODIFY anchor before editing; a count that
   differs means the anchor moved, `0` means stop and report
5. **Update status** in the index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint, complete every `# FILL IN:`, never rename
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-integrations/src`
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4724 local-inter-agent verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker (FEAT-747 execution 0b6f3a52)
**Date**: 2026-10-26
**Notes**: Delivered by engine; merge-tier green.
Seat: gpt-5.6-terra empty_delivery, then gpt-5.6-sol (codex) · Attempts: 2

**Deviations from spec**: none
