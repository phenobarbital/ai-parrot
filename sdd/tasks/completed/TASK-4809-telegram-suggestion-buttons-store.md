# TASK-4809: Telegram suggestion buttons — token store, keyboard builder, config toggle

**Feature**: FEAT-752 — Follow-up Suggestion Chips
**Spec**: `sdd/specs/followup-suggestion-chips.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4794
**Assigned-to**: unassigned

---

## Context

Spec rev 0.3, §3 Module 9 (building blocks), G7, Q3. Telegram `callback_data` is capped at 64 bytes, so a chip's
prompt cannot ride in the button. This task adds a self-contained module: a TTL token store mapping
`sg:<token>` → `{prompt, output_mode, chat_id, user_id}`, a keyboard builder that turns `AIMessage.suggestions` into
a `build_inline_keyboard` dict, and the opt-in config fields. Wiring into the wrapper is TASK-4810.

---

## Scope

- New `telegram/suggestion_buttons.py`: `SUGGESTION_PREFIX = "sg"`, `SuggestionButtonStore`,
  `build_suggestion_keyboard(...)`.
- `TelegramAgentConfig`: `suggestion_buttons: bool = False`, `suggestion_button_ttl_s: int = 86400` (+ `from_dict`).
- Tests in `packages/ai-parrot-integrations/tests/telegram/test_suggestion_buttons.py`.

**NOT in scope**: `wrapper.py` (TASK-4810); Redis-backed store (the store accepts any object with the
`InMemoryStateStore` async `set/get/delete` interface, but only the in-memory default is wired in v1).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/suggestion_buttons.py` | CREATE | Store + keyboard |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/models.py` | MODIFY | Two config fields |
| `packages/ai-parrot-integrations/tests/telegram/test_suggestion_buttons.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.integrations.telegram.callbacks import CallbackData, build_inline_keyboard   # callbacks.py:111, :318
from parrot.integrations.core.state import InMemoryStateStore                          # core/state.py:14
from parrot.integrations.telegram.models import TelegramAgentConfig                    # models.py:42
from parrot.models import Suggestion                                                   # TASK-4794
```

### Existing Signatures to Use
```python
# callbacks.py
class CallbackData:  SEPARATOR = ":"; MAX_BYTES = 64                                    # :111-166
    @staticmethod def encode(prefix, payload) -> str   # raises ValueError past 64 bytes (:142-147)
    @staticmethod def decode(data) -> tuple[str, dict] # non-JSON payload → {"raw": "<str>"} (:164)
def build_inline_keyboard(buttons: List[List[Dict[str, Any]]]) -> Dict[str, Any]       # :318 → {"inline_keyboard": rows}
#   each button dict: {"text": ..., "callback_data": "<already encoded>"} | prefix+payload | url
# core/state.py
class InMemoryStateStore:                                                              # :14
    async def set(self, key: str, value: str, expire: int = 0) -> None                 # :42 (expire in seconds)
    async def get(self, key: str) -> Optional[str]                                     # :49 (None when missing/expired)
    async def delete(self, key: str) -> None                                           # :56
# models.py — @dataclass class TelegramAgentConfig (:41-42)
#   `    enable_reply_context: bool = True` (:139, 1 occurrence)
#   from_dict: `            enable_reply_context=bool(data.get("enable_reply_context", True)),` (:301, 1 occurrence)
```

### Does NOT Exist
- ~~`telegram/suggestion_buttons.py`~~, ~~`TelegramAgentConfig.suggestion_buttons`~~ — created here.
- ~~a TTL store in `callbacks.py`~~ — use `InMemoryStateStore`.
- ~~explain support on Telegram~~ — `kind == "action"` chips are dropped.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/telegram/suggestion_buttons.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/telegram/models.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/tests/telegram/test_suggestion_buttons.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/models.py#TelegramAgentConfig"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Config fields + `from_dict` — *why*: opt-in, default off (no behaviour change for existing bots).
2. The module — *why*: keeps the 4k-line wrapper change in TASK-4810 small.
3. Tests; run Validation Commands.

### `models.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    enable_reply_context: bool = True' models.py)
# AFTER — insert below that line (models.py:139)
    # Follow-up suggestion chips as inline buttons (FEAT-752) — opt-in.
    suggestion_buttons: bool = False
    suggestion_button_ttl_s: int = 86400

