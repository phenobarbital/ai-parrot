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
- ~~`WhatsAppBridgeConfig._is_authorized()`~~ — that method is on `WhatsAppAgentWrapper` (wrapper.py:340), the **Meta Cloud API** path, which is NOT the selected transport. On the selected transport it is `WhatsAppBridgeWrapper._is_authorized()` (bridge_wrapper.py:289).
- ~~a global "safe mode" flag~~ — no such concept exists. The control is per-config.
- ~~a `start_bridge()` free function~~ — the Test Specification's scaffold names one, but no such function exists anywhere in `whatsapp/`. The actual "start" point — where the webhook route is registered and thus where fail-closed must raise — is `WhatsAppBridgeWrapper.__init__()` (bridge_wrapper.py:54), called once per bridge at wiring time. Tests below construct `WhatsAppBridgeWrapper(...)` directly instead of a nonexistent `start_bridge()`.

### Additional Verified References (added at implementation time)

```python
# packages/ai-parrot/src/parrot/bots/abstract.py:386
self.tool_manager: ToolManager = ToolManager(...)   # every AbstractBot/Agent has one

# packages/ai-parrot/src/parrot/tools/manager.py — the exact, already-shipped
# pattern for walking from an agent to its toolkit instances, reused verbatim
# (ToolManager.cleanup_toolkits(), lines 2084-2148):
from .toolkit import ToolkitTool
for tool in self._tools.values():          # ToolManager._tools: dict[str, AbstractTool]
    if not isinstance(tool, ToolkitTool):
        continue
    bound = getattr(tool, "bound_method", None)
    toolkit = getattr(bound, "__self__", None)   # the owning AbstractToolkit instance

# packages/ai-parrot/src/parrot/tools/toolkit.py:33
class ToolkitTool(AbstractTool): ...

# packages/ai-parrot-tools/src/parrot_tools/business_automation/toolkit.py (TASK-2390)
class BusinessAutomationToolkit(AbstractToolkit):
    self._operations: Dict[str, BusinessOperation]   # populated in __init__

# packages/ai-parrot-tools/src/parrot_tools/business_automation/models.py (TASK-2390)
class BusinessOperation(BaseModel):
    kind: OperationKind   # READ | DRAFT | SUBMIT
```

**Cross-satellite import note**: `ai-parrot-integrations`'s `pyproject.toml`
declares only `ai-parrot` (core) as a dependency — it does not declare
`ai-parrot-tools`. Importing `parrot_tools.business_automation` from
`bridge_wrapper.py` is therefore wrapped in `try/except ImportError` (deferred,
inside the detection helper, not at module import time): if
`ai-parrot-tools`/`parrot_tools.business_automation` is not installed, no
`BusinessAutomationToolkit` can exist on any agent, so "exposes a SUBMIT
operation" is trivially `False` and permissive behaviour is preserved —
consistent with the scope's own instruction to leave bots without SUBMIT
operations unaffected.

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

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-24
**Notes**: Implemented the fail-closed financial control in
`bridge_wrapper.py`/`bridge_config.py`:

- `WhatsAppBridgeConfig.normalized_allowed_numbers` (property) and a new
  module-level `normalize_phone_number()` helper in `bridge_config.py`
  normalize both the configured allowlist and an incoming phone to
  digits-only via a `_DIGITS_ONLY = re.compile(r"\D+")` pattern, so
  `+34 600 11 22 33` and `34600112233` compare equal.
