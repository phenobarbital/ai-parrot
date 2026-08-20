# TASK-2261: PerlScanner — tree-sitter outline extraction

**Feature**: FEAT-432 — Wikitoolkit Perl Scanner
**Spec**: `sdd/specs/wikitoolkit-perl-scanner.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2260
**Assigned-to**: unassigned

---

## Context

TASK-2260 created `PerlScanner` with the heuristic fallback, import
extraction, and reference resolution. This task adds the tree-sitter
code path: `_outline_treesitter()` that uses `tree_sitter_perl`'s AST
for accurate outline extraction of all Perl constructs including
Corinna OO, and updates the `mode` property to report `"tree-sitter"`
when the grammar loads.

Implements spec Module 2 (tree-sitter path).

---

## Scope

- Implement `_outline_treesitter(parser, source)` in `perl.py`
- Walk the tree-sitter AST to extract:
  - `subroutine_declaration_statement` → `sub name(params): doc`
  - `package_statement` → `package Foo::Bar`
  - `class_statement` → `class Foo: doc` (Corinna)
  - `role_statement` → `role Foo: doc` (Corinna)
  - `method_statement` → `method name(params): doc` (Corinna)
  - `field_statement` → `field $x` (Corinna)
  - `function_call_expression` where callee is `has` → `has attr: type` (Moose/Moo)
- Extract POD summary from tree-sitter `pod_statement` node
- Extract doc-comments from preceding `comment` nodes
- Update `mode` property to check `treesitter.get_parser("perl")`

**NOT in scope**: Heuristic fallback (TASK-2260), import extraction
(TASK-2260), reference resolution (TASK-2260), tests (TASK-2262).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/languages/perl.py` | MODIFY | Add `_outline_treesitter()`, update `mode` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Already in perl.py from TASK-2260:
from parrot.knowledge.wiki.languages import treesitter  # treesitter.py
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/languages/treesitter.py
def get_parser(language: str) -> Parser | None: ...  # line 62
# Returns a tree_sitter.Parser configured for the language, or None.
# Parser.parse(bytes) -> Tree; Tree.root_node -> Node
```

### Reference Implementation — rust.py tree-sitter outline

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/languages/rust.py:236-321
def _outline_treesitter(self, parser: Any, source: str) -> tuple[str, list[str]]:
    tree = parser.parse(source.encode("utf-8"))
    root = tree.root_node
    source_bytes = source.encode("utf-8")
    lines: list[str] = []

    def _text(node): return source_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="replace")
    def _name_of(node):
        name_node = node.child_by_field_name("name")
        return _text(name_node) if name_node is not None else ""
    def _leading_doc(node): ...  # walks prev_sibling for doc comments
    def _is_pub(node): ...       # checks visibility_modifier

    def _walk(node, in_impl):
        for child in node.children:
            # dispatch by child.type
            ...

    _walk(root, in_impl=None)
    # summary from first doc comment
    return summary, lines
```

### tree-sitter-perl Node Types (key ones)

These are the node types from the tree-sitter-perl grammar (v1.2.1).
**IMPORTANT**: Verify these against the actual grammar at implementation
time — the grammar is "unstable" tier and node types may differ:

| Node Type | Perl Construct |
|---|---|
| `subroutine_declaration_statement` | `sub foo { }` |
| `package_statement` | `package Foo::Bar;` |
| `use_statement` | `use Module::Name;` |
| `require_statement` | `require Module::Name;` |
| `class_statement` | `class Foo { }` (Corinna) |
| `role_statement` | `role Foo { }` (Corinna) |
| `method_statement` | `method bar { }` (Corinna) |
| `field_statement` | `field $x :param;` (Corinna) |
| `function_call_expression` | `has('attr', ...)` (Moose — special-case) |
| `pod_statement` | `=head1 NAME ... =cut` |
| `comment` | `# comment line` |

