# TASK-4586: GoogleGenAIClient: explicit computer-use opt-in + v3_8 action vocabulary

**Feature**: FEAT-719 — Model Deprecation Follow-ups (Veo → Omni, Computer Use 3.8, gpt-transcribe)
**Spec**: `sdd/specs/model-deprecation-followups.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4585
**Assigned-to**: unassigned

> **Prerequisite**: branch `fix/model-deprecations-2026-10` (the 2026-10-22 deprecation sweep) must be merged into `dev` before this task starts — every anchor below was verified against `origin/dev` 63442566b + that sweep. Re-run each `grep -c` before editing.

---

## Context

Implements spec §3 Module 5. Computer-use mode is inferred from model-name prefixes, and the translation table only knows the 2.5-preview vocabulary. The live probe (spec §6) showed `gemini-3.8-flash` uses `click/move/type/scroll/hotkey/wait/navigate/go_back/drag_and_drop`, each with an `intent` argument.

---

## Scope

- Add `computer_use: bool = False` to `GoogleGenAIClient`.
- Add `_computer_use_enabled(model)` and replace `_is_computer_use_model(model)` at the five call sites (284, 2113, 2213, 3304, 3414). Keep `_is_computer_use_model` as the legacy-id check it calls.
- Add `_COMPUTER_USE_V3_8_MAP` and `_computer_use_vocabulary(model)`; select the map in the dispatcher (~:1910).
- Extend `_adapt_computer_use_args(native_name, args, vocabulary="legacy")` for v3_8 renames; strip `intent` (log it).
- Unknown action under an active vocabulary → error function-response, never silently skipped.
- `_build_tools("computer_use")` raises when `computer_use` is set but `_computer_use_config` is missing.
- New test file.

**NOT in scope**: ComputerAgent default/wiring (TASK-4587); enumerating actions beyond the probe (spec §8 Q1 — handled by the unknown-action path).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-client-google/src/parrot/clients/google/client.py` | MODIFY | opt-in, vocabularies, arg adapter, raise |
| `packages/ai-parrot-client-google/tests/unit/test_computer_use_vocabulary.py` | CREATE | tests |

---

## Codebase Contract (Anti-Hallucination)

> Use these exact imports and signatures. Verify anything not listed before using it.

### Verified Imports
```python
from parrot.clients.google import GoogleGenAIClient  # verified: clients/google/__init__.py
```

### Existing Signatures to Use
```python
# packages/ai-parrot-client-google/src/parrot/clients/google/client.py
class GoogleGenAIClient(AbstractClient, GoogleGeneration, GoogleAnalysis)   # line 103
def _requires_thinking(model: str) -> bool  # staticmethod; uses _is_computer_use_model   # line 271/284
_COMPUTER_USE_PREDEFINED_MAP = {...13 legacy names → computer_*}             # line 254
def _is_computer_use_model(model: str) -> bool  # staticmethod              # line 374
#   startswith("gemini-2.5-computer-use") or startswith("gemini-3-flash-preview")
config = getattr(self, "_computer_use_config", None)  # in _build_tools     # line 1281
def _adapt_computer_use_args(native_name: str, args: Dict[str, Any]) -> Dict[str, Any]  # staticmethod  # line 1802
# dispatcher (~1910): mapped = self._COMPUTER_USE_PREDEFINED_MAP.get(tool_name);
#   if mapped is not None and self._has_registered_tool(mapped): parameters = self._adapt_computer_use_args(...)
# other call sites of _is_computer_use_model: 2113, 2213, 3304, 3414
# toolkit targets: click_at(x,y) hover_at(x,y) type_text(text,press_enter)[TASK-4585] scroll_at(x,y,direction,magnitude=800)
#   key_combination(keys: str csv) wait(seconds=5) navigate(url) go_back() drag_and_drop(x,y,destination_x,destination_y)
```

### Does NOT Exist
- ~~`GoogleGenAIClient.computer_use`~~ / ~~`_computer_use_enabled`~~ / ~~`_COMPUTER_USE_V3_8_MAP`~~ / ~~`_computer_use_vocabulary`~~ — created by this task
- ~~v3_8 actions `click_at`, `type_text_at`, `key_combination`, `hover_at`, `wait_5_seconds`~~ — those are legacy names; 3.8 never emits them (probe)

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-client-google/src/parrot/clients/google/client.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-client-google/tests/unit/test_computer_use_vocabulary.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-client-google/src/parrot/clients/google/client.py#GoogleGenAIClient",
    "sym:packages/ai-parrot-client-google/src/parrot/clients/google/client.py#GoogleGenAIClient._is_computer_use_model",
    "sym:packages/ai-parrot-client-google/src/parrot/clients/google/client.py#GoogleGenAIClient._adapt_computer_use_args",
    "sym:packages/ai-parrot-client-google/src/parrot/clients/google/client.py#GoogleGenAIClient._requires_thinking"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Async throughout; `self.logger` (never `print`); Pydantic v2; aiohttp only.
- Hard cut — no deprecation shims (no external consumers).
- `_requires_thinking` is a staticmethod: keep it model-only (legacy check); the opt-in affects tool building and dispatch, not thinking — document this.
- Probe evidence (spec §6) is the source of truth for the v3_8 table and argument names.

---

## Implementation Blueprint

