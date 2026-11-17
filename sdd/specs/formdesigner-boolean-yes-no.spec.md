---
type: feature
base_branch: dev
projects: [parrot-formdesigner]
tags: [formdesigner, renderers, html5, pdf, boolean]
---

# Feature Specification: Form Designer — boolean questions render as Yes / No (HTML5 + PDF)

**Feature ID**: FEAT-800
**Date**: 2026-11-04
**Author**: Juan (decisions) / Claude (scaffold)
**Status**: approved
**Target version**: next patch release (no bump in this feature — see NG3)

---

## 1. Motivation & Business Requirements

### Problem Statement

The Form Designer's Export panel (navigator-svelte `FormExportPanel.svelte`) gets its HTML and PDF
from `GET /forms/{uid}/render/{format}`, i.e. this package's renderers. A `boolean` question
(NetworkNinja `FIELD_YES_NO`) exports as a bare checkbox (`<input type="checkbox" value="true">`),
while the live form in navigator-svelte has rendered it as two radios **Yes / No** since svelte
FEAT-532 (Aug 2026). Customers reviewing an exported Target Form see checkboxes where reps answer
Yes/No.

### Goals
- G1 (D1) HTML5: a `FieldType.BOOLEAN` renders as a radio group with two options, labels `Yes` / `No`,
  values `"true"` / `"false"`, with the SAME markup/classes as `_render_radio_group`.
- G2 (D2) PDF: a `FieldType.BOOLEAN` prints the question plus two choices `Yes` / `No` — never a
  single bare checkbox.
- G3 Every BOOLEAN path in `HTML5Renderer` (type map, registry entry, form-field branch) produces the radios.

### Non-Goals (explicitly out of scope)
- NG1 `html5.py` REST-field **arguments** form (`arg.data_type == "boolean"`, ~l.1490-1525) is not a
  form question — untouched.
- NG2 `adaptive_card.py` (Teams, `Input.Toggle`) — changing it alters the value Teams submits. Untouched.
- NG3 No version bump / release in this feature; the release is Jesús's call (follow-up).
- D3 The submitted value contract is unchanged: boolean `true`/`false`.

---

## Governing Decisions

<!-- decision-audit: input_digest=sha256:685764b5a8743691cbfca74211cd3476dfa827082f7fb5c964da1580e002dfe4 evaluation_digest=sha256:3e972005f2f28b06d53cf08d1885b4fb16e8db35d228cf72d3d6771aa963885b rules_version=1 status=pass -->

No eligible decisions govern subsystems: none

## 2. Architectural Design

### Overview

**HTML5 (D1).** Reuse `_render_radio_group` by letting it take an optional explicit option list
(or factor a shared private helper it delegates to) — no third markup. For BOOLEAN, a new
`_render_boolean_radio_group(field, value, locale)` normalizes the value to `"true"` / `"false"` /
`""` and renders two options `Yes`(`true`) / `No`(`false`) through the shared markup
(`div.form-field__radio-group > label.form-field__radio-label > input[type=radio][name=field_id]`).
Nothing is checked when the value is `None`; `True`/`"true"`/`"True"`/`1`/`"1"` checks Yes;
`False`/`"false"`/`"False"`/`0`/`"0"` checks No. `required` is emitted on both radios as for the radio
select. The BOOLEAN branch of `_render_field_html` renders the question as the field label above the
group (same `<label class="block text-sm font-medium …">` + optional description `<span>` as the
SELECT branch), not inline. `data-depends-on` emission (wrapper `div`) is unchanged. `_INPUT_TYPE_MAP`
and the `_CheckboxRenderer` registry entry are aligned so the registry `FieldRenderer` path for BOOLEAN
also returns the radio group.

**PDF (D2).** The BOOLEAN branch of `PdfRenderer._render_field` emits two AcroForm radio buttons of
ONE group (`form.radio(name=field_id, value="true"/"false", …)`) with `Yes` / `No` text labels drawn
next to each. ReportLab's `radio()` defaults `fieldFlags` to `'noToggleToOff required radio'` — the
`required` flag must be passed explicitly only for required fields. Prefill is read from the raw
`prefilled` mapping (NOT the stringified `prefilled_value`, because `bool("False")` is `True`).

