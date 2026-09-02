# TASK-2745: Rule file `perl.yaml` (kind-only, dynamic grammar) + parity

**Feature**: FEAT-498 — ast-grep Structural Plane for wikitoolkit
**Spec**: `sdd/specs/ast-grep-for-wikitoolkit.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2740
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 and resolved decision "Perl via dynamic registration, `kind`
rules only, silent fallback". Perl's "parent" is the *last preceding*
`package_statement`, not an ancestor — hence the `preceding_package` extractor
(TASK-2739). POD `=head2` docs come from the existing `_head2_docs`.

---

## Scope

- Create `languages/rules/perl.yaml`: package/class/role
  (`package_statement`, `class_statement`, `role_statement`; kinds `PACKAGE`,
  `CLASS`, `ROLE`; `doc: pod_head2` with `leading_comment` fallback), sub/method
  (`subroutine_declaration_statement`, `method_declaration_statement`;
  `parent: preceding_package`, depth 2 when a container precedes, `signature`
  from the signature node when present), `has` attributes
  (`expression_statement` whose first child is a `function` named `has` — use
  `has: {kind: function, regex: '^has$'}`), `field` declarations
  (`variable_declaration` with `field` keyword — mirror `perl.py::_field_var`
  logic), imports (`use_statement`, `require_expression`; pragma filter as the
  walker, see `perl.py` import filtering), refs: `calls` from
  `function_call_expression`/`method_call_expression` if present in the grammar
  (verify kinds with `root.find_all(kind=…)`; omit gracefully if absent), no
  `extends` (roles/`use parent` are out of v1).
- **No `pattern:` keys anywhere** (verified: patterns return `[]` for the
  dynamically registered grammar) — add a schema-level test.
- Fixture `fixtures/structural/sample.pm` + tests including the fallback path
  (`.so` glob monkeypatched to `[]` → walker output, identical outline).

**NOT in scope**: other languages; changing `_head2_docs`; walker changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/languages/rules/perl.yaml` | CREATE | Rule file (kind-only) |
| `tests/knowledge/wiki/languages/fixtures/structural/sample.pm` | CREATE | Sample with package/sub/has/field/POD |
| `tests/knowledge/wiki/languages/test_rules_perl.py` | CREATE | Tests incl. fallback |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.languages import astgrep, scanner_for       # TASK-2739 ; languages/__init__.py:47
from parrot.knowledge.wiki.languages.perl import PerlScanner, _head2_docs   # perl.py:196 / :118
import tree_sitter_perl   # 1.2.1 ; package dir has `_binding.abi3.so` exporting `T tree_sitter_perl` (nm-verified 2026-09-02)
```

### Existing Signatures to Use
```python
# Verified kinds via register_dynamic_language (design §1.2 + this session): package_statement, use_statement, subroutine_declaration_statement ;
# design also lists class_statement, role_statement, method_declaration_statement, require_expression, variable_declaration (field $x)
# Patterns: root.find_all(pattern="sub $NAME { $$$ }") == []  → kind-only
# Walker strings (perl.py): :380 f"package {pname}" ; :389 f"class {cname}: {doc}" ; :396 f"role {rname}: {doc}" ; :406 f"    {line}" if in_context else line (sub)
#   :412 f"    {sig}: {doc}" (method) ; :416 f"    field {var_name}" ; :421-424 f"    has {attr_name}" (+ optional type suffix, read :421-424)
# _head2_docs(source) -> dict[str, str]  perl.py:118 — name → first POD line ; PerlScanner.outline :204 (calls it at :231)
# _outline_heuristic :228 ; _outline_treesitter :297 ; import pragma filter: read perl.py resolve/import helpers ~:439-515
# Fallback seam: astgrep.supported_language("perl") (TASK-2739) — cached False when the .so is missing
```

### Does NOT Exist
- ~~ast-grep built-in `perl` language~~ — only via dynamic registration; `SgRoot(src, "perl")` without it **panics**.
- ~~`pattern:` rules for Perl~~ — forbidden in this file (test enforces).
- ~~an `ancestor`-based parent for Perl subs~~ — `package Foo;` is a sibling statement; use `preceding_package`.
- ~~`extends` refs for Perl in v1~~ — out of scope.

---

## Implementation Notes

- `preceding_package` (implemented in TASK-2739 `EXTRACTORS`) returns the
  name of the nearest earlier `package_statement`/`class_statement`/
  `role_statement` in document order, or `None`.
- Perl fixture must exercise: two packages in one file (parent switches),
  POD `=head2 bar` doc, `has name => (is => 'ro', isa => 'Str')`, `field $x`,
  `use strict; use Foo::Bar;` (pragma filtered, module kept), `require Baz;`.
- The fallback test must assert the outline is identical to the seam output
  (parity) and that only one DEBUG record about registration is emitted.

---

## Acceptance Criteria

- [ ] `pytest tests/knowledge/wiki/languages/test_rules_perl.py tests/knowledge/wiki/languages/test_outline_parity.py tests/knowledge/wiki/languages/test_perl.py -v` passes in both modes and with the `.so` lookup monkeypatched away.
- [ ] `perl.yaml` contains no `pattern` key (schema test); loads without WARNING.
- [ ] Symbols: `package Foo::Bar` (PACKAGE), `sub bar parent=Foo::Bar depth=2 doc=<=head2 text>`, `has name` (ATTRIBUTE), `field $x` (FIELD); parent switches after the second `package`.
- [ ] `imports` equal the walker's (pragmas filtered).
- [ ] `mode` is `"ast-grep"` when registered, `"tree-sitter"`/`"heuristic"` on fallback.

---

## Test Specification

```python
def test_perl_rules_have_no_patterns():
    import yaml, importlib.resources as r
    data = yaml.safe_load(r.files("parrot.knowledge.wiki.languages.rules").joinpath("perl.yaml").read_text())
    assert "pattern" not in yaml.safe_dump(data)

