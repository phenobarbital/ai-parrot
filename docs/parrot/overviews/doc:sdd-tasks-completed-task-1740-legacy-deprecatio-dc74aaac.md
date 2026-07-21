---
type: Wiki Overview
title: 'TASK-1740: Legacy format deprecation warnings'
id: doc:sdd-tasks-completed-task-1740-legacy-deprecation-warnings-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 12** of the spec (§3, "Legacy deprecation warnings")
  in
relates_to:
- concept: mod:parrot.models.outputs
  rel: mentions
- concept: mod:parrot.outputs.a2ui
  rel: mentions
- concept: mod:parrot.outputs.formats
  rel: mentions
---

# TASK-1740: Legacy format deprecation warnings

**Feature**: FEAT-273 — A2UI Protocol Integration — Rendering Core (parrot.outputs.a2ui)
**Spec**: sdd/specs/a2ui-implementation.spec.md
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1738
**Assigned-to**: unassigned

---

## Context

Implements **Module 12** of the spec (§3, "Legacy deprecation warnings") in
service of goal **G7 — coexist + deprecate**: legacy `OutputMode` formats keep
working unchanged, but the modes replaced by the A2UI pipeline start emitting
`DeprecationWarning` from the single lazy-load choke point, `get_renderer` in
`packages/ai-parrot/src/parrot/outputs/formats/__init__.py`. Each warning names
the concrete A2UI replacement path so callers know where to migrate — which is
why this task depends on TASK-1738 (the replacement wiring must exist to be
pointed at). **Zero behavior change**: rendering output for every legacy mode
stays byte-identical; only warnings are added.

---

## Scope

- Add `DeprecationWarning` emission in `get_renderer`
  (`packages/ai-parrot/src/parrot/outputs/formats/__init__.py:62`) for the
  **replaced modes ONLY**:
  `ALTAIR`, `PLOTLY`, `MATPLOTLIB`, `SEABORN`, `ECHARTS`, `MAP`, `HTML`,
  `TABLE`, `CARD`, `JINJA2`, `TEMPLATE_REPORT`, `STRUCTURED_CHART`,
  `STRUCTURED_TABLE`, `STRUCTURED_MAP`, `APPLICATION` — plus the
  **infographic-HTML path only** (see Implementation Notes: `INFOGRAPHIC` mode
  maps to both `.infographic` (JSON, kept) and `.infographic_html` (replaced);
  the warning must fire on the HTML renderer path, e.g. in
  `get_infographic_html_renderer` (:92) / the `.infographic_html` module, NOT
  on plain `get_renderer(OutputMode.INFOGRAPHIC)`).
- Kept modes get **NO warning**: `JSON`, `YAML`, `MARKDOWN`, `SLACK`,
  `WHATSAPP`, `TERMINAL`, and the infographic-JSON path (plus `DEFAULT`, which
  never reaches `get_renderer`).
- Each warning message names the mode being deprecated AND its A2UI
  replacement (e.g. chart modes → `OutputMode.A2UI` + the Chart catalog
  component; `TEMPLATE_REPORT`/`JINJA2` → Report component; `MAP` → Map
  component; `CARD` → Card/KPICard; `TABLE` → DataTable; `HTML`/`APPLICATION`
  → A2UI SSR-HTML renderer path).
- Add a short docs note listing deprecated modes and replacements (per spec
  Module 12 "docs note").
- Write `test_legacy_modes_unchanged` proving legacy rendering still works AND
  the warning fires for replaced modes, and does NOT fire for kept modes.

**NOT in scope**:
- Removing or altering any legacy renderer's behavior/output (removal is a
  later feature per G7).
- Warnings anywhere other than the `formats` lazy-load seam (no warnings in
  `bots/base.py`, `OutputFormatter`, or handlers).