### Component Diagram
```
FormField(BOOLEAN)
   ├── HTML5Renderer._render_field_html ──→ _render_boolean_radio_group ──→ _render_radio_group (shared markup)
   ├── HTML5Renderer registry (_BooleanRenderer) ──→ _render_boolean_radio_group
   └── PdfRenderer._render_field ──→ form.radio ×2 (+ "Yes"/"No" drawString)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `HTML5Renderer._render_radio_group` | extends (optional `options` arg) | SELECT `render_as: radio` output must stay byte-identical |
| `HTML5Renderer._render_field_html` | modifies BOOLEAN branch | label above group; `data-depends-on` untouched |
| `HTML5Renderer._build_registry` | replaces `_CheckboxRenderer` for BOOLEAN | |
| `PdfRenderer._render_field` | modifies BOOLEAN branch | reportlab `acroForm.radio` |
| navigator-svelte `forms.css` | downstream consumer | targets `form-field__radio-group` / `form-field__radio-label` — keep them |

### Data Models
No new models. `FormField`, `FieldOption(value, label)` reused.

### New Public Interfaces
None public. Private helpers only (see §3).

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: html5 boolean radios | yes | helper names, value normalization table, markup reuse, label branch (below) | — |
| M2: pdf boolean radios | yes | `form.radio` ×2 same name, `fieldFlags`, raw prefill, labels | — |
| M3: html5 tests | yes | assertions listed in §4 | — |
| M4: pdf tests | yes | assert on generated PDF fields/text via `pypdf`, no mocks of reportlab | — |

### Module 1: HTML5 boolean radios
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/html5.py`
- **Responsibility**: BOOLEAN → Yes/No radio group on every HTML5 path.
- **Depends on**: existing `_render_radio_group`, `_resolve`.
- **Interface Skeleton**:
  ```python
  # html5.py (modifies)
  _INPUT_TYPE_MAP[FieldType.BOOLEAN]            # modifies :41 — remove the "checkbox" entry (or map to "radio"); no BOOLEAN path may emit type="checkbox"
  class _BooleanRenderer:                        # replaces _CheckboxRenderer (verified html5.py:199)
      async def render(self_, field, *, locale="en", prefilled=None, error=None) -> Any:
          """Return the Yes/No radio group HTML."""
  # registry: FieldType.BOOLEAN: _BooleanRenderer(self)   # modifies html5.py:351

  _BOOLEAN_OPTIONS = (("true", "Yes"), ("false", "No"))   # module constant

  def _normalize_boolean(value: Any) -> str:
      """Return "true" for True/"true"/"True"/1/"1", "false" for False/"false"/"False"/0/"0", else ""."""

  def _render_radio_group(self, field: FormField, value: Any, locale: str,
                          options: Sequence[FieldOption] | None = None) -> str:   # modifies :1816
      """Existing contract; when `options` is given they replace `field.options`. Default path output unchanged."""

  def _render_boolean_radio_group(self, field: FormField, value: Any, locale: str) -> str:
      """Render Yes/No radios (values "true"/"false") via _render_radio_group using the normalized value."""
  ```
  `_render_field_html` BOOLEAN branch (`:791-796`) becomes: question `<label class="block text-sm font-medium text-gray-700 mb-1">{label_text}</label>`, optional description span, then `self._render_boolean_radio_group(field, value, locale)`. The label must appear exactly once. `_render_checkbox` (`:1698`) has no remaining caller for BOOLEAN; remove it only if nothing else references it (grep first), otherwise leave.

