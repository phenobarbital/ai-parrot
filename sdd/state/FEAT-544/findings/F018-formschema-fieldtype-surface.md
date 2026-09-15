---
id: F018
query_id: Q018
type: grep
intent: FormSchema / FieldType surface to map
executed_at: 2026-09-10T00:39:55Z
duration_ms: null
parent_id: null
depth: 0
---

# F018 — core: FieldType (47 values), FormField, FormSchema, SubmitAction, FieldConstraints, RenderedForm

## Summary

`FieldType` has 47 members (text, text_area, number, integer, boolean, date, datetime, time, select, multi_select, file, image, color, url, email, phone, password, hidden, group, array, signature, dynamic_select, transfer_list, remote_response, availability, location, tags, nps, likert, ranking, rest, audio, formula, search, masked, color_picker, emoji, cron, tree_select, signature_pad, credit_card, image_dropzone, multi_upload, ai_capture, place). `FormField` carries field_id/field_uid, label (LocalizedString), required, default, read_only, constraints, options, options_source, depends_on, post_depends, children, item_template. `FormSchema` has sections[]→subsections→fields, `submit: SubmitAction{action_type: tool_call|endpoint|event|callback, action_ref, method, confirm_message}`, is_public, tenant, unknown_fields. `FieldConstraints`: min/max_length, min/max_value, step, pattern(+message), min/max_items, mime/size caps, scale_min/max/step, anchor_labels. `RenderedForm{content: Any, content_type, style_output, metadata, warnings}`.

## Citations

- path: `packages/parrot-formdesigner/src/parrot_formdesigner/core/types.py`
  lines: 16-70
  symbol: `FieldType`
- path: `packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py`
  lines: 65-143
  symbol: `FormField`
- path: `packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py`
  lines: 229-256
  symbol: `FormSection`
- path: `packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py`
  lines: 300-314
  symbol: `SubmitAction`
  excerpt: |
    action_type: Literal["tool_call", "endpoint", "event", "callback"]
    action_ref: str
    method: str = "POST"
- path: `packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py`
  lines: 401-475
  symbol: `FormSchema`
- path: `packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py`
  lines: 671-688
  symbol: `RenderedForm`
- path: `packages/parrot-formdesigner/src/parrot_formdesigner/core/constraints.py`
  lines: 21-68
  symbol: `FieldConstraints`
