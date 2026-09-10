---
id: F020
query_id: Q020
type: git_log
intent: Recent activity on renderers + a2ui catalog
executed_at: 2026-09-10T00:39:55Z
duration_ms: null
parent_id: null
depth: 0
---

# F020 — git log (60 days)

## Summary

25 commits, all by the repo owner. Themes: FEAT-527 infographic→A2UI migration (2026-09-05, HtmlDocument component), FEAT-493 FilterBar lowering (09-02), FEAT formfield-content-type touching audio/jsonschema/xforms renderers (09-01/02), FEAT-470 a2ui-v1-dialect (08-28/29: TASK-2539 parrot catalog moved to catalog/parrot, TASK-2540 build_form + export_catalog_definition), FEAT-458 unknown-fields + FEAT-460 raw upload renderers (08-25/26). Both areas are actively evolving; no conflicting in-flight A2UI form work.

## Citations

- path: `packages/parrot-formdesigner/src/parrot_formdesigner/renderers`
  excerpt: |
    5efc51fa7 2026-09-02 feat(formfield-content-type): make VoiceAnswerEnvelope enforceable
    3c3a64e1e 2026-09-01 TASK-2681 — Audio Renderer reads accept_content_types
    48227a5fd 2026-08-25 TASK-2449 — Other Renderers Update (html5/pdf/adaptive_card)
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot`
  excerpt: |
    1450dda35 2026-09-05 TASK-2863 — HtmlDocument Parrot catalog component + build_html_document()
    74384aba9 2026-08-28 TASK-2540 — build_form(), export_catalog_definition(), builders emit root + catalogId
    2246eaa18 2026-08-28 TASK-2539 — parrot catalog moved to catalog/parrot/, lower() to v1.0 primitives
