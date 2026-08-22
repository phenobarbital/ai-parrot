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
