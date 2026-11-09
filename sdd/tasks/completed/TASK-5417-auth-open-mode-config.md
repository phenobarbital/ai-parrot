# TASK-5417: Config fields `auth_open_mode` + `public_base_url`

**Feature**: FEAT-854 — Telegram Auth Open Mode (webview | browser)
**Spec**: `sdd/specs/telegram-auth-open-mode.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1. Every other module reads the presentation mode from
`TelegramAgentConfig.auth_open_mode` (decision `open-mode-config-driven`: the mode
comes from config, never from a new `build_login_keyboard` kwarg). Browser mode also
needs an absolute `public_base_url` to build the server-side completion URL. Today
`public_base_url` is not a declared field: the wrapper reads it with
`getattr(self.config, "public_base_url", "")` (wrapper.py:793, 2686). This task
formalizes both fields and fails config load loudly for invalid combinations.

---

## Scope

- Add `auth_open_mode: str = "webview"` and `public_base_url: Optional[str] = None` to
  `TelegramAgentConfig`.
- Map both keys in `TelegramAgentConfig.from_dict` (YAML loading).
- In `__post_init__`, raise `ValueError` when `auth_open_mode` is not `"webview"` or
  `"browser"`, and when `auth_open_mode == "browser"` without a usable absolute
  `http(s)` `public_base_url`.
- Add the three M1 unit tests to `test_auth_strategies.py`.

**NOT in scope**: keyboards (TASK-5419), the wrapper (TASK-5422/5423), env-var
fallbacks for `public_base_url` (the spec defines none — do not invent one).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/models.py` | MODIFY | Two fields, `from_dict` mapping, `__post_init__` validation |
| `packages/ai-parrot-integrations/tests/integrations/telegram/test_auth_strategies.py` | MODIFY | Append `TestAuthOpenModeConfig` |

---

## Codebase Contract (Anti-Hallucination)

> Verified against dev @ `0083e04b62` (2026-11-09).

### Verified Imports
```python
from dataclasses import dataclass, field          # verified: telegram/models.py:6
from typing import TYPE_CHECKING, Dict, List, Optional, Any  # verified: telegram/models.py:7
from parrot.integrations.telegram.models import TelegramAgentConfig  # verified: tests/.../test_oauth2_integration.py:21
```

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/integrations/telegram/models.py
@dataclass
class TelegramAgentConfig:                                   # line 37
    name: str                                                # line 65
    chatbot_id: str                                          # line 66
    auth_method: str = "basic"                               # line 89
    auth_methods: List[str] = field(default_factory=list)    # line 92
    def __post_init__(self):                                 # line 156 (spec said 166 — moved)
    #   last statement of __post_init__:
    #   self.google_auth_url = f"{base}/google/"            # line 224
    @property
    def voice_enabled(self) -> bool:                         # line 227
    @classmethod
    def from_dict(cls, name: str, data: Dict[str, Any]) -> "TelegramAgentConfig":  # line ~231
    #   return cls(... auth_methods=auth_methods, ...)       # line 287
```

Existing readers of `public_base_url` (they keep working unchanged):
```python
# packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py:793 and :2686
getattr(self.config, "public_base_url", "")
# Only consumer of that value today discards it:
# packages/ai-parrot-integrations/src/parrot/integrations/telegram/post_auth_connection.py:66-68
async def build_auth_url(self, session: Any, config: Any, callback_base_url: str) -> str:
    del config, callback_base_url
```
After this task those readers get `None` instead of `""` when the field is unset;
the consumer discards it, so no wrapper change is needed here.

### Does NOT Exist
- ~~`TelegramAgentConfig.auth_open_mode`~~ / ~~`TelegramAgentConfig.public_base_url`~~ — created by THIS task.
- ~~`{NAME}_PUBLIC_BASE_URL` env fallback~~ — not specified; do not add one.
- ~~`AuthOpenMode` enum~~ — the spec uses a plain `str` field; do not add an enum.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/telegram/models.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/tests/integrations/telegram/test_auth_strategies.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/models.py#TelegramAgentConfig",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/models.py#TelegramAgentConfig.from_dict"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Default `"webview"` must leave every existing config byte-for-byte unchanged (spec AC 1).
- Validation runs at config load (`__post_init__`), not at login time (spec §7 Known Risks).
- Error messages name the agent (`Agent '<name>': ...`), matching the existing
  `auth_methods` error at models.py:186-189.

---

## Implementation Blueprint

### Steps (in order)
1. Insert the two fields below `auth_methods` — *why*: they sit with the other auth settings and keep dataclass field order valid (both have defaults).
2. Append the validation block at the end of `__post_init__` — *why*: it runs after `auth_methods` normalization, so later checks can rely on it.
3. Map both keys in `from_dict` — *why*: YAML-loaded bots would otherwise silently stay in webview mode.
4. Append the tests and run them.

### `packages/ai-parrot-integrations/src/parrot/integrations/telegram/models.py` (MODIFY — fields)
```python
# occurrences: 1 (verified: grep -c '    auth_methods: List\[str\] = field(default_factory=list)' telegram/models.py)
# AFTER — insert below `    auth_methods: List[str] = field(default_factory=list)` (verified: telegram/models.py:92)
    # FEAT-854: auth presentation mode. "webview" (default) = WebApp button +
    # Telegram.WebApp.sendData(); "browser" = inline URL button opened in the
    # system browser + server-side completion endpoints.
    auth_open_mode: str = "webview"
    # FEAT-854: public base URL of the parrot server (e.g. "https://parrot.example").
    # Required in browser mode to build absolute completion URLs. Formalizes the
    # getattr(config, "public_base_url", "") reads in wrapper.py.
    public_base_url: Optional[str] = None