- Toolkit-level deprecation flags (TASK-1739 owns those).
- Deprecating modes without a registered renderer (`CHART`, `INTERACTIVE`,
  `CODE`, `IMAGE`, etc. — see Does NOT Exist): leave them alone.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/formats/__init__.py` | MODIFY | Warning emission in `get_renderer` + infographic-HTML path |
| `packages/ai-parrot/tests/outputs/test_legacy_deprecation.py` | CREATE | `test_legacy_modes_unchanged` + warning matrix |
| `docs/` (page per repo docs convention) | MODIFY/CREATE | Deprecated-modes → A2UI replacement table |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: Verified 2026-07-10 against `dev`. Use these exact references.
> If anything drifted, re-verify with `grep` before implementing.

### Verified Imports
```python
from parrot.outputs.formats import register_renderer, get_renderer  # formats/__init__.py:47/:62
from parrot.models.outputs import OutputMode                        # models/outputs.py:36
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/outputs/formats/__init__.py
RENDERERS: Dict[OutputMode, Type[Renderer]] = {}      # :16
_MODULE_MAP: dict = { ... }                           # :20 — lazy-load table; entries:
#   TERMINAL, HTML, JSON, MARKDOWN, YAML, CHART, MAP, ALTAIR, STRUCTURED_CHART,
#   STRUCTURED_TABLE, STRUCTURED_MAP, JINJA2, TEMPLATE_REPORT, PLOTLY, MATPLOTLIB,
#   ECHARTS, SEABORN, TABLE, APPLICATION, CARD, WHATSAPP, SLACK,
#   INFOGRAPHIC: ('.infographic', '.infographic_html')   # dual-module entry
def register_renderer(mode: OutputMode, system_prompt: Optional[str] = None)  # :47
def get_renderer(mode: OutputMode) -> Type[Renderer]  # :62 — lazy import via _MODULE_MAP,
    # raises ValueError(f"No renderer registered for mode: {mode}") on miss
def get_output_prompt(mode: OutputMode) -> Optional[str]  # :78 — calls get_renderer internally
def get_infographic_html_renderer()                    # :92 — infographic-HTML-specific seam

# packages/ai-parrot/src/parrot/models/outputs.py:36 — class OutputMode(str, Enum)
# members through STRUCTURED_MAP (:69); TASK-1738 adds A2UI
```

### Does NOT Exist
- ~~A renderer for `OutputMode.CHART`~~ — `_MODULE_MAP` maps `'.chart'` but the
  module registers nothing (base class only); `get_renderer(CHART)` raises
  ValueError today. Do NOT add a warning that changes this into something else.
- ~~`_MODULE_MAP` entries for `INTERACTIVE`, `CODE`, `IMAGE`, `SQL_ANALYSIS`,
  `TELEGRAM`, `MSTEAMS`, `JUPYTER`, `NOTEBOOK`~~ — no renderer entries; out of
  this task's warning matrix.
- ~~A per-mode deprecation mechanism in `formats`~~ — nothing exists today;
  this task creates the (minimal) warning table.
- ~~An "infographic-html" `OutputMode` member~~ — there is one `INFOGRAPHIC`
  mode whose `_MODULE_MAP` entry loads two modules; the HTML/JSON split is a
  renderer-path distinction, not an enum distinction.

---

## Implementation Notes

### Pattern to Follow
- `warnings.warn(msg, DeprecationWarning, stacklevel=2)` at the top of
  `get_renderer` when `mode` is in a module-level frozenset/dict of replaced
  modes; the dict value is the replacement hint string (single source of
  truth for messages).
- Note that `get_output_prompt` / `has_system_prompt` call `get_renderer`
  internally — the warning will also fire through those paths; that is
  acceptable, but keep `stacklevel` meaningful and do not double-warn within
  one call.

### Key Constraints
- **Zero behavior change**: same renderer classes returned, same ValueError on
  unregistered modes, no import-order changes. Only warnings are added.
- Warning text MUST name the A2UI replacement (mode `OutputMode.A2UI` + the
  catalog component or renderer that supersedes it).
- Infographic split: warn only on the HTML path (`get_infographic_html_renderer`
  / `.infographic_html` registration path); `get_renderer(INFOGRAPHIC)` for the
  JSON renderer stays silent.
- Tests must assert both directions: `pytest.warns(DeprecationWarning)` for
  every replaced mode; `warnings.catch_warnings` with `error` filter (or
  equivalent) proving silence for kept modes.

### References in Codebase
- `packages/ai-parrot/src/parrot/outputs/formats/__init__.py:16-110` — the whole seam
- `sdd/proposals/a2ui-outputs-brainstorm.md` — cutover table (replace/keep columns)
- TASK-1738 output — `OutputMode.A2UI` member the messages point at

---

## Acceptance Criteria

- [ ] Every replaced mode listed in Scope emits exactly one
      `DeprecationWarning` per `get_renderer` call, naming its A2UI replacement.
- [ ] Kept modes (`JSON`, `YAML`, `MARKDOWN`, `SLACK`, `WHATSAPP`, `TERMINAL`,
      infographic-JSON path) emit NO warning.
- [ ] Infographic: warning fires on the HTML renderer path only.
- [ ] Legacy rendering output unchanged for all modes (G7) — full existing
      `outputs` test suite green with warnings filtered.
- [ ] `test_legacy_modes_unchanged` passes: legacy rendering still works AND
      warning fires for replaced modes.
- [ ] Docs note added mapping deprecated modes → A2UI replacements.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/outputs/test_legacy_deprecation.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/outputs/formats/__init__.py`