- `WhatsAppBridgeWrapper.__init__()` raises `ValueError` (naming the
  config's `name`/`chatbot_id` and mentioning `allowed_numbers`) when
  `config.normalized_allowed_numbers` is empty **and** the bound agent
  exposes at least one `OperationKind.SUBMIT` `BusinessOperation` — before
  the webhook route is ever registered (true fail-closed: the bridge never
  starts, not just "starts but silently ignores writes").
- Bots with no `BusinessAutomationToolkit` at all, or one with only
  READ/DRAFT operations, are provably unaffected (dedicated tests) — the
  pre-existing "empty = all" permissive default is preserved for them.
- `_is_authorized()` now compares normalized numbers on both sides, fixing
  a latent bug where a literal string compare against `allowed_numbers`
  would silently reject a legitimately-listed number formatted with a `+`
  or internal spaces/dashes.
- New `_agent_exposes_submit_operation()` helper detects a bound
  `BusinessAutomationToolkit` by walking `agent.tool_manager._tools` for a
  `ToolkitTool` whose `bound_method.__self__` is a `BusinessAutomationToolkit`
  instance — the exact, already-shipped pattern
  `ToolManager.cleanup_toolkits()` uses (verified by reading
  `parrot/tools/manager.py:2084-2148`), reused rather than inventing a new
  toolkit-introspection path.
- Runbook §4 rewritten to explain the control is a security boundary, name
  the detection mechanism, and describe the normalization.

**Codebase Contract corrections applied at implementation time** (added to
the contract section above before implementing, per Cardinal Rule 4): the
Test Specification's `start_bridge()` scaffold function does not exist
anywhere in `whatsapp/` — the actual "start" point is
`WhatsAppBridgeWrapper.__init__()` itself (where the webhook route is
registered), so tests construct `WhatsAppBridgeWrapper(...)` directly.
Also documented the additional verified references needed to walk from an
agent to its toolkit instances (`ToolManager._tools`, `ToolkitTool.bound_method`,
`BusinessAutomationToolkit._operations`) — none of these were hallucinated;
each was `read`-verified against the actual source before use.

**Cross-satellite import handling**: `ai-parrot-integrations`'s
`pyproject.toml` does not declare `ai-parrot-tools` as a dependency (each
integration satellite depends only on core `ai-parrot`). The
`parrot_tools.business_automation` import in `_agent_exposes_submit_operation()`
is therefore deferred (inside the function) and wrapped in
`try/except ImportError`, returning `False` when that distribution isn't
installed — an unrelated bot with no such toolkit is unaffected by
definition, matching the scope's own "must not break unrelated
integrations" constraint.

**Test-environment workaround (self-contained, no shared files touched)**:
this repo's shared venv has `ai-parrot-tools` editable-installed pointing
at the **main-repo** checkout, not this worktree — `BusinessAutomationToolkit`
only exists in this worktree (TASK-2390, unmerged). A pre-existing
`packages/ai-parrot-integrations/conftest.py` already solves this same
problem for `ai-parrot-integrations`/`ai-parrot` core by prepending the
worktree's own `src/` onto `sys.path`, but it does not cover
`ai-parrot-tools`, and it is out of this task's file scope to edit. Rather
than touching that shared file, `test_allowlist_failclosed.py` performs its
own scoped `sys.path` prepend for `packages/ai-parrot-tools/src`, plus (since
`parrot_tools` may already be cached in `sys.modules` from another test
collected earlier in the same pytest session, pointing at the main-repo
copy) splices the worktree's `parrot_tools/` directory onto the front of
the already-imported package's `__path__` so `parrot_tools.business_automation`
resolves correctly regardless of test-collection order. This is purely a
local development/testing artifact of running inside a not-yet-merged
worktree; the production import path in `bridge_wrapper.py` itself needs
no such workaround.

**Unrelated concurrent-process note**: mid-task, an automated
"style: apply black formatting (post sdd-worker)" commit (`ac8e9064a`,
authored outside this task) landed on this same branch and reformatted
(black, not behavioral) every file this sdd-worker run had touched so far
— including this task's own uncommitted `bridge_config.py`/`bridge_wrapper.py`
edits, which were swept into that commit before this task's own commit
could land. Verified via `git show ac8e9064a -- .../bridge_config.py` and
`.../bridge_wrapper.py` that the diff is exactly this task's intended
implementation, reformatted — no content was lost or altered in meaning.
This task's own commit therefore contains only the files black's pass
didn't already carry (the new test file, `__init__.py`, and the runbook
doc, which wasn't yet tracked/touched by that commit).

Full targeted regression: `packages/ai-parrot-integrations/tests/whatsapp/`
(11/11 passed), `packages/ai-parrot-integrations/tests/` filtered to
`-k "whatsapp or telegram"` (534 passed, 13 failed — all in
pre-existing/unrelated telegram voice/photo/enrich_question suites,
confirmed via `git stash` to fail identically without any of this task's
changes present), and `packages/ai-parrot-tools/tests/business_automation/`
+ `tests/scraping/` (864 passed, 7 failed — the same pre-existing
`CrawlEngine`/FEAT-013 group every prior task in this feature has already
noted). Zero regressions attributable to this task. `ruff check` clean
except the same `UP006`/`UP035`/`UP045`/`G201`/`SIM117`/`BLE001`
pre-existing debt in `bridge_wrapper.py`/`bridge_config.py`, confirmed via
`git stash` to be present before any of this task's edits.

**Deviations from spec**: none beyond the contract corrections already
flagged above (`start_bridge()` does not exist; the real fail-closed check
point is `WhatsAppBridgeWrapper.__init__()`).
