# TASK-2337: A recorded renderer posture for each of the twelve new types

**Feature**: FEAT-448 — field-type-catalog-reconciliation
**Spec**: `sdd/specs/field-type-catalog-reconciliation.spec.md` §4, AC6
**Status**: pending · **Priority**: medium · **Effort**: L
**Depends-on**: TASK-2332, TASK-2335

## Context

Twelve new types across seven renderers is not eighty-four implementations.
Every renderer already has a documented, precedented fallback posture:

```
xforms          unsupported -> ("input","string") with an explicit "# fallback" comment
adaptive_card   a fallback branch already covering SIGNATURE, REMOTE_RESPONSE, AVAILABILITY
pdf             _PDF_FALLBACK_NEW_TYPES -> placeholder textfields
audio, telegram explicit unsupported sets
html5           per-type renderer classes
jsonschema      _TYPE_MAP / _FORMAT_MAP
```

What is required is a CHOICE per type per renderer, written down. "Fallback" is
a legitimate answer. "Nobody looked" is not, and is indistinguishable from it
afterwards — which is why this is its own task with its own AC.

## Scope

For each of `search`, `masked`, `color_picker`, `emoji`, `cron`, `tree_select`,
`signature_pad`, `credit_card`, `image_dropzone`, `multi_upload`, `ai_capture`,
`place`: pick native or fallback in each of the seven renderers and implement
it.

Native is worth it where the channel plausibly serves the type — `place` in
html5 (three selects) and `tree_select` in html5, for instance. Fallback is the
right answer for `ai_capture` in telegram.

`credit_card` never renders its accepted shape as an input in any channel: the
server value is `{brand, last4, name, expiry}` and `last4` is a display value,
not something a renderer should invite a user to type. Read-only display or
unsupported — never an editable card widget generated server-side.

## Acceptance Criteria

- AC1 Every renderer produces output for every one of the twelve without
  raising. Parametrised over the full cross-product, so a missing case fails
  rather than silently defaulting.
- AC2 The choice is recorded per type per renderer — in the unsupported set, in
  the fallback map, or as an implementation. A reader can tell native from
  fallback without running it.
- AC3 A fallback renders as a clearly-labelled placeholder, never as a control
  that looks functional and is not.
- AC4 `credit_card` is not rendered as an editable card widget in any channel.

### Completion Note

Recorded posture per type, per renderer (native unless noted "fallback"):