**How to verify**: Write a small test script that parses Perl source with
`tree_sitter_perl` and prints node types:
```python
import tree_sitter_perl, tree_sitter
lang = tree_sitter.Language(tree_sitter_perl.language())
parser = tree_sitter.Parser(lang)
tree = parser.parse(b"package Foo; sub bar { } 1;")
def show(node, depth=0):
    print("  " * depth + f"{node.type} [{node.start_point}-{node.end_point}]")
    for c in node.children: show(c, depth+1)
show(tree.root_node)
```

### Does NOT Exist

- ~~`tree_sitter_perl.language_perl()`~~ — use `language()`, not `language_perl()`
- ~~`node.field_name`~~ on all nodes — only named fields have this; use
  `child_by_field_name()` which returns `None` for unnamed children
- ~~`node.text`~~ — tree-sitter Python binding does not have `.text`;
  use `source_bytes[node.start_byte:node.end_byte]`
- ~~`subroutine_definition`~~ — verify; might be `subroutine_declaration_statement`

---

## Implementation Notes

### Walk Strategy

Follow rust.py's `_walk(node, context)` pattern:

```python
def _walk(node: Any, in_package: str | None) -> None:
    for child in node.children:
        if child.type == "package_statement":
            name = _name_of(child)
            lines.append(f"package {name}")
            _walk(child, in_package=name)
        elif child.type == "subroutine_declaration_statement":
            name = _name_of(child)
            params = _params_of(child)
            doc = _leading_doc(child)
            sig = f"sub {name}({params})"
            if in_package:
                lines.append(f"    {sig}: {doc}".rstrip(": "))
            else:
                lines.append(f"{sig}: {doc}".rstrip(": "))
        elif child.type == "class_statement":
            # Corinna class
            ...
        elif child.type == "function_call_expression":
            # Check if callee is "has" (Moose)
            ...
        else:
            _walk(child, in_package=in_package)
```

### Moose `has` Detection

`has` in Moose/Moo is a function call, not syntax. In tree-sitter it
appears as `function_call_expression`. Check:
```python
if child.type == "function_call_expression":
    callee = child.child_by_field_name("function")
    if callee and _text(callee) == "has":
        # Extract attribute name from first argument
        args = child.child_by_field_name("arguments")
        ...
```

### POD Summary

Look for `pod_statement` nodes. Extract the text after `=head1 NAME`:
```python
if child.type == "pod_statement":
    text = _text(child)
    # Parse "=head1 NAME\n\nModule::Name - short description"
    ...
```

### Key Constraints

- `_outline_treesitter()` returns `tuple[str, list[str]]` (summary, lines)
- The caller's `except Exception` guard handles any tree-sitter failure
- Match the outline rendering style established by TASK-2260's heuristic

### References in Codebase

- `packages/ai-parrot/src/parrot/knowledge/wiki/languages/rust.py:236-321` — tree-sitter walk
- `packages/ai-parrot/src/parrot/knowledge/wiki/languages/javascript.py` — tree-sitter for JS
- `packages/ai-parrot/src/parrot/knowledge/wiki/languages/php.py` — tree-sitter for PHP

---

## Acceptance Criteria

- [ ] `_outline_treesitter()` extracts `sub`, `package` from basic Perl source
- [ ] `_outline_treesitter()` extracts Corinna `class`/`role`/`method`/`field`
- [ ] `_outline_treesitter()` detects Moose `has` calls and extracts attribute names
- [ ] POD summary extracted from `=head1 NAME` block
- [ ] Doc-comments from `# comment` preceding declarations are captured
- [ ] `mode` property returns `"tree-sitter"` when grammar loads
- [ ] `mode` property returns `"heuristic"` when grammar is unavailable
- [ ] Outline style matches heuristic mode output
- [ ] No new `except Exception` needed — caller already has one

---

## Test Specification