```
**Why**: Spec §3 M1 skeleton fixes names, types and defaults; keep them exactly.

### `packages/ai-parrot-integrations/src/parrot/integrations/telegram/models.py` (MODIFY — validation)
```python
# occurrences: 1 (verified: grep -c 'self.google_auth_url = f"{base}/google/"' telegram/models.py)
# AFTER — insert below `                self.google_auth_url = f"{base}/google/"` (verified: telegram/models.py:224)
# Indentation: 8 spaces (method body level, NOT inside the `if "google"` block).
        # FEAT-854: validate the auth presentation mode.
        _ALLOWED_OPEN_MODES = {"webview", "browser"}
        if self.auth_open_mode not in _ALLOWED_OPEN_MODES:
            raise ValueError(
                f"Agent '{self.name}': auth_open_mode must be one of "
                f"{sorted(_ALLOWED_OPEN_MODES)}, got {self.auth_open_mode!r}"
            )
        if self.auth_open_mode == "browser":
            # FILL IN: reject a missing/blank public_base_url AND one that is not an
            # absolute http(s) URL — use urllib.parse.urlsplit (stdlib) and require
            # scheme in {"http", "https"} and a non-empty netloc — bounded by spec AC
            # "browser without public_base_url fails at config load with a clear ValueError".
            # Message must name the agent and say browser mode requires public_base_url.
            pass
```
**Why**: Spec M1 skeleton: ValueError for unknown mode and for browser without
`public_base_url`. The http(s) check prevents `javascript:`/relative values from
reaching the completion URL builder (spec §7 open-redirect risk). Import
`urlsplit` locally or at module top (stdlib — no new dependency).

### `packages/ai-parrot-integrations/src/parrot/integrations/telegram/models.py` (MODIFY — from_dict)
```python
# occurrences: 1 (verified: grep -c '            auth_methods=auth_methods,' telegram/models.py)
# AFTER — insert below `            auth_methods=auth_methods,` (verified: telegram/models.py:287)
            auth_open_mode=data.get("auth_open_mode", "webview"),
            public_base_url=data.get("public_base_url"),
```
**Why**: `from_dict` maps every field explicitly; unmapped keys are dropped.

### `packages/ai-parrot-integrations/tests/integrations/telegram/test_auth_strategies.py` (MODIFY)
```python
# AFTER — append at end of file (last line today: `        assert session.authenticated is False`, line 219)
# Add `from parrot.integrations.telegram.models import TelegramAgentConfig` to the
# import block at the top of the file.


class TestAuthOpenModeConfig:
    """FEAT-854 M1: auth_open_mode / public_base_url config surface."""

    def test_config_auth_open_mode_default_webview(self):
        """Unset field resolves to 'webview' (legacy behavior)."""
        cfg = TelegramAgentConfig(name="t", chatbot_id="c")
        assert cfg.auth_open_mode == "webview"
        assert cfg.public_base_url is None

    def test_config_auth_open_mode_invalid_raises(self):
        """An unknown mode fails at config load."""
        # FILL IN: auth_open_mode="popup" -> pytest.raises(ValueError, match="auth_open_mode")

    def test_config_browser_requires_public_base_url(self):
        """Browser mode without public_base_url fails at config load."""
        # FILL IN: no public_base_url -> ValueError; "ftp://x" -> ValueError;
        # "https://parrot.example" -> accepted.

    def test_config_from_dict_maps_open_mode(self):
        """YAML loading carries both new keys."""
        # FILL IN: TelegramAgentConfig.from_dict("t", {"auth_open_mode": "browser",
        # "public_base_url": "https://parrot.example"}) round-trips both values.
```

### FILL IN checklist
- [ ] `models.py::TelegramAgentConfig.__post_init__` — absolute http(s) check for `public_base_url`; bounded by spec AC (clear ValueError at load)
- [ ] `test_auth_strategies.py::TestAuthOpenModeConfig` — three test bodies

---

## Acceptance Criteria

- [ ] `TelegramAgentConfig(name="t", chatbot_id="c").auth_open_mode == "webview"`.
- [ ] `auth_open_mode="popup"` raises `ValueError`; browser mode without (or with a non-http(s)) `public_base_url` raises `ValueError`.
- [ ] `from_dict` maps `auth_open_mode` and `public_base_url`.
- [ ] Existing telegram config tests still pass unchanged (`test_config_auth_methods.py`, `test_config_validation_multi_auth.py` are run by the merge tier).
- [ ] `ruff check` clean on both files.

---

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/integrations/telegram/test_auth_strategies.py -q`

---

## Test Specification

See the `TestAuthOpenModeConfig` block above (spec §4 M1 rows:
`test_config_auth_open_mode_default_webview`, `test_config_auth_open_mode_invalid_raises`,
`test_config_browser_requires_public_base_url`).

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug telegram-auth-open-mode --feature-id FEAT-854`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/telegram-auth-open-mode.json`
4. **Verify the Codebase Contract** before writing any code; fix stale entries first
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:` marker
7. **Verify** all acceptance criteria — run the Validation Commands with
   `PYTHONPATH=packages/ai-parrot-integrations/src`
8. **Commit the code** — stage only the files this task lists
9. **Close the task** with `parrot sdd task close TASK-5417 telegram-auth-open-mode verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker orchestrator; seat gpt-5.6-terra (codex), attempt 1, 128s
**Date**: 2026-11-09
**Notes**: Added auth_open_mode/public_base_url fields, from_dict mapping and __post_init__ validation; 3 M1 tests. Merge-tier validation green (50 passed, chunk 0). Delivery diff reviewed against task file list: no out-of-scope files. No review fixes.

**Deviations from spec**: none
