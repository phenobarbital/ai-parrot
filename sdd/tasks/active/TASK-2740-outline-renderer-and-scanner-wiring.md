# TASK-2740: `render_outline` parity projection and scanner wiring (JS/TS, PHP, Rust, Perl)

**Feature**: FEAT-498 — ast-grep Structural Plane for wikitoolkit
**Spec**: `sdd/specs/ast-grep-for-wikitoolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2739
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 (non-Python half). The rendered `## API outline` must stay
**byte-identical** (resolved decision). This task writes the projection
`render_outline(symbols, language)` that reproduces each walker's exact
strings, wires `astgrep.extract()` as the first tier of the four tree-sitter
scanners, and builds the parity harness the rule tasks will run against.
With no rule files yet, the seam returns `None` and behaviour is unchanged —
the harness must already pass.

---

## Scope

- Create `languages/render.py::render_outline(symbols: list[SymbolRecord], language: str) -> list[str]`
  reproducing, per language, the walkers' emit formats (see contract). Symbols
  the walkers never rendered (TS methods, PHP namespaces, depth > what the
  walker shows) are **skipped** by the renderer.
- Wire `JavaScriptScanner`, `PhpScanner`, `RustScanner`, `PerlScanner`:
  `outline()` → if `config.structural_backend` (read via a module-level
  `structural_enabled()` helper that later tasks may bind to config; default
  `True`) call `astgrep.extract(source, <ast-grep lang>, rel_path)`; on a
  result return `LanguageOutline(summary=..., outline=render_outline(...),
  imports=..., symbols=..., refs=...)`; otherwise unchanged fallback chain.
  JS/TS: after `_extract_script_blocks()`, choose ast-grep lang
  `typescript`/`tsx`/`javascript` by suffix and `<script lang>`.
- `mode` property returns `"ast-grep"` when the seam served the last file.
- Parity harness: `force_no_astgrep` fixture usage + a parametrised
  `test_outline_parity.py` that runs every fixture source through `outline()`
  with and without the seam and asserts `outline`, `summary`, `imports` equal.
  Reuse the existing fixture sources from `test_{javascript,php,rust,perl}*.py`
  and `conftest.polyglot_repo`.

**NOT in scope**: rule YAML content (TASK-2742…2745), Python (`TASK-2741`),
symbol persistence.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/languages/render.py` | CREATE | `render_outline` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/languages/javascript.py` | MODIFY | seam first in `outline()` (:505), `mode` (:747) |
| `packages/ai-parrot/src/parrot/knowledge/wiki/languages/php.py` | MODIFY | seam first in `outline()` (:136), `mode` (:417) |
| `packages/ai-parrot/src/parrot/knowledge/wiki/languages/rust.py` | MODIFY | seam first in `outline()` (:135), `mode` (:416) |
| `packages/ai-parrot/src/parrot/knowledge/wiki/languages/perl.py` | MODIFY | seam first in `outline()` (:204), `mode` (:515) |
| `tests/knowledge/wiki/languages/test_outline_parity.py` | CREATE | Parity harness (parametrised by language + fixture) |
| `tests/knowledge/wiki/languages/test_render.py` | CREATE | Renderer unit tests from hand-built `SymbolRecord`s |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.symbols import SymbolKind, SymbolRecord, SymbolRef, StructuralOutline   # TASK-2738
from parrot.knowledge.wiki.languages import astgrep                                               # TASK-2739
from parrot.knowledge.wiki.languages.base import LanguageOutline, LanguageScanner                 # languages/__init__.py:14
from parrot.knowledge.wiki.languages.treesitter import get_parser                                 # treesitter.py:64
from parrot.knowledge.wiki.languages.javascript import JavaScriptScanner, _extract_script_blocks  # javascript.py:492 / :187
from parrot.knowledge.wiki.languages.php import PhpScanner                                        # php.py:128
from parrot.knowledge.wiki.languages.rust import RustScanner                                      # rust.py:127
from parrot.knowledge.wiki.languages.perl import PerlScanner, _head2_docs                         # perl.py:196 / :118
```

### Existing Signatures to Use
```python
# Each scanner today:  outline() → parser = get_parser(lang) → self._outline_treesitter(parser, source) or self._outline_heuristic(source)
class PhpScanner(LanguageScanner):        # php.py:128  outline :136 ; _outline_heuristic(self, source) -> tuple[str, list[str]] :161 ; _outline_treesitter(self, parser, source) :249 ; mode :417
class RustScanner(LanguageScanner):       # rust.py:127 outline :135 ; _outline_heuristic :159 ; _outline_treesitter :236 ; mode :416
class JavaScriptScanner(LanguageScanner): # javascript.py:492 outline :505 (calls _extract_script_blocks(source, suffix) at :524) ; _outline_heuristic :536 ; _outline_treesitter :582 ; mode :747
class PerlScanner(LanguageScanner):       # perl.py:196 outline :204 (calls _head2_docs(source) :231) ; _outline_heuristic :228 ; _outline_treesitter :297 ; mode :515
def _extract_script_blocks(source: str, suffix: str) -> tuple[str, str | None]   # javascript.py:187 — (script_source, lang)

