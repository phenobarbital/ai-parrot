# TASK-3823: Module-local JS/TS functions, `js_call_scope`, and per-rule `languages:` filter

**Feature**: FEAT-609 — Honest structural tier, Svelte component symbols, module-local JS functions, and federated symbol queries in wikitoolkit
**Spec**: `sdd/specs/wikitoolkit-structural-coverage.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §1 defect 3 / §3 Module 4.

1. The only `lexical_declaration` rule in `rules/typescript.yaml` requires `export`
   (`typescript.yaml:67`). So `const onSave = () => …`, the normal way to write a Svelte
   handler, is invisible. There are 643 such declarations in `navigator-svelte/src/**/*.svelte`.
2. The `calls` ref scope is a plain ancestor-kind list (`typescript.yaml:77`), so a call inside
   an arrow has no owner, and the resolver drops it.
3. The TS-only kinds (`interface`, `type`, `extends`, `implements`) are evaluated under the
   `javascript` alias and log four `could not be evaluated` warnings on every build
   (`astgrep.py:863`).

Everything here is inside the structural seam and never reaches `## API outline`, which is the
parity contract (spec G5).

---

## Scope

- **`languages:` filter.** Add an optional `languages: list[str] | None = None` to `SymbolSpec`
  and `RefSpec`. In `extract()`, skip a spec whose `languages` is set and does not contain the
  `lang` being extracted, *before* `_find_all_isolated`.
- **Tag the TS-only rules.** In `typescript.yaml`, add `languages: [typescript, tsx]` to the
  `interface` and `type` symbol rules and to the `extends` and `implements` ref rules.
- **Arrow and function-expression rule.** Add a `function` symbol rule for top-level,
  non-exported `const|let NAME = <arrow_function | function_expression>`. The YAML below was
  verified with ast-grep-py 0.45.3 on 2026-09-28.
- **`js_call_scope` extractor.** Replace the `calls` ref's `scope: { ancestor: [...] }` with
  `scope: js_call_scope`, a new `EXTRACTORS` entry, following the `python_call_scope`
  precedent (`astgrep.py:440`, registered at `:552`). The body below was prototyped and
  verified.
- **Keep the outline unchanged.** `render._render_javascript` skips records whose
  `node_kind == "variable_declarator"` (spec G5).
- Write tests.

**Deviation from spec (recorded):** spec M4 says "`is_async` is read from the function node".
`async` is an anonymous grammar token: `kind: async` raises "Invalid Kind" (verified), and
`_resolve_bool_spec` (`astgrep.py:784-799`) only supports `inside`/`has` by kind. The existing
TS `function` rule does not set `async` either. So the new rule leaves `is_async` False, for
consistency. Record this in the Completion Note.

**NOT in scope**: the Svelte component symbol and the re-attribution of orphan refs
(TASK-3826); any change to `const` rule semantics.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/languages/astgrep.py` | MODIFY | `languages` field on both specs, the skip in `extract`, `js_call_scope` + registration |
| `packages/ai-parrot/src/parrot/knowledge/wiki/languages/rules/typescript.yaml` | MODIFY | new `function` rule, `scope: js_call_scope`, `languages:` tags |
| `packages/ai-parrot/src/parrot/knowledge/wiki/languages/render.py` | MODIFY | skip `node_kind == "variable_declarator"` |
| `tests/knowledge/wiki/languages/test_rules_typescript_local_functions.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.languages import astgrep               # module under test
from parrot.knowledge.wiki.languages.javascript import JavaScriptScanner
from parrot.knowledge.wiki.symbols import SymbolKind
```

### Existing Signatures to Use
```python
# astgrep.py:440
def python_call_scope(node: SgNode) -> str:           # precedent for a named scope extractor
# astgrep.py:539-554
EXTRACTORS: dict[str, Callable[[SgNode], str]] = {
    ...
    "python_call_scope": python_call_scope,            # :552
    "perl_sub_parent": perl_sub_parent,
}
# astgrep.py:562  SymbolSpec(BaseModel): id, rule, name, signature, doc, parent, exported,
#                 is_async (alias "async"), depth, qualname_joiner; model_config populate_by_name
# astgrep.py:620  RefSpec(BaseModel): rel, rule, target, scope
# astgrep.py:784  def _resolve_bool_spec(node, spec) -> bool   # "always"|"never"|{"inside": k}|{"has": k}
# astgrep.py:863  logger.warning("ast-grep rule %r for language=%s could not be evaluated", rule_id, language)
# astgrep.py:867  def extract(src: str, lang: str, rel_path: str, *, max_depth: int = 2) -> StructuralOutline | None:
# astgrep.py:892      for spec in ruleset.symbols:          occurrences: 1
# astgrep.py:899      for ref_spec in ruleset.refs:         occurrences: 1
#                     scope str -> EXTRACTORS.get(ref_spec.scope)(node)   (astgrep.py:901-903)
```
```yaml
# rules/typescript.yaml:14   aliases: [tsx, javascript]
# rules/typescript.yaml:67   rule: { kind: lexical_declaration, inside: { kind: export_statement } }   (the `const` rule)
# rules/typescript.yaml:77   scope: { ancestor: [function_declaration, method_definition, class_declaration] }  (the `calls` ref)
```
```python
# render.py:112-125
_JS_RENDERED_KINDS = frozenset({CLASS, FUNCTION, INTERFACE, TYPE, CONST})
def _render_javascript(symbols: list[SymbolRecord]) -> list[str]:
    for sym in symbols:
        if sym.kind not in _JS_RENDERED_KINDS:
            continue
