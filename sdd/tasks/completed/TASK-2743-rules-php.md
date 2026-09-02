# TASK-2743: Rule file `php.yaml` + parity

**Feature**: FEAT-498 — ast-grep Structural Plane for wikitoolkit
**Spec**: `sdd/specs/ast-grep-for-wikitoolkit.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2740
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4, design §4.3 "PHP" table. Adds namespaces as qualname prefix
(not rendered), methods under class/trait/enum, functions, `use` imports, three
call kinds and inheritance clauses.

---

## Scope

- Create `languages/rules/php.yaml`: class/interface/trait/enum
  (`class_declaration`, `interface_declaration`, `trait_declaration`,
  `enum_declaration`; `doc: leading_comment`), method (`method_declaration`,
  `parent: {ancestor: [class_declaration, trait_declaration, enum_declaration], name: {field: name}}`,
  depth 2, `signature: {field: parameters}`), function (`function_definition`,
  `signature: {field: parameters}`), namespace (`namespace_definition`, kind
  `PACKAGE`, depth 1, **not rendered**; the loader/extractor prefixes following
  qualnames with `Ns\\` and joins members with `::`), imports
  (`namespace_use_declaration` — group `use A\{B, C}` expanded like the walker),
  refs: `calls` from `function_call_expression`, `member_call_expression`,
  `scoped_call_expression` (`target: {field: function}` or `{field: name}`),
  `extends` from `base_clause`, `implements` from `class_interface_clause`.
- Fixture `fixtures/structural/sample.php` (prototype :36-49) + tests (symbol
  table, `qualname == "App\\Models\\User::getFullName"`, parity harness for
  `.php`, group-use expansion parity).

**NOT in scope**: other languages; walker changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/languages/rules/php.yaml` | CREATE | Rule file |
| `tests/knowledge/wiki/languages/fixtures/structural/sample.php` | CREATE | §4.4 sample |
| `tests/knowledge/wiki/languages/test_rules_php.py` | CREATE | Tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.languages import astgrep, scanner_for      # TASK-2739 ; languages/__init__.py:47
from parrot.knowledge.wiki.languages.php import PhpScanner            # php.py:128
```

### Existing Signatures to Use
```python
# Verified kinds (design §1.2): class_declaration, interface_declaration, trait_declaration, enum_declaration, method_declaration,
# function_definition, namespace_definition, namespace_use_declaration, base_clause, class_interface_clause,
# function_call_expression, member_call_expression, scoped_call_expression
# Walker strings (php.py): :291 f"{kind} {cname}: {doc}" ; :299 f"    def {fname}({params}): {doc}" ; :301 f"function {fname}({params}): {doc}"
# Group-use expansion precedent: php.py ~:95-125 (`parts.append(part)` :124) — imports must match test_php_group_use_expanded (test_php_plugin.py:43)
# PhpScanner.outline :136 ; _outline_heuristic :161 ; _outline_treesitter :249 ; PSR-4 resolution unchanged (:319-404)
# Prototype rules: artifacts/ast/astgrep_rules_prototype.py:126-152
```

### Does NOT Exist
- ~~a rendered `namespace …` outline line~~ — the walker never emits one; namespace symbols are `symbols`-only.
- ~~`method_declaration` field `parameters` being named `params`~~ — tree-sitter-php uses `parameters`; verify with `n.field("parameters")`.
- ~~PSR-4 changes~~ — `build_reference_index`/`resolve_import` untouched.

---

## Implementation Notes

- `qualname` for a method under `namespace App\Models; class User` is
  `App\Models\User::getFullName`; without a namespace `User::getFullName`
  (matches spec §2 `SymbolRecord.qualname` examples).
- Enum cases are not symbols in v1 (depth would be 2 with kind `CONST`; skip to
  keep the table small — note in Completion Note if you disagree).
- HTML-prefixed files (`test_php_tolerates_html_prefix`) must still pass —
  the grammar handles `text` nodes; do not strip the prefix yourself.

---

## Acceptance Criteria

- [ ] `pytest tests/knowledge/wiki/languages/test_rules_php.py tests/knowledge/wiki/languages/test_outline_parity.py tests/knowledge/wiki/languages/test_php_plugin.py -v` passes in both modes.
- [ ] §4.4 rows reproduced: `class User L5-8 doc='Represents an application user.'`, `method getFullName parent=User doc='Get the full name.'`, interface/trait/enum/function rows.
- [ ] `qualname` carries the namespace prefix; `PACKAGE` symbol present in `symbols`, absent from `outline`.
- [ ] `extends`/`implements`/`calls` refs present for the fixture.
- [ ] Rule file validates without WARNING.

---

## Test Specification

```python
@requires_astgrep
def test_php_qualnames_namespaced():
    out = PhpScanner().outline((FIXTURES / "sample.php").read_text(), "sample.php")
    q = {s.qualname for s in out.symbols}
    assert "App\\Models\\User" in q and "App\\Models\\User::getFullName" in q
    assert [s for s in out.symbols if s.kind.value == "package"][0].name == "App\\Models"