### Module 2: PDF boolean radios
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/pdf.py`
- **Responsibility**: BOOLEAN → two radio widgets + Yes/No text.
- **Depends on**: reportlab `acroForm.radio` (reportlab 4.1.0 in venv).
- **Interface Skeleton**:
  ```python
  # pdf.py  modifies PdfRenderer._render_field BOOLEAN branch (:394)
  # replaces form.checkbox(...) with, for each (value, text) in (("true","Yes"),("false","No")):
  #     form.radio(name=field.field_id, value=value, selected=<raw prefill normalizes to value>,
  #                x=<per-choice x>, y=y, size=4*mm, tooltip=f"{label}: {text}",
  #                fieldFlags="noToggleToOff radio" + (" required" if field.required else ""))
  #     c.drawString(<x + size + gap>, y, text)
  def _boolean_selected(raw: Any) -> str:
      """Return "true"/"false"/"" from the raw (unstringified) prefilled value; same table as HTML5."""
  ```
  `_boolean_selected` may be a small module-level helper in `pdf.py` (do not import from html5 — keep renderers independent; or place the one shared normalizer in `renderers/base.py` only if both modules import it — implementer picks ONE, recorded in the task).

### Module 3: HTML5 tests
- **Path**: `packages/parrot-formdesigner/tests/unit/renderers/test_html5_boolean.py` (new)

### Module 4: PDF tests
- **Path**: `packages/parrot-formdesigner/tests/unit/renderers/test_pdf_boolean.py` (new)

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_boolean_renders_two_radios_yes_no` | M3 | two `input[type=radio]`, labels Yes/No, values `true`/`false`, no `type="checkbox"` |
| `test_boolean_none_checks_nothing` | M3 | prefilled/default `None` → no `checked` |
| `test_boolean_true_checks_yes` / `_false_checks_no` | M3 | True/"true"/1 → Yes; False/"false"/0 → No |
| `test_boolean_required_on_radios` | M3 | `required` present when `field.required` |
| `test_boolean_label_once` | M3 | question label appears exactly once, above the group |
| `test_boolean_depends_on_emitted` | M3 | conditional boolean keeps `data-depends-on` |
| `test_boolean_registry_path_matches` | M3 | `_BooleanRenderer.render` returns radios too |
| `test_select_radio_unchanged` | M3 | SELECT `render_as: radio` output regression (exact string equality vs. pre-change golden) |
| `test_pdf_boolean_has_yes_no_choices` | M4 | `PdfReader.get_fields()` has `field_id` radio group with two kids; page text contains `Yes` and `No`; no checkbox (`/FT /Btn` without radio flag) |
| `test_pdf_boolean_prefill_false_not_selected_yes` | M4 | prefilled `False` selects No, not Yes |
| `test_pdf_boolean_none_selects_nothing` | M4 | no prefill → neither selected |

### Integration Tests
| Test | Description |
|---|---|
| existing `tests/unit/test_renderers.py` BOOLEAN registry-coverage cases | still pass |
| existing `tests/unit/renderers/test_pdf.py` | still pass (its fixture contains a BOOLEAN) |

### Validation Contract

tests:
- packages/parrot-formdesigner/tests/unit/renderers/test_html5_boolean.py
- packages/parrot-formdesigner/tests/unit/renderers/test_pdf_boolean.py
- packages/parrot-formdesigner/tests/unit/renderers/test_pdf.py
- packages/parrot-formdesigner/tests/unit/test_renderers.py
markers: none

### Test Data / Fixtures
```python
@pytest.fixture
def boolean_field() -> FormField:
    return FormField(field_id="has_signage", field_type=FieldType.BOOLEAN, label={"en": "Has signage?"})
```

---

## 5. Acceptance Criteria

- [ ] HTML5: BOOLEAN renders two radios `Yes`/`No` with values `true`/`false`, same markup/classes as the radio select; no `type="checkbox"` for BOOLEAN on any path (registry or form-field).
- [ ] None → nothing checked; True/"true"/"True"/1/"1" → Yes checked; False/"false"/"False"/0/"0" → No checked.
- [ ] `required` emitted when the field is required; question label rendered once above the group; `data-depends-on` unchanged.
- [ ] SELECT `render_as: radio` output unchanged (regression test).
- [ ] PDF: BOOLEAN produces Yes and No choices (two radio widgets of one group + text), never a lone checkbox; prefilled `False` does not select Yes.
- [ ] Submitted value contract unchanged (true/false); `adaptive_card.py` and REST-arguments boolean untouched.
- [ ] `pytest packages/parrot-formdesigner/tests/...` (this package only) passes; `ruff check` clean on changed files.

---

## 6. Codebase Contract

### Verified Imports
```python
from parrot_formdesigner.core.types import FieldType                     # verified: pdf.py:35
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection   # verified: tests/unit/renderers/test_pdf.py:9-14
from parrot_formdesigner.core.options import FieldOption                 # verified: tests/unit/renderers/test_pdf.py:9
from parrot_formdesigner.renderers.pdf import PdfRenderer                # verified: tests/unit/renderers/test_pdf.py:19
from pypdf import PdfReader                                              # verified: tests/unit/renderers/test_pdf.py:7
```
(Source root: `packages/parrot-formdesigner/src/parrot_formdesigner/` — the package is top-level `parrot_formdesigner`, not under `parrot.*`.)