---

## Test Specification

> Minimal scaffold — names and intent only; the agent writes the bodies.

```python
# packages/ai-parrot/tests/outputs/test_legacy_deprecation.py

class TestLegacyDeprecationWarnings:
    def test_legacy_modes_unchanged(self):
        """Replaced modes still resolve to their legacy renderer classes and render
        as before, AND get_renderer emits DeprecationWarning naming the A2UI
        replacement."""

    def test_replaced_mode_warning_matrix(self):
        """Parametrized over ALTAIR/PLOTLY/MATPLOTLIB/SEABORN/ECHARTS/MAP/HTML/TABLE/
        CARD/JINJA2/TEMPLATE_REPORT/STRUCTURED_CHART/STRUCTURED_TABLE/STRUCTURED_MAP/
        APPLICATION: each emits DeprecationWarning whose message contains 'A2UI'."""

    def test_kept_modes_no_warning(self):
        """Parametrized over JSON/YAML/MARKDOWN/SLACK/WHATSAPP/TERMINAL: get_renderer
        emits no DeprecationWarning."""

    def test_infographic_html_path_only_warns(self):
        """get_infographic_html_renderer warns; plain get_renderer(INFOGRAPHIC) for the
        JSON renderer path does not."""

    def test_unregistered_mode_error_unchanged(self):
        """get_renderer still raises ValueError('No renderer registered for mode: ...')
        for modes without a registration (e.g. CHART) — behavior unchanged."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in the per-spec index → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-1740-legacy-deprecation-warnings.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-11
**Notes**: Added `_A2UI_REPLACEMENTS` (single-source-of-truth dict of replaced mode →
A2UI replacement hint) and `_warn_if_deprecated(mode)` to `formats/__init__.py`, called
at the top of `get_renderer` (one `DeprecationWarning` per call, naming the A2UI
replacement). Kept modes are absent from the dict → silent. `get_infographic_html_renderer`
warns for the HTML path only; `get_renderer(OutputMode.INFOGRAPHIC)` (JSON path) stays
silent. Zero behavior change (same classes returned, same ValueError on unregistered
modes). Added docs note `docs/migration/feat-273-a2ui-deprecations.md`. 24 tests pass
(replaced-mode matrix, kept-mode silence, infographic-HTML-only, unregistered-mode
ValueError unchanged).

**Deviations from spec**: A pre-existing `E402` lint error in `formats/__init__.py`
(the `from .base import RenderResult, RenderError` at the file bottom) predates this
change — confirmed present on `dev`. Per the no-scope-creep rule I did NOT fix it
(moving it risks a circular import). All MY additions are ruff-clean; no new lint
introduced.
