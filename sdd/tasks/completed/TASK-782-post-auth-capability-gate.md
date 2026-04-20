# TASK-782: Replace `isinstance(BasicAuthStrategy)` Post-Auth Gate

**Feature**: FEAT-109 — Telegram Multi-Auth Negotiation
**Spec**: `sdd/specs/FEAT-109-telegram-multi-auth-negotiation.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 1h)
**Depends-on**: TASK-777, TASK-781
**Assigned-to**: unassigned

---

## Context

`wrapper.py:1021` today gates the FEAT-108 `post_auth_actions`
redirect chain on
`isinstance(self._auth_strategy, BasicAuthStrategy)`. With TASK-777
introducing `supports_post_auth_chain` and TASK-778 making Azure
chain-capable, the `isinstance` check is obsolete and actively wrong
(it would exclude Azure and Composite even when they can chain).

Implements **Module 6** of the spec.

---

## Scope

- Replace the `isinstance(self._auth_strategy, BasicAuthStrategy)`
  check at `wrapper.py:1021` with:
  ```python
  getattr(self._auth_strategy, "supports_post_auth_chain", False)
  ```
- Ensure `build_login_keyboard` is called with the same
  `next_auth_url` / `next_auth_required` kwargs regardless of the
  concrete strategy class — the abstract base now accepts them
  (TASK-777).
- Preserve behavior for strategies that do NOT support the chain:
  the wrapper does not compute `next_auth_url` at all, matching
  today's logic for Azure/OAuth2 single-method setups.

**NOT in scope**:
- Other `isinstance` checks in wrapper.py that are NOT the
  post_auth gate — leave them alone unless obviously broken by
  TASK-779.
- Strategy selection — TASK-781 owns that.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/integrations/telegram/wrapper.py` | MODIFY | Swap isinstance for capability flag; forward kwargs uniformly |
| `packages/ai-parrot/tests/integrations/telegram/test_post_auth_capability_gate.py` | CREATE | Prove Azure + Composite now enter the chain branch |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# wrapper.py already imports AbstractAuthStrategy via the strategies module.
# No new imports needed — the capability flag lives on the base class.
```

### Existing Signatures to Use

```python
# wrapper.py around line 1021 (verify with grep — line may shift):
# Today the block reads roughly:
#     if self.config.enable_login and self._auth_strategy:
#         if isinstance(self._auth_strategy, BasicAuthStrategy):
#             next_auth_url, required = await self._build_next_auth_url(...)
#             keyboard = await self._auth_strategy.build_login_keyboard(
#                 self.config, state,
#                 next_auth_url=next_auth_url,
#                 next_auth_required=required,
#             )
#         else:
#             keyboard = await self._auth_strategy.build_login_keyboard(
#                 self.config, state,
#             )

# After this task:
#         if self._auth_strategy.supports_post_auth_chain:
#             next_auth_url, required = await self._build_next_auth_url(...)
#             keyboard = await self._auth_strategy.build_login_keyboard(
#                 self.config, state,
#                 next_auth_url=next_auth_url,
#                 next_auth_required=required,
#             )
#         else:
#             keyboard = await self._auth_strategy.build_login_keyboard(
#                 self.config, state,
#             )
```

### Does NOT Exist

- ~~`AbstractAuthStrategy.supports_post_auth_chain`~~ — introduced
  by TASK-777. Verify that task is completed before starting this
  one.

---

## Implementation Notes

### Minimal diff

Find the `isinstance(self._auth_strategy, BasicAuthStrategy)` at
`wrapper.py:1021` and its surrounding block. Replace the conditional
expression only — keep the rest of the flow intact.

### Unused import cleanup

Check whether `BasicAuthStrategy` is still imported elsewhere in
`wrapper.py` after the swap. If this `isinstance` was the only
consumer, keep it anyway — it is still part of the public import
contract (`from .auth import BasicAuthStrategy` serves callers that
might access it via `wrapper.BasicAuthStrategy`). DO NOT remove
unless you are certain it's unused and breaking nothing.

---

## Acceptance Criteria

- [ ] `wrapper.py` no longer contains
      `isinstance(self._auth_strategy, BasicAuthStrategy)` for the
      post_auth gate.
- [ ] The gate uses
      `getattr(self._auth_strategy, "supports_post_auth_chain", False)`.
- [ ] When the primary method is Azure (single-method setup with
      TASK-778 complete), the post_auth chain now fires.
- [ ] When the primary method is Composite with all members
      supporting the chain, the post_auth chain fires.
- [ ] When the primary method is OAuth2 (chain unsupported), the
      chain does NOT fire — same as today.
- [ ] All existing FEAT-108 tests pass.

---

## Test Specification (sketch)

```python
# tests/integrations/telegram/test_post_auth_capability_gate.py
import pytest
from unittest.mock import MagicMock, AsyncMock


async def test_azure_strategy_enters_chain_branch(wrapper_factory, caplog):
    wrapper = wrapper_factory(auth_methods=["azure"], ...)
    # Trigger the login path; assert _build_next_auth_url was called
    ...


async def test_oauth2_strategy_skips_chain_branch(wrapper_factory):
    wrapper = wrapper_factory(auth_methods=["oauth2"], ...)
    ...  # _build_next_auth_url NOT called


async def test_composite_all_chain_enters_chain_branch(wrapper_factory):
    wrapper = wrapper_factory(auth_methods=["basic", "azure"], ...)
    ...  # _build_next_auth_url called
```

Concrete fixtures are up to the agent — follow the pattern already
used in `tests/integrations/telegram/` for wrapper-level tests.

---

## Agent Instructions

1. Grep `wrapper.py` for the current line number of the
   `isinstance(BasicAuthStrategy)` check.
2. Apply the minimal diff described above.
3. Run the FEAT-108 wrapper tests — they are the primary regression
   surface for this change.
4. Commit.

---

## Completion Note

*(Agent fills this in when done)*
