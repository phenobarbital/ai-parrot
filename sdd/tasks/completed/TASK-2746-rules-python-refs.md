# TASK-2746: Rule file `python.yaml` (refs + imports only) and `calls`/`extends` enrichment

**Feature**: FEAT-498 — ast-grep Structural Plane for wikitoolkit
**Spec**: `sdd/specs/ast-grep-for-wikitoolkit.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2741
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 (Python file). Resolved: Python symbols come from `ast`
(TASK-2741). This rule file therefore has **no `symbols:` section** — only
`refs` (`calls`, `extends`) and `imports` — and TASK-2741's merge step picks
up the refs when ast-grep is installed.

---

## Scope

- Create `languages/rules/python.yaml`: `language: python`, `summary: none`,
  `symbols: []`, refs: `calls` (`kind: call`, `not: {inside: {kind: decorator}}`,
  `target: {field: function}`, `scope: {ancestor: [function_definition, class_definition]}`),
  `extends` (`class_definition` with `has: {field: superclasses}`,
  `target: {field: superclasses, each: identifier}`), imports:
  `import_statement`, `import_from_statement` (normalised to the same dotted
  specs the `ast` walker emits — absolute only).
- `astgrep.extract()` must accept an empty `symbols` list (returns
  `StructuralOutline(symbols=[], refs=[…], imports=[…])`).
- Tests: refs for the §4.4 Python sample (`helper` call inside `UserService`
  → `src_qualname="UserService.get_user"`; `extends BaseService`), decorator
  calls excluded, `imports` identical to `ast` output, no symbols from rules.

**NOT in scope**: Python symbol extraction (done); renderer.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/languages/rules/python.yaml` | CREATE | refs + imports |
| `tests/knowledge/wiki/languages/fixtures/structural/sample.py` | CREATE | §4.4 sample (prototype :7-20) + call sites |
| `tests/knowledge/wiki/languages/test_rules_python.py` | CREATE | Tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.languages import astgrep                    # TASK-2739
from parrot.knowledge.wiki.languages.python import PythonScanner       # python.py:30
```

### Existing Signatures to Use
```python
# Verified kinds (design §1.2): call (field: function), class_definition (field: superclasses), decorator, function_definition,
# import_statement, import_from_statement
# PythonScanner import contract (python.py:63-66): ast.Import → alias.name ; ast.ImportFrom with node.module and node.level == 0 → node.module (relative imports dropped)
# TASK-2741 merge point: PythonScanner.outline() merges ONLY `refs` from astgrep.extract(source, "python", rel_path)
# SymbolRef(src_qualname, rel, target_text, line)  — symbols.py (TASK-2738)
```

### Does NOT Exist
- ~~`symbols:` rules for Python~~ — must be empty; a test asserts it.
- ~~ast-grep replacing `ast` byte offsets~~ — not done; offsets stay `ast`-derived.
- ~~relative-import specs in `imports`~~ — the walker drops `level > 0`; the rule normaliser must too.

---

## Implementation Notes

- `src_qualname` for a ref comes from the nearest enclosing
  `function_definition`/`class_definition` names joined with `.` (e.g.
  `UserService.get_user`); module-level calls use `src_qualname=""` and are
  kept (they matter for `blast_radius` of module-level code).
- `target_text` is the raw `function` field text (`helper`, `self.repo.get`,
  `obj.helper`) — resolution happens in TASK-2748.

---

## Acceptance Criteria

- [ ] `pytest tests/knowledge/wiki/languages/test_rules_python.py tests/knowledge/wiki/languages/test_python_plugin.py -v` passes in both modes.
- [ ] With ast-grep: `refs` include `("UserService.get_user"|"", "calls", "helper")`-style entries and `("UserService", "extends", "BaseService")`; a `@decorator(...)` call is **not** a ref.
- [ ] Symbols unchanged vs. `force_no_astgrep`; `imports` identical.
- [ ] `python.yaml` has `symbols: []` (schema test); loads without WARNING.

---

## Test Specification

```python
@requires_astgrep
def test_python_refs_only():
    src = (FIXTURES / "sample.py").read_text() + "\n@helper(1)\ndef g():\n    return helper(2)\n"
    out = PythonScanner().outline(src, "sample.py")
    calls = [(r.src_qualname, r.target_text, r.line) for r in out.refs if r.rel == "calls"]
    assert ("g", "helper", src.count("\n") ) in calls or any(c[0] == "g" and c[1] == "helper" for c in calls)
    assert not any(c[1] == "helper" and c[0] == "" and c[2] == src.splitlines().index("@helper(1)") + 1 for c in calls)
    assert ("UserService", "BaseService") in {(r.src_qualname, r.target_text) for r in out.refs if r.rel == "extends"}
```

---

## Agent Instructions

1. Read spec §3 Module 4 (python.yaml) and TASK-2741's merge step. 2. Confirm
TASK-2741 completed. 3. Index → `in-progress`. 4. Rule file → fixture → tests.
5. Both modes green. 6. Move to `completed/`. 7. Index → `done`. 8. Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-09-02
**Notes**: `python.yaml` has `symbols: []` (schema-tested) — Python
symbols stay exclusively `ast`-derived (TASK-2741); only `refs`/`imports`
extraction rules exist. Verified live against the §4.4 sample + a
decorator/call fixture: `calls` refs carry the correct dotted
`src_qualname` (`"UserService.get_user"` for a call inside a method,
`"g"` for a top-level decorated function, and the decorator's own call
site `@helper(1)` is correctly excluded via `not: {inside: {kind:
decorator}}`); `extends` correctly isolates the superclass list
(`argument_list` matched directly, not the whole `class_definition`, so
`each: identifier` never picks up the class's own name). `PythonScanner`
merges only `refs` — symbols and the rendered outline are byte-identical
with and without the seam (verified via `model_dump()` equality, not
just field spot-checks).
`pytest tests/knowledge/wiki/languages/test_rules_python.py
tests/knowledge/wiki/languages/test_python_plugin.py -v` → 19 passed.
Full `tests/knowledge/wiki/languages`: 265 passed. Full
`tests/knowledge/wiki`: 1322 passed (same single pre-existing unrelated
failure). `ruff check` / `mypy --ignore-missing-imports` clean.
**Deviations from spec**: One additive `astgrep.py` (TASK-2739)
extension, verified necessary live, not changing any existing behavior
(265/265 languages tests pass): `RefSpec.scope` gained a string form
(alongside the existing `{"ancestor": [...]}` dict form) naming an
:data:`EXTRACTORS` entry, plus a new extractor `python_call_scope`. The
existing ancestor-dict scope resolution stops at the *nearest* matching
ancestor's own bare `name` field — for a Python call inside a method,
that is just `"get_user"`, not the class-qualified `"UserService.
get_user"` this task's own acceptance criteria and TASK-2741's
`ast`-derived symbol qualnames require; `python_call_scope` walks
outward once, joining an enclosing `function_definition`'s name with its
enclosing `class_definition`'s name when both are present. This is the
same "generic engine falls short of one language's qualname shape"
pattern as TASK-2743's `php_qualified_container`/`qualname_joiner` and
TASK-2745's `perl_sub_parent` — extending the schema, not the language
files' scope.