```

### Does NOT Exist
- ~~An ast-grep `async` kind in the typescript grammar~~: an anonymous token, rejected as an
  invalid kind (verified).
- ~~`SymbolSpec.languages` / `RefSpec.languages`~~: created here.
- ~~`js_call_scope`~~: created here.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/languages/astgrep.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/languages/rules/typescript.yaml", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/languages/render.py", "action": "MODIFY"},
    {"path": "tests/knowledge/wiki/languages/test_rules_typescript_local_functions.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/languages/astgrep.py#python_call_scope",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/languages/astgrep.py#SymbolSpec",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/languages/astgrep.py#RefSpec",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/languages/astgrep.py#extract",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/languages/render.py#_render_javascript"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Parity (G5):** `tests/knowledge/wiki/languages/test_outline_parity.py` must pass
  **unmodified**. The render skip is what guarantees it.
- A `variable_declarator` has a `name` field, so `name: { field: name }` works for the new rule.
- The `extends`/`implements` refs use `target: { each: … }`, and their `rule_id` passed to
  `_find_all_isolated` is `ref_spec.rel`. The skip must happen before either call.

---

## Implementation Blueprint

### Steps (in order)
1. Add the `languages` fields and the skip in `extract`. *Why*: G6, with no warnings under the
   `javascript` alias.
2. Add `js_call_scope` and register it. *Why*: a bare ancestor kind cannot name an arrow (see
   Context).
3. Edit `typescript.yaml`. *Why*: capture the handlers and scope their calls.
4. Add the render skip. *Why*: the outline must not change.
5. Write the tests, run the parity test, and mutation-check.

### `packages/ai-parrot/src/parrot/knowledge/wiki/languages/astgrep.py` (MODIFY) — spec fields
```python
# occurrences: 1 (verified: grep -c '    qualname_joiner: str | None = None' astgrep.py)
# AFTER — insert below `    qualname_joiner: str | None = None` (SymbolSpec, verified: astgrep.py:601)
    languages: list[str] | None = None
```
```python
# occurrences: 1 (verified: grep -c '    scope: dict\[str, Any\] | str | None = None' astgrep.py)
# AFTER — insert below `    scope: dict[str, Any] | str | None = None` (RefSpec, verified: astgrep.py:640)
    languages: list[str] | None = None
```
Document both fields in their class docstrings. `None` means every language the RuleSet serves.

### `astgrep.py` (MODIFY) — skip in `extract`
```python
# occurrences: 1 each (verified: grep -c '    for spec in ruleset.symbols:' / '    for ref_spec in ruleset.refs:' astgrep.py)
# AFTER `    for spec in ruleset.symbols:` (astgrep.py:892):
        if spec.languages is not None and lang not in spec.languages:
            continue
# AFTER `    for ref_spec in ruleset.refs:` (astgrep.py:899):
        if ref_spec.languages is not None and lang not in ref_spec.languages:
            continue
```

### `astgrep.py` (MODIFY) — `js_call_scope`
```python
# occurrences: 1 (verified: grep -c '^def python_call_scope(node: SgNode) -> str:' astgrep.py)
# BEFORE — insert above `def python_call_scope(node: SgNode) -> str:` (verified: astgrep.py:440)

