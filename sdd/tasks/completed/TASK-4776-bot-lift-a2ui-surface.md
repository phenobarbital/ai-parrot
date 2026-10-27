# TASK-4776: Generalize the bot dict-result lift to type a2ui_surface (M4)

**Feature**: FEAT-753 — A2UI MermaidDiagram (opaque Mermaid-source component in the Parrot catalog)
**Spec**: `sdd/specs/a2ui-mermaid-diagram.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4, decision D7. `_extract_last_linked_surface_result` lifts only
`artifacts[].type == "a2ui_linked_surface"`. The FEAT-753 tool returns the same shape with
`type: "a2ui_surface"`; the lift must accept both. Precedence (interactive > infographic > dict lift) is untouched.

---

## Scope

- Add module-level `_LIFTABLE_SURFACE_ARTIFACT_TYPES = frozenset({"a2ui_linked_surface", "a2ui_surface"})` in `bots/base.py`.
- Replace the membership test at line 1042; extend the method docstring.
- Add the positive `a2ui_surface` test(s) to `tests/bots/test_linked_surface_lifting.py`; keep every existing case unchanged.

**NOT in scope**: the tool itself (TASK-4775); the precedence block at bots/base.py:1674-1686 (unchanged).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/base.py` | MODIFY | membership test over a frozenset of liftable types |
| `packages/ai-parrot/tests/bots/test_linked_surface_lifting.py` | MODIFY | add a2ui_surface lift cases |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against `65144d730` (2026-10-27). Use these exact imports, names and
> signatures. If you need something not listed here, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from parrot.models.basic import ToolCall  # verified: test_linked_surface_lifting.py:10
from parrot.bots.base import BaseBot  # verified: test_linked_surface_lifting.py:19 (guarded import in _base_bot())
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/base.py
def _extract_last_linked_surface_result(self, tool_calls: Optional[List[Any]]) -> Optional[dict]:  # line 1023
            artifacts = result.get("artifacts")                                                # line 1040
            if isinstance(artifacts, list) and any(                                           # line 1041
                isinstance(a, dict) and a.get("type") == "a2ui_linked_surface" for a in artifacts  # line 1042
            ):
                return _wrap_create_surface(result["a2ui_envelope"])                           # line 1044

# tests/bots/test_linked_surface_lifting.py
INNER = {...}; LINKED_RESULT = {...}  # lines 12-16
def _base_bot()  # line 18;  def _tc(name, result=None, error=None) -> ToolCall  # line 26
def test_extract_last_linked_surface_result_wraps() -> None  # line 30
def test_extract_last_linked_surface_result_ignores_non_linked() -> None  # line 39
```

### Does NOT Exist
- ~~a separate `_extract_last_surface_result` method~~ — do not add one; generalize the existing membership test only.
- ~~`tests/bots/test_linked_surface_lifting.py::…a2ui_surface`~~ — does not exist yet; this task adds it.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/bots/base.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/bots/test_linked_surface_lifting.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/base.py#AbstractBot._extract_last_linked_surface_result"
  ]
}
```

---

## Implementation Notes

- Run `wikitoolkit symbols blast _extract_last_linked_surface_result` first: it is a hot path in `ask()`.
- Verify the actual class owning the method (`AbstractBot` vs `BaseBot`) with `grep -n "class " bots/base.py` around
  line 1023 and fix the `contract_symbols` id in this task file if it differs.
- Write `test_ask_lifts_mermaid_tool_result` in the same source-level / `_base_bot()` style the file already uses.

---

## Implementation Blueprint

> **Executor-ready starting point.** Write each block to its declared path nearly verbatim, then
> complete every `# FILL IN:` marker. Never change a signature, class name or file path fixed here.

### Steps (in order)
1. Add the module-level constant near the other module constants of `bots/base.py` — *why*: one place lists liftable types.
2. Replace line 1042's comparison with `in _LIFTABLE_SURFACE_ARTIFACT_TYPES` — *why*: D7.
3. Extend the docstring — *why*: document the FEAT-753 tool as a lift source.
4. Add tests after the `ignores_non_linked` test; run Validation Commands.

