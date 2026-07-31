# TASK-2020: Claim the `.svelte` suffix for the JavaScript scanner

**Feature**: FEAT-396 — Svelte / hardened-TypeScript support in the wiki repo scanner
**Spec**: `sdd/specs/wikitoolkit-svelte-typescript-support.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements **Module 2** of the spec (§3). `.svelte` is currently in neither
`CODE_SUFFIXES` (`repo_scan.py:58-66`) nor `JavaScriptScanner.suffixes`
(`javascript.py:143-145`), so in a SvelteKit repo every component is invisible to the
wiki graph — `scanner_for(".svelte")` returns `None` and the file never even reaches a
scanner.

This task is two frozenset entries. After it lands, `.svelte` files get shallow pages
**plus working imports** (the regex extractor already works on raw Svelte source — see
the measured baseline in spec §6, where all 8 relative imports of a real component were
found). The **outline** stays degraded until TASK-2021.

Deliberately kept separate from TASK-2021 so the routing change is reviewable and
revertable on its own.

---

## Scope

- Add `".svelte"` to `CODE_SUFFIXES` in `repo_scan.py`.
- Add `".svelte"` to `JavaScriptScanner.suffixes` in `languages/javascript.py`.
- Add the two unit tests from spec §4 (`test_registry_claims_svelte`,
  `test_code_suffixes_contains_svelte`).

**NOT in scope**:
- `_extract_script_blocks`, `outline()` changes, grammar selection — TASK-2021.
- Alias resolution / `JsIndex` — TASK-2022.
- `mode` changes, docs, pyproject — TASK-2023.
- Editing `_SUFFIX_INDEX` or `_SCANNERS` by hand — `_SUFFIX_INDEX` is a **derived
  comprehension** (`languages/__init__.py:39-43`) and picks the new suffix up
  automatically. Same for `DEFAULT_SUFFIXES` (`repo_scan.py:78`), a set union.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/repo_scan.py` | MODIFY | Add `".svelte"` to `CODE_SUFFIXES` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/languages/javascript.py` | MODIFY | Add `".svelte"` to `JavaScriptScanner.suffixes` |
| `tests/knowledge/wiki/languages/test_registry.py` | MODIFY | Add `test_registry_claims_svelte` |
| `tests/knowledge/wiki/languages/test_repo_scan_integration.py` | MODIFY | Add `test_code_suffixes_contains_svelte` |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED against the working tree on 2026-07-31 (branch `dev`, commit
> `349a184c3`).

### Verified Imports

```python
# verified: languages/__init__.py __all__ / test_registry.py:3-7
from parrot.knowledge.wiki.languages import (
    all_scanners, get_scan_root, scanned_suffixes, scanner_for, set_scan_root,
)
from parrot.knowledge.wiki.languages.javascript import JavaScriptScanner

# verified: repo_scan.py:40-44
from parrot.knowledge.wiki.repo_scan import CODE_SUFFIXES, DEFAULT_SUFFIXES
```

### Existing Signatures to Use

```python
# repo_scan.py — the exact current literal, lines 58-66
CODE_SUFFIXES: frozenset[str] = frozenset({
    ".py", ".pyx", ".pxd", ".pyi",
    ".rs", ".go", ".java", ".kt", ".c", ".h", ".cpp", ".hpp",
    ".js", ".jsx", ".ts", ".tsx", ".mjs",
    ".php",
    ".sql", ".sh", ".bash",
})
DEFAULT_SUFFIXES: frozenset[str] = CODE_SUFFIXES | DOC_SUFFIXES | CONFIG_SUFFIXES  # line 78

# languages/javascript.py — the exact current literal, lines 142-146
class JavaScriptScanner(LanguageScanner):     # line 139
    name: ClassVar[str] = "javascript"
    suffixes: ClassVar[frozenset[str]] = frozenset(
        {".js", ".jsx", ".mjs", ".ts", ".tsx"}
    )

