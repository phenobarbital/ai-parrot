# TASK-4585: ComputerInteractionToolkit.type_text (focused element, no coordinates)

**Feature**: FEAT-719 — Model Deprecation Follow-ups (Veo → Omni, Computer Use 3.8, gpt-transcribe)
**Spec**: `sdd/specs/model-deprecation-followups.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

> **Prerequisite**: branch `fix/model-deprecations-2026-10` (the 2026-10-22 deprecation sweep) must be merged into `dev` before this task starts — every anchor below was verified against `origin/dev` 63442566b + that sweep. Re-run each `grep -c` before editing.

---

## Context

Implements the toolkit half of spec §3 Module 6. The live probe showed `gemini-3.8-flash` emits `type {text, press_enter, intent}` with NO coordinates; the toolkit only has `type_text_at(x, y, ...)`. TASK-4586 maps the v3_8 `type` action to the new `computer_type_text` tool.

---

## Scope

- Add `type_text(text, press_enter=False)` to the Playwright backend (type into the focused element; no click).
- Add `type_text(text, press_enter=False)` to `ComputerInteractionToolkit` (exposed as `computer_type_text`).
- Tests.

**NOT in scope**: client vocabulary mapping (TASK-4586); ComputerAgent (TASK-4587).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/computer/backend.py` | MODIFY | backend type_text |
| `packages/ai-parrot-tools/src/parrot_tools/computer/toolkit.py` | MODIFY | toolkit type_text |
| `packages/ai-parrot-tools/tests/computer/test_backend.py` | MODIFY | tests |

---

## Codebase Contract (Anti-Hallucination)

> Use these exact imports and signatures. Verify anything not listed before using it.

### Verified Imports
```python
from parrot_tools.computer.toolkit import ComputerInteractionToolkit  # verified: toolkit.py:24
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/computer/backend.py
async def type_text_at(self, x: int, y: int, text: str, press_enter: bool = False,
                       clear_before_typing: bool = True) -> EnvState            # line 291
#   body: await self._page.mouse.click(x, y); keyboard.press("ControlOrMeta+a") if clear; keyboard.type(text);
#         if press_enter: keyboard.press("Enter"); wait_for_load_state("domcontentloaded", timeout=5_000) (swallowed); return await self.current_state()
# packages/ai-parrot-tools/src/parrot_tools/computer/toolkit.py
async def type_text_at(self, x, y, text, press_enter=False, clear_before_typing=True) -> dict   # line 149
#   body: state = await self._backend.type_text_at(self._denormalize_x(x), ...); return self._state_to_dict(state)
```

### Does NOT Exist
- ~~`ComputerInteractionToolkit.type_text`~~ / ~~backend `type_text`~~ — created by this task

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/computer/backend.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/computer/toolkit.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-tools/tests/computer/test_backend.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/computer/toolkit.py#ComputerInteractionToolkit",
    "sym:packages/ai-parrot-tools/src/parrot_tools/computer/toolkit.py#ComputerInteractionToolkit.type_text_at"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Async throughout; `self.logger` (never `print`); Pydantic v2; aiohttp only.
- Hard cut — no deprecation shims (no external consumers).
- Toolkit method needs a docstring (it is the LLM-facing description).

---

## Implementation Blueprint

### Steps (in order)
1. Backend: copy `type_text_at` minus the click and the clear — *why*: v3_8 `type` targets the focused element.
2. Toolkit: thin wrapper returning `_state_to_dict` — *why*: same shape as every other action.
3. Tests with the existing mocked Playwright page fixtures.

### `packages/ai-parrot-tools/src/parrot_tools/computer/backend.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    async def type_text_at(' backend.py) — insert ABOVE it (:291)
    async def type_text(self, text: str, press_enter: bool = False) -> EnvState:
        """Type text into the currently focused element (no click, no clearing)."""
        await self._page.keyboard.type(text)
        if press_enter:
            await self._page.keyboard.press("Enter")
            try:
                await self._page.wait_for_load_state("domcontentloaded", timeout=5_000)
            except Exception:
                pass
        return await self.current_state()
```
### `packages/ai-parrot-tools/src/parrot_tools/computer/toolkit.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    async def type_text_at(' toolkit.py) — insert ABOVE it (:149)
    async def type_text(self, text: str, press_enter: bool = False) -> dict:
        """Type text into the currently focused element without clicking first.

        Args:
            text: Text to type.
            press_enter: If True, presses Enter after typing.

        Returns:
            Dict with ``url`` and ``screenshot_taken``.
        """
        state = await self._backend.type_text(text, press_enter=press_enter)
        return self._state_to_dict(state)
```

### FILL IN checklist
- [ ] tests mirroring the existing `type_text_at` tests — bounded by spec AC (toolkit/backend type without coordinates)

---

## Acceptance Criteria

- [ ] backend `type_text` never calls `mouse.click`
- [ ] toolkit exposes `computer_type_text`
- [ ] existing tests green

---

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/computer/test_backend.py -q`

---

## Test Specification

```python
async def test_type_text_focused(backend_with_mock_page):
    await backend_with_mock_page.type_text("hello", press_enter=True)
    backend_with_mock_page._page.mouse.click.assert_not_called()
    backend_with_mock_page._page.keyboard.type.assert_awaited_with("hello")
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
9. **Close** with `scripts/sdd/close_task.sh TASK-4585 model-deprecation-followups verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

Implemented by an sdd-coder seat, merged by sdd-worker orchestrator. Task tests green (verified in sub-worktree); fidelity ok. Engine task-tier validation was unavailable for TASK-4581 (attempt had no execution_id), tests re-run manually: 39 passed.
