# TASK-2021: `<script>` pre-extraction and `lang`-aware grammar selection

**Feature**: FEAT-396 — Svelte / hardened-TypeScript support in the wiki repo scanner
**Spec**: `sdd/specs/wikitoolkit-svelte-typescript-support.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2019, TASK-2020
**Assigned-to**: unassigned

---

## Context

Implements **Module 3** of the spec (§3) — the core of the feature.

Two defects are fixed together here:

1. `outline()` hands the **whole file** to `parser.parse()` (`javascript.py:229` in
   `_outline_treesitter`). A `.svelte` file is not valid TS/JS — the markup breaks the
   tree, and the `except Exception` at `javascript.py:171-173` silently returns an empty
   outline. Measured on a real component: `summary: ''`, outline = 2 garbage lines
   scraped from markup, 0 real symbols (spec §6).
2. The grammar is selected from the **file suffix** (`javascript.py:163-165`), so a
   `.svelte` file — whose suffix is neither `.ts` nor `.tsx` — would fall to the
   JavaScript grammar even though 96% of components in the motivating repo declare
   `<script lang="ts">`.

The fix is a **pre-extraction seam**: before parsing, pull out the `<script>` bodies and
the declared `lang`, then choose the grammar from `lang` rather than the suffix.

Depends on TASK-2019 because `lang`-based selection is inert while
`get_parser("typescript")` returns `None`; depends on TASK-2020 because `.svelte` files
do not reach this scanner until the suffix is claimed.

---

## Scope

- Add a module-level helper
  `_extract_script_blocks(source: str, suffix: str) -> tuple[str, str | None]`:
  - For `.svelte`: return the **concatenated bodies** of every `<script>` block
    (instance **and** `<script module>` / `<script context="module">`), plus the `lang`
    attribute value if declared.
  - For every other suffix: return `(source, None)` **unchanged** — behaviour for
    `.js`/`.jsx`/`.mjs`/`.ts`/`.tsx` must be byte-identical to today.
- Wire it into `outline()` ahead of parsing.
- Replace the suffix-based grammar ternary with `lang`-based selection:
  `lang` in `("ts", "typescript")` → `typescript`; `lang` absent/other → `javascript`;
  **non-Svelte files keep the existing suffix rule** (`.ts`/`.tsx` → `typescript`).
- Extract **imports from the RAW source**, not from the extracted script body. The
  regexes already work on raw Svelte source and this keeps non-Svelte behaviour identical.
- Add the four Module-3 unit tests from spec §4.

Must handle: multiple `<script>` blocks; attributes in any order; `lang='ts'`
single-quoted; self-closing/empty blocks; and a file with **no** `<script>` at all
(empty outline, never raises).

**NOT in scope**:
- Alias resolution / `JsIndex` / `_extract_imports` relaxation — TASK-2022.
- `mode` tightening, docs, pyproject — TASK-2023.
- Parsing Svelte **markup** semantics: component usage as edges, `{#if}`/`{#each}`,
  slots. Only the `<script>` block is analysed (spec §1 Non-Goals).
- `.vue` / `.astro`. The seam is designed to make them cheap later, but they are **not**
  claimed by this spec and must not be added.
- Svelte-semantic special-casing of `export let` vs `export const` — render both, do not
  pretend to know the difference (spec §7).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/languages/javascript.py` | MODIFY | Add `_extract_script_blocks`, rewire `outline()`, `lang`-based grammar selection |
| `tests/knowledge/wiki/languages/test_javascript_plugin.py` | MODIFY | Add the four Module-3 unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED against the working tree on 2026-07-31 (branch `dev`, commit
> `349a184c3`). TASK-2020 will have added `".svelte"` to `suffixes` before this runs —
> re-read the file first.

### Verified Imports

```python
# verified: languages/javascript.py:16-25
from __future__ import annotations
import logging
import re
from collections.abc import Iterable
from pathlib import PurePosixPath
from typing import Any, ClassVar
from parrot.knowledge.wiki.languages import treesitter
from parrot.knowledge.wiki.languages.base import LanguageOutline, LanguageScanner
```

### Existing Signatures to Use

```python
# languages/base.py
class LanguageOutline(BaseModel):          # line 21
    summary: str = ""                      # line 35
    outline: list[str] = Field(...)        # line 36
    imports: list[str] = Field(...)        # line 37

# languages/javascript.py — the method being rewired, lines 149-174 (VERBATIM today):
    def outline(self, source: str, rel_path: str) -> LanguageOutline:
        try:
            imports = _extract_imports(source)
            language = "typescript" if PurePosixPath(rel_path).suffix in (
                ".ts", ".tsx"
            ) else "javascript"                       # <-- lines 163-165, the ternary
            parser = treesitter.get_parser(language)
            if parser is not None:
                summary, lines = self._outline_treesitter(parser, source)
            else:
                summary, lines = self._outline_heuristic(source)
        except Exception as exc:  # noqa: BLE001 - degrade, never raise
            logger.debug("JS/TS outline extraction failed on %s: %s", rel_path, exc)
            return LanguageOutline()
        return LanguageOutline(summary=summary, outline=lines, imports=imports)

# helpers to REUSE, not reimplement
def _extract_imports(source: str) -> list[str]: ...            # line 111
def _outline_heuristic(self, source: str) -> tuple[str, list[str]]: ...   # line 176
def _outline_treesitter(self, parser: Any, source: str) -> tuple[str, list[str]]: ...  # line 222
def _docblock_first_line(doc_body: str) -> str: ...            # line 83
def _find_docblocks(source: str) -> list[tuple[int, int, str]]: ...  # line 92

_SUMMARY_MAX_CHARS = 240                                       # line 29

# languages/treesitter.py
def get_parser(language: str) -> Parser | None: ...            # line 38
```

### Existing regex style to match (line-anchored, bounded — `javascript.py:31-67`)

```python
_RE_DOCBLOCK = re.compile(r"/\*\*(.*?)\*/", re.DOTALL)                       # line 36
_RE_EXPORT_CLASS = re.compile(
    r"^\s*export\s+(?:default\s+)?(?:abstract\s+)?class\s+(\w+)", re.MULTILINE
)                                                                             # lines 38-40
```

### Does NOT Exist

- ~~`tree_sitter_svelte`~~ — not in `_GRAMMAR_MODULES` (`treesitter.py:30-35`), not in
  the `wiki-languages` extra. Svelte is parsed with the **typescript** and **javascript**
  grammars against the extracted `<script>` body. Do not add a Svelte grammar.
- ~~`LanguageScanner.script_block()`~~ / ~~`LanguageScanner.aliases`~~ — no such ABC
  members. The ABC is **frozen** (`base.py:40-114`, plus the TASK-2010 note at
  `languages/__init__.py:78-86`). `_extract_script_blocks` is a **module-level private
  helper**, not an ABC method.
- ~~`LanguageOutline.lang`~~ / ~~`LanguageOutline.script`~~ — the model has exactly three
  fields: `summary`, `outline`, `imports` (`base.py:35-37`). Do not add fields.
- ~~`SvelteScanner`~~, ~~`languages/svelte.py`~~ — do not create.
- ~~`html.parser` / `BeautifulSoup` / `lxml`~~ for the `<script>` extraction — no new
  dependency is introduced by this feature (spec §7 "External dependencies"). Use a
  bounded regex.

---

## Implementation Notes

### Pattern to Follow

```python
#: `<script>` open tag with its attributes, and the lazy body up to `</script>`.
#: Bounded: `[^>]*` cannot cross the tag, `.*?` is lazy and anchored by the
#: required closing literal — no nested quantifiers (see javascript.py:31-34).
_RE_SVELTE_SCRIPT = re.compile(
    r"<script([^>]*)>(.*?)</script\s*>", re.DOTALL | re.IGNORECASE
)
_RE_SCRIPT_LANG = re.compile(r"""lang\s*=\s*['"]([^'"]+)['"]""", re.IGNORECASE)

_SVELTE_SUFFIX = ".svelte"
_TYPESCRIPT_LANGS = frozenset({"ts", "typescript"})


def _extract_script_blocks(source: str, suffix: str) -> tuple[str, str | None]:
    """Concatenated `<script>` bodies and the declared `lang`, for `.svelte`.

    Non-Svelte suffixes return the source unchanged with ``lang=None`` so
    JS/TS behaviour is byte-identical to before this seam existed.
    """
    if suffix != _SVELTE_SUFFIX:
        return source, None
    bodies: list[str] = []
    lang: str | None = None
    for match in _RE_SVELTE_SCRIPT.finditer(source):
        attrs, body = match.group(1), match.group(2)
        if lang is None:
            lang_match = _RE_SCRIPT_LANG.search(attrs)
            if lang_match is not None:
                lang = lang_match.group(1).strip().lower()
        bodies.append(body)
    return "\n".join(bodies), lang
```

Then in `outline()`: keep `imports = _extract_imports(source)` on the **raw** source,
compute `suffix = PurePosixPath(rel_path).suffix`, call the helper, and select:

```python
if suffix == _SVELTE_SUFFIX:
    language = "typescript" if (lang or "") in _TYPESCRIPT_LANGS else "javascript"
else:
    language = "typescript" if suffix in (".ts", ".tsx") else "javascript"
```

…then feed **`script_src`** (not `source`) to `_outline_treesitter` /
`_outline_heuristic`.

### Key Constraints

- **`outline()` must stay non-raising.** The `except Exception` at `javascript.py:171-173`
  is the contract (`base.py:59-61`): degrade to an empty outline, never propagate.
- **Keep regexes line-anchored and bounded.** `<script[^>]*>` with a lazy body is safe;
  a catch-all `.*` across the file is not (`javascript.py:31-34`).
- **The summary must never be the literal `<script lang="ts">` line.** This is an explicit
  acceptance criterion — feeding markup to the summary extractor is exactly the bug.
  A component with no JSDoc gets `""`.
- A markup-only component (no `<script>`) yields an **empty outline and no exception** —
  `_extract_script_blocks` returns `("", None)`, which parses to nothing.
- Everything must still work with the optional extra **absent**: `get_parser` returning
  `None` is a supported state, and the heuristic path must receive the extracted script
  body too (not the raw markup).
- Google-style docstrings + type hints.

### Testing this task

CI on `dev` is red since 2026-07-27 for an **unrelated** `pillow-heif` dependency
conflict that kills `uv sync` before any test runs. Do not fix it, do not wait for green.

```bash
cd packages/ai-parrot/src
SITE_ROOT=~/.local/share/parrot-site ENV=dev PYTHONPATH=. \
  ~/.venvs/parrot-lite/bin/python -m pytest ../../../tests/knowledge/wiki/languages/ -q
```

`SITE_ROOT` is mandatory or navconfig raises `FileExistsError`.

### References in Codebase

- `languages/javascript.py:149-174` — `outline()`, the method to rewire
- `languages/javascript.py:222-294` — `_outline_treesitter`, receives the extracted body
- `languages/javascript.py:176-220` — `_outline_heuristic`, same
- `tests/knowledge/wiki/languages/conftest.py:11-23` — `force_heuristic` fixture, for
  asserting the degraded path deterministically

---

## Acceptance Criteria

- [ ] A `.svelte` file with `<script lang="ts">` yields a **non-empty** `outline`
- [ ] Its `summary` is the leading JSDoc or `""` — **never** the literal
      `<script lang="ts">` line
- [ ] Both instance and `<script module>` / `<script context="module">` bodies are
      included; markup between them is excluded
- [ ] `lang="ts"`, `lang='ts'` and `lang="typescript"` all select the `typescript`
      grammar; an absent `lang` selects `javascript`
- [ ] A markup-only `.svelte` file (no `<script>`) returns an empty outline and does
      **not** raise
- [ ] `export function` / `export const` / `interface` declared inside
      `<script lang="ts">` appear in the outline
- [ ] Imports are still extracted from the raw source (a `.svelte` file's imports are
      unchanged from TASK-2020's behaviour)
- [ ] Behaviour on `.js`/`.jsx`/`.mjs`/`.ts`/`.tsx` is unchanged — existing
      `test_javascript_plugin.py` passes untouched
- [ ] The whole path degrades with tree-sitter unavailable (use `force_heuristic`)
- [ ] Full suite green: `pytest ../../../tests/knowledge/wiki/languages/ -q`
- [ ] No lint errors on `javascript.py`

---

## Test Specification

```python
# tests/knowledge/wiki/languages/test_javascript_plugin.py — ADD

import pytest
from parrot.knowledge.wiki.languages.javascript import (
    JavaScriptScanner,
    _extract_script_blocks,
)

SVELTE_TS = (
    '<script context="module" lang="ts">\n'
    "  export const prerender = true\n"
    "</script>\n"
    '<script lang="ts">\n'
    "  import { helper } from '$lib/util'\n"
    "  export interface Props { label: string }\n"
    "  export function greet(name: string): string { return name }\n"
    "</script>\n"
    "<div class='wrapper'>{label}</div>\n"
)


def test_extract_script_blocks_instance_and_module():
    """Both blocks are concatenated; markup is excluded."""
    body, lang = _extract_script_blocks(SVELTE_TS, ".svelte")
    assert "prerender" in body
    assert "greet" in body
    assert "wrapper" not in body       # markup must not leak in
    assert lang == "ts"


@pytest.mark.parametrize(
    ("attr", "expected"),
    [
        ('lang="ts"', "ts"),
        ("lang='ts'", "ts"),
        ('lang="typescript"', "typescript"),
        ("", None),
    ],
)
def test_extract_script_blocks_lang_variants(attr, expected):
    """`lang` is read regardless of quoting; absent means None."""
    src = f"<script {attr}>\nexport const a = 1\n</script>\n<p>hi</p>\n"
    _body, lang = _extract_script_blocks(src, ".svelte")
    assert lang == expected


def test_extract_script_blocks_non_svelte_passthrough():
    """Non-Svelte suffixes are untouched — byte-identical passthrough."""
    src = "export const a = 1\n"
    assert _extract_script_blocks(src, ".ts") == (src, None)


def test_extract_script_blocks_no_script():
    """A markup-only component yields an empty outline, never an exception."""
    scanner = JavaScriptScanner()
    result = scanner.outline("<div>only markup</div>\n", "src/lib/Plain.svelte")
    assert result.outline == []
    assert result.summary == ""


def test_svelte_outline_exports():
    """Symbols inside `<script lang="ts">` reach the outline."""
    scanner = JavaScriptScanner()
    result = scanner.outline(SVELTE_TS, "src/lib/Widget.svelte")
    assert result.outline, "outline must not be empty for a scripted component"
    rendered = " ".join(result.outline)
    assert "greet" in rendered or "Props" in rendered


def test_svelte_summary_is_not_script_tag():
    """The summary is never the literal `<script …>` line."""
    scanner = JavaScriptScanner()
    result = scanner.outline(SVELTE_TS, "src/lib/Widget.svelte")
    assert "<script" not in result.summary
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** — §2 (step 2 and 3), §3 Module 3, §7
2. **Check dependencies** — TASK-2019 and TASK-2020 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — re-read `outline()`; TASK-2020 changed `suffixes`
4. **Update status** in `sdd/tasks/index/wikitoolkit-svelte-typescript-support.json`
5. **Implement** per scope
6. **Verify** every acceptance criterion
7. **Move this file** to `sdd/tasks/completed/TASK-2021-svelte-script-extraction-lang-grammar.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: Claude Code session (Opus 5), with Emmanuel Arroyo
**Date**: 2026-07-31

**Notes**:

Two module-level helpers plus a rewired `outline()`, all inside `javascript.py`:

- `_extract_script_blocks(source, suffix) -> tuple[str, str | None]` — for
  `.svelte`, the concatenated `<script>` bodies in document order and the declared
  `lang`; for every other suffix, `(source, None)` unchanged.
- `_grammar_for(suffix, lang) -> str` — `.svelte` selects on `lang`, every other
  suffix keeps the original suffix rule verbatim.

`outline()` now extracts imports from the **raw** source (unchanged), then feeds
the **script body** to `_outline_treesitter` / `_outline_heuristic`. The
`except Exception` guard and the never-raising contract are untouched.

Measured on a two-block component:

```
              before (TASK-2020)   after
outline       []                   export const prerender
                                   export function greet: Renders a widget.
                                   export interface Props
summary       ''                   ''      (no file-level JSDoc; never the <script> line)
imports       ['./util']           ['./util']   (unchanged)
```

The JSDoc attached to `greet` survives, and the `<script module>` block's
`prerender` is included — both blocks are analysed, markup is not.

Two design calls worth recording, neither of which the task pinned down:

1. **When blocks disagree on `lang`, a TypeScript declaration wins.** Svelte 5's
   bare `<script module>` carries no `lang`, so first-declaration-wins would have
   demoted a component whose *instance* block is `lang="ts"` down to the
   JavaScript grammar and lost its type-level symbols. The TS grammar also parses
   plain JS, so preferring it cannot lose anything.
   Covered by `test_typescript_declaration_wins_over_undeclared_block`.
2. **The `lang` pattern is anchored with `(?:^|\s)`, not `\b`.** `\blang` also
   matches `data-lang="ts"`, since `-` is a non-word character. Covered by
   `test_lookalike_attribute_not_mistaken_for_lang`.

Regexes follow the file's existing discipline (`javascript.py:31-34`): the lazy
`<script([^>]*)>(.*?)</script\s*>` body is anchored by the required closing
literal and `[^>]*` cannot cross the tag, so there is no nested quantifier.

Tests: 34 added (4 required by the task, plus edge cases the task's "must handle"
list named but did not spell out as tests — attribute order, `lang="TS"` casing,
self-closing `<script />`, empty block, lookalike attribute, per-suffix
passthrough, and the full `_grammar_for` truth table). Both the heuristic path
(`force_heuristic`) and the real tree-sitter path are exercised; the latter runs
rather than skips here, because TASK-2019 made the TypeScript grammar load.
`test_jsts_outline_unchanged_by_the_seam` pins that `.ts` files are unaffected.

Also refreshed this test module's docstring, which claimed the grammar wheels
were "not the case in this dev environment" — stale, they are installed in
`parrot-lite`, and after TASK-2019 they actually load.

Verification (`~/.venvs/parrot-lite`):
- `tests/knowledge/wiki/languages/` — **115 passed, 1 skipped** (81+1 after
  TASK-2020; +34 from this task)
- wider `tests/knowledge/wiki/` — 166 failed / 378 passed, **identical failure
  count to clean `dev`** (166/333)
- `ruff check` on both changed files — **All checks passed**

**Deviations from spec**: none. Scope held to `javascript.py` + its test file; no
alias work, no `mode` change, no `.vue`/`.astro`, no Svelte-semantic special-casing
of `export let` vs `export const` (both render as written).
