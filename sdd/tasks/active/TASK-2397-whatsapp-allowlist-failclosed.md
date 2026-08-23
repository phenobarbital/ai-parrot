# TASK-2397: Channel allowlist as a financial control (fail-closed)

**Feature**: FEAT-453 — Business Browser Automation
**Spec**: `sdd/specs/web-automation-infra.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2390
**Assigned-to**: unassigned

---

## Context

Implements **Module 11** (Goal G5, security half).

`WhatsAppBridgeConfig.allowed_numbers` (bridge_config.py:31) and the Telegram
auth module already gate who may talk to a bot. For a general assistant that is
a convenience; for **this** agent — which can spend money and file tax-relevant
records — it is a financial control. An empty allowlist means anyone who learns
the number can instruct the agent.

The operator selected the personal-number whatsmeow bridge
(`WhatsAppBridgeWrapper`), not the Meta Cloud API path (spec §8, resolved U2).

Implements spec **Module 11**.

---

## Scope

- Make the bridge **fail closed**: refuse to start when `allowed_numbers` is
  empty/None **and** the bound agent exposes any `OperationKind.SUBMIT`
  operation. Refuse loudly, naming the offending configuration.
- Leave the permissive behaviour intact when no SUBMIT operations are exposed,
  so unrelated bots are unaffected.
- Document the control in the runbook: it is a security boundary, not a UX nicety.
- Tests for both directions.

**NOT in scope**: the Meta Cloud API wrapper; Telegram auth changes beyond
documentation.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/whatsapp/bridge_config.py` | MODIFY | Fail-closed validation |
| `packages/ai-parrot-integrations/tests/whatsapp/test_allowlist_failclosed.py` | CREATE | Both directions |
| `docs/business-automation-runbook.md` | MODIFY | Document the control |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references from the actual codebase, re-checked on `dev`
> after the FEAT-449/450/452 merges. Use these exact imports and signatures.
> **DO NOT** invent, guess, or assume anything not listed here. If you need
> something absent, VERIFY it exists with `grep`/`read` and update this section
> FIRST.

### Verified Imports

```python
from parrot.integrations.whatsapp.bridge_config import WhatsAppBridgeConfig   # verified: whatsapp/bridge_config.py:9
from parrot.integrations.whatsapp.bridge_wrapper import WhatsAppBridgeWrapper # verified: whatsapp/bridge_wrapper.py
from parrot_tools.business_automation.models import OperationKind             # created by TASK-2390
```

### Existing Signatures to Use

```python
# packages/ai-parrot-integrations/src/parrot/integrations/whatsapp/bridge_config.py
@dataclass
class WhatsAppBridgeConfig:                         # line 9
    """Configuration for WhatsApp Bridge wrapper (whatsmeow-based)."""
    name: str                                       # line 24
    chatbot_id: str                                 # line 25
    bridge_url: str = "http://localhost:8765"       # line 26
    webhook_path: Optional[str] = None              # line 27
    welcome_message: Optional[str] = None           # line 28
    system_prompt_override: Optional[str] = None    # line 29
    commands: Dict[str, str] = field(default_factory=dict)  # line 30
    allowed_numbers: Optional[List[str]] = None     # line 31  <- "Empty = all"

# packages/ai-parrot-integrations/src/parrot/integrations/whatsapp/bridge_wrapper.py
class WhatsAppBridgeWrapper:
    """WhatsApp -> Go whatsmeow bridge -(HTTP POST)-> wrapper -> agent.ask()
       -> bridge POST /send -> WhatsApp"""

# For reference, the OTHER (not selected) transport:
#   whatsapp/wrapper.py:37  class WhatsAppAgentWrapper   (pywa / Meta Cloud API)
#     def _is_authorized(self, wa_id: str) -> bool       # line 340
```

### Does NOT Exist

- ~~`WhatsAppBridgeConfig.allowlist`~~ — the field is `allowed_numbers` (line 31).
- ~~`WhatsAppBridgeConfig._is_authorized()`~~ — that method is on `WhatsAppAgentWrapper` (wrapper.py:340), the **Meta Cloud API** path, which is NOT the selected transport.
- ~~a global "safe mode" flag~~ — no such concept exists. The control is per-config.

---

## Implementation Notes

### Key Constraints
- Fail **closed and loudly**. A silent refusal to start is nearly as bad as
  starting open — the operator must see why.
- Do not change behaviour for bots with no SUBMIT operations; this must not
  break unrelated integrations.
- `allowed_numbers` is documented as "digits only, no +" (bridge_config.py:19) —
  normalize and validate accordingly.

### References in Codebase
- `packages/ai-parrot-tools/src/parrot_tools/scraping/advanced_actions.py` — the FEAT-222 extraction pattern
- `packages/ai-parrot/src/parrot/tools/obsidian.py` — FEAT-391 lazy-lifecycle toolkit
- `packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py` — FEAT-207 shared-state toolkit + run_id polling

---

## Acceptance Criteria

- [ ] Implementation complete per scope
- [ ] Empty `allowed_numbers` + any exposed SUBMIT operation ⇒ the bridge refuses to start, naming the config
- [ ] Empty `allowed_numbers` + no SUBMIT operations ⇒ unchanged permissive behaviour
- [ ] A populated allowlist starts normally and rejects a non-listed number
- [ ] Numbers are normalized to digits-only before comparison
- [ ] The runbook describes the allowlist as a financial control
- [ ] All tests pass: `pytest packages/ai-parrot-tools/tests/ -v`
- [ ] No linting errors: `ruff check` on every changed file

---

## Test Specification

> Minimal scaffold. The agent must make these pass and add more as needed.

```python
import pytest
from parrot.integrations.whatsapp.bridge_config import WhatsAppBridgeConfig


class TestFailClosed:
    async def test_empty_allowlist_with_submit_refuses(self, submit_capable_agent):
        cfg = WhatsAppBridgeConfig(name="g", chatbot_id="gestoria", allowed_numbers=None)
        with pytest.raises(ValueError, match="allowed_numbers"):
            await start_bridge(cfg, submit_capable_agent)

    async def test_empty_allowlist_without_submit_is_allowed(self, read_only_agent):
        cfg = WhatsAppBridgeConfig(name="g", chatbot_id="reader", allowed_numbers=None)
        await start_bridge(cfg, read_only_agent)   # must not raise

    async def test_normalizes_numbers(self):
        cfg = WhatsAppBridgeConfig(name="g", chatbot_id="x", allowed_numbers=["+34 600 11 22 33"])
        assert "34600112233" in cfg.normalized_allowed_numbers
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/web-automation-infra.spec.md` — especially §6 Codebase Contract and §7 Decisions D1-D4.
2. **Check dependencies** — verify `Depends-on` tasks are in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** before writing ANY code:
   - Confirm every import still resolves (`grep`/`read` the source).
   - Confirm every listed signature still matches.
   - If anything changed, update this contract FIRST, then implement.
   - **NEVER** reference an import, attribute, or method not in the contract
     without verifying it exists.
4. **Update status** in `sdd/tasks/index/web-automation-infra.json` → `"in-progress"`.
5. **Implement** per scope, contract, and notes — nothing more.
6. **Verify** every acceptance criterion.
7. **Move this file** to `sdd/tasks/completed/TASK-2397-whatsapp-allowlist-failclosed.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
