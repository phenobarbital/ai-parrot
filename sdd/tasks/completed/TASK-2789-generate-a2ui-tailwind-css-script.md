# TASK-2789: scripts/generate_a2ui_css.py — AST-scan + Tailwind v4 CSS generation with --check mode

**Feature**: FEAT-522 — Interactive-HTML Map Rendering + Tailwind CSS Coverage
**Spec**: `sdd/specs/interactive-html-map-tailwind.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §1 Problem Statement (gap 2): `interactive_html.py` emits base primitive CSS
classes (`.a2ui-text`, `.a2ui-label`, `.a2ui-value`, `.a2ui-col`, `.a2ui-title`,
`.a2ui-heading`, `.a2ui-section`, `.a2ui-chart-wrap`, `.a2ui-table-wrap`, …) that
have zero rules in `DesignSystem.stylesheet()`'s output. Spec §8 resolves this
feature's two deferred open questions: Tailwind **v4** (CSS-first config, no
`tailwind.config.js`/PostCSS needed for `@apply`) and a **Python AST-based**
safelist-generation script, explicitly mirroring the existing
`scripts/generate_tool_registry.py --check` pattern (confirmed at spec time to
be a real, working repo convention: `ast`-based source scanning, `--check`/
`--dry-run`/`--verbose` CLI flags, exit 1 on drift).

This task builds that script. It does NOT wire it into CI (TASK-2791) or into
`DesignSystem.stylesheet()` (TASK-2790) — this task's job is: scan source, run
Tailwind, write the generated CSS file, and support `--check` mode standalone.

## Scope

- Create `scripts/generate_a2ui_css.py`, following `scripts/generate_tool_registry.py`'s
  CLI shape (`argparse`, `--check`, `--dry-run`, `--verbose`):
  - **Scan**: use the `ast` module to parse
    `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/interactive_html.py`
    and extract every literal string constant matching the `a2ui-*`/`ds-*`/
    `kpi-*`/`filter-*`/`msf-*` class-name vocabulary (f-strings built from
    Python constants count too — the spec's brainstorm carry-forward confirms
    "every class is a literal or f-string built from Python constants, never
    user-controlled — greppable directly from the renderer source"). Build a
    sorted, deduplicated safelist.
  - **Generate**: invoke the Tailwind v4 CLI (standalone binary — document the
    exact invocation used, e.g. `npx @tailwindcss/cli` or a pinned standalone
    binary path) against a minimal CSS-first entry file
    (`@import "tailwindcss";`) plus the safelist, to produce utility CSS;
    `@apply` the relevant utilities onto each EXISTING semantic selector from
    the safelist (e.g. `.a2ui-col { @apply flex flex-col gap-2; }`) — the
    exact utility choices per selector are an implementation judgment call
    (match the visual intent implied by each class's existing usage context in
    `interactive_html.py`, e.g. `.a2ui-heading` should look like a heading);
    there is no pre-existing golden CSS to copy from, since this coverage gap
    has never been closed before.
  - **Write**: output to
    `packages/ai-parrot-visualizations/src/parrot/outputs/formats/assets/design_system/tailwind.generated.css`.
  - **`--check` mode**: regenerate the CSS in-memory (same scan + Tailwind
    invocation), compare against the committed file's current content, exit 1
    with a clear diff-style message if they differ, exit 0 if identical. Mirrors
    `generate_tool_registry.py --check`'s "CI mode: exit 1 if stale" contract
    exactly.
  - **`--dry-run`**: print what would be written without writing.
  - **`--verbose`**: print the full scanned class list and Tailwind invocation.
- Markup class names in `interactive_html.py` must NOT change — this script only
  writes `@apply` rules onto existing selectors, never renames anything in the
  renderer source.

**NOT in scope**:
- Wiring `--check` into `.github/workflows/ci.yml` (TASK-2791).
- Wiring the generated file into `DesignSystem.stylesheet()`'s concatenation
  (TASK-2790).
- Extending the AST scan to cover the vendored-asset-name staleness check
  described in spec §3 Module 6 — that's TASK-2791's scope, layered on top of
  this script (may live in the same script file as an additional `--check`
  sub-check, or a separate flag — implementer's call, document the choice in
  the Completion Note).

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `scripts/generate_a2ui_css.py` | CREATE | AST-scan + Tailwind v4 generation + `--check` mode |
| `packages/ai-parrot-visualizations/src/parrot/outputs/formats/assets/design_system/tailwind.generated.css` | CREATE | Generated output, committed |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# scripts/generate_tool_registry.py — the pattern to mirror (verified at spec
# time, re-read the actual file before implementing, it's the reference impl,
# not something to import from):
#   import argparse
#   import ast
#   import sys
#   from pathlib import Path
#   WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
```

