---
kind: inline
jira_key: null
fetched_at: 2026-09-10T22:19:37Z
summary_oneline: Renderer exporting a FormDesigner Form/Survey definition as an MS Teams-compatible Adaptive Card JSON (interactive inputs + submit action to existing payload endpoint).
---

# Source (inline)

**Slug requested**: `msteams-formdesigner-renderer`

Using the ability of FormDesigner to export a Form or survey in a format using a
renderer, build a renderer to export a Form as an interactive Adaptive Card
compatible with MS Teams. The button for answering the questions must point to
the existing endpoint for sending the form's payload.

For this spec we need to cover the basics of a form in Adaptive Card. In
`ai-parrot-integrations` there is code for rendering input tools as Adaptive
Cards — can we use that code as the example/pattern we are looking for here?

Also check whether pictures can be uploaded in a form exposed as an Adaptive
Card.

The Renderer is responsible for exporting a Form Definition as an Adaptive Card,
but NOT responsible for sending it — it only returns the JSON of the Form.
