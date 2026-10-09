---
id: FEAT-648
title: products_found for every product-detecting planogram type (endcap, shelves), not only ink_wall
slug: products-found-endcap
type: feature
mode: enrichment
status: review
source:
  kind: inline
  jira_key: null
  jira_url: null
  fetched_at: 2026-10-09
  summary_oneline: Fill products_found for every product-detecting planogram type (Endcap etc.), not only ink_wall
overall_confidence: high
base_branch: dev
projects: [ai-parrot-pipelines, docs]
tags: [planogram, products-found, endcap, reporting-policy, slot-presence]
research_state: sdd/state/FEAT-648/
created: 2026-10-09
updated: 2026-10-10
---

# FEAT-648 — `products_found` for every product-detecting planogram type

> **Mode**: enrichment
> **Confidence**: high
> **Source**: `inline` (slug requested: `products_found_endcap`)
> **Audit**: [`sdd/state/FEAT-648/`](../state/FEAT-648/)

---

## 0. Origin

The original request, preserved verbatim (`sdd/state/FEAT-648/source.md`):

> Ahora que incorporamos "products_found" como columna en el planogram
> (ai-parrot-pipelines, PlanogramCompliance) para el planogram_type ink_wall, la
> idea es agregar también para otros planogram, por ejemplo para el Endcap, donde
> con imágenes de referencia buscamos impresoras, pues llenar products_found con
> idéntica estructura para saber si una impresora se encontró (o no), en general
> para un planogram que detecta productos, "products_found" debería siempre
> llenarse con los productos encontrados (o no)

**Initial signals** (extracted, not interpreted):
- Verbs: "agregar", "llenar", "debería siempre llenarse" → feature extension, positive polarity
- Named entities: `products_found`, `PlanogramCompliance`, `ai-parrot-pipelines`, `ink_wall`, Endcap, reference images, printers
- Components / labels: planogram compliance pipeline; downstream column consumer (flowtask)
- Acceptance criteria provided: no (one implicit: "idéntica estructura" — same `SlotPresence` shape)

---

## 1. Synthesis Summary

`products_found` is already computed in the shared compare stage
`compare_observations` for every planogram type; the only reason non-ink-wall
types return `[]` is the `ReportingPolicy.slot_presence` flag, whose default is
`False` and which only `InkWall.default_layout_profile` turns on. The builder
`build_slot_presence` reads nothing but the slots definition and the
`PositionResult`s, and a printer matched through a reference image is resolved to
a definition product by `_reference_product`, so the ink-wall `SlotPresence`
structure applies unchanged to endcaps and shelves. The feature is therefore a
per-type policy opt-in (decided at the Q&A gate: Option B), a positive test for a
non-ink-wall type replacing FEAT-645's `test_non_ink_wall_result_unchanged`, and a
documentation section. Shelf-level `expected_products` / `found_products` keep
their display-name labels (`product_label` unchanged). Recommended next step:
`/sdd-spec FEAT-648`.

---

## 2. Codebase Findings

> All entries are grounded in `sdd/state/FEAT-648/findings/`. No fabricated paths or symbols.

### 2.1 Localization

