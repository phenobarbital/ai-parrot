---
id: F032
query_id: Q007
type: wiki_query
intent: "Follow-up (cross-lane note of F027): the products-found reporting policy for a graphics-only endcap."
executed_at: 2026-11-06T16:20:30Z
duration_ms: 400
parent_id: F027
depth: 2
lanes: [wiki]
merged_from: []
---

# F032 — Documented reporting policy: `products_found` is off for `endcap_no_shelves_promotional` ("zone-only definitions")

## Summary

`wikitoolkit query "products found endcap reporting policy graphics zone"` returns `file:sdd/tasks/completed/TASK-4208-reporting-policy-docs.md` (score 1.00). The task documents the per-type reporting policy: `endcap_backlit_multitier`, `product_on_shelves`, `product_counter` and `graphic_panel_display` report `products_found` by `display_name` with the feature on, while `endcap_no_shelves_promotional` is listed as "off (zone-only definitions)" — "zone-only → [] anyway". An empty product list for these two planograms is therefore the documented behaviour, not a defect. A second query for a zone reference-image / image-similarity rule ("zone reference image similarity graphic correct artwork rule") returned no spec or task planning one; its top hits are the `GraphicPanelDisplay` test and the FlowTask FEAT-004 spec.

## Citations

- path: `sdd/tasks/completed/TASK-4208-reporting-policy-docs.md`
  lines: 117-118
  symbol: `(reporting policy table)`
  wiki: `file:sdd/tasks/completed/TASK-4208-reporting-policy-docs.md` (score 1.00)
  excerpt: |
    | `endcap_backlit_multitier`, `product_on_shelves`, `product_counter`, `graphic_panel_display` | `display_name` | on |
    | `endcap_no_shelves_promotional` | `display_name` | off (zone-only definitions) |
- path: `sdd/tasks/completed/TASK-4208-reporting-policy-docs.md`
  lines: 58-59
  symbol: `(policy comment)`
  excerpt: |
    #   endcap_backlit_multitier, product_on_shelves, product_counter, graphic_panel_display: display_name / True
    #   endcap_no_shelves_promotional: default (display_name / False); zone-only → [] anyway

## Notes

- The task's doc target was `docs/pipelines/planogram-compliance-cycle.md`; after the 2026-11-05 docs move (F010, F026) the document's current location was not checked.
- Absence of a planned zone image-similarity rule is a "no result" from one lexical query, not proof that none is planned anywhere.