# EXACT outline line formats the renderer must reproduce (walker emit sites):
# PHP   php.py:291  f"{kind} {cname}: {doc}".rstrip(": ")           kind ∈ class|interface|trait|enum
#       php.py:299  f"    def {fname}({params}): {doc}".rstrip(": ")   method (4-space indent, `def`)
#       php.py:301  f"function {fname}({params}): {doc}".rstrip(": ")  top-level function
# Rust  rust.py:300 f"pub {kind} {name}: {doc}".rstrip(": ")         struct|enum|trait
#       rust.py:304 f"pub mod {name}"
#       rust.py:308 f"impl {name}:"
#       rust.py:293 f"    {sig}: {doc}".rstrip(": ")   fn inside impl ;  rust.py:295 f"{sig}: {doc}" top-level pub fn   (sig = source text of the fn header)
# JS/TS javascript.py:632 f"{prefix}{kind} {name}: {doc}".rstrip(": ")  prefix "export " or "" ; kind ∈ class|function|interface|type
#       javascript.py:642 f"{prefix}const {name}: {doc}".rstrip(": ")
# Perl  perl.py:380 f"package {pname}" ; :389 f"class {cname}: {doc}" ; :396 f"role {rname}: {doc}"
#       perl.py:406 f"    {line}" if in_context else line   (sub) ; :412 f"    {sig}: {doc}" (method) ; :416 f"    field {var_name}" ; :421 f"    has {attr_name}"
# → Read each emit site AND its `sig`/`params` construction before writing render.py. Copy the strings; do not normalise.

# tests/knowledge/wiki/languages/conftest.py — force_heuristic :11, polyglot_repo :69 ; force_no_astgrep added by TASK-2739
```

### Does NOT Exist
- ~~`languages/render.py`~~ — created here.
- ~~rule files under `languages/rules/`~~ — none yet; `astgrep.extract()` returns `None` for all languages until TASK-2742…2745; the wiring must be a no-op in that state.
- ~~`LanguageScanner.outline()` receiving config~~ — the ABC signature is `outline(self, source, rel_path)` and is frozen (TASK-2010); read the kill switch through a module-level helper, not a new parameter.
- ~~a shared "render" helper in the walkers~~ — every walker formats inline; there is nothing to reuse except the string literals above.
- ~~`PythonScanner` wiring~~ — TASK-2741, not here.

---

## Implementation Notes

### Pattern to Follow
```python
def outline(self, source: str, rel_path: str) -> LanguageOutline:
    so = astgrep.extract(source, "php", rel_path) if structural_enabled() else None
    if so is not None:
        self._last_mode = "ast-grep"
        return LanguageOutline(summary=so.summary, outline=render_outline(so.symbols, "php"),
                               imports=so.imports, symbols=so.symbols, refs=so.refs)
    parser = get_parser("php")            # existing chain, untouched below this line
    ...
```

### Key Constraints
- Never change a walker's emitted strings; the renderer conforms to them.
- Order of rendered lines = source order (`start_byte`), containers before
  their members, exactly as the walkers emit.
- Rust: today only `pub` items are rendered except fns inside `impl`; the
  renderer must apply the same filter using `SymbolRecord.exported`/`parent`.
- The parity harness must be **language-parametrised** and easy for the rule
  tasks to extend with new fixture files (`fixtures/structural/<lang>.<ext>`).

### References in Codebase
- `tests/knowledge/wiki/languages/test_{php,rust,javascript}_plugin.py`, `test_perl.py` — fixture sources and expected lines.
- `tests/knowledge/wiki/test_subagent_parity.py` (repo) — parity-test style precedent named in the design.

---

## Acceptance Criteria

- [ ] `pytest tests/knowledge/wiki/languages -v` passes with and without `ast-grep-py`; the new parity harness passes trivially (no rules yet) in both modes.
- [ ] `test_render.py`: hand-built `SymbolRecord` lists reproduce the exact strings at the emit sites listed above for all four languages (including `rstrip(": ")` behaviour with empty doc).
- [ ] `mode` returns `"ast-grep"` only after the seam served a file; returns the previous values otherwise.
- [ ] Wiring adds no behaviour when `astgrep.extract()` is `None` (existing plugin tests unchanged).
- [ ] `ruff` / `mypy` clean.

---

## Test Specification

```python
# tests/knowledge/wiki/languages/test_outline_parity.py
import pytest
from parrot.knowledge.wiki.languages import scanner_for

CASES = [("php", ".php", PHP_SRC), ("rust", ".rs", RUST_SRC), ("javascript", ".ts", TS_SRC), ("perl", ".pm", PERL_SRC)]

@pytest.mark.parametrize("lang,suffix,src", CASES)
def test_outline_parity(lang, suffix, src, monkeypatch):
    scanner = scanner_for(suffix)
    with_seam = scanner.outline(src, f"x{suffix}")
    from parrot.knowledge.wiki.languages import astgrep
    monkeypatch.setattr(astgrep, "is_available", lambda: False)
    without = scanner.outline(src, f"x{suffix}")
    assert (with_seam.outline, with_seam.summary, with_seam.imports) == (without.outline, without.summary, without.imports)
```

---

## Agent Instructions

1. Read spec §2 Overview ("Rendering"), §7 Patterns ("Parity oracle").
2. Confirm TASK-2739 completed. 3. Read the four emit sites before coding.
4. Index → `in-progress`. 5. Implement. 6. Run tests in both modes.
7. Move to `completed/`. 8. Index → `done`. 9. Completion Note.

---

## Completion Note

**Completed by**: —
**Date**: —
**Notes**: —
**Deviations from spec**: none
