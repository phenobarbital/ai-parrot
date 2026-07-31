# TASK-2016: Stats surface, wiki-languages extra, and docs update

**Feature**: FEAT-394 — Pluggable Language Scanners for wikitoolkit build
**Spec**: `sdd/specs/wikitoolkit-language-plugins.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2010, TASK-2011, TASK-2012, TASK-2013, TASK-2014, TASK-2015
**Assigned-to**: unassigned

---

## Context

> Spec Module 7. Adds the per-language mode stats block to `wiki_stats.json`
> and `wikitoolkit status`, creates the `wiki-languages` optional extra in
> pyproject.toml (tree-sitter grammar dependencies), updates documentation,
> and runs the polyglot integration test suite.

---

## Scope

- Add a `languages` block to `wiki_stats.json` in `_write_reports()` (cli.py:515-529)
  reporting each scanner's active mode, e.g.
  `{"python": "ast", "php": "tree-sitter", "rust": "heuristic"}`.
- Add the `languages` block to `wikitoolkit status` CLI output.
- Create the `wiki-languages` optional extra in `packages/ai-parrot/pyproject.toml`
  with the grammar dependencies (resolve §8 open question: individual wheels vs
  bundled — verify py3.10-3.12 wheel availability).
- Update `repo_scan.py` module docstring to say "no *required* external parsers"
  (soften the "no external parsers" claim).
- Update `documentation/parrot-wiki-cli.md` to document:
  - Language support table (Python, PHP, JS/TS, Rust, HTML).
  - The `wiki-languages` extra and how to install it.
  - Fallback behavior (heuristic mode when tree-sitter absent).
- Write and run the polyglot integration test (`test_scan_repository_polyglot_fixture`).
- Verify the full existing test suite passes: `pytest tests/knowledge/wiki/ -v`.

**NOT in scope**: any scanner implementation changes (those are TASK-2010–2015).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | `languages` block in `_write_reports` + `status` output |
| `packages/ai-parrot/src/parrot/knowledge/wiki/repo_scan.py` | MODIFY | Module docstring softening |
| `packages/ai-parrot/pyproject.toml` | MODIFY | `wiki-languages` optional extra |
| `documentation/parrot-wiki-cli.md` | MODIFY | Language support docs |
| `tests/knowledge/wiki/languages/test_polyglot_integration.py` | CREATE | Polyglot fixture integration test |
| `tests/knowledge/wiki/languages/conftest.py` | MODIFY | `polyglot_repo` fixture + `force_heuristic` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.knowledge.wiki.languages import all_scanners
# verified: created in TASK-2010
```

### Existing Signatures (verified 2026-07-31)

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:515-529
def _write_reports(output_dir, wiki_name, store_stats, okf_report, graph_stats):
    # Writes wiki_stats.json with keys: wiki_name, generated_at, pages, edges,
    # categories, okf, graph
    # New: add "languages" key

# packages/ai-parrot/pyproject.toml:184-187
# graphindex = [
#     "tree-sitter>=0.23",
#     "tree-sitter-languages>=1.10",
# ]
# wiki-languages extra does NOT exist yet