### Existing Class Signatures
```python
# renderers/html5.py
_INPUT_TYPE_MAP[FieldType.BOOLEAN] = "checkbox"                 # line 41
class _CheckboxRenderer: ... render(...) -> self_._r._render_checkbox(field, prefilled)   # lines 199-206
FieldType.BOOLEAN: _CheckboxRenderer(self)                      # line 351
def _render_field_html(...)  # BOOLEAN branch lines 791-796 (inline checkbox label)
def _render_checkbox(self, field, value) -> str                 # line 1698
def _render_radio_group(self, field: FormField, value: Any, locale: str) -> str   # line 1816
    # selected = str(value) if value is not None else ""; compares opt.value == selected
    # emits div.form-field__radio-group.space-y-2 > label.form-field__radio-label > input[type=radio]
def _resolve(value, locale="en") -> str                         # line 107

# renderers/pdf.py
def PdfRenderer._render_field(self, c, section_id, field, cursor_y, locale, prefilled, unsupported, render_warnings=None) -> float   # line 325
    # prefilled_value = str(prefilled[field_id]) if present else ""   (lines ~351-356)  → bool("False") is True!
    # BOOLEAN branch: form.checkbox(name, tooltip, x, y, size=4*mm, checked=bool(prefilled_value))   # lines 394-401
# reportlab 4.1.0: AcroForm.radio(value=None, selected=False, buttonStyle='circle', shape='circle', ..., size=20, x=0, y=0,
#                  tooltip=None, name=None, annotationFlags='print', fieldFlags='noToggleToOff required radio', ...)
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `_render_boolean_radio_group` | `_render_radio_group` | direct call with explicit options | `html5.py:1816` |
| `_BooleanRenderer` | `_render_boolean_radio_group` | registry entry | `html5.py:351` |
| PDF radios | `canvas.acroForm.radio` | `form.radio(...)` ×2 | `pdf.py:394` |

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.formdesigner.*`~~ — the package is `parrot_formdesigner` (no `parrot.` prefix); there is no `renderers/html5` under `parrot/`.
- ~~`HTML5Renderer._render_boolean*`~~ / ~~`_BooleanRenderer`~~ — new in this feature.
- ~~`FieldType.YES_NO`~~ — NetworkNinja `FIELD_YES_NO` maps to `FieldType.BOOLEAN`; no new enum value.
- ~~`formdesigner/tests/...` under `packages/parrot-formdesigner/tests/formdesigner/`~~ is a different test tree; renderer tests live under `tests/unit/` and `tests/unit/renderers/`.
- Existing tests contain NO assertion on `type="checkbox"` for BOOLEAN in html5 (verified by grep).

### Edit Sites (Blueprint Anchors)

