# TASK-2742: Rule file `typescript.yaml` (TS / TSX / JavaScript / Svelte scripts) + parity

**Feature**: FEAT-498 — ast-grep Structural Plane for wikitoolkit
**Spec**: `sdd/specs/ast-grep-for-wikitoolkit.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2740
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4, design §4.3 "JavaScript / TypeScript / TSX / Svelte" table.
First real rule file: it must make `JavaScriptScanner` produce symbols through
the seam while `render_outline` keeps the outline byte-identical to the
tree-sitter walker. Class methods are extracted (depth 2) but **not rendered**
(resolved: strict parity).

---

## Scope

- Create `languages/rules/typescript.yaml` with `language: typescript`,
  `aliases: [tsx, javascript]`, `summary: first_heading_comment`, and rules:
  class (`class_declaration`, `exported: {inside: export_statement}`, `doc: leading_comment`),
  function (`function_declaration`, idem), method (`method_definition` inside
  `class_body`, `parent: {ancestor: class_declaration, name: {field: name}}`, depth 2,
  `async: {has: async}`), interface (`interface_declaration`), type alias
  (`type_alias_declaration`), exported const (`lexical_declaration` inside
  `export_statement`, `name: {path: [variable_declarator, name]}`); refs:
  `calls` (`call_expression`, `target: {field: function}`, scope ancestors
  function/method/class), `extends`/`implements` from `class_heritage`
  (`extends_clause` / `implements_clause` children); imports: `import_statement`.
- Fixture `tests/knowledge/wiki/languages/fixtures/structural/sample.ts`
  (design §4.4 sample — `artifacts/ast/astgrep_rules_prototype.py:21-35`) plus
  a `.svelte` fixture reusing `conftest.svelte_repo` content.
- Tests: symbol table matches design §4.4 (kind/name/parent/exported/doc/L-range),
  method depth 2 present in `symbols` but absent from `outline`, parity harness
  green for `.ts`, `.tsx`, `.js`, `.svelte`; `imports` still read from the raw
  source for Svelte (walker behaviour).

**NOT in scope**: other languages' rule files; renderer changes (if parity
fails, fix the *rule* or open a bug — never the walker's strings).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/languages/rules/typescript.yaml` | CREATE | Rule file |
| `tests/knowledge/wiki/languages/fixtures/structural/sample.ts` | CREATE | §4.4 sample |
| `tests/knowledge/wiki/languages/fixtures/structural/sample.svelte` | CREATE | `<script lang="ts">` sample |
| `tests/knowledge/wiki/languages/test_rules_typescript.py` | CREATE | Symbol-table + parity tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.languages import astgrep, scanner_for          # TASK-2739 ; languages/__init__.py:47
from parrot.knowledge.wiki.languages.javascript import JavaScriptScanner, _extract_script_blocks   # javascript.py:492 / :187
from parrot.knowledge.wiki.languages.render import render_outline         # TASK-2740
```

### Existing Signatures to Use
```python
# Verified tree-sitter kinds (ast-grep-py 0.45.3 built-in typescript/tsx/javascript grammars — design §1.2):
# class_declaration, function_declaration, method_definition, class_body, interface_declaration, type_alias_declaration,
# lexical_declaration, variable_declarator, export_statement, import_statement, call_expression (field: function),
# class_heritage, extends_clause, implements_clause
# Walker strings to keep (javascript.py:632 / :642):  f"{prefix}{kind} {name}: {doc}"  /  f"{prefix}const {name}: {doc}"   prefix = "export " | ""
# JavaScriptScanner.outline :505 → _extract_script_blocks(source, suffix) :524 → (script_source, lang) ; imports for Svelte read from RAW source (design §4.3)
# Rule-file schema: spec §2 Data Models (YAML block) ; loader: astgrep.RuleSet.load(lang) (TASK-2739)
# Prototype rules that already reproduced the §4.4 table: artifacts/ast/astgrep_rules_prototype.py:92-125
```

### Does NOT Exist
- ~~`languages/rules/javascript.yaml` / `tsx.yaml`~~ — one file, served via `aliases`.
- ~~a `svelte` ast-grep grammar~~ — not built in; Svelte is handled by pre-extracting `<script>` (existing `_extract_script_blocks`).
- ~~rendered method lines for TS classes~~ — the walker never emitted them; the renderer skips depth-2 TS symbols.
- ~~`exported` for methods~~ — always `False` (matches design §4.4: `method createUser exp=False`).

---

## Implementation Notes

### Key Constraints
- `doc: leading_comment` must look **before the `export_statement` wrapper** when the declaration is exported (prototype `leading_comment`, :189-198).
- Keep the rule file free of any `pattern:` keys unless a `kind` rule cannot express it — `kind` rules are grammar-version-stable.
- Sort symbols by `start_byte` before rendering (renderer contract).

### References in Codebase
- `tests/knowledge/wiki/languages/test_javascript_plugin.py` — expected outline lines for TS/JS/Svelte.
- `sdd/specs/wikitoolkit-svelte-typescript-support.spec.md` (FEAT-396) — Svelte `lang` semantics.

---

## Acceptance Criteria

- [ ] `pytest tests/knowledge/wiki/languages/test_rules_typescript.py tests/knowledge/wiki/languages/test_outline_parity.py tests/knowledge/wiki/languages/test_javascript_plugin.py -v` passes with and without ast-grep.
- [ ] With ast-grep: `sample.ts` yields exactly the §4.4 rows — `class UserService exp=True L2-5 doc='Main service class.'`, `method createUser parent=UserService depth=2`, `function createUser exp=True`, `function internalHelper exp=False`, `interface UserRecord`, `const DEFAULT_TIMEOUT`, `type Id`.
- [ ] `outline` identical to walker output for `.ts`, `.tsx`, `.js`, `.svelte` fixtures.
- [ ] `refs` contain a `calls` entry per call expression and `extends`/`implements` per heritage clause.
- [ ] `yaml.safe_load` of the file validates against `RuleSet` (no WARNING at load).

---

## Test Specification

```python
@requires_astgrep
def test_typescript_symbol_table():
    src = (FIXTURES / "sample.ts").read_text()
    out = JavaScriptScanner().outline(src, "sample.ts")
    rows = {(s.kind.value, s.name): (s.parent, s.exported, s.start_line, s.end_line, s.doc) for s in out.symbols}
    assert rows[("class", "UserService")] == (None, True, 2, 5, "Main service class.")
    assert rows[("method", "createUser")][0] == "UserService"
    assert not any(l.startswith("    ") for l in out.outline)   # methods not rendered