# packages/ai-parrot/src/parrot/knowledge/wiki/repo_scan.py:1-21
# Module docstring says "no external parsers" — change to "no *required* external parsers"
```

### Does NOT Exist

- ~~`wiki-languages` extra in pyproject~~ — only `graphindex` exists.
- ~~`languages` key in `wiki_stats.json`~~ — only `pages`, `edges`, `categories`, `okf`, `graph`.
- ~~`wikitoolkit status` language reporting~~ — does not exist yet.

---

## Implementation Notes

### Stats Block in `_write_reports()`

```python
# After existing stats dict construction (cli.py ~line 528):
from parrot.knowledge.wiki.languages import all_scanners
stats["languages"] = {name: s.mode for name, s in all_scanners().items()}
```

### `wiki-languages` Optional Extra

Verify py3.10-3.12 wheel availability for these packages before choosing:

**Option A: Individual grammar wheels** (following `graphindex` `tree_sitter_python` precedent):
```toml
wiki-languages = [
    "tree-sitter>=0.23",
    "tree-sitter-php>=0.23",
    "tree-sitter-typescript>=0.23",
    "tree-sitter-javascript>=0.23",
    "tree-sitter-rust>=0.23",
]
```

**Option B: Bundled** (if individual wheels unavailable):
```toml
wiki-languages = [
    "tree-sitter>=0.23",
    "tree-sitter-language-pack>=0.23",
]
```

Check PyPI for wheel availability before deciding. Document the decision.

### `_write_reports` Signature Change

The `_write_reports` function signature does NOT need to change — `all_scanners()`
is imported directly. No new parameter needed.

### Key Constraints

- `cli.py` call sites at `scan_repository(...)` must require NO edits.
- Core install gains zero new required dependencies — `wiki-languages` is optional.
- `documentation/parrot-wiki-cli.md` must document the fallback behavior clearly.

---

## Acceptance Criteria

- [ ] `wiki_stats.json` contains a `languages` block with per-language mode
- [ ] `wikitoolkit status` output includes the languages block
- [ ] `pip install ai-parrot[wiki-languages]` installs grammar dependencies
- [ ] Core install (`pip install ai-parrot`) gains zero new required dependencies
- [ ] `repo_scan.py` docstring updated to "no *required* external parsers"
- [ ] `documentation/parrot-wiki-cli.md` documents language support and the extra
- [ ] Polyglot integration test passes (py+php+ts+rs+html fixture repo)
- [ ] **`pytest tests/knowledge/wiki/ -v` passes entirely** (including existing tests)
- [ ] `ruff check` and `mypy` clean on all new/modified files

---

## Test Specification

```python
# tests/knowledge/wiki/languages/test_polyglot_integration.py
def test_scan_repository_polyglot_fixture(polyglot_repo):
    """Fixture repo with py+php+ts+rs+html: verify pages, outlines, and
    cross-file references edges per language."""
    from parrot.knowledge.wiki.repo_scan import scan_repository
    scan = scan_repository(polyglot_repo)

    # All files scanned
    paths = {fs.rel_path for fs in scan.files}
    assert "src/app.py" in paths
    assert "src/Service.php" in paths
    assert "web/index.ts" in paths
    assert "native/src/lib.rs" in paths
    assert "public/index.html" in paths

    # Language field set correctly
    py_file = next(fs for fs in scan.files if fs.rel_path == "src/app.py")
    assert py_file.language == "python"
    php_file = next(fs for fs in scan.files if fs.rel_path == "src/Service.php")
    assert php_file.language == "php"
    html_file = next(fs for fs in scan.files if fs.rel_path == "public/index.html")
    assert html_file.language is None  # shallow scan, no scanner

    # Cross-file edges exist per language
    edge_pairs = {(s, d) for s, d, _ in scan.import_edges}
    # PHP edges don't resolve to TS files
    for src, dst, _ in scan.import_edges:
        if "php" in src.lower():
            assert "ts" not in dst.lower() and "js" not in dst.lower()

def test_existing_python_regression():
    """Ensure the entire existing test_repo_scan.py passes unchanged."""
    import subprocess
    result = subprocess.run(
        ["python", "-m", "pytest", "tests/knowledge/wiki/test_repo_scan.py", "-v"],
        capture_output=True, text=True
    )
    assert result.returncode == 0, f"Regression: {result.stdout}\n{result.stderr}"

def test_stats_languages_block(polyglot_repo, tmp_path):
    """wiki_stats.json carries per-language mode."""
    import json
    stats_file = tmp_path / "wiki_stats.json"
    # Simulate _write_reports or read from a build
    from parrot.knowledge.wiki.languages import all_scanners
    languages = {name: s.mode for name, s in all_scanners().items()}
    assert "python" in languages
    assert languages["python"] == "ast"
    assert "php" in languages
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — ALL prior tasks (TASK-2010 through TASK-2015) must be done
3. **Verify the Codebase Contract** — re-read cli.py _write_reports, pyproject.toml
4. **Update status** in `sdd/tasks/index/wikitoolkit-language-plugins.json` → `"in-progress"`
5. **Resolve the open question**: check PyPI for grammar wheel availability and choose individual vs bundled
6. **Implement** following the scope, codebase contract, and notes above
7. **Run `pytest tests/knowledge/wiki/ -v`** — EVERYTHING must pass
8. **Verify** all acceptance criteria are met
9. **Move this file** to `sdd/tasks/completed/TASK-2016-stats-extra-docs.md`
10. **Update index** → `"done"`
11. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
