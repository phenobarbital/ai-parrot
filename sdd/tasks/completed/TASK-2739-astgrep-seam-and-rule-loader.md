# TASK-2739: ast-grep seam, rule loader, extractors and `wiki-structural` extra

**Feature**: FEAT-498 — ast-grep Structural Plane for wikitoolkit
**Spec**: `sdd/specs/ast-grep-for-wikitoolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2738
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2. The optional structural backend: a seam mirroring
`languages/treesitter.py` (never raises, `None` = use next tier), a validated
YAML `RuleSet` schema, the fixed extractor table, and `extract()` that turns
`SgRoot.find_all({"rule": …})` matches into `StructuralOutline`. It ships with
no rule files (those are TASK-2742…2746); with no rule file for a language
`extract()` returns `None`.

---

## Scope

- Create `languages/astgrep.py`: `is_available()`, `supported_language(lang)`
  (built-in whitelist `{"python","javascript","typescript","tsx","php","rust"}`
  ∪ cached dynamic registration for `perl` via `register_dynamic_language` on
  `tree_sitter_perl/_binding*.so`, symbol `tree_sitter_perl`, extensions
  `pl pm t`), `parse(src, lang)` with `except BaseException` **only** around
  `SgRoot(...)`, `RuleSet` (Pydantic: `language`, `aliases`, `summary`,
  `symbols: list[SymbolSpec]`, `refs: list[RefSpec]`, `imports: list[ImportSpec]`)
  with `RuleSet.load(lang)` (lru-cached; resolves aliases; returns `None` +
  one WARNING on invalid file/unknown extractor), `EXTRACTORS` dict
  (`first_docstring`, `leading_comment`, `leading_doc_comment`, `pod_head2`,
  `module_docstring`, `first_heading_comment`, `preceding_package`, `none`),
  `extract(src, lang, rel_path, *, max_depth=2) -> StructuralOutline | None`,
  helper `named_text(node, var) -> str` joining only `is_named()` nodes.
- Per-(language, rule-id) once-only logging when a rule raises
  `RuntimeError` (`cannot get matcher`); other rules keep running.
- Symbol ordinals: repeated `qualname` in one file → `ordinal` 2, 3 … in
  source order (feeds `sym_concept_id`).
- `pyproject.toml`: extra `wiki-structural = ["ast-grep-py>=0.45"]`, include it
  in the `wiki` meta-extra, add package-data
  `"parrot.knowledge.wiki.languages.rules" = ["*.yaml"]`; create the empty
  package dir `languages/rules/__init__.py`.
- Tests: availability/unsupported/panic fence/perl registration/ruleset
  validation/bad kind isolation/named_text — the ast-grep-dependent ones
  under a `requires_astgrep` skip marker.

**NOT in scope**: rule YAML files, `render_outline`, scanner wiring, Python
`ast` symbols.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/languages/astgrep.py` | CREATE | Seam + RuleSet + extractors + extract |
| `packages/ai-parrot/src/parrot/knowledge/wiki/languages/rules/__init__.py` | CREATE | Empty package (rule files land later) |
| `packages/ai-parrot/pyproject.toml` | MODIFY | `wiki-structural` extra (:248-272 area), package-data (:759) |
| `tests/knowledge/wiki/languages/conftest.py` | MODIFY | `force_no_astgrep` fixture + `requires_astgrep` marker helper |
| `tests/knowledge/wiki/languages/test_astgrep_seam.py` | CREATE | Seam tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.symbols import SymbolKind, SymbolRecord, SymbolRef, StructuralOutline, sha1_of_text   # TASK-2738
from parrot.knowledge.wiki.languages.treesitter import get_parser      # treesitter.py:64 — pattern to mirror, not to call
import tree_sitter_perl                                                # site-packages; dir has `_binding.abi3.so` (nm: `T tree_sitter_perl`)
# Optional, import guarded:
from ast_grep_py import SgRoot, SgNode, register_dynamic_language      # ast-grep-py 0.45.3 — NOT installed in the venv today
import yaml                                                            # PyYAML, already a transitive dependency (file_store.py uses it)
```

### Existing Signatures to Use
```python
# languages/treesitter.py — the seam pattern to copy
_PARSER_CACHE: dict[str, Parser | None]              # module-level cache
def get_parser(language: str) -> Parser | None        # :64 — "Never raises … degrade to None"
def _build_parser(language: str) -> Parser | None     # :86 — importlib.import_module(module_name) inside try/except

