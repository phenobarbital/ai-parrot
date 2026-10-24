# TASK-4688: Picker, login, empty and error cards (M3)

**Feature**: FEAT-734 — Serve FormDesigner forms from a Teams agent
**Spec**: `sdd/specs/formdesigner-serve-forms.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S
**Depends-on**: TASK-4682
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 3**: every card this feature sends except the form itself —
the picker, login prompt, empty state, "no form found", error card, and the
visible `RenderWarning` note. It also owns the routing key
`PICKER_ACTION_KEY = "_formdesigner_action"`.

**Placement decision**: the spec shows `PICKER_ACTION_KEY` in the mixin module,
but the picker card (here) must embed it and the mixin imports this module, so
defining it in the mixin would create an import cycle. It is defined HERE and
re-exported by `formdesigner_mixin.py` (TASK-4691), so
`from …formdesigner_mixin import PICKER_ACTION_KEY` still works as the spec shows.
The wrapper (TASK-4693) imports it from this module, which keeps the wrapper free
of a mixin import.

Depends on TASK-4682 (`FormDescriptor`). Wave 2.

---

## Scope

- Create `formdesigner_cards.py`: `PICKER_ACTION_KEY`, `PICKER_GET_FORM`,
  `build_picker_card`, `build_login_required_card`, `build_empty_forms_card`,
  `build_form_not_found_card`, `build_error_card`, `append_render_warnings`.
- Texts in `en` and `es` (fallback `en`), Adaptive Card `version` default
  `DEFAULT_ADAPTIVE_CARD_VERSION`.
- Picker: one `Input.ChoiceSet` (id `form_uid`, `isRequired`, values = `str(form_uid)`)
  and exactly ONE `Action.Submit` whose `data` is
  `{PICKER_ACTION_KEY: PICKER_GET_FORM, "tenant": tenant}` — never `ENVELOPE_KEY`,
  never `a2ui_token` / `a2ui_action`.
- Write `tests/msteams/test_formdesigner_cards.py`.

**NOT in scope**: sending cards, the wizard control object (mixin), the form card itself.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_cards.py` | CREATE | PICKER_ACTION_KEY + card builders |
| `packages/ai-parrot-integrations/tests/msteams/test_formdesigner_cards.py` | CREATE | M3 unit tests |


---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.outputs.cards.spec import DEFAULT_ADAPTIVE_CARD_VERSION       # verified: parrot/outputs/cards/spec.py:12 (used by msteams/models.py:9)
from parrot_formdesigner.renderers.teams import ENVELOPE_KEY, UPLOAD_WARNING_REASON  # verified: renderers/teams.py:36, :45
from .formdesigner_client import FormDescriptor                           # created by TASK-4682
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/renderers/teams.py
ENVELOPE_KEY: str = "_formdesigner"                                       # line 36 — the picker must NEVER use it
UPLOAD_WARNING_REASON: str = "file/image upload unsupported in Teams cards — web form link rendered"  # line 45
# packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py
class RenderWarning(BaseModel):                                           # line 713
    field_id: str; field_uid: uuid | None; field_type: str; renderer: str; reason: str
# Renderer warnings reach this module as dicts (RenderWarning.model_dump(mode="json")) — read w.get("reason").

# wrapper dispatch order (msteams/wrapper.py): a2ui_token (:508) and a2ui_action (:546) run BEFORE the
#   envelope branch (:576) — a picker carrying either key would be stolen by the A2UI lanes.
```

### Does NOT Exist
- ~~`PICKER_ACTION_KEY`~~ — created here (0 hits today).
- ~~`dialogs/card_builder.py`~~ — removed by TASK-524; do not import it.
- ~~A shared Adaptive Card builder helper for plain cards in msteams~~ — build dicts directly.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_cards.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-integrations/tests/msteams/test_formdesigner_cards.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py#RenderWarning"
  ]
}
```

---

## Implementation Notes

