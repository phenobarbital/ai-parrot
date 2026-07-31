# TASK-2012: repo_scan.py integration — registry-driven file slicing and per-language edge resolution

**Feature**: FEAT-394 — Pluggable Language Scanners for wikitoolkit build
**Spec**: `sdd/specs/wikitoolkit-language-plugins.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2010, TASK-2011
**Assigned-to**: unassigned

---

## Context

> Spec Module 3. Modifies `repo_scan.py` to consult the language scanner
> registry instead of the hardcoded Python-only branch. Adds the `language`
> field to `FileSlice`, extends suffix sets, adds an HTML `<title>` summary
> helper, and generalizes the incremental fast-path. Public API stays frozen.

---

## Scope

- Add optional `language: Optional[str] = None` field to `FileSlice` (line 132).
- Replace the hardcoded `if suffix in {".py", ".pyi"}` branch in
  `build_file_slice()` (line 551) with a registry lookup:
  `scanner = scanner_for(suffix)` → if scanner, call `scanner.outline()`.
- Set `FileSlice.language = scanner.name` when a scanner is used.
- Rewrite `build_import_edges()` to group files by `language`, build each
  language's reference index once, and resolve each file's imports via
  the per-language scanner. Unresolvable specifiers are dropped (no dangling edges).
- Generalize the incremental fast-path in `scan_repository()` (line 749):
  replace `{".py", ".pyi"}` with `scanned_suffixes()` so changed `.php`/`.ts`/`.rs`
  files also trigger repo-wide discovery.
- Add `.php` to `CODE_SUFFIXES` (line 43).
- Add `.html`, `.htm` to `DOC_SUFFIXES` (line 51).
- Add `_html_title_summary(content) -> str` helper (separate from
  `_markdown_summary`) for extracting `<title>` or first heading from HTML.
- Wire the HTML summary into the `DOC_SUFFIXES` branch of `build_file_slice()`.
- Keep `_python_outline` and `_module_index` as thin wrappers delegating to
  `PythonScanner` (for any external callers), or remove if grep confirms no
  external callers besides `build_file_slice` and `build_import_edges`.
- Wrap scanner.outline() calls defensively: parse failures → shallow page
  (log warning, no exception).
- Ensure **all existing `tests/knowledge/wiki/test_repo_scan.py` pass unchanged**.

**NOT in scope**: PHP/JS/Rust plugins (TASK-2013–2015), CLI stats (TASK-2016).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/repo_scan.py` | MODIFY | Registry integration, FileSlice.language, suffix sets, HTML helper, fast-path |
| `tests/knowledge/wiki/languages/test_repo_scan_integration.py` | CREATE | Integration tests for the new behavior |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.knowledge.wiki.languages import scanner_for, scanned_suffixes, all_scanners
# verified: created in TASK-2010

from parrot.knowledge.wiki.languages.base import LanguageOutline
# verified: created in TASK-2010
```

### Existing Signatures (verified 2026-07-31)

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/repo_scan.py
CODE_SUFFIXES: frozenset[str]     # line 43 — NO .php currently
DOC_SUFFIXES: frozenset[str]      # line 51 — {".md", ".rst", ".txt"}, NO .html/.htm

class FileSlice(BaseModel):       # line 132
    rel_path: str
    record: WikiPageRecord
    imports: list[str]
    # NO language field yet

def build_file_slice(root, rel_path, body_max_chars=16_000, max_file_bytes=524_288) -> Optional[FileSlice]:
    # line 517 — contains hardcoded `if suffix in {".py", ".pyi"}` at line 551

def build_import_edges(files, index_paths=None) -> list[tuple[str, str, str]]:
    # line 669 — calls _module_index() (Python-only) at line 690

def scan_repository(root, suffixes=None, exclude_dirs=None, ...):
    # line 711 — incremental fast-path at line 749: `{".py", ".pyi"}`

def _python_outline(source) -> tuple[str, list[str], list[str]]:  # line 425
def _module_index(rel_paths) -> dict[str, str]:                    # line 644
def _markdown_summary(content: str) -> str:                        # line 469
def _category_for(rel_path: str) -> str:                           # line 415
```

### Does NOT Exist

- ~~`FileSlice.language`~~ — field does not exist yet; this task adds it.
- ~~`_html_title_summary()`~~ — does not exist; this task creates it.
- ~~any non-Python outline/import in `repo_scan.py`~~ — Python `ast` only today.

---

## Implementation Notes

### Key Changes in `build_file_slice()` (line 551 area)