# ast-grep-py 0.45.3 API (verified 2026-09-02 in sandbox; see artifacts/ast/astgrep_rules_prototype.py:223-246)
root = SgRoot(src, lang).root()                       # raises pyo3 PanicException (BaseException!) for an unregistered lang
root.find_all({"rule": {...}})                        # positional dict MUST have key "rule"
root.find_all(kind="class_definition") / root.find_all(pattern="helper($$$ARGS)")
n.kind() n.text() n.range() n.field("name") n.parent() n.ancestors() n.prev() n.next() n.child(i) n.find(kind=…) n.is_named()
n.get_match("X") -> SgNode | None ; n.get_multiple_matches("ARGS") -> list[SgNode]   # includes anonymous ',' nodes
r = n.range(); r.start.line (0-based) r.start.column r.start.index (byte) ; r.end.*
root.find_all(kind="no_such_kind") -> RuntimeError("cannot get matcher …")            # ordinary exception
register_dynamic_language({"perl": {"library_path": "<…>/_binding.abi3.so", "language_symbol": "tree_sitter_perl", "extensions": ["pl","pm","t"]}})

# pyproject.toml (packages/ai-parrot)
wiki-languages = [...]                                # :248-255
wiki = ["ai-parrot[graphindex,wiki-languages,leiden]", "pymupdf>=1.27"]   # :269-272 → add wiki-structural
[tool.setuptools.package-data]                        # :759 ; precedent "parrot.openapi" = ["*.yaml"] :765

# tests/knowledge/wiki/languages/conftest.py:11
@pytest.fixture
def force_heuristic(monkeypatch):
    monkeypatch.setattr(treesitter, "get_parser", lambda language: None)   # copy this style for force_no_astgrep
