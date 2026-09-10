---
id: F004
query_id: Q004
type: read
intent: Existing AdaptiveCardRenderer: field mapping, submit action, warnings, gaps
executed_at: 2026-09-10T22:27:13Z
duration_ms: 0
parent_id: null
depth: 0
---

# F004 — AdaptiveCardRenderer — what exists and where the gaps are

## Summary
`AdaptiveCardRenderer(AbstractFormRenderer)` (L121-1224) already renders a full FormSchema as Adaptive Card v1.5 JSON for MS Teams: header, sections/subsections, per-field label+input+error, wizard (`render_section`), summary and error cards, i18n, prefilled values. Inputs are keyed `id = field.field_id`. The Submit button is a bare `Action.Submit` with `data: {"_action": "submit"}` — it carries NO form identity, tenant or endpoint reference, so the payload cannot be routed to `POST .../data` by a receiver that lacks dialog state. Upload field types (FILE/IMAGE/IMAGE_DROPZONE/MULTI_UPLOAD) degrade to `Input.Text` showing a filename; only IMAGE_DROPZONE/MULTI_UPLOAD are in `_AC_FALLBACK_TYPES` (FILE/IMAGE degrade silently, no RenderWarning). Buttons use `style: positive/destructive` (ignored by Teams, harmless).

## Citations
- path: `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/adaptive_card.py`
  lines: 1-24
  symbol: module header / imports
  excerpt: |
    """Adaptive Card renderer for FormSchema.
    Migrated and extended from parrot/integrations/msteams/dialogs/card_builder.py.
    Produces valid Adaptive Card JSON (schema v1.5) from FormSchema + StyleSchema."""
    from ..core.file_envelope import UPLOAD_FIELD_TYPES
    from parrot.outputs.cards.spec import DEFAULT_ADAPTIVE_CARD_VERSION
    from .base import AbstractFormRenderer, FallbackRenderer, FieldRenderer
- path: `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/adaptive_card.py`
  lines: 70-91
  symbol: `_FIELD_TYPE_MAPPING`
  excerpt: |
    FieldType.TEXT: "Input.Text", ... FieldType.SELECT: "Input.ChoiceSet",
    FieldType.MULTI_SELECT: "Input.ChoiceSet", ... FieldType.FILE: None, FieldType.IMAGE: None,
- path: `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/adaptive_card.py`
  lines: 95-118
  symbol: `_AC_FALLBACK_TYPES`
  excerpt: |
    SIGNATURE, REMOTE_RESPONSE, AVAILABILITY, REST, FORMULA, TREE_SELECT, SIGNATURE_PAD,
    CREDIT_CARD, IMAGE_DROPZONE, MULTI_UPLOAD, AI_CAPTURE, PLACE   # FILE / IMAGE absent
- path: `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/adaptive_card.py`
  lines: 121-159
  symbol: `AdaptiveCardRenderer.__init__`
  excerpt: |
    SCHEMA_URL = "http://adaptivecards.io/schemas/adaptive-card.json"
    DEFAULT_VERSION = DEFAULT_ADAPTIVE_CARD_VERSION
    CONTENT_TYPE = "application/vnd.microsoft.card.adaptive"
    def __init__(self, version: str | None = None) -> None
- path: `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/adaptive_card.py`
  lines: 182-273
  symbol: `AdaptiveCardRenderer.render`
  excerpt: |
    actions = self._build_form_actions(show_cancel=form.cancel_allowed, submit_label=..., cancel_label=...)
    card = self._wrap_card(body, actions)
    # RenderWarning only for field.field_type in _AC_FALLBACK_TYPES
    return RenderedForm(content=card, content_type=self.CONTENT_TYPE, warnings=warnings)
- path: `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/adaptive_card.py`
  lines: 498-520
  symbol: `AdaptiveCardRenderer._wrap_card`
  excerpt: |
    card = {"type": "AdaptiveCard", "$schema": self.SCHEMA_URL, "version": self.version, "body": body}
    if actions: card["actions"] = actions
- path: `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/adaptive_card.py`
  lines: 689-756
  symbol: `AdaptiveCardRenderer._build_field`
  excerpt: |
    value = prefilled.get(field.field_id, field.default); label TextBlock (+" *" if required),
    description TextBlock, input_elem = self._build_input_element(field, value, locale), error TextBlock
- path: `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/adaptive_card.py`
  lines: 774-777
  symbol: `AdaptiveCardRenderer._build_input_element` (base)
  excerpt: |
    base = {"id": field.field_id, "isRequired": field.required}
- path: `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/adaptive_card.py`
  lines: 1028-1044
  symbol: upload fallback branch
  excerpt: |
    # FEAT-460 — FILE/IMAGE/IMAGE_DROPZONE/MULTI_UPLOAD: no native Adaptive Card upload element
    elif ft in UPLOAD_FIELD_TYPES:
        display_name = _extract_display_name(value) ... thumbnail_url ...
        return {**base, "type": "Input.Text", "placeholder": ..., "value": display_value}
- path: `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/adaptive_card.py`
  lines: 1079-1113
  symbol: `AdaptiveCardRenderer._build_form_actions`
  excerpt: |
    {"type": "Action.Submit", "title": submit_label, "style": "positive", "data": {"_action": "submit"}}
    {"type": "Action.Submit", "title": cancel_label, "style": "destructive", "data": {"_action": "cancel"}, "associatedInputs": "none"}
- path: `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/adaptive_card.py`
  lines: 1115-1189
  symbol: `AdaptiveCardRenderer._build_wizard_actions`
  excerpt: |
    back/skip/cancel/next/submit Action.Submit with data {"_action": ...}

## Notes
`DEFAULT_ADAPTIVE_CARD_VERSION` resolves to `config.get("ADAPTIVE_CARD_VERSION") or "1.4"` (`packages/ai-parrot/src/parrot/outputs/cards/spec.py` L12) — within Teams' "v1.6 or earlier" ceiling (F020).