# occurrences: 1 (verified: grep -c '            enable_reply_context=bool(data.get("enable_reply_context", True)),' models.py)
# AFTER — insert below that line (models.py:301)
            suggestion_buttons=bool(data.get("suggestion_buttons", False)),
            suggestion_button_ttl_s=int(data.get("suggestion_button_ttl_s", 86400)),
```

### `suggestion_buttons.py` (CREATE)
```python
"""Telegram inline-keyboard rendering of follow-up suggestion chips (FEAT-752).

``callback_data`` is capped at 64 bytes, so each button carries ``sg:<token>`` and the chip itself lives in a TTL
store keyed by that token. Only non-action chips are rendered (Telegram has no explain path).
"""

from __future__ import annotations

import json
import logging
import secrets
from typing import Any, Optional, Sequence

from ..core.state import InMemoryStateStore
from .callbacks import CallbackData, build_inline_keyboard

SUGGESTION_PREFIX = "sg"
MAX_BUTTONS = 6
BUTTONS_PER_ROW = 2
MAX_LABEL = 40


class SuggestionButtonStore:
    """Token → chip mapping with expiry. ``store`` must expose async ``set/get/delete`` (InMemoryStateStore API)."""

    def __init__(self, ttl_s: int = 86400, store: Optional[Any] = None) -> None:
        self.ttl_s = int(ttl_s)
        self._store = store if store is not None else InMemoryStateStore()
        self.logger = logging.getLogger(__name__)

    @staticmethod
    def _key(token: str) -> str:
        return f"telegram:suggestion:{token}"

    async def put(self, *, prompt: str, output_mode: Optional[str], chat_id: int, user_id: int) -> str:
        """Store one chip and return its token (``secrets.token_urlsafe(9)`` → 12 chars)."""
        token = secrets.token_urlsafe(9)
        record = {"prompt": prompt, "output_mode": output_mode, "chat_id": int(chat_id), "user_id": int(user_id)}
        await self._store.set(self._key(token), json.dumps(record), expire=self.ttl_s)
        return token

    async def get(self, token: str) -> Optional[dict]:
        """Return the stored chip, or None when unknown/expired/corrupt."""
        # FILL IN: get → json.loads; None on missing; log + None on JSONDecodeError
        raise NotImplementedError


async def build_suggestion_keyboard(
    suggestions: Sequence[Any], store: SuggestionButtonStore, *, chat_id: int, user_id: int
) -> Optional[dict]:
    """Build a ``build_inline_keyboard`` dict for the non-action chips, or None when nothing is renderable.

    Chips are read duck-typed (``label``, ``prompt``, ``output_mode``, ``kind``) so plain dicts work too.
    """
    # FILL IN: skip kind == "action" (enum or str: compare str(getattr(kind, "value", kind))); cap MAX_BUTTONS;
    #          label[:MAX_LABEL]; token = await store.put(...); callback_data = f"{SUGGESTION_PREFIX}{CallbackData.SEPARATOR}{token}"
    #          (assert len(callback_data.encode()) <= CallbackData.MAX_BYTES); rows of BUTTONS_PER_ROW
    #          {"text": label, "callback_data": callback_data}; return build_inline_keyboard(rows) or None if empty
    raise NotImplementedError