```

---

## Agent Instructions

1. Read spec §3 Module 4 + design §4.3 PHP table. 2. Confirm TASK-2740 completed.
3. Index → `in-progress`. 4. Rule file → fixture → tests. 5. Both modes green.
6. Move to `completed/`. 7. Index → `done`. 8. Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-09-02
**Notes**: `php.yaml` reproduces the design §4.4 PHP table exactly
(verified live): `class User L5-8 doc='Represents an application
user.'`, `method getFullName parent=App\Models\User doc='Get the full
name.'`, interface/trait/enum/function rows, namespace `PACKAGE` symbol
present in `symbols` and absent from `outline`. `extends`/`implements`
refs verified; all three PHP call-expression kinds
(`function_call_expression`/`member_call_expression`/
`scoped_call_expression`) verified to produce `calls` refs despite
exposing the callee under two different field names (`function` vs
`name`) — three ref specs, not one `any` rule. Parity holds for
`sample.php` including group-use imports (still read from raw source by
`PhpScanner`, unaffected by the seam).
`pytest tests/knowledge/wiki/languages/test_rules_php.py
tests/knowledge/wiki/languages/test_outline_parity.py
tests/knowledge/wiki/languages/test_php_plugin.py -v` → 31 passed. Full
`tests/knowledge/wiki/languages`: 242 passed. Full `tests/knowledge/wiki`:
1306 passed (same single pre-existing unrelated failure). `ruff check` /
`mypy --ignore-missing-imports` clean.
**Deviations from spec**: PHP's namespace qualname requirement
(`App\Models\User` / `App\Models\User::getFullName`, i.e. two different
separators — `\` namespace→class, `::` class→method — in the same
symbol tree) is not expressible by TASK-2739's original single
per-language `_QUALNAME_JOINER` + ancestor-only `parent` resolution, so
`astgrep.py` (owned by TASK-2739) gained three small, additive pieces,
all verified necessary by running the actual grammar (PHP's block-less
`namespace Foo\Bar;` is a *preceding sibling*, like Perl's `package`, not
an ancestor of what it scopes — confirmed live):
1. `SymbolSpec.qualname_joiner: str | None = None` — per-spec override
   of the qualname separator, defaulting to the existing per-language map
   when unset (zero behavior change for every already-shipped rule).
2. `preceding_package` generalized to also match `namespace_definition`
   (previously Perl-only, `package_statement`).
3. New extractor `php_qualified_container` (registered in `EXTRACTORS`,
   used only by `php.yaml`'s `method` rule's `parent`) — combines the
   preceding-namespace lookup with the immediate class/interface/trait/
   enum ancestor's own name into one `Ns\Class` string, since a method's
   `parent` needs the class's *already-namespace-qualified* name, which
   the generic ancestor-based `parent: {ancestor: ..., name: {...}}` form
   cannot produce (it only reads the ancestor's bare `name` field).
Also added `_strip_enclosing_parens()` inside `_resolve_value_spec`
(field/path branches): `signature: {field: parameters}` returns the
parameter list's `.text()` **including** its own surrounding parens in
PHP's grammar, which combined with `render.py`'s
`f"({sym.signature})"` produced doubled parens — verified live,
confirmed a parity break, not present in TypeScript (TASK-2742 never
set `signature` on any rule). Stripping one layer of enclosing parens
matches every walker's own `params_node.text().strip("()")` convention
(render.py's documented contract) and is a no-op for non-parenthesized
fields (names, paths) — verified via the full regression suite.
None of these four changes alter TASK-2739/2742's existing behavior
(regression-tested: 242/242 `tests/knowledge/wiki/languages` pass,
including every TASK-2742 TypeScript test unchanged).