### Existing Signatures to Use
```python
# scripts/generate_tool_registry.py CLI contract to mirror (docstring, lines 8-13):
#   python scripts/generate_tool_registry.py              # Update
#   python scripts/generate_tool_registry.py --dry-run     # Show changes without writing
#   python scripts/generate_tool_registry.py --check       # CI mode: exit 1 if stale
#   python scripts/generate_tool_registry.py --verbose     # Verbose output

# Target file to scan (read-only for this script):
# packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/interactive_html.py
# — contains the a2ui-*/ds-*/kpi-*/filter-*/msf-* class vocabulary as Python
# string literals and f-strings, per spec §1 gap 2's exact class list.

# packages/ai-parrot-visualizations/src/parrot/outputs/formats/assets/design_system/__init__.py:32-58
_ASSETS_DIR = Path(__file__).parent
def _read_asset(name: str) -> str | None: ...  # existing pattern this script's OUTPUT feeds
_BASE_CSS: str = _read_asset("base.css") or ""
_COMPONENTS_CSS: str = _read_asset("components.css") or ""
```

### Does NOT Exist
- ~~A Node/Tailwind toolchain already wired into `ai-parrot-visualizations`~~ —
  confirmed absent (spec §6): `pyproject.toml` uses plain
  `setuptools.build_meta`, no build hooks. This script is a standalone,
  CI/dev-time-only tool — never imported by the package at runtime.
- ~~`design_system/tailwind.generated.css` already existing~~ — this task
  creates it for the first time; there is no prior version to diff against on
  first run.
- ~~A `tailwind.config.js` file anywhere in this repo for this feature~~ —
  intentionally not created (Tailwind v4 is CSS-first, spec §2/§8 resolved
  decision).

---

## Implementation Notes

### Pattern to Follow
Mirror `scripts/generate_tool_registry.py`'s overall shape (argparse CLI,
`ast`-based scanning, `--check` exits 1 on drift, `WORKSPACE_ROOT =
Path(__file__).resolve().parent.parent`-style path resolution) — read that file
in full before starting; it is the concrete, working precedent this task
implements the same pattern for, applied to CSS instead of the tool registry.

### Key Constraints
- The Tailwind CLI itself must NOT become a runtime or install-time dependency
  — it only needs to be present in the dev/CI environment when this script
  runs, never imported by `ai-parrot-visualizations`'s own package code.
- Markup class names in `interactive_html.py` are never touched by this script
  — only the generated CSS's selectors change, and those selectors must exactly
  match the EXISTING class names already emitted (verify by cross-referencing
  the scan output against a manual read of `interactive_html.py`'s emitted
  markup).
- Keep the generated CSS's `@apply` rule authorship reasonably minimal/sane per
  selector — this task does not need to achieve pixel-perfect design, only
  real coverage (every emitted class gets SOME sensible rule) — the
  coverage-audit test (TASK-2794) is what enforces completeness, not visual
  fidelity.

### References in Codebase
- `scripts/generate_tool_registry.py` — the CLI/AST-scan pattern to mirror.
- `.github/workflows/ci.yml:29-30` — "Check registry freshness" step, the
  precedent for how this script's `--check` mode will eventually be wired into
  CI (TASK-2791, not this task).
- `packages/ai-parrot-visualizations/src/parrot/outputs/formats/assets/design_system/__init__.py` — the consumer of this task's output (TASK-2790, not this task).

---

## Acceptance Criteria

- [ ] `scripts/generate_a2ui_css.py` exists with `--check`, `--dry-run`,
  `--verbose` flags matching `generate_tool_registry.py`'s contract shape.
- [ ] Running the script (no flags) writes
  `design_system/tailwind.generated.css` containing `@apply`-based rules for
  every literal `a2ui-*`/`ds-*`/`kpi-*`/`filter-*`/`msf-*` class string found
  by the AST scan of `interactive_html.py`.
- [ ] `--check` on a freshly-generated, unmodified file exits 0.
- [ ] `--check` after editing `interactive_html.py` to add a new literal class
  string (without regenerating) exits 1 with a clear message naming the
  drifted class.
- [ ] `--dry-run` writes nothing to disk.
- [ ] Existing markup-substring tests (`test_document_shell.py`,
  `test_interactive_html.py`, `test_semantic_classes.py`) are unaffected — no
  class name renamed anywhere.
- [ ] No linting errors: `ruff check scripts/generate_a2ui_css.py`

---

## Test Specification