Paths below are relative to `packages/ai-parrot-pipelines/src/parrot_pipelines/` unless they start with `packages/`, `docs/` or `sdd/`.

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `planogram/comparison/definition.py` | `ReportingPolicy` | 49-57 | `slot_presence: bool = False` is the only gate; `product_label` default `display_name` | F004, F006 |
| 2 | `planogram/comparison/definition.py` | `effective_reporting` | 196-225 | merges layout-profile reporting with the per-row `slots_definition.meta.reporting` override | F004 |
| 3 | `planogram/stages/compare.py` | `compare_observations` | 188-231 | shared stage: `products_found = build_slot_presence(...) if policy.slot_presence else []` | F003, F001 |
| 4 | `planogram/comparison/presence.py` | `build_slot_presence`, `facing_presence` | 1-99 | type-agnostic builder: one `SlotPresence` per occupied-expected (shelf, position) | F005 |
| 5 | `planogram/types/ink_wall.py` | `InkWall.default_layout_profile` | 65-84 | the only type enabling `slot_presence=True` (+ `product_label="product"`) | F006 |
| 6 | `planogram/layout.py` | `LayoutProfile.reporting` | 98-100 | per-type profile field, defaults to `ReportingPolicy()` | F006 |
| 7 | `planogram/types/endcap_backlit_multitier.py` | `EndcapBacklitMultitier.default_layout_profile`, `.compare` | 160-174, 214-222 | printers on tiers with reference images; delegates to `compare_observations` | F006, F007 |
| 8 | `planogram/types/product_on_shelves.py` | `ProductOnShelves.default_layout_profile`, `.compare` | 105-118, 141-158 | shelf type with reference images; delegates after fact-tag corroboration | F006, F007 |
| 9 | `planogram/types/product_counter.py` | `ProductCounter.compare` | 115-122 | delegates to `compare_observations` | F006, F007 |
| 10 | `planogram/types/graphic_panel_display.py` | `GraphicPanelDisplay.compare` | 94-101 | delegates to `compare_observations` | F006, F007 |
| 11 | `planogram/types/endcap_no_shelves_promotional.py` | `EndcapNoShelvesPromotional.compare` | 96-103 | zone-only definition → `products_found` stays `[]` by construction | F007, F005 |
| 12 | `planogram/stages/compare.py` | `_reference_product` | 34-57 | `ref-NNNN` → `catalog_key` → `resolve_identity` → definition product | F008 |
| 13 | `planogram/identification/references.py` | `load_reference_bank`, `reference_label` | 20-80 | reference bank with opaque labels + `catalog_key` | F008 |
| 14 | `planogram/contracts.py` | `SlotPresence` | 231-249 | the structure reused unchanged | F012 |
| 15 | `planogram/plan.py` | `PlanogramCompliance._assemble` | 505-540 | additive result key `"products_found"` | F001, F012 |
| 16 | `handlers/planogram_compliance.py` | `PlanogramComplianceHandler` | 191-193 | job JSON `products_found` serialisation | F001 |
| 17 | `packages/ai-parrot-pipelines/tests/planogram_cycle/test_ink_wall.py` | `test_non_ink_wall_result_unchanged` | 546-613 | asserts `products_found == []` for `product_on_shelves` — to be replaced | F009 |
| 18 | `packages/ai-parrot-pipelines/tests/planogram_cycle/test_ink_wall.py` | `test_reporting_meta_override_reaches_pipeline` | 616-630 | proves the per-row `meta.reporting.slot_presence=false` opt-out works | F009 |
| 19 | `planogram/migration.py` | legacy shelf → facings | 262-292 | legacy rows map `product = name`; occupied facings always carry a product | F013, F004 |
| 20 | `docs/pipelines/planogram-compliance-cycle.md` | — | — | only planogram doc; no section on reporting / `products_found` | F012 |

### 2.2 Constraints Discovered

- **Single gate.** `products_found` is produced by the shared stage for every type; the gate is `ReportingPolicy.slot_presence` (default `False`), set to `True` only by InkWall's layout profile.
  *Implication*: no per-type builder code; the change is the policy in each type's `default_layout_profile`, plus tests and docs.
  *Evidence*: F003, F004, F006

- **Builder is definition-driven.** `build_slot_presence` walks `definition.shelves`; every occupied facing has a non-blank `product` (validator), and legacy rows set `product = name`.
  *Implication*: endcap / shelf definitions yield one `SlotPresence` per slot with `model` = the printer/product name; zone-only definitions yield `[]`.
  *Evidence*: F005, F004, F013

- **Reference-image identity.** A `reference_id` is mapped to its `catalog_key` and resolved against the definition (`_reference_product`).
  *Implication*: `found` / `observed` for printers follow the same `FacingStatus` semantics as ink wall; no new identity path.
  *Evidence*: F008

- **Recorded decision being reversed.** FEAT-645 scoped presence to ink_wall and encoded it in `test_non_ink_wall_result_unchanged` and the AC "empty list when presence is off".
  *Implication*: the spec must state the reversal; the negative test becomes a positive one.
  *Evidence*: F009

- **`product_label` is orthogonal.** Only ink_wall switches shelf lists to model names.
  *Implication*: turning presence on does not alter `expected_products` / `found_products` for other types (decided: keep display names, U1).
  *Evidence*: F004, F013

- **Downstream is type-agnostic.** flowtask (FEAT-564) reads `result.get("products_found") or []` and writes the JSON + DataFrame column regardless of `planogram_type`.
  *Implication*: no flowtask change; endcap rows start persisting non-empty lists on the next ai-parrot-pipelines release.
  *Evidence*: F010

- **Per-row kill switch exists.** `slots_definition.meta.reporting` is validated and merged by `effective_reporting`.
  *Implication*: any configuration can opt out with `{"reporting": {"slot_presence": false}}`.
  *Evidence*: F004, F009

- **Active area.** FEAT-646 merged 2026-10-09; WIP neighbour-spill commit `b12e115c3` touches `identification/` and `types/ink_wall.py`.
  *Implication*: branch from `origin/dev`; keep the diff to type profiles, tests and docs.
  *Evidence*: F011

### 2.3 Recent History (Relevant)