_JS_NAMED_SCOPES = ("function_declaration", "method_definition", "class_declaration")
_JS_FUNCTION_VALUES = ("arrow_function", "function_expression")


def js_call_scope(node: SgNode) -> str:
    """``src_qualname`` of a JS/TS call: the nearest named enclosing function.

    Named declarations (function/method/class) yield their ``name`` exactly as the
    former ``scope: {ancestor: [...]}`` did. An arrow/function expression yields the
    identifier of the TOP-LEVEL ``const|let NAME = …`` declaring it (the same
    declarations the FEAT-609 ``function`` rule extracts); any other arrow — an
    inline callback, a nested local — is skipped and the walk continues outward.
    Returns ``""`` for a module-level call (TASK-3826 re-attributes those in
    ``.svelte`` files to the component).
    """
    for ancestor in node.ancestors():
        kind = ancestor.kind()
        if kind in _JS_NAMED_SCOPES:
            name = ancestor.field("name")
            return name.text() if name is not None else ""
        if kind not in _JS_FUNCTION_VALUES:
            continue
        declarator = ancestor.parent()
        if declarator is None or declarator.kind() != "variable_declarator":
            continue
        name = declarator.field("name")
        lexical = declarator.parent()
        container = lexical.parent() if lexical is not None else None
        if (
            name is not None
            and name.kind() == "identifier"
            and lexical is not None
            and lexical.kind() == "lexical_declaration"
            and container is not None
            and container.kind() in ("program", "export_statement")
        ):
            return name.text()
    return ""
```
```python
# occurrences: 1 (verified: grep -c '    "python_call_scope": python_call_scope,' astgrep.py)
# AFTER — insert below `    "python_call_scope": python_call_scope,` (verified: astgrep.py:552)
    "js_call_scope": js_call_scope,
```
**Why**: this is the body prototyped against ast-grep-py 0.45.3 on 2026-09-28. The results:

| Call | Resolved scope |
|---|---|
| `$props` | `""` |
| `persist` | `onSave` |
| `rows.map` | `onSave` |
| `fmt` (inline callback) | `onSave` |
| `blur` | `onBlur` |
| `clear` | `onReset` |
| `twice` (exported arrow) | `helper` |
| `deep` (nested arrow) | `outer` |
| `inm` | `m` (today's behaviour) |

### `rules/typescript.yaml` (MODIFY)
```yaml
# occurrences: 1 (verified: grep -c '    rule: { kind: lexical_declaration, inside: { kind: export_statement } }' typescript.yaml)
# AFTER the whole `const` symbol entry that contains that line (ends with `    depth: 1`, verified: typescript.yaml:66-71)

  # FEAT-609 M4: top-level, NON-exported `const|let NAME = () => …` /
  # `= function () {…}` — the normal shape of a Svelte <script> handler.
  # Exported ones keep their `const` record above (no duplicates): the
  # `inside: program` hop excludes them, since their lexical_declaration's
  # parent is export_statement. Verified against ast-grep-py 0.45.3.
  # node_kind is `variable_declarator`, which render.py skips (G5 parity).
  # No `async:` — `async` is an anonymous token, not a kind (see TASK-3823).
  - id: function
    rule:
      kind: variable_declarator
      has: { field: value, any: [{ kind: arrow_function }, { kind: function_expression }] }
      inside: { kind: lexical_declaration, inside: { kind: program } }
    name: { field: name }
    doc: leading_comment
    exported: never
    depth: 1
```
```yaml
# occurrences: 1 (verified: grep -c '    scope: { ancestor: \[function_declaration, method_definition, class_declaration\] }' typescript.yaml)
# REPLACE that line (the `calls` ref, typescript.yaml:77) with:
    scope: js_call_scope
```
Also add `languages: [typescript, tsx]` to the `interface` and `type` symbol entries and to
the `extends` and `implements` ref entries.
**Why**: YAML field order does not matter to pydantic. Keep the comments explaining why.

### `packages/ai-parrot/src/parrot/knowledge/wiki/languages/render.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        if sym.kind not in _JS_RENDERED_KINDS:' render.py)
# AFTER the `continue` under `        if sym.kind not in _JS_RENDERED_KINDS:` (verified: render.py:121-122)
        if sym.node_kind == "variable_declarator":
            # FEAT-609 M4: module-local arrow/function-expression symbols feed the
            # symbol plane only — the tree-sitter walker never rendered them (G5).
            continue