- Card skeleton: `{"type": "AdaptiveCard", "$schema": "http://adaptivecards.io/schemas/adaptive-card.json", "version": version, "body": [...], "actions": [...]}`.
- `build_error_card` text is operator-supplied and must not include exception
  details — callers pass a fixed message; the builder does not inspect exceptions.
- `append_render_warnings` returns a NEW dict (deep-copy the body list) — never mutate the caller's card.

---

## Implementation Blueprint

### Steps (in order)
1. Constants + `_card()` / `_text()` helpers — *why*: every builder shares the skeleton.
2. Picker — *why*: the only card with routing data; its shape is an AC.
3. Static cards and `append_render_warnings`.
4. Tests asserting structure, not prose.

### `packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_cards.py` (CREATE) — part 1
```python
"""Adaptive Cards for FormDesigner form serving (FEAT-734 M3): picker, login, empty, error, warnings."""
from __future__ import annotations

import copy
from typing import Any, Sequence

from parrot.outputs.cards.spec import DEFAULT_ADAPTIVE_CARD_VERSION
from parrot_formdesigner.renderers.teams import UPLOAD_WARNING_REASON

from .formdesigner_client import FormDescriptor

PICKER_ACTION_KEY: str = "_formdesigner_action"  # NEVER "_formdesigner" (ENVELOPE_KEY) — spec §7
PICKER_GET_FORM: str = "get_form"
_SCHEMA = "http://adaptivecards.io/schemas/adaptive-card.json"

_TEXTS: dict[str, dict[str, str]] = {
    "en": {
        "pick_title": "Choose a form", "pick_submit": "Open form",
        "login": "Please sign in with /login to use forms.",
        "empty": "There are no forms available for this workspace.",
        "not_found": "No form found for '{ref}'.",
        "upload_note": "Some fields can't be filled in Teams. Use the web form link to complete them.",
    },
    "es": {
        # FILL IN: Spanish translations for the same keys
    },
}


def _t(key: str, locale: str) -> str:
    lang = (locale or "en").split("-")[0]
    return _TEXTS.get(lang, {}).get(key) or _TEXTS["en"][key]


def _card(body: list[dict[str, Any]], actions: list[dict[str, Any]] | None = None, *,
          version: str = DEFAULT_ADAPTIVE_CARD_VERSION) -> dict[str, Any]:
    card: dict[str, Any] = {"type": "AdaptiveCard", "$schema": _SCHEMA, "version": version, "body": body}
    if actions:
        card["actions"] = actions
    return card


def _text(text: str, **extra: Any) -> dict[str, Any]:
    return {"type": "TextBlock", "text": text, "wrap": True, **extra}


def build_picker_card(
    forms: Sequence[FormDescriptor], *, tenant: str, locale: str = "en",
    version: str = DEFAULT_ADAPTIVE_CARD_VERSION,
) -> dict[str, Any]:
    """Input.ChoiceSet of `forms` + one Submit carrying {PICKER_ACTION_KEY: "get_form", "tenant": tenant}."""
    choices = [{"title": f.title, "value": str(f.form_uid)} for f in forms]
    # FILL IN: body = [_text(pick_title, weight="Bolder"), {"type": "Input.ChoiceSet", "id": "form_uid",
    #   "style": "compact", "isRequired": True, "choices": choices, "value": choices[0]["value"] if choices else None}]
    #   actions = [{"type": "Action.Submit", "title": _t("pick_submit"), "data": {PICKER_ACTION_KEY: PICKER_GET_FORM, "tenant": tenant}}]
    raise NotImplementedError
```