Verified against: 6a991940b6 (re-run `grep -c` in `/sdd-task`; anchors may drift).

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/html5.py` | MODIFY | `FieldType.BOOLEAN: "checkbox",` | `html5.py:41` | 1 |
| same | MODIFY | `class _CheckboxRenderer:` | `html5.py:199` | 1 |
| same | MODIFY | `FieldType.BOOLEAN: _CheckboxRenderer(self),` | `html5.py:351` | 1 |
| same | MODIFY | `elif ft == FieldType.BOOLEAN:` | `html5.py:791` | 1 |
| same | MODIFY | `def _render_radio_group(` | `html5.py:1816` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/pdf.py` | MODIFY | `elif field.field_type == FieldType.BOOLEAN:` | `pdf.py:394` | 1 |
| `packages/parrot-formdesigner/tests/unit/renderers/test_html5_boolean.py` | CREATE | — | — | — |
| `packages/parrot-formdesigner/tests/unit/renderers/test_pdf_boolean.py` | CREATE | — | — | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Reuse `_render_radio_group` markup/classes — never a third markup (navigator-svelte CSS depends on `form-field__radio-group` / `form-field__radio-label`).
- Escape nothing new: option values/labels are fixed constants; `field_id` interpolation follows the existing radio-group behaviour.
- `self.logger`, strict type hints, Google docstrings, 120 columns; no `print`.
- Tests: `source .venv/bin/activate`, run `pytest` on `packages/parrot-formdesigner` only (mixing packages gives a spurious `ImportPathMismatchError`); inside a worktree prefix `PYTHONPATH=packages/parrot-formdesigner/src`.

### Known Risks / Gotchas
- Existing bug: PDF `prefilled_value = str(...)`, so `bool("False")` is `True` — the BOOLEAN branch must use the raw prefilled value.
- reportlab `radio()` default `fieldFlags` includes `required`; passing it unconditionally makes optional questions required in PDF viewers.
- `_render_radio_group` compares `opt.value == str(value)`: `str(True)` is `"True"`, so the boolean path must normalize first.
- Radios have no per-field `id`; the `<label for=field_id>` pattern of other branches would point nowhere — use a plain label (as the SELECT radio branch's `for=` also does, keep consistent but not load-bearing).
- Radio groups cannot be unselected once chosen (HTML and PDF `noToggleToOff`); acceptable for Yes/No.
- Labels `Yes`/`No` are English literals (decision D1); i18n is out of scope.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `reportlab` | 4.1.0 (installed) | `acroForm.radio` |
| `pypdf` | installed (used by tests) | assert on generated PDF fields |

### Related
- navigator-svelte has a sibling spec (separate FEAT-ID, its own repo) that restyles `src/lib/styles/forms.css` for this markup and replaces the Export panel's PDF with a print of the Svelte FormBuilder. Its CSS targets `form-field__radio-group` / `form-field__radio-label` — keep them.
- Follow-up (NG3): release/version bump is Jesús's call.

---

## Worktree Strategy

- Isolation: one feature worktree for FEAT-800; each task gets its own sub-worktree.
- Module dependency graph: M3 → M1 (tests import the renderer behaviour M1 adds); M4 → M2. M1 and M2 touch different files and have no edge between them → run concurrently; M3/M4 likewise.
- Shared files: none (html5.py only M1/M3-reads; pdf.py only M2).
- Exclusive resources: none.
- Cross-feature dependencies: none.

---

## Consequences

<!-- decision-audit: input_digest=sha256:685764b5a8743691cbfca74211cd3476dfa827082f7fb5c964da1580e002dfe4 evaluation_digest=sha256:3e972005f2f28b06d53cf08d1885b4fb16e8db35d228cf72d3d6771aa963885b rules_version=1 status=pass -->

Audit status: `pass` (exit 0)

Findings:
- none

Diagnostics:
- `SPEC_BLOCK_MISSING`; path: /home/juanfran/Documents/navigator/AI-BOTS/ai-parrot/sdd/specs/formdesigner-boolean-yes-no.spec.md; message: no fenced yaml block under '## Decisions'

Coverage:
- Subsystems: not recorded
- Unmapped tags: boolean, formdesigner, html5, pdf, renderers
- Targets resolved: 0/0
- Impact complete: true
- Inventory complete: true
- Omitted ids: not recorded

```json
{
  "coverage": {
    "impact_complete": true,
    "inventory_complete": true,
    "omitted_ids": [],
    "subsystems": [],
    "targets_resolved": 0,
    "targets_total": 0,
    "unmapped_tags": [
      "boolean",
      "formdesigner",
      "html5",
      "pdf",
      "renderers"
    ]
  },
  "diagnostics": [
    {
      "code": "SPEC_BLOCK_MISSING",
      "decision_id": null,
      "message": "no fenced yaml block under '## Decisions'",
      "path": "/home/juanfran/Documents/navigator/AI-BOTS/ai-parrot/sdd/specs/formdesigner-boolean-yes-no.spec.md"
    }
  ],
  "evaluation_digest": "sha256:3e972005f2f28b06d53cf08d1885b4fb16e8db35d228cf72d3d6771aa963885b",
  "exit_code": 0,
  "findings": [],
  "input_digest": "sha256:685764b5a8743691cbfca74211cd3476dfa827082f7fb5c964da1580e002dfe4",
  "snapshot": {
    "approvals_digest": "6e5b5a5fb07d04ec7e7cdbf3afac1a634711ea195aa4061a8261bcf61b19992f",
    "config_digest": "sha256:a6bce9c0800713c30eaa78146ad0c06399f6ec0e9b083129e494abb6fd073343",
    "inventory": {},
    "rules_version": 1,
    "structural_revision": "sha256:b11fe8e33d80455017c18de7c66615b790b28eae29c88d3cc6defc398db393fb",
    "taxonomy_digest": "9887c26aa37a5daa626531f2ef465c9f7ef63adf1a9d890eb248ea33c0053dbd"
  },
  "status": "pass"
}
```

## 8. Open Questions

- [x] Labels/values/markup for HTML5 boolean — *Resolved in brief (D1)*: Yes/No, `"true"`/`"false"`, same markup as `_render_radio_group`.
- [x] PDF representation — *Resolved in brief (D2)*: two radio buttons of one group, or two labelled boxes if impractical; reportlab `radio()` is available so radios are used.
- [x] Value contract — *Resolved in brief (D3)*: unchanged boolean true/false.
- [x] Teams `adaptive_card.py` and REST-arguments boolean — *Resolved in brief (NG1/NG2)*: out of scope.
- [x] Version bump — *Resolved in brief (NG3)*: not in this feature.

---

## 9. Design Research Cross-Check

Status: skipped (no accepted brainstorm/proposal; decisions were fixed in the requesting brief)

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-11-04 | Juan / Claude | Initial approved spec from brief |