```

### `tests/knowledge/wiki/languages/test_rules_typescript_local_functions.py` (CREATE)
```python
"""FEAT-609 M4: module-local JS/TS functions, js_call_scope, rule languages filter."""

from __future__ import annotations

import logging

from parrot.knowledge.wiki.languages import astgrep
from parrot.knowledge.wiki.symbols import SymbolKind

from .conftest import requires_astgrep

SRC = (
    "let { rows }: { rows: string[] } = $props()\n"
    "const onSave = async () => { persist(rows); rows.map(r => fmt(r)) }\n"
    "const onBlur = function () { blur() }\n"
    "function onReset() { clear() }\n"
    "export const helper = (x: number) => twice(x)\n"
    "function outer() { const inner = () => deep() }\n"
)


def _extract(lang: str = "typescript"):
    out = astgrep.extract(SRC, lang, "src/lib/x.ts")
    assert out is not None
    return out


@requires_astgrep
def test_arrow_function_symbol() -> None:
    names = {(s.name, s.kind) for s in _extract().symbols}
    assert ("onSave", SymbolKind.FUNCTION) in names
    assert ("onBlur", SymbolKind.FUNCTION) in names


@requires_astgrep
def test_exported_arrow_stays_const() -> None:
    helpers = [s for s in _extract().symbols if s.name == "helper"]
    assert [s.kind for s in helpers] == [SymbolKind.CONST]


@requires_astgrep
def test_nested_arrow_not_a_symbol() -> None:
    assert "inner" not in {s.name for s in _extract().symbols}


@requires_astgrep
def test_call_inside_arrow_scoped() -> None:
    scopes = {r.target_text: r.src_qualname for r in _extract().refs if r.rel == "calls"}
    assert scopes["persist"] == "onSave"
    assert scopes["fmt"] == "onSave"
    assert scopes["deep"] == "outer"
    assert scopes["clear"] == "onReset"


@requires_astgrep
def test_ts_only_rules_skip_javascript(caplog) -> None:
    astgrep._WARNED_RULE_KEYS.clear()
    with caplog.at_level(logging.WARNING):
        astgrep.extract("function f() { g() }\n", "javascript", "a.js")
    assert "could not be evaluated" not in caplog.text


@requires_astgrep
def test_outline_does_not_render_local_functions() -> None:
    # FILL IN: JavaScriptScanner().outline(SRC, "src/lib/x.ts").outline must not mention
    # onSave/onBlur — bounded by G5 (render skip on node_kind == "variable_declarator")
    ...
```
**Why**: `test_ts_only_rules_skip_javascript` clears `_WARNED_RULE_KEYS` (`astgrep.py:71`)
because the warning is emitted once per process. Without the clear, the test would pass
vacuously after any earlier test.

### FILL IN checklist
- [ ] `test_outline_does_not_render_local_functions`. Bound: G5.
- [ ] Docstrings for the new `languages` fields.

---

## Acceptance Criteria

- [ ] `onSave`/`onBlur` become `function` symbols with `node_kind == "variable_declarator"`;
      `helper` stays a single `const`; `inner` is not a symbol.
- [ ] A call inside an arrow gets the arrow's name as `src_qualname`.
- [ ] No `could not be evaluated` warning for `.js` extraction.
- [ ] `test_outline_parity.py` and the existing `test_rules_typescript.py` pass unmodified.
- [ ] Mutation-checked: restoring the old `scope: { ancestor: … }` line turns
      `test_call_inside_arrow_scoped` RED.

---

## Validation Commands

- `pytest tests/knowledge/wiki/languages/test_rules_typescript_local_functions.py -q`
- `pytest tests/knowledge/wiki/languages/test_rules_typescript.py -q`
- `pytest tests/knowledge/wiki/languages/test_outline_parity.py -q`
- `pytest tests/knowledge/wiki/languages/test_render.py -q`

---

## Test Specification

See the CREATE block above.

---

## Agent Instructions

1. **Work in the feature worktree**
   (`python -m scripts.sdd.ensure_worktree --slug wikitoolkit-structural-coverage --feature-id FEAT-609`).
2. Verify the contract, re-run each `grep -c`, then set the task in-progress in the index.
3. Implement, validate, mutation-check, and stage only the listed files.
4. Close with `scripts/sdd/close_task.sh TASK-3823 wikitoolkit-structural-coverage verified`,
   then fill in the Completion Note, including the `is_async` deviation.

---

## Completion Note

*(Agent fills this in when done)*