| Commit | When | Author | Message | Touched files |
|--------|------|--------|---------|---------------|
| `b12e115c3` | 2026-10-09 | Jesus Lara | wip planogram compliance ink wall (neighbour spill) | `identification/identify.py`, `identification/spill.py`, `types/ink_wall.py`, `tests/.../test_neighbour_spill.py` |
| `42a93f350` | 2026-10-09 | Jesus Lara | fix(planogram): skip reference images for types that do not use them | identification |
| `4e44ccad5`…`1cdc894a4` | 2026-10-09 | engine seats | FEAT-646 ink-wall registration & completeness (TASK-4174..4178) | registration, completeness |
| `7093cb88c`, `3721eaba0` | 2026-10-08 | Jesus Lara | FEAT-645 follow-up fixes (float SKUs, projection fallback label) | `comparison/definition.py`, `comparison/projection.py` |
| `181e04cfa` | 2026-10-08 | engine seat | TASK-4169 — creation of `comparison/presence.py` | `comparison/presence.py` |
| `3e446e87b`…`5aafa2f79` | 2026-10-08 | engine seats | FEAT-645 slot presence (TASK-4166..4171) | contracts, compare, plan, handler, tests |

No commits on the endcap types in the window. *Evidence*: F011

---

## 3. Probable Scope  *(mode = enrichment)*

### What's New

- **`products_found` for shelf-based types** — `endcap_backlit_multitier`, `product_on_shelves`, `product_counter`, `graphic_panel_display` emit one `SlotPresence` per occupied-expected slot, identical in structure to ink_wall (`model`, `sku`, `brand`, `display_name`, `found` ∈ {True, False, None}, `misplaced`, `status`, `confidence`, `facings`, `facings_found`, `observed`). *Evidence*: F003, F005, F007, F012
- **Positive non-ink-wall test** — synthetic `product_on_shelves` run with a fake reference bank + `fake_vision_client`: a reference-matched printer yields `found=True` with `observed` = the facing model; an unmatched slot yields `found=False`; an unseen one `found=None`. *Evidence*: F008, F009
- **Docs section** in `docs/pipelines/planogram-compliance-cycle.md`: `ReportingPolicy` (`slot_presence`, `product_label`, `misplaced_min_confidence`), per-type defaults, the `meta.reporting` override, the `products_found` contract and its tri-state `found`. *Evidence*: F012

### What Changes

- **`planogram/types/endcap_backlit_multitier.py`**::`default_layout_profile` — add `reporting=ReportingPolicy(slot_presence=True)` (keep `product_label` default). *Evidence*: F006
- **`planogram/types/product_on_shelves.py`**::`default_layout_profile` — same. *Evidence*: F006
- **`planogram/types/product_counter.py`**::`default_layout_profile` — same. *Evidence*: F006
- **`planogram/types/graphic_panel_display.py`**::`default_layout_profile` — same. *Evidence*: F006
- **`tests/planogram_cycle/test_ink_wall.py`**::`test_non_ink_wall_result_unchanged` — replace by a positive `products_found` assertion while `expected_products` keep display-name labels; move non-ink-wall presence tests to their own module. *Evidence*: F009
- **`sdd/specs/planogram-ink-wall-slot-presence.spec.md`** — annotate that the "other types → `[]`" test is superseded by FEAT-648 (the AC "empty list when presence is off" stays true). *Evidence*: F009
- **`docs/pipelines/planogram-compliance-cycle.md`** — new section. *Evidence*: F012

### What's Untouched (Non-Goals)

- `ReportingPolicy.slot_presence` default stays `False` (Option A rejected at the gate, U2).
- `product_label` for non-ink-wall types stays `display_name`; shelf-level lists unchanged (U1).
- `SlotPresence`, `build_slot_presence`, `compare_observations`, `_assemble`, the aiohttp handler, scoring, credits, `FacingStatus`, reference selection.
- flowtask consumer (FEAT-564).
- `endcap_no_shelves_promotional` (zone-only; keeps `[]`) and `ink_wall` behaviour.
- No DB schema change; no prod-config edits.

### Patterns to Follow

- Per-type behaviour lives in `default_layout_profile()` policies (`ReferencePolicy`, `ReportingPolicy`, `CompletenessPolicy`), overridable per row via `slots_definition.meta`. *Evidence*: F004, F006
- Additive result keys in `_assemble`; handler serialises with `model_dump(mode="json")`. *Evidence*: F001, F012
- Synthetic end-to-end tests with `fake_vision_client` + `synthetic_slots_definition` in `tests/planogram_cycle/`. *Evidence*: F009

### Integration Risks