### Steps (in order)
1. Add `computer_use` and `_computer_use_enabled` — *why*: plain 3.8-flash calls must not get the ComputerUse tool (AC-5).
2. Replace the instance-level call sites (2113, 2213, 3304, 3414) — *why*: those decide tool building and dispatch.
3. Add the v3_8 table + vocabulary selection — *why*: probe showed a different vocabulary.
4. Extend the arg adapter (renames, strip intent) — *why*: toolkit signatures differ (spec §7 gotchas).
5. Unknown-action error response — *why*: vocabulary may be incomplete (§8 Q1).
6. Raise on missing config — *why*: resolved decision.

### `packages/ai-parrot-client-google/src/parrot/clients/google/client.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    _COMPUTER_USE_PREDEFINED_MAP = {' client.py) — AFTER the closing brace of that dict (:254):
    # gemini-3.8-flash computer-use vocabulary (live probe 2026-10-22, FEAT-719 spec §6). Every call
    # also carries an ``intent`` string, stripped by _adapt_computer_use_args.
    _COMPUTER_USE_V3_8_MAP = {
        "click": "computer_click_at",
        "move": "computer_hover_at",
        "type": "computer_type_text",
        "scroll": "computer_scroll_at",
        "hotkey": "computer_key_combination",
        "wait": "computer_wait",
        "navigate": "computer_navigate",
        "go_back": "computer_go_back",
        "drag_and_drop": "computer_drag_and_drop",
    }

    computer_use: bool = False

    def _computer_use_enabled(self, model: str) -> bool:
        """True when computer use is explicitly enabled or ``model`` is a legacy computer-use id."""
        return bool(self.computer_use) or self._is_computer_use_model(model)

    def _computer_use_vocabulary(self, model: str) -> str:
        """``"legacy"`` for the 2.5-preview / 3-flash-preview ids, else ``"v3_8"``."""
        return "legacy" if self._is_computer_use_model(model) else "v3_8"
```
```python
# occurrences: 1 (verified: grep -c '    def _adapt_computer_use_args(native_name: str, args: Dict[str, Any]) -> Dict[str, Any]:' client.py) — :1802
# CHANGE signature to: def _adapt_computer_use_args(native_name: str, args: Dict[str, Any], vocabulary: str = "legacy") -> Dict[str, Any]:
# ADD at the top of the body:
        if vocabulary == "v3_8":
            args = dict(args)
            args.pop("intent", None)
            # FILL IN: scroll: magnitude_in_pixels → magnitude; drag_and_drop: start_x/start_y/end_x/end_y →
            #          x/y/destination_x/destination_y; hotkey: keys list → csv (reuse key_combination fixup) — bounded by spec §7
            return args
```
```python
# occurrences: 1 (verified: grep -c '            config = getattr(self, "_computer_use_config", None)' client.py) — :1281
            if config is None and self.computer_use:
                raise ValueError("computer_use is enabled but _computer_use_config is not set (configure ComputerAgent first).")
```
```python
# FILL IN: dispatcher (~:1910): pick the map by self._computer_use_vocabulary(model); log the stripped intent at debug;
#          when the active vocabulary is v3_8 and tool_name is not in it but looks like a computer action, return an
#          error function-response naming the action — bounded by spec AC-6 (never silent)
# FILL IN: replace self._is_computer_use_model(model) with self._computer_use_enabled(model) at 2113, 2213, 3304, 3414
```

### FILL IN checklist
- [ ] arg renames for scroll / drag_and_drop / hotkey — bounded by spec §7 gotchas and §6 probe evidence
- [ ] dispatcher vocabulary selection + unknown-action error response — bounded by AC-6
- [ ] how `model` reaches the dispatcher (thread it or read self.model) — bounded by existing call structure

---

## Acceptance Criteria

- [ ] `computer_use=False` + `gemini-3.8-flash` → no ComputerUse tool
- [ ] each probed v3_8 action maps to the right toolkit tool and args; `intent` never reaches the toolkit
- [ ] unmapped action → error function-response
- [ ] `computer_use=True` without `_computer_use_config` raises
- [ ] legacy ids keep the legacy map

---

## Validation Commands

- `pytest packages/ai-parrot-client-google/tests/unit/test_computer_use_vocabulary.py -q`
- `pytest packages/ai-parrot/tests/test_google_client.py -q`

---

## Test Specification

```python
from parrot.clients.google import GoogleGenAIClient


def test_plain_38_flash_not_enabled():
    c = GoogleGenAIClient(api_key="k")
    assert c._computer_use_enabled("gemini-3.8-flash") is False


def test_v38_scroll_args():
    out = GoogleGenAIClient._adapt_computer_use_args(
        "scroll", {"x": 500, "y": 500, "direction": "down", "magnitude_in_pixels": 500, "intent": "i"}, "v3_8")
    assert out == {"x": 500, "y": 500, "direction": "down", "magnitude": 500}


def test_opt_in_without_config_raises():
    c = GoogleGenAIClient(api_key="k"); c.computer_use = True
    # FILL IN: call _build_tools("computer_use") and assert ValueError
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug model-deprecation-followups --feature-id FEAT-719`)
2. **Read the spec** at `sdd/specs/model-deprecation-followups.spec.md` for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/model-deprecation-followups.json`
4. **Verify the Codebase Contract** — re-run every `grep -c` in the blueprint; a changed count means the
   anchor moved (re-locate it), a `0` means drift (stop and report)
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`; never change a fixed
   signature or path
7. **Verify** — run the Validation Commands with `PYTHONPATH` pointing at the worktree's `packages/*/src`
8. **Commit the code** — stage only the files listed above
9. **Close** with `scripts/sdd/close_task.sh TASK-4586 model-deprecation-followups verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none