```python
# Basic tree-sitter verification — full suite in TASK-2262
import pytest
from parrot.knowledge.wiki.languages.perl import PerlScanner

scanner = PerlScanner()

@pytest.mark.skipif(
    scanner.mode != "tree-sitter",
    reason="tree-sitter-perl not installed"
)
def test_treesitter_extracts_sub():
    source = "package Foo;\nsub bar { }\n1;\n"
    result = scanner.outline(source, "lib/Foo.pm")
    assert any("sub bar" in line for line in result.outline)

@pytest.mark.skipif(
    scanner.mode != "tree-sitter",
    reason="tree-sitter-perl not installed"
)
def test_treesitter_extracts_corinna():
    source = "use v5.38;\nclass Point {\n  field $x :param;\n  method coords { }\n}\n"
    result = scanner.outline(source, "lib/Point.pm")
    assert any("class Point" in line for line in result.outline)
    assert any("method coords" in line for line in result.outline)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** §7 for tree-sitter node type table
2. **Read `rust.py` `_outline_treesitter()`** in full — it is the reference
3. **Verify node types**: Run the verification script in the contract above
   to confirm actual node type names before writing the walker
4. **Read TASK-2260's `perl.py`** to understand the existing structure
5. **Implement** `_outline_treesitter()` and update `mode` property
6. **Test locally** with a small Perl file: `wikitoolkit build --path /tmp/test-perl/`

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-19
**Notes**: Implemented `_outline_treesitter()` and updated `mode`. Verified
actual `tree-sitter-perl` 1.2.1 node types with a live parse (installed
the wheel in the dev venv for verification, per the task's own
instructions) — several node types differ from the spec/task's assumed
names, all confirmed and adapted:
- Package/class/role name is a **named field `"name"`** on
  `package_statement`/`class_statement`/`role_statement` (of node type
  `"package"` itself, not `"identifier"` — verified via
  `child_by_field_name("name")`, which works uniformly across all three).
- `field_statement` does **not exist** — Corinna `field $x :param;`
  parses as `variable_declaration` whose first (unnamed) child is a
  `"field"` token; distinguished from `my (...)` declarations (also
  `variable_declaration`, first child `"my"`) by checking that first
  child's type.
- `method_statement` does **not exist** — it is
  `method_declaration_statement`.
- `require_statement`/`use_statement`'s targets are not consulted here —
  import extraction stays regex-only in both modes per the spec, so
  tree-sitter's `use_statement`/`require_expression` nodes are skipped
  (fall through to generic recursion, which finds nothing under them).
- Moose `has(...)` appears as `function_call_expression` **only when
  parens are used**; the no-parens `has 'x' => (...)` idiom (used in the
  spec's own Moose fixture) parses as `ambiguous_function_call_expression`
  — both wrapped in an `expression_statement`. Both are handled.
- `pod_statement` does **not exist** — the node type is `"pod"`.
- Params: neither `subroutine_declaration_statement` nor
  `method_declaration_statement` expose a `"signature"`/`"prototype"`
  *field*; located by child *type* instead (`signature` when an explicit
  Perl signature is present, `prototype` for the empty-parens Corinna
  method form).
- Classic (non-block) `package Foo;` has no `block` child at all — it
  rebinds a mutable `in_context` for forward sibling statements at the
  same level (Perl's real scoping rule) rather than nesting; block-form
  `package Foo { ... }` and `class`/`role` bodies recurse into their
  `block.named_children` instead. Verified with the spec's
  `multi_package_source` fixture (two packages, each package's subs
  correctly attributed) and a synthetic block-form package.
- Verified with all spec/task fixtures (Moose `has`, Corinna `class`/
  `field`/`method`, `role`, POD `=head1 NAME`, multi-package,
  never-raises-on-garbage) plus the full existing
  `tests/knowledge/wiki/languages/` suite (146 passed, no regressions).
  `ruff check` clean.

**Deviations from spec**: Every node-type deviation above was explicitly
anticipated by the task's own "verify against the actual grammar" warning
(the grammar is tagged "unstable" tier) — none is a design deviation from
the task's intent, only from its illustrative (unverified) node-type
names. No behavioral deviation from the acceptance criteria.
