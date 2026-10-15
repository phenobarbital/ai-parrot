# TASK-4364: Escape text-selector XPath, honour focused clear_first, strip submit pseudos

**Feature**: FEAT-684 — Scraping Executor Fixes 2
**Spec**: `sdd/specs/scraping-executor-fixes-2.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned
**discovered_from**: issue:28c2e9573ce2

---

## Context

Ledger `issue:28c2e9573ce2` (major): `_resolve_locator`/`_action_click` interpolate text into
`//*[contains(text(), '...')]` unescaped (invalid XPath / injection); `type` with
`selector=None` ignores `clear_first` on every driver; `_action_submit` forwards BS4-only
pseudos to `document.querySelector`. See spec §1.

---

## Scope

- Add `_xpath_literal(value: str) -> str` (private helper, next to `_resolve_locator`).
- `_resolve_locator` text branch → `f"//*[contains(text(), {_xpath_literal(selector)})]"`.
- `_action_click` text branch → `_resolve_locator(selector, "text")`.
- `_action_type`: if `action.selector is None and action.clear_first`, `await driver.evaluate(<IIFE clearing document.activeElement>)` before `type_text`.
- `_action_submit`: strip soup-only pseudos from non-XPath `selector` and from `wait_after_submit`; raise `RuntimeError` when the target selector reduces to empty.
- Tests in `test_executor_action_gaps.py`.

**NOT in scope**: `scraping/tool.py`, `drivers/*.py`, models.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py` | MODIFY | the three fixes |
| `packages/ai-parrot-tools/tests/scraping/test_executor_action_gaps.py` | MODIFY | regression tests |

---

## Codebase Contract (Anti-Hallucination)

See spec §6. Existing test `test_hover_text_selector_builds_xpath` expects
`"//*[contains(text(), 'Menu')]"` — quote-free input must keep that exact form.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-tools/tests/scraping/test_executor_action_gaps.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py#_resolve_locator",
    "sym:packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py#_action_submit",
    "sym:packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py#_action_type",
    "sym:packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py#_action_click"
  ]
}
```

---

## Implementation Notes

- XPath 1.0 has no escape syntax: use `'v'` if no `'`, else `"v"` if no `"`, else
  `concat('a', "'", 'b', ...)`.
- The `evaluate` IIFE must not start with a newline (Selenium prefixes `return `).
- XPath detection in submit mirrors its JS: leading `/` or `./`.

---

## Acceptance Criteria

- [ ] Text selectors containing `'`, `"`, or both yield valid XPath literals.
- [ ] `type(selector=None, clear_first=True)` clears the focused element via `driver.evaluate`.
- [ ] `submit` strips `:contains`/`:-soup-contains`/`:has` from CSS selectors; XPath untouched.
- [ ] All `tests/scraping/test_executor*.py` pass; `ruff check` clean on both files.

---

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/scraping/test_executor_action_gaps.py -q`
- `pytest packages/ai-parrot-tools/tests/scraping/test_executor.py -q`
- `pytest packages/ai-parrot-tools/tests/scraping/test_executor_driver_parity.py -q`

---

## Test Specification

```python
def test_xpath_literal_quotes():
    assert _xpath_literal("Menu") == "'Menu'"
    assert _xpath_literal("Don't") == '"Don\'t"'
    assert _xpath_literal("a'b\"c") == "concat('a', \"'\", 'b\"c')"

async def test_type_focused_clear_first_evaluates_before_typing(spy_driver): ...
async def test_submit_strips_soup_pseudos(spy_driver): ...
```

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug scraping-executor-fixes-2 --feature-id FEAT-684`).
2. Implement, run the Validation Commands with `PYTHONPATH=packages/ai-parrot-tools/src`.
3. Commit only the two listed files; close with `scripts/sdd/close_task.sh TASK-4364 scraping-executor-fixes-2 verified`.

---

## Completion Note