```python
# BEFORE (line 551):
if suffix in {".py", ".pyi"}:
    summary, outline, imports = _python_outline(content)
    ...

# AFTER:
scanner = scanner_for(suffix)
if scanner is not None:
    try:
        lang_out = scanner.outline(content, rel_path)
        summary = lang_out.summary or f"{scanner.name.title()} module {rel_path}"
        outline_lines = lang_out.outline
        imports = lang_out.imports
    except Exception:
        logger.warning("Scanner %s failed on %s, falling back to shallow", scanner.name, rel_path)
        summary = _first_line(content) or rel_path
    else:
        if outline_lines:
            sections.append("## API outline\n" + "\n".join(outline_lines))
elif suffix in DOC_SUFFIXES:
    ...
```

### Key Changes in `build_import_edges()` (line 669 area)

```python
# Group files by language; build per-language reference indexes
by_lang: dict[str, list[FileSlice]] = {}
for fs in files:
    if fs.language:
        by_lang.setdefault(fs.language, []).append(fs)

for lang_name, lang_files in by_lang.items():
    scanner = all_scanners().get(lang_name)
    if not scanner:
        continue
    index = scanner.build_reference_index(index_paths or [f.rel_path for f in files])
    for fs in lang_files:
        src = file_concept_id(fs.rel_path)
        for spec in fs.imports:
            target = scanner.resolve_import(spec, fs.rel_path, index)
            if target and target != fs.rel_path:
                edges.add((src, file_concept_id(target), "references"))
```

### HTML Summary Helper

```python
def _html_title_summary(content: str) -> str:
    # Extract <title>...</title> or first <h1>...<h6> text
    # Regex-based, no external parser needed
    import re
    m = re.search(r"<title[^>]*>(.*?)</title>", content, re.IGNORECASE | re.DOTALL)
    if m:
        return m.group(1).strip()
    m = re.search(r"<h[1-6][^>]*>(.*?)</h[1-6]>", content, re.IGNORECASE | re.DOTALL)
    if m:
        return re.sub(r"<[^>]+>", "", m.group(1)).strip()
    return ""
```

### Key Constraints

- **Public API frozen**: signatures of `build_file_slice`, `build_import_edges`,
  `scan_repository`, `FileSlice`, `RepoScan` must not change (additive fields only).
- **Existing tests must pass unchanged**: `tests/knowledge/wiki/test_repo_scan.py`.
- `_markdown_summary()` is frontmatter-aware (PR #1081) — do NOT extend it for HTML.
- Parse failures must degrade to shallow page, never raise.
- POSIX rel-paths throughout (match existing style).

---

## Acceptance Criteria

- [ ] `FileSlice` has an optional `language` field
- [ ] `build_file_slice()` on a `.py` file sets `language="python"` and produces identical output
- [ ] `build_file_slice()` on an `.html` file produces a shallow page with `<title>`-based summary
- [ ] `.php` is in `CODE_SUFFIXES`; `.html`/`.htm` are in `DOC_SUFFIXES`
- [ ] `build_import_edges()` groups by language and uses per-language resolvers
- [ ] Incremental fast-path triggers on changed `.php`/`.ts`/`.rs` (not just `.py`)
- [ ] Parse failure → shallow page, no exception
- [ ] Mixed-language indexes are isolated (PHP `require` never resolves to a `.ts` file)
- [ ] **`pytest tests/knowledge/wiki/test_repo_scan.py -v` passes UNCHANGED**
- [ ] `pytest tests/knowledge/wiki/languages/test_repo_scan_integration.py -v` passes
- [ ] `ruff check packages/ai-parrot/src/parrot/knowledge/wiki/repo_scan.py`

---

## Test Specification

```python
# tests/knowledge/wiki/languages/test_repo_scan_integration.py
def test_parse_failure_degrades_shallow(tmp_path):
    # Write a .py file with invalid syntax, verify shallow page returned
    ...

def test_html_shallow_title_summary(tmp_path):
    # Write an .html file with <title>, verify summary extracted
    ...

def test_mixed_language_indexes_isolated(tmp_path):
    # PHP require should not resolve to a .ts file
    ...

def test_incremental_fastpath_generalized(tmp_path):
    # Changed .php triggers full discovery; docs-only does not
    ...

def test_fileslice_language_field(tmp_path):
    # .py file → language="python"; .html → language=None
    ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2010 and TASK-2011 must be done
3. **Verify the Codebase Contract** — re-read repo_scan.py line numbers
4. **Update status** in `sdd/tasks/index/wikitoolkit-language-plugins.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Run `pytest tests/knowledge/wiki/test_repo_scan.py -v`** — MUST pass unchanged
7. **Verify** all acceptance criteria are met
8. **Move this file** to `sdd/tasks/completed/TASK-2012-repo-scan-integration.md`
9. **Update index** → `"done"`
10. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