| type | xforms | adaptive_card | pdf | audio | telegram | html5 | jsonschema |
|---|---|---|---|---|---|---|---|
| search | native `<xf:input>` | native `Input.Text` | fallback | PROMPT_SELECT | fallback (WebApp) | native `<input type=search>` | `string`/`search` |
| masked | native | native | fallback | VOICE (default) | fallback | native `<input type=text>` | `string`/`masked` |
| color_picker | native | native | fallback | PROMPT_SELECT | fallback | native `<input type=color>` | `string`/`color-picker` |
| emoji | native | native | fallback | VOICE (default) | fallback | native `<input type=text>` | `string`/`emoji` |
| cron | native | native | fallback | VOICE (default) | fallback | native `<input type=text>` | `string`/`cron` |
| tree_select | native `<xf:select>` | fallback | fallback | VISUAL_FALLBACK | fallback | native (flat multi-select, `data-tree-select`) | `array`/`tree-select` |
| signature_pad | fallback | fallback | fallback | VISUAL_FALLBACK | fallback | native (reuses SIGNATURE's canvas) | `string`/`signature-pad` |
| credit_card | fallback | fallback | fallback | VISUAL_FALLBACK | fallback | **fallback — disabled placeholder, never editable** | `object`/`credit-card` w/ `{brand,last4,name,expiry}` |
| image_dropzone | fallback | fallback | fallback | VISUAL_FALLBACK | fallback | fallback (disabled placeholder — no upload endpoint) | `object`/`image-dropzone` |
| multi_upload | fallback | fallback | fallback | VISUAL_FALLBACK | fallback | fallback (disabled placeholder — no upload endpoint) | `array`/`multi-upload` |
| ai_capture | fallback | fallback | fallback | VISUAL_FALLBACK | fallback | fallback (disabled placeholder — shape not ours) | `object`/`ai-capture` |
| place | fallback | fallback | fallback | VISUAL_FALLBACK | fallback | native (3 cascading `<select>`s: country populated via pycountry; state/city empty, client-populated via `data-cascade-parent`) | `object`/`place` w/ `{country,state,city}` |

Rationale for each posture, and the exact recorded set/map touched, is in the
per-file `FEAT-448 (TASK-2337)` comments:
- `xforms.py` — `_FIELD_TO_XFORMS` (native tuple or `# fallback` comment).
- `adaptive_card.py` — the text-like `if ft in (...)` tuple (native) and
  `_AC_FALLBACK_TYPES` (fallback, RenderWarning via existing mechanism).
- `pdf.py` — `_PDF_FALLBACK_NEW_TYPES` (all twelve; no AcroForm widget kind
  matches any of the twelve shapes).
- `audio.py` — `_PROMPT_SELECT_TYPES` / `_VISUAL_FALLBACK_TYPES`; masked/
  emoji/cron left to the documented VOICE default (plain scalar strings,
  same posture as TEXT/PHONE).
- `telegram/renderer.py` — `_WEBAPP_FIELD_TYPES` (all twelve; none fits an
  inline-keyboard choice).
- `html5.py` — `_INPUT_TYPE_MAP` additions (search/masked/color_picker/
  emoji/cron), new `_render_tree_select`/`_render_place` methods, reuse of
  `_render_signature` for signature_pad, and `_HTML5_FALLBACK_TYPES` +
  `_render_unsupported_placeholder` (disabled/readonly, `RenderWarning`
  emitted in `render()`) for image_dropzone/multi_upload/ai_capture/
  credit_card.
- `jsonschema.py` — `_TYPE_MAP`/`_FORMAT_MAP` entries for all twelve, plus
  explicit `properties` blocks for `credit_card` (server-accepted shape
  only — no `cvv`/`number`) and `place` (`country` required).

AC4 (`credit_card` never editable): verified per-renderer — xforms/
adaptive_card/pdf/audio/telegram all treat it as fallback (audio: not
voiceable; the rest: text-placeholder, never a card-input widget); html5
renders it via the shared disabled/readonly placeholder helper, same as
image_dropzone/multi_upload/ai_capture — `test_html5_task2337_credit_card_never_editable`
asserts `disabled` is present in the output and a RenderWarning is emitted.

New tests: `test_renderers.py` — 15 new tests covering the full
(type × renderer) cross-product per AC1 (parametrised so a missing case
fails, not silently defaults) and AC2 (asserts the specific recorded
set/map membership, not just "renders without raising").
`test_audio_form_renderer.py::TestClassifyVoiceMode` — extended the three
existing parametrised lists (`test_voice_types`, `test_prompt_select_types`,
`test_visual_fallback_types`) with the twelve types' audio classification.

Verification: `PYTHONPATH=.../packages/parrot-formdesigner/src pytest
tests/unit/test_renderers.py tests/formdesigner/test_audio_form_renderer.py -q`
→ 114 passed. Full `tests/unit` run: 31 failed, 18 errors (49 total,
identical set to the pre-existing baseline) — confirmed by diffing against
a `git stash` run of the same suite (346→358 passed in
`tests/formdesigner`+`tests/integration`, same 1 failed/63 errors on both
sides — the 12-test delta is exactly the new audio classification tests;
the errors are pre-existing `aiohttp_client` fixture/DB-dependent
integration tests, unaffected by this change).

Noted, not fixed (out of scope for this task): `tests/unit/test_core_models.py
::test_field_type_enum_total_count` hardcodes `len(FieldType) == 32` and
already fails at 45 (pre-existing, from TASK-2332/2335's enum growth, not
from this task). `tests/unit/api/test_form_controls_endpoint.py` and
`tests/integration/test_form_controls_contract.py` assert the served
`/api/v1/form-controls` catalog covers `len(FieldType)` exactly — that
catalog is TASK-2338's subject, not this one's.