```python
# tests (location: co-locate near scripts/ tests if such a convention exists in
# this repo — check for an existing scripts/ test suite location before
# choosing; if none exists, packages/ai-parrot-visualizations/tests/ is the
# fallback since the output CSS lives in that package)
import subprocess
import sys


def test_generate_a2ui_css_check_mode_clean(tmp_path_generated_css_matches_source):
    result = subprocess.run(
        [sys.executable, "scripts/generate_a2ui_css.py", "--check"],
        capture_output=True,
    )
    assert result.returncode == 0


def test_generate_a2ui_css_check_mode_stale(monkeypatched_stale_source):
    result = subprocess.run(
        [sys.executable, "scripts/generate_a2ui_css.py", "--check"],
        capture_output=True,
    )
    assert result.returncode == 1
```

*(Fixture names above are illustrative placeholders — design the actual
fixtures to isolate a temp copy of the scanned source file so the test doesn't
depend on/mutate the real `interactive_html.py`.)*

---

## Agent Instructions

1. Read the spec at `sdd/specs/interactive-html-map-tailwind.spec.md` §2
   Overview (Tailwind paragraph), §3 Module 4, §8 (resolved v4 + AST-script
   decisions).
2. No dependencies — start immediately.
3. Read `scripts/generate_tool_registry.py` in full before writing any code —
   it is the concrete pattern this task must mirror, not a loose inspiration.
4. Update status in the per-spec index → `"in-progress"`.
5. Implement per scope.
6. Verify all acceptance criteria.
7. Move this file to `sdd/tasks/completed/`.
8. Update the per-spec index → `"done"`.
9. Fill in the Completion Note below.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-09-03
**Notes**: Created `scripts/generate_a2ui_css.py` mirroring
`generate_tool_registry.py`'s CLI shape (`--check`/`--dry-run`/`--verbose`).
AST-scan walks every `ast.Constant` string (including f-strings' literal
segments, reached via `ast.walk`'s natural recursion into `ast.JoinedStr`)
and regex-extracts `a2ui-*`/`ds-*`/`kpi-*`/`filter-*`/`msf-*` tokens embedded
anywhere inside the string — module/class/function docstrings are excluded
via an explicit docstring-node-id set, since a prose docstring phrase like
"a live filter-state summary" would otherwise false-positive as the literal
class token `filter-state` (verified this exclusion was necessary: the naive
scan without it found 44 "classes", one of which was never actually emitted
markup). Found 43 real classes in the current `interactive_html.py`. Curated
a `SELECTOR_UTILITIES` per-class `@apply` mapping (Tailwind v4 utilities,
referencing the design system's own existing CSS custom properties —
`--panel-bg`, `--neutral-text`, `--density-gap`, etc. — via arbitrary-value
syntax for visual consistency with `_BASE_CSS`/`_COMPONENTS_CSS`), plus a
`_DEFAULT_UTILITIES = "block"` fallback so any future unmapped class still
gets a deterministic rule (guarantees `--check` never crashes on drift, only
reports it). The Tailwind v4 CSS-first entry imports only
`"tailwindcss/theme"` + `"tailwindcss/utilities"` (NOT the full
`@import "tailwindcss";`, which also pulls in a global `preflight` reset
that would duplicate/conflict with this design system's own `_BASE_CSS`
reset — verified this by direct experimentation: the full import emits a
~150-line preflight block, the theme+utilities-only import does not).
`tailwindcss@^4`/`@tailwindcss/cli@^4` are installed on demand into an
isolated `tempfile.TemporaryDirectory()` (never the repo's own
`node_modules`) so `@import "tailwindcss/theme"` resolves regardless of
ambient Node setup; the locally-installed CLI binary is then invoked
directly. Manually verified all four AC behaviors end-to-end: (1) full run
writes `tailwind.generated.css` with `@apply`-derived rules for all 43
classes, (2) `--check` on the freshly-generated file exits 0, (3) `--check`
after appending a new literal class string to a scratch copy of
`interactive_html.py` (restored immediately after) exits 1 and names the
drifted class (`+ new class(es) not yet covered: a2ui-brand-new-test-class`),
(4) `--dry-run` leaves the committed file's SHA-256 unchanged. Existing
markup-substring tests (`test_document_shell.py`, `test_interactive_html.py`,
`test_semantic_classes.py`) pass unmodified (35/35) — no class name was
renamed. `ruff check scripts/generate_a2ui_css.py` clean. Per the task's own
"NOT in scope" note, the vendored-asset-name staleness sub-check (spec §3
Module 6) is deferred entirely to TASK-2791, not started here.

**Deviations from spec**: none. One implementation note not spelled out in
the task text: `_run_tailwind_cli()` installs the Tailwind v4 npm packages
into an isolated temp directory per invocation (documented in the
function's own docstring) rather than assuming a pre-installed global/repo
`node_modules` — this was necessary because no `tailwindcss` installation
exists anywhere in this repo today (verified), and installing into the
repo's own `node_modules`/lockfiles would have violated the "never a
runtime or install-time dependency of `ai-parrot-visualizations`"
constraint (spec §7).