- **Reversal of FEAT-645's recorded decision**: state it in the FEAT-648 motivation; replace the negative test; keep the per-row opt-out. *Evidence*: F009
- **Tri-state `found`**: a slot whose only view is NOT_VISIBLE reports `None`, never `False`. Consumers must not read `None` as "not found" — document it. *Evidence*: F005, F009
- **Multi-facing positions** (e.g. ×3): grouped by (shelf, position); `found` is True if any facing is found, `facings_found` counts. Add one endcap multi-facing case. *Evidence*: F005
- **Rows that opted in via `meta.reporting`** already (if any) are unaffected: the override still wins over the profile. *Evidence*: F004

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | `products_found` is gated solely by `ReportingPolicy.slot_presence` inside `compare_observations` | F003, F004, F006 | high | direct read of `compare.py:224-227`; grep shows the only `True` is `ink_wall.py:80` |
| C2 | All six registered types delegate `compare()` to `compare_observations` | F007 | high | each body read; InkWall's `model_copy` preserves `products_found` |
| C3 | `build_slot_presence` works unchanged for endcap/shelf definitions | F005, F004, F013 | high | reads only definition + positions; occupied facings always carry a product |
| C4 | A reference-matched printer resolves to a definition product | F008 | high | `_reference_product` → `resolve_identity(product=catalog_key)` |
| C5 | flowtask persists `products_found` for any type with no change | F010 | medium | based on the sibling-repo spec text, not flowtask code |
| C6 | Per-type opt-in (Option B) is the adopted activation | F006 + U2 | high | user decision at the gate; mechanism verified |
| C7 | No doc describes `ReportingPolicy` / `products_found` | F012 | high | grep over `docs/` returned nothing |
| C8 | Zone-only types keep `products_found == []` | F005, F007 | high | builder iterates `definition.shelves` |

Distribution: **7** high, **1** medium, **0** low.

---

## 5. Open Questions

### Resolved (during proposal phase)

- [x] **U2 — Activation mechanism: default `True` (A) or per-type opt-in (B)?** — *Resolved*: Opción B, opt-in por tipo: `reporting=ReportingPolicy(slot_presence=True)` en el `default_layout_profile` de `endcap_backlit_multitier`, `product_on_shelves`, `product_counter` y `graphic_panel_display`; el default de `ReportingPolicy` queda en `False`.
  *Resolves claims*: C6
- [x] **U1 — Switch `product_label` to `product` for non-ink-wall types?** — *Resolved*: No, solo `products_found`; las listas por estante siguen con `display_name`.
  *Resolves claims*: C6 (scope)
- [x] **U3 — Fixture for the positive test?** — *Resolved*: fixture sintético (`product_on_shelves` sintético con banco de referencias falso y `fake_vision_client`), sin datos de prod.

### Unresolved (defer to spec / implementation)

- [ ] **Does `graphic_panel_display` / `product_counter` have shelves-based definitions in production, or only zones?** — *Owner*: tbd (spec can check `troc.planograms_configurations` rows via the planogram-migrate skill). If zone-only, their opt-in is harmless but inert.
  *Blocks claims*: — (C8 covers the behaviour either way)

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-648`** — *Rationale*: localization is complete and high-confidence; the change is four one-line profile edits, one replaced test plus new positive tests, and a docs section. The only design fork (A vs B) is already decided.

### Alternatives

- **`/sdd-task FEAT-648`** directly — tempting given the size, but the FEAT-645 reversal and the docs section deserve a short spec with explicit acceptance criteria.
- **`/sdd-brainstorm FEAT-648`** — not needed; no architectural options remain.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-648/state.json` |
| Source (raw) | `sdd/state/FEAT-648/source.md` |
| Research plan | `sdd/state/FEAT-648/research_plan.json` |
| Findings (digests) | `sdd/state/FEAT-648/findings/F001-*.md` … `F013-*.md` |
| Synthesis (JSON) | `sdd/state/FEAT-648/synthesis.json` |
| Synthesis reasoning | not persisted |

**Budget consumed** (profile `default`):
- Files read: 19 / 40
- Grep calls: 11 / 25
- Git calls: 5 / 10
- Wiki queries: 2 (free)
- Wall time: ~420s / 300s (soft limit exceeded by the Q&A gate wait, research itself completed within budget)
- Truncated: **no**

**Mode determination**: `auto` → resolved to `enrichment` (positive polarity: "agregar", "llenar", "debería siempre llenarse").

**Gate note**: the research-plan gate was auto-passed (read-only research); the user gates were consolidated at the synthesis review + Q&A, where all three unknowns were answered.

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` |
| Synthesis prompt | `sdd/templates/synthesis.prompt.md v1.0` |
| Plan prompt | `sdd/templates/research_plan.prompt.md v1.0` |
| Schema versions | state=1.0, synthesis=1.0, research_plan=1.0 |
| Operator | Jesus Lara (Claude Fable 5.1 session) |