# languages/__init__.py — DERIVED, do not hand-edit
_SUFFIX_INDEX: dict[str, str] = {             # lines 39-43
    suffix: scanner.name
    for scanner in _SCANNERS.values()
    for suffix in scanner.suffixes
}
def scanner_for(suffix: str) -> LanguageScanner | None: ...
def scanned_suffixes() -> frozenset[str]: ...
```

### Does NOT Exist

- ~~`parrot.knowledge.wiki.languages.svelte`~~ — there is no Svelte module and this task
  must **not** create one. The extension lives in `javascript.py` (spec §1 Non-Goals).
- ~~`SvelteScanner`~~ — not a class anywhere in the tree, and not to be added.
- ~~`_SUFFIX_INDEX[".svelte"] = ...`~~ — never assign to it; it is a derived comprehension.
- ~~`register_scanner(...)`~~ / an entry-point plugin registry — registration is the
  explicit `_SCANNERS` dict at `languages/__init__.py:31-36`, which needs **no edit**
  here (`JavaScriptScanner` is already registered).
- ~~`CODE_SUFFIXES.add(".svelte")`~~ — it is a `frozenset`; edit the literal.

---

## Implementation Notes

### Key Constraints

- Two literal edits only. Resist any urge to touch `outline()` in the same task — that
  is TASK-2021 and the whole point of splitting is an isolated, revertable diff.
- `.svelte` belongs in `CODE_SUFFIXES` (category `module`), not `DOC_SUFFIXES`.
- After this task, a `.svelte` file's outline is expected to be **garbage or empty**
  (markup fed to a JS grammar). That is not a bug at this stage — TASK-2021 fixes it.
  Do not write an assertion here that locks in the degraded outline.

### Testing this task

CI on `dev` has been red since 2026-07-27 for an **unrelated** dependency conflict
(`pillow-heif` — `ai-parrot[all]` wants `>=1.3.0`, `flowtask>=5.12.3` pins `==0.22.0`;
`uv sync` fails before any test runs). Do not fix it, do not wait for green. Verify
locally:

```bash
cd packages/ai-parrot/src
SITE_ROOT=~/.local/share/parrot-site ENV=dev PYTHONPATH=. \
  ~/.venvs/parrot-lite/bin/python -m pytest ../../../tests/knowledge/wiki/languages/ -q
```

`SITE_ROOT` is mandatory or navconfig raises `FileExistsError`.

### References in Codebase

- `languages/__init__.py:39-43` — the derived `_SUFFIX_INDEX`
- `repo_scan.py:78` — `DEFAULT_SUFFIXES` union
- `repo_scan.py:809` — edge gating via `PurePosixPath(t).suffix in scanned_suffixes()`
- `tests/knowledge/wiki/languages/test_registry.py` — existing registry test style

---

## Acceptance Criteria

- [ ] `".svelte" in CODE_SUFFIXES`
- [ ] `".svelte" in DEFAULT_SUFFIXES` (derived — assert, don't edit)
- [ ] `scanner_for(".svelte")` returns the `JavaScriptScanner` instance
- [ ] `".svelte" in scanned_suffixes()`
- [ ] No `SvelteScanner` class and no `languages/svelte.py` were created
- [ ] Behaviour on `.js`/`.jsx`/`.mjs`/`.ts`/`.tsx` is unchanged — the existing
      `test_javascript_plugin.py` suite passes untouched
- [ ] Full suite green: `pytest ../../../tests/knowledge/wiki/languages/ -q`
- [ ] No lint errors on both modified source files

---

## Test Specification

```python
# tests/knowledge/wiki/languages/test_registry.py — ADD
from parrot.knowledge.wiki.languages import scanned_suffixes, scanner_for
from parrot.knowledge.wiki.languages.javascript import JavaScriptScanner


def test_registry_claims_svelte():
    """`.svelte` routes to the JS scanner via the derived suffix index."""
    scanner = scanner_for(".svelte")
    assert isinstance(scanner, JavaScriptScanner)
    assert ".svelte" in scanned_suffixes()


# tests/knowledge/wiki/languages/test_repo_scan_integration.py — ADD
from parrot.knowledge.wiki.repo_scan import CODE_SUFFIXES, DEFAULT_SUFFIXES


def test_code_suffixes_contains_svelte():
    """`.svelte` is a code suffix and flows into the default scan set."""
    assert ".svelte" in CODE_SUFFIXES
    assert ".svelte" in DEFAULT_SUFFIXES
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** — §3 Module 2
2. **Check dependencies** — none
3. **Verify the Codebase Contract** — confirm both frozenset literals still match
4. **Update status** in `sdd/tasks/index/wikitoolkit-svelte-typescript-support.json`
5. **Implement** per scope — two literal edits plus tests
6. **Verify** every acceptance criterion
7. **Move this file** to `sdd/tasks/completed/TASK-2020-claim-svelte-suffix.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