```

### FILL IN checklist
- [ ] `SuggestionButtonStore.get`; `build_suggestion_keyboard`.
- [ ] Test bodies below.

---

## Acceptance Criteria

- [ ] `TelegramAgentConfig()` defaults: `suggestion_buttons is False`, `suggestion_button_ttl_s == 86400`;
      `from_dict` reads both.
- [ ] Keyboard: action chips dropped; ≤ 6 buttons, 2 per row; labels ≤ 40 chars; every `callback_data` is
      `sg:<token>` and ≤ 64 bytes; `CallbackData.decode` of it gives prefix `sg` and `{"raw": token}`.
- [ ] Store: `put` → `get` round-trips; expired or unknown token → `None`.
- [ ] `packages/ai-parrot/tests/test_callbacks.py` stays green; `ruff check` clean.

---

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/telegram/test_suggestion_buttons.py -q`
- `pytest packages/ai-parrot/tests/test_callbacks.py -q`

---

## Test Specification

```python
# packages/ai-parrot-integrations/tests/telegram/test_suggestion_buttons.py
import pytest

from parrot.integrations.telegram.callbacks import CallbackData
from parrot.integrations.telegram.models import TelegramAgentConfig
from parrot.integrations.telegram.suggestion_buttons import SuggestionButtonStore, build_suggestion_keyboard
from parrot.models import Suggestion


def test_config_defaults_off():
    cfg = TelegramAgentConfig.from_dict("b", {"bot_token": "x"})  # FILL IN: adjust required keys to from_dict
    assert cfg.suggestion_buttons is False and cfg.suggestion_button_ttl_s == 86400


@pytest.mark.asyncio
async def test_keyboard_skips_actions_and_caps():
    store = SuggestionButtonStore()
    chips = [Suggestion(label=f"Chip {i}", prompt=f"p{i}") for i in range(8)]
    chips.append(Suggestion(label="Explain this", prompt="Explain", kind="action", action="explain"))
    kb = await build_suggestion_keyboard(chips, store, chat_id=1, user_id=2)
    buttons = [b for row in kb["inline_keyboard"] for b in row]
    assert len(buttons) == 6 and all(len(r) <= 2 for r in kb["inline_keyboard"])
    for b in buttons:
        assert len(b["callback_data"].encode()) <= CallbackData.MAX_BYTES
        prefix, payload = CallbackData.decode(b["callback_data"])
        assert prefix == "sg" and await store.get(payload["raw"]) is not None


@pytest.mark.asyncio
async def test_store_expiry_and_unknown():
    # FILL IN: unknown token -> None; put with ttl_s=0 is "no expiry" in InMemoryStateStore — use monkeypatched
    #          time.monotonic (core/state.py uses it) to expire a ttl_s=1 entry -> None
    ...
```

---

## Agent Instructions

Follow `sdd/templates/task.md` § Agent Instructions (worktree via `ensure_worktree --slug followup-suggestion-chips
--feature-id FEAT-752`, `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-integrations/src`, commit only listed
files, `scripts/sdd/close_task.sh TASK-4809 followup-suggestion-chips verified`).

---

## Completion Note

Implemented directly by the worker (sequential fallback). Files exactly as listed; anchors in models.py re-verified.
DEVIATION from the blueprint (deliberate, small): the token is `"s" + secrets.token_urlsafe(8)` (still 12 URL-safe chars) instead of a bare `secrets.token_urlsafe(9)`. `CallbackData.decode` runs `json.loads` on the part after the separator, so a purely numeric token (about 2e-10 per token, but real) would decode to an int instead of `{"raw": token}`, breaking the acceptance criterion and TASK-4810's handler. A letter prefix makes JSON parsing impossible; a test asserts it over 2000 tokens and documents the hazard.
Also: `get()` returns None for corrupt JSON and for non-dict JSON; `build_suggestion_keyboard` skips chips without a label/prompt and reads chips duck-typed (dicts or models).
Tests: 8 new in `test_suggestion_buttons.py` plus `packages/ai-parrot/tests/test_callbacks.py` = 12 passed. ruff and black clean.