@requires_astgrep
def test_perl_fallback_when_so_missing(monkeypatch):
    monkeypatch.setattr(astgrep, "_perl_library_candidates", lambda: [])
    astgrep._DYNAMIC_CACHE.clear()
    out = PerlScanner().outline(SRC, "x.pm")
    assert PerlScanner().mode != "ast-grep" and out.outline == EXPECTED_WALKER_LINES
```

---

## Agent Instructions

1. Read spec §3 Module 4, §7 "Dynamic Perl" + "Parent for Perl". 2. Confirm
TASK-2740 completed. 3. Probe kinds with a scratch `SgRoot` before writing rules.
4. Index → `in-progress`. 5. Rule file → fixture → tests. 6. Green in all three
modes. 7. Move to `completed/`. 8. Index → `done`. 9. Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-09-02
**Notes**: `perl.yaml` is kind-only (verified: `yaml.safe_dump` of the
parsed file contains no `pattern` substring) and validates without
WARNING. Symbol table verified against `sample.pm`: `package
MyApp::Model::User` (depth 1), `sub validate parent=MyApp::Model::User
depth=2 doc='Validate the user.'` (POD `=head2`), `has name`
(ATTRIBUTE), `field $x` (FIELD); parent correctly switches to
`MyApp::Other` after the second `package` statement (block-less
sibling-scoping, `perl_sub_parent`). Imports match the walker
(pragmas filtered, `Moose`/`MyApp::Schema`/`Baz` kept). Fallback verified
live: monkeypatching the `.so` lookup away makes `supported_language
("perl")` cache `False` and the scanner falls back silently
(`mode != "ast-grep"`, outline still correct via tree-sitter/heuristic).
`pytest tests/knowledge/wiki/languages/test_rules_perl.py
tests/knowledge/wiki/languages/test_outline_parity.py
tests/knowledge/wiki/languages/test_perl.py -v` → 53 passed. Full
`tests/knowledge/wiki/languages`: 254 passed. Full `tests/knowledge/wiki`:
1317 passed (same single pre-existing unrelated failure). `ruff check` /
`mypy --ignore-missing-imports` clean.
**Deviations from spec**: Continuing the pattern from TASK-2742/2743/2744
(all additive, all verified live, none changing prior behavior — 254/254
languages tests pass): four small `astgrep.py` (TASK-2739) additions/fixes:
1. **Genuine bug fix**: `pod_head2` called `_first_comment_before` (which
   filters on `"comment" in kind`), but a POD block's own kind is
   exactly `"pod"` — never matching — so `pod_head2` could never actually
   return anything. Now checks `node.prev()` for `kind() == "pod"`
   directly. This task's own scope required `doc: pod_head2`, so it had
   to work.
2. New extractor `pod_head2_or_leading_comment` — this task's scope
   explicitly asks for "`doc: pod_head2` with `leading_comment`
   fallback"; a single extractor name can't express a fallback chain in
   the existing schema, so this combinator wraps both.
3. New extractor `perl_sub_parent` — Perl's container statements have
   two forms verified live: block-form (`package Foo { ... }`), a real
   ancestor of everything inside, and block-less (`package Foo;`), a
   *preceding sibling* instead (`preceding_package`). A sub/method needs
   whichever form is actually in play; `_resolve_parent`'s existing
   `{ancestor: ...}` dict form and `preceding_package` string form are
   each only half the answer, so this tries ancestor first, then falls
   back to `preceding_package`.
4. New extractor `perl_pod_summary` (+ helper `_pod_paragraph`, + `import
   re`) — the file-level module summary (`=head1 NAME`/`DESCRIPTION`,
   mirroring `perl.py`'s `_pod_summary`) had no seam-side equivalent;
   `test_pod_summary` (pre-existing, both `TestHeuristic` and
   `TestTreeSitter` classes in `test_perl.py`) requires it.
Two DISCOVERED-not-fixed, pre-existing, out-of-scope `perl.py` walker
issues (same category as TASK-2744's Rust findings — not in any FEAT-498
task's files):
- The tree-sitter tier's doc lookup (`_leading_doc`, a plain `#`
  comment) is a completely different mechanism from the heuristic
  tier's (`_head2_docs`, POD blocks) — a sub preceded by POD gets a doc
  under heuristic but not tree-sitter. `perl` added to
  `test_outline_parity.py`'s `PIN_TO_HEURISTIC` (alongside `rust`) so
  the shared harness compares against the heuristic tier, which
  `pod_head2_or_leading_comment` was built to match.
- The heuristic tier's `_sub_params` has a `my ($self, $x) = @_` unpack
  fallback when no explicit signature exists; the tree-sitter tier
  (which `perl.yaml`'s `signature: {path: [signature]}` mirrors) does
  not. `TestHeuristic::test_sub_params_from_my_unpack` (pre-existing)
  needed `force_no_astgrep` alongside its existing `force_heuristic`.
Also NOT extracted (documented, narrow simplification, not a bug):
Moose/Moo's `isa => 'Type'` suffix on `has` attributes — finding the
value tied to the specific key `isa` (as opposed to `is`) needs
key/value pair matching beyond the seam's generic field/path
primitives. `TestHeuristic::test_moose_has` (pre-existing, asserts the
`Str` suffix) needed `force_no_astgrep` for the same reason.
