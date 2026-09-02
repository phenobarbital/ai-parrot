# TASK-2744: Rule file `rust.yaml` + parity

**Feature**: FEAT-498 — ast-grep Structural Plane for wikitoolkit
**Spec**: `sdd/specs/ast-grep-for-wikitoolkit.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2740
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4, design §4.3 "Rust" table. Rust's walker renders only `pub`
items except fns inside `impl`; doc comments must skip `#[derive]` attribute
items; trait impls become `implements` edges.

---

## Scope

- Create `languages/rules/rust.yaml`: struct/enum/trait/mod
  (`struct_item`/`enum_item`/`trait_item`/`mod_item` with
  `has: {kind: visibility_modifier}`, `doc: leading_doc_comment`), impl
  (`impl_item`, `name: {field: type}`, kind `IMPL`), fn (`function_item`,
  `any: [{has: {kind: visibility_modifier}}, {inside: {kind: impl_item, stopBy: end}}]`,
  `parent: {ancestor: impl_item, name: {field: type}}`, depth 2 inside impl,
  `signature` = header text up to the body, `doc: leading_doc_comment`,
  `exported: {has: visibility_modifier}`), imports (`use_declaration` → `a::b`,
  `mod_item` → `mod:<name>` exactly as the walker), refs: `calls`
  (`call_expression`, `target: {field: function}`), `implements` (`impl_item`
  with `field: trait`), `extends` none.
- Fixture `fixtures/structural/sample.rs` (prototype :50-64) + tests.

**NOT in scope**: other languages; walker changes; private items outside `impl`
(walker omits them → not rendered; they *may* be in `symbols` with `exported=False` only if depth rules allow — keep them out in v1 to match "what the scanner emits today").

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/languages/rules/rust.yaml` | CREATE | Rule file |
| `tests/knowledge/wiki/languages/fixtures/structural/sample.rs` | CREATE | §4.4 sample |
| `tests/knowledge/wiki/languages/test_rules_rust.py` | CREATE | Tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.languages import astgrep, scanner_for      # TASK-2739 ; languages/__init__.py:47
from parrot.knowledge.wiki.languages.rust import RustScanner          # rust.py:127
```

### Existing Signatures to Use
```python
# Verified kinds (design §1.2): struct_item, enum_item, trait_item, mod_item, impl_item (field: type, field: trait), function_item,
# visibility_modifier, attribute_item, use_declaration, call_expression (field: function; `a.b()` is call_expression whose function is field_expression)
# Walker strings (rust.py): :300 f"pub {kind} {name}: {doc}" ; :304 f"pub mod {name}" ; :308 f"impl {name}:" ; :293 f"    {sig}: {doc}" (fn in impl) ; :295 f"{sig}: {doc}" (top-level pub fn)
# `sig` construction: read rust.py ~:280-295 (header text before `{`, trailing whitespace stripped) and reproduce it in render_outline's Rust branch (TASK-2740) — this task only supplies `signature`
# RustScanner.outline :135 ; _outline_heuristic :159 ; _outline_treesitter :236 ; resolve_import (:360) handles "mod:<name>" specs (:381)
# Prototype rules: artifacts/ast/astgrep_rules_prototype.py:153-184 ; doc-skipping-attributes: :189-198
```

### Does NOT Exist
- ~~`method_call_expression` kind in tree-sitter-rust~~ — `a.b()` is `call_expression` + `field_expression`.
- ~~rendered lines for non-pub top-level fns~~ — walker omits them (`[fn not_pub omitido]` in §4.4).
- ~~`extends` for Rust~~ — no inheritance; only `implements` via trait impls.

---

## Implementation Notes

- `leading_doc_comment` walks `prev()` past `attribute_item` nodes until a
  `line_comment`/`block_comment`, then takes the first line stripped of `///`.
- `impl Display for Parser` → symbol `impl` name `Parser` **and** a
  `SymbolRef(rel="implements", target_text="Display")`.
- `parent` for a fn inside `impl X` is `X`; qualname `X::new`.

---

## Acceptance Criteria

- [ ] `pytest tests/knowledge/wiki/languages/test_rules_rust.py tests/knowledge/wiki/languages/test_outline_parity.py tests/knowledge/wiki/languages/test_rust_plugin.py -v` passes in both modes.
- [ ] §4.4 rows: `struct Parser doc='A document parser.'` (attribute skipped), `impl Parser`, `fn new parent=Parser doc='Create a parser.'`, `fn private_helper parent=Parser`, `trait Visitor`, `mod utils`, `enum Kind`; `not_pub` absent.
- [ ] `implements` ref for a `impl Trait for Type` fixture line.
- [ ] `imports` == walker's (`std::collections::HashMap`, `mod:utils`).
- [ ] Rule file validates without WARNING.

---

## Test Specification

```python
@requires_astgrep
def test_rust_table_and_trait_impl():
    src = (FIXTURES / "sample.rs").read_text() + "\nimpl std::fmt::Display for Parser { }\n"
    out = RustScanner().outline(src, "sample.rs")
    assert ("fn", "new", "Parser") in {(s.kind.value if s.kind.value != "function" else "fn", s.name, s.parent) for s in out.symbols}
    assert any(r.rel == "implements" and r.target_text.endswith("Display") for r in out.refs)
    assert all("not_pub" not in line for line in out.outline)
```

---

## Agent Instructions

1. Read spec §3 Module 4 + design §4.3 Rust table. 2. Confirm TASK-2740 completed.
3. Index → `in-progress`. 4. Rule file → fixture → tests. 5. Both modes green.
6. Move to `completed/`. 7. Index → `done`. 8. Completion Note.

---

## Completion Note

**Completed by**: —
**Date**: —
**Notes**: —
**Deviations from spec**: none