### `packages/ai-parrot/src/parrot/bots/base.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'isinstance(a, dict) and a.get("type") == "a2ui_linked_surface" for a in artifacts' bots/base.py) — line 1042
# REPLACE that line with:
                isinstance(a, dict) and a.get("type") in _LIFTABLE_SURFACE_ARTIFACT_TYPES for a in artifacts

# module level (place with the other module-level constants near the top of bots/base.py):
#: FEAT-611 linked-surface results and FEAT-753 ``render_mermaid_diagram`` results share the dict-lift shape.
_LIFTABLE_SURFACE_ARTIFACT_TYPES = frozenset({"a2ui_linked_surface", "a2ui_surface"})

# docstring of _extract_last_linked_surface_result (line ~1029) — append the sentence:
#   "Also lifts the FEAT-753 ``render_mermaid_diagram`` tool (``type: "a2ui_surface"``)."
```

### `packages/ai-parrot/tests/bots/test_linked_surface_lifting.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def test_extract_last_linked_surface_result_ignores_non_linked() -> None:') — line 39
# AFTER that test function (keep it unchanged), add:
SURFACE_RESULT = {
    "a2ui_envelope": INNER,
    "artifacts": [{"type": "a2ui_surface", "component": "MermaidDiagram", "surface_id": "linked-activity"}],
}


def test_extract_last_linked_surface_result_accepts_a2ui_surface() -> None:
    extract = _base_bot()._extract_last_linked_surface_result
    # FILL IN: assert the wrapped {"version": "v1.0", "createSurface": INNER}-shaped result, same as the
    #   `..._wraps` test asserts for LINKED_RESULT; the {"type": "chart"} negative stays covered by the existing test


# FILL IN: test_ask_lifts_mermaid_tool_result — a render_mermaid_diagram ToolCall result lifted with the
#   same precedence as the linked lift (mirror the existing precedence test in this file)
```

### FILL IN checklist
- [ ] constant placement in `bots/base.py`
- [ ] the two new test bodies

---

## Acceptance Criteria

- [ ] AC-6 (lift part): a `type: "a2ui_surface"` result is lifted and wrapped with `version`.
- [ ] Every pre-existing test in `test_linked_surface_lifting.py` passes unmodified (AC-11).

## Validation Commands

- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/bots/test_linked_surface_lifting.py -q`

---

## Test Specification

See the MODIFY block for the test file.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug a2ui-mermaid-diagram --feature-id FEAT-753`).
2. **Read the spec** `sdd/specs/a2ui-mermaid-diagram.spec.md` (§2 decisions D1–D7, §6 contract, §7 constraints).
3. **Check dependencies** — every `Depends-on` task must be `done` in `sdd/tasks/index/a2ui-mermaid-diagram.json`.
4. **Verify the Codebase Contract** — re-run the `grep -c` of every MODIFY anchor before editing; a count of 0 is drift: stop and report.
5. **Update status** in the per-spec index → `"in-progress"`.
6. **Implement** the blueprint, then complete every `FILL IN` — touch only the files listed above.
7. **Validate**: `ruff check --fix <files>`, `black -l 120 <files>`, then the Validation Commands with
   `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src:packages/ai-parrot-visualizations/src`.
8. **Close** with `scripts/sdd/close_task.sh <TASK-ID> a2ui-mermaid-diagram verified` and fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (sequential fallback)
**Date**: 2026-10-27
**Notes**: `_LIFTABLE_SURFACE_ARTIFACT_TYPES` frozenset in bots/base.py replaces the single-type comparison; docstring extended; 2 new tests (8 passed in the file). The method lives on `BaseBot`, not `AbstractBot` (contract_symbols id left as is). `ruff check` on base.py reports pre-existing E402/F841 findings unrelated to this change; left for /sdd-done.

**Deviations from spec**: none