### `formdesigner_cards.py` (CREATE) — part 2 (append)
```python
def build_login_required_card(*, locale: str = "en") -> dict[str, Any]:
    """Explains that /login is required; fetches nothing."""
    return _card([_text(_t("login", locale))])


def build_empty_forms_card(*, tenant: str, locale: str = "en") -> dict[str, Any]:
    """Empty-state card for a tenant with no forms."""
    return _card([_text(_t("empty", locale))])


def build_form_not_found_card(ref: str, *, locale: str = "en") -> dict[str, Any]:
    """A slug/uid that matches nothing — a card, not an error (spec §5)."""
    return _card([_text(_t("not_found", locale).format(ref=ref))])


def build_error_card(message: str, *, locale: str = "en") -> dict[str, Any]:
    """Operator-facing reason; callers never pass a verification-failure reason."""
    return _card([_text(message, color="Attention")])


def append_render_warnings(
    card: dict[str, Any], warnings: Sequence[dict[str, Any]], *, locale: str = "en"
) -> dict[str, Any]:
    """Return a copy of `card` with a visible note when an upload warning is present."""
    # FILL IN: no warnings -> return card unchanged. Any warning yields the note (decided: every RenderWarning
    #   is a degradation the user should see; UPLOAD_WARNING_REASON is just the common case). Deep-copy and append
    #   _text(_t("upload_note"), isSubtle=True, size="Small") to body
    raise NotImplementedError
```
**Why this shape**: the picker's data shape is spec §3 M3's contract; the ChoiceSet id `form_uid` makes Teams merge the choice into `activity.value["form_uid"]`, which is what the mixin reads. `tenant` in the data is informational only — the mixin re-resolves the tenant and never trusts it.

### `packages/ai-parrot-integrations/tests/msteams/test_formdesigner_cards.py` (CREATE)
```python
"""FEAT-734 M3 — card builders."""
import json
import uuid

from parrot_formdesigner.renderers.teams import ENVELOPE_KEY, UPLOAD_WARNING_REASON

from parrot.integrations.msteams.formdesigner_cards import (
    PICKER_ACTION_KEY, append_render_warnings, build_empty_forms_card, build_error_card,
    build_form_not_found_card, build_login_required_card, build_picker_card,
)
from parrot.integrations.msteams.formdesigner_client import FormDescriptor


def _forms():
    return [FormDescriptor(form_uid=uuid.uuid4(), form_id=f"f{i}", title=f"Form {i}") for i in range(2)]


def test_picker_card_choiceset_and_action_key(): ...   # FILL IN: one ChoiceSet, one Submit, PICKER_ACTION_KEY present,
                                                        #   ENVELOPE_KEY/a2ui_token/a2ui_action absent from json.dumps(card)
def test_login_and_empty_cards(): ...                  # FILL IN
def test_append_render_warnings_adds_note(): ...       # FILL IN: original card not mutated
def test_not_found_and_error_cards(): ...              # FILL IN
def test_spanish_locale_falls_back_cleanly(): ...      # FILL IN: "es-MX" uses es; "fr" uses en
```

### FILL IN checklist
- [ ] Spanish texts
- [ ] `build_picker_card` body/actions
- [ ] `append_render_warnings` — any warning → one note; bounded by spec §5 "RenderWarnings are visible in the card"
- [ ] five test bodies

---

## Acceptance Criteria

- [ ] Picker: exactly one `Input.ChoiceSet` and one `Action.Submit`; data carries `PICKER_ACTION_KEY`; serialized card contains no `_formdesigner"`, `a2ui_token`, `a2ui_action`.
- [ ] `append_render_warnings` never mutates its input.
- [ ] `ruff check` clean.

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/msteams/test_formdesigner_cards.py -q`


---

## Test Specification

Five tests in the blueprint (first three are spec §4 M3 rows).

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug formdesigner-serve-forms --feature-id FEAT-734`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/formdesigner-serve-forms.json`
4. **Verify the Codebase Contract** — confirm every import/signature before writing code; never use anything under "Does NOT Exist"
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:` marker, never change a fixed signature or path
7. **Verify** — run the Validation Commands with
   `PYTHONPATH=packages/ai-parrot-integrations/src:packages/ai-parrot/src:packages/parrot-formdesigner/src`
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4688 formdesigner-serve-forms verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any


### Completion Note
Implemented by the sdd-coder pool; merged to the feature branch, file-fidelity gate green, merge-tier validation green, review recorded (0 corrections).