```

---

## Agent Instructions

1. Read spec §3 Module 4 + design §4.3 table. 2. Confirm TASK-2740 completed.
3. Index → `in-progress`. 4. Write the rule file, then fixtures, then tests.
5. Run in both modes. 6. Move to `completed/`. 7. Index → `done`. 8. Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-09-02
**Notes**: `typescript.yaml` matches the design §4.4 table exactly (verified
live against ast-grep-py 0.45.3): `class UserService exp=True L2-5 doc=
'Main service class.'`, `method createUser parent=UserService exp=False
depth=2`, `function createUser exp=True`, `function internalHelper
exp=False`, `interface UserRecord`, `const DEFAULT_TIMEOUT`, `type Id`.
Refs verified: `calls`/`extends`/`implements`. Parity holds for `.ts`,
`.tsx`, `.js`, `.svelte` fixtures (methods never rendered, matching the
walker). `is_async` for TS/JS methods is left at its default `False`
rather than the scoped `async: {has: async}` (see Deviations) — render.py
never consumes `is_async` for JS/TS, so this has no effect on the
rendered outline or any acceptance criterion.
`pytest tests/knowledge/wiki/languages/test_rules_typescript.py
tests/knowledge/wiki/languages/test_outline_parity.py
tests/knowledge/wiki/languages/test_javascript_plugin.py -v` → 101
passed. Full `tests/knowledge/wiki/languages`: 236 passed. Full
`tests/knowledge/wiki`: 1299 passed (same single pre-existing unrelated
failure in `test_claude_code.py`). `ruff check` / `mypy
--ignore-missing-imports` clean.
**Deviations from spec**: Three corrections outside this task's own
Files table, all verified necessary (not guessed) by running the actual
grammar and the actual pre-existing tests, documented here rather than
shipping a broken rule or a false-red suite:
1. **`languages/astgrep.py`** (owned by TASK-2739): `node.find(kind=
   "async")` raises `RuntimeError: Kind async is invalid` — "async" is
   an anonymous keyword token, not a matchable kind in ast-grep-py
   0.45.3's typescript grammar, and this error is NOT caught anywhere
   between `_resolve_bool_spec` and the scanner's outer
   `except Exception`, so keeping `async: {has: async}` in the YAML
   would silently degrade the *entire* file to the tree-sitter fallback
   (defeating the whole rule), not just drop the `is_async` field —
   hence dropping it from the YAML instead of fixing the resolver (out
   of this task's file scope). Separately, `leading_comment`/
   `leading_doc_comment`'s `_first_comment_before` didn't look past an
   `export_statement` wrapper, so NO exported TS declaration ever got
   its doc comment; added a new, separate extractor
   `leading_comment_exported` (registered in `EXTRACTORS`) used only by
   `class`/`function`/`interface`/`type` — matching the walker's own
   asymmetric behavior, which does the same parent-probing for those
   four kinds via `javascript.py`'s `_leading_doc(child) or
   _leading_doc(child.parent if _is_exported(child) else child)` but
   NOT for `lexical_declaration` (`const`, which keeps plain
   `leading_comment` and is a documented parity casualty in the walker
   itself, verified live).
2. **`tests/knowledge/wiki/languages/test_javascript_plugin.py`**:
   `test_jsts_parse_failure_degrades_empty` used only `force_heuristic`,
   which no longer forces the fallback path now that a real TS rule
   exists — added `force_no_astgrep` too.
3. **`tests/knowledge/wiki/languages/test_outline_parity.py`** /
   **`test_polyglot_integration.py`**: both pre-existing tests asserted
   a closed set of `mode` values that excluded `"ast-grep"` — the exact,
   anticipated consequence flagged by `test_outline_parity.py`'s own
   module docstring ("Rule tasks extend CASES … once a rule file makes
   the seam actually serve a file"). Renamed
   `test_seam_is_currently_a_noop` → `test_seam_service_matches_available_rules`
   (tracks per-language expectation via a new `SERVED_BY_RULE` set) and
   widened the `test_stats_languages_block` mode set to include
   `"ast-grep"`.