```

### Does NOT Exist
- ~~`parrot.knowledge.wiki.languages.astgrep`~~ — created here.
- ~~`ast_grep_py` in the project venv~~ — install locally with `uv pip install "ast-grep-py>=0.45"` after activating `.venv`; tests must still pass when it is absent.
- ~~ast-grep `pattern` support for Perl~~ — verified to return `[]`; Perl rules are `kind`-only (enforced later in TASK-2745).
- ~~`SgRoot` raising `Exception` for unsupported languages~~ — it panics (`PanicException` ⊂ `BaseException`).
- ~~`register_dynamic_language` returning a status~~ — treat success as "no exception"; verify by a probe `SgRoot("", "perl")` inside the fence.
- ~~`languages/rules/*.yaml`~~ — none exist yet; `RuleSet.load` must return `None` for a missing file without logging at WARNING.

---

## Implementation Notes

### Pattern to Follow
```python
def parse(src: str, lang: str) -> "SgRoot | None":
    if not is_available() or not supported_language(lang):
        return None
    try:
        return SgRoot(src, lang)
    except BaseException:                 # noqa: BLE001 — pyo3 PanicException is not an Exception
        logger.warning("ast-grep panicked while parsing %s; falling back", lang)
        return None
```

### Key Constraints
- `supported_language()` must be called *before* `SgRoot` in every path; the
  panic fence is defence in depth, not the primary guard.
- Dynamic registration: locate the `.so` with
  `importlib.util.find_spec("tree_sitter_perl")` → `Path(origin).parent.glob("_binding*.so")`;
  cache the boolean per process; log at DEBUG once on failure (not per file).
- `RuleSet` YAML schema is the one in spec §2 "Data Models" (keys `language`,
  `aliases`, `summary`, `symbols[].{id,rule,name,signature,doc,parent,exported,async,depth}`,
  `refs[].{rel,rule,target,scope}`, `imports[].rule`). Validate extractor names
  against `EXTRACTORS.keys()` at load.
- `extract()` computes `SymbolRecord.start_line = r.start.line + 1`,
  `end_line = r.end.line + 1`, `start_byte/end_byte = r.start.index/r.end.index`,
  `content_hash = sha1_of_text(node.text())`, `depth` from the spec's `depth`
  key (default 1; `parent` present ⇒ 2), and drops symbols with `depth > max_depth`.
- `named_text(node, "ARGS")` → `", ".join(n.text() for n in node.get_multiple_matches("ARGS") if n.is_named())`.

### References in Codebase
- `languages/treesitter.py` — whole file, the seam pattern.
- `artifacts/ast/astgrep_rules_prototype.py:187-246` — extractor and extraction skeleton that already produces the §4.4 table.
- `artifacts/ast/astgrepstructuralplanedesign.md` §4.1–4.2 — rule schema and loader sketch.

---

## Acceptance Criteria

- [ ] `pytest tests/knowledge/wiki/languages/test_astgrep_seam.py -v` passes with **and** without `ast-grep-py` installed (skip markers for the dependent cases).
- [ ] `supported_language("cobol") is False` and `SgRoot` is never constructed for it (spy).
- [ ] With ast-grep installed: forcing an unregistered language through the whitelist makes `parse()` return `None` and the test process survives.
- [ ] With ast-grep + `tree-sitter-perl`: `supported_language("perl")` is `True` and `parse("package Foo;", "perl").root().find_all(kind="package_statement")` is non-empty; with the `.so` glob monkeypatched to `[]` → `False`, cached, one DEBUG record.
- [ ] `RuleSet.load("nonexistent")` → `None` silently; an invalid YAML (unknown extractor) → `None` + exactly one WARNING.
- [ ] A rule with a nonexistent `kind` is isolated: one WARNING per (language, rule id), other rules still yield symbols.
- [ ] `named_text` yields `"1, b=2"` for `helper(1, b=2)` matched by `helper($$$ARGS)`.
- [ ] `pip install -e "packages/ai-parrot[wiki-structural]"` resolves `ast-grep-py>=0.45`; `python -c "import importlib.resources as r; print(r.files('parrot.knowledge.wiki.languages.rules'))"` works.
- [ ] `ruff check` / `mypy` clean; Google docstrings on every public symbol.

---

## Test Specification

```python
# tests/knowledge/wiki/languages/test_astgrep_seam.py
import pytest
from parrot.knowledge.wiki.languages import astgrep

requires_astgrep = pytest.mark.skipif(not astgrep.is_available(), reason="ast-grep-py not installed")

def test_unsupported_language_short_circuits(monkeypatch):
    calls = []
    monkeypatch.setattr(astgrep, "_sgroot_factory", lambda *a: calls.append(a))
    assert astgrep.parse("x", "cobol") is None and calls == []

@requires_astgrep
def test_panic_fence(monkeypatch):
    monkeypatch.setattr(astgrep, "supported_language", lambda lang: True)
    assert astgrep.parse("x", "definitely-not-a-language") is None

@requires_astgrep
def test_perl_dynamic_registration():
    assert astgrep.supported_language("perl") is True
    root = astgrep.parse("package Foo::Bar;\nsub bar {}\n", "perl").root()
    assert root.find_all(kind="subroutine_declaration_statement")

def test_ruleset_missing_is_none(caplog):
    assert astgrep.RuleSet.load("nope") is None and not [r for r in caplog.records if r.levelname == "WARNING"]
```

---

## Agent Instructions

1. Read spec §2 (Overview, Data Models, New Public Interfaces) and §7 Patterns.
2. Confirm TASK-2738 is in `sdd/tasks/completed/`. 3. Verify the contract with
`grep -n`. 4. Index → `in-progress`. 5. Implement. 6. Run the acceptance pytest
line twice: with and without `ast-grep-py`. 7. Move file to `completed/`.
8. Index → `done`. 9. Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-09-02
**Notes**: Implemented `languages/astgrep.py` per spec — `is_available`,
`supported_language` (whitelist + cached Perl dynamic registration),
`parse` with the `BaseException` fence, `RuleSet` (Pydantic, `SymbolSpec`/
`RefSpec`/`ImportSpec`, `lru_cache`d `load()` resolving aliases and
validating extractor names), the fixed `EXTRACTORS` table, `named_text`,
and `extract()` with per-(language, rule-id) once-only `RuntimeError`
isolation. `ast-grep-py==0.45.3` installed locally
(`uv pip install "ast-grep-py>=0.45"`) so the `requires_astgrep`-marked
tests ran for real (dynamic Perl registration against the installed
`tree-sitter-perl` wheel verified live, not just mocked).
`pytest tests/knowledge/wiki/languages/test_astgrep_seam.py -v` → 12/12
passed (all ast-grep-dependent cases executed, none skipped in this env).
Full `tests/knowledge/wiki/languages` suite (197 tests) and
`tests/knowledge/wiki` (1239 passed, 1 pre-existing unrelated failure in
`test_claude_code.py` verified present before this task's changes too)
unaffected. `ruff check` / `mypy --ignore-missing-imports` clean on all
touched/created files (two `# type: ignore` comments document genuine
`ast_grep_py` stub gaps — an incomplete `CustomLang` TypedDict missing
`extensions`, and the SDK's `find_all` overload being too strict for the
YAML-driven dynamic rule dicts this feature's "rules are pure data"
design requires).
**Deviations from spec**: The exact resolution semantics of the `name`/
`signature`/`parent`/`exported`/`is_async` spec shapes (`field`/`path`/
`text`, `ancestor`, `inside`/`has`) and the qualname joiner per language
(`.` default, `::` for php/rust/perl) are my own reasonable interpretation
of §2's YAML schema — no rule YAML file exists yet to exercise them
end-to-end (that starts at TASK-2742). Flagging so TASK-2742..2746 verify
against real grammars and extend `_resolve_value_spec`/`_resolve_parent`/
`_resolve_bool_spec` if a shape does not match what a real rule file
needs; none of this task's own acceptance criteria depend on those exact
shapes beyond the isolated-bad-kind test (which uses a hand-built
`RuleSet`, not a YAML file).
