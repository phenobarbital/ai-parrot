---
id: FEAT-301
title: "Themed Component Catalog — HTML Renderer v2"
type: feature
mode: enrichment
status: review
run: 2
source:
  kind: file
  path: sdd/proposals/infographic-theme-catalog-a2ui.spec.md
base_branch: dev
confidence: high
research_state: sdd/state/FEAT-301/
related:
  - FEAT-094 (infographic-html-output)
  - FEAT-273 (a2ui-implementation — completed 2026-07-11)
  - FEAT-324 (infographic-builder — completed 2026-07-22)
  - FEAT-326 (dataagent-infographic — completed 2026-07-24)
  - FEAT-327 (infographic-render-endpoint — completed 2026-07-24)
  - FEAT-420 (finance-reporter-tier2-narrative — completed 2026-08-07)
  - FEAT-423 (purge-matplotlib-renderer-libs — completed 2026-08-16)
  - FEAT-425 (agentcrew-tales-research — completed 2026-08-17)
---

# Proposal: Themed Component Catalog — HTML Renderer v2

**FEAT-301** | Mode: enrichment | Overall confidence: **high**

> **Run 2** (2026-08-19). Run 1 (2026-07-10) produced a medium-confidence
> proposal. Since then 8 features landed in the infographic/A2UI domain,
> invalidating the prior synthesis. This run re-researched the codebase and
> produces a high-confidence, narrowed scope.

---

## §0 Origin

Source file: `sdd/proposals/infographic-theme-catalog-a2ui.spec.md` (draft spec,
author: Jesus Lara, 2026-07-10).

The original spec proposed three workstreams:

- **WS-A — Theme Schema v2**: extend `ThemeConfig` into a grouped design-system
  schema, register a `petrol` theme replicating the FieldSync design system.
- **WS-B — HTML Renderer v2**: add FieldSync block catalog (`chain`, `steps`,
  `code`, `card_grid`), inline components (chips, method badges), bilingual text
  convention (`I18nText`), and document chrome to `InfographicHTMLRenderer`.
- **WS-C — A2UI Output**: publish a versioned `parrot-catalog.json` and an
  `A2UIRenderer` that deterministically translates `InfographicResponse` into
  A2UI envelope messages.

**WS-C is fully resolved by FEAT-273** (completed 2026-07-11, 22 tasks) and is
excluded from this proposal. The scope is **WS-A + WS-B + A2UI adapter
extension for new block types**.

---

## §1 Synthesis Summary

The codebase is in an excellent state for this feature. The infographic model
(`infographic.py`) has received **zero commits** since the original proposal
date — the extension surface is pristine. All 8 downstream features that landed
since run-1 are **block-type-agnostic**: they delegate to the toolkit/renderer
pipeline and require zero changes for new block types.

FEAT-273 built the complete A2UI infrastructure (envelope models, catalog
registry, InfographicComponent, adapter, builders, renderers, delivery bridges).
The adapter already handles unknown blocks via a Card fallback, but explicit
mappings for the 4 new block types will improve fidelity.

**Scope (final)**:
1. **WS-A**: ThemeConfig v2 fields + `petrol` theme (5th built-in)
2. **WS-B**: 4 new block types, 4 HTML renderers, I18nText, document chrome,
   micro-syntax expander, CSS variable migration, system prompt update,
   dependency declarations
3. **A2UI adapter extension**: explicit `_Converter` mappings for new blocks

---

## §2 Codebase Findings

### §2.1 Localization

| File | Symbol | Lines | Role | Evidence |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/models/infographic.py` | `BlockType` | 71-87 | 15-member enum → extend to 19 | [F108] |
| `packages/ai-parrot/src/parrot/models/infographic.py` | `ThemeConfig` | 1033-1095 | 12 color tokens + font → extend with CodePalette, soft/surface tokens | [F108] |
| `packages/ai-parrot/src/parrot/models/infographic.py` | `ThemeRegistry`, `theme_registry` | 1098-1228 | 4 built-in themes → add `petrol` (5th) | [F108] |
| `packages/ai-parrot-visualizations/.../infographic_html.py` | `InfographicHTMLRenderer` | 655-900+ | `_block_renderers` dict (15 entries) → add 4 | [F101] |
| `packages/ai-parrot-visualizations/.../infographic_html.py` | `_BLOCK_MODEL_MAP` | 69-85 | Block coercion map → add 4 entries | [F101] |
| `packages/ai-parrot-visualizations/.../infographic_html.py` | `BASE_CSS` | 153-617 | ~20 literal colors → migrate to CSS variables | [F101] |
| `packages/ai-parrot-visualizations/.../infographic.py` | `INFOGRAPHIC_SYSTEM_PROMPT` | 16-46 | Documents 12/15 blocks → update to 19/19 | [F104] |
| `packages/ai-parrot/src/parrot/outputs/a2ui/adapters/infographic.py` | `_Converter.walk()` | entire | Card fallback for unknown blocks → add explicit mappings for 4 new types | [F100] |
| `packages/ai-parrot-visualizations/pyproject.toml` | `dependencies` | 28-30 | Missing `markdown-it-py`, `markupsafe`, `orjson` | [F106] |

### §2.2 Constraints Discovered

1. **No frozen/extra convention.** No block model uses `frozen=True` or
   `extra="forbid"`. New models must be plain `BaseModel`. [F108, F003]

2. **4 built-in themes, not 3.** `light`, `dark`, `corporate`, `midnight`.
   `petrol` will be the 5th. [F108]

3. **INFOGRAPHIC_SYSTEM_PROMPT gap.** Documents 12/15 existing blocks —
   `accordion`, `checklist`, `tab_view` are missing. With 4 new blocks, the
   gap grows to 7/19 if not addressed. [F104]

4. **~20 literal CSS colors in BASE_CSS.** Callout backgrounds/h3 colors,
   `#fff` (×4), `tr:hover`, print styles. Must migrate to CSS variables for
   theme consistency. [F101]

5. **Dependencies undeclared.** `markdown-it-py`, `markupsafe`, `orjson` are
   imported but not in `ai-parrot-visualizations/pyproject.toml`. [F106]

6. **A2UI catalog has no Code/Steps/CardGrid component.** New blocks map to
   `Card` in the A2UI adapter (acceptable degradation) or need new catalog
   components (scope-expanding). Recommended: Card-based lowering for v1,
   with component-specific `properties` carrying semantic hints. [F105]

### §2.3 Downstream Consumer Analysis (NEW in Run 2)

| Consumer | Block-aware? | Changes needed? | Evidence |
|---|---|---|---|
| `SectionDescriptor` (FEAT-326) | No — shape-based | None | [F102] |
| `InfographicAuthoringMixin` (FEAT-326) | No — delegates to toolkit | None | [F102] |
| `RecipeRunner` (FEAT-324) | No — data-model + `$bind` | None | [F102] |
| `InfographicToolkit` | No — template-driven | None | [F102] |
| `InfographicNode` / Thales (FEAT-425) | No — calls `render_template()` | None | [F103] |
| `infographic_response_to_envelope()` (FEAT-273) | **Yes** — block-type switch | Extend `_Converter` | [F100] |
| `InfographicHTMLRenderer` (FEAT-094) | **Yes** — `_block_renderers` dict | Add 4 renderers | [F101] |
| `INFOGRAPHIC_SYSTEM_PROMPT` | **Yes** — block documentation | Update to 19 blocks | [F104] |

**Key insight**: Only 3 consumers need changes. All others are block-agnostic.

### §2.4 Recent History

Since run-1 (2026-07-10), **zero commits** to `infographic.py`. The 8 features
that landed in the infographic/A2UI domain all worked at higher abstraction
levels (toolkit, adapter, mixin, flow nodes) and left the model untouched.

---

## §3 Hypothesis & Scope

### Primary Hypothesis

FEAT-301 scoped to WS-A + WS-B + A2UI adapter extension is independently
shippable with zero conflicts against any active or completed feature. All
downstream consumers are block-agnostic except the 3 identified extension
points.

**Confidence: high** — all 9 findings grounded, all downstream consumers
verified, model untouched, no active feature conflicts.

### Scope

| In scope | Out of scope |
|---|---|
| `ThemeConfig` v2 fields (CodePalette, MethodBadgePalette, soft/surface tokens, callout tokens) | `A2UIRenderer` class (FEAT-273 built this) |
| `derive_soft()` helper | `parrot-catalog.json` (FEAT-273 has catalog registry) |
| `to_css_variables()` extension for new tokens | `OutputMode.A2UI` (exists since FEAT-273) |
| `petrol` built-in theme (5th) | New A2UI catalog components (Card fallback is v1 strategy) |
| `I18nText` type + block field widening | JSONL envelope serialization (FEAT-273) |
| `ChainBlock`, `StepsBlock`, `CodeBlock`, `CardGridBlock` models | |
| `DocumentMeta`, `ChangelogEntry` models | |
| `InfographicResponse.document_meta` field | |
| 4 new block renderers in `InfographicHTMLRenderer` | |
| Micro-syntax expander (`[[chip:…]]`, `[[m:…]]`, `[[comp:…]]`) | |
| Document chrome (top bar, changelog, pills, footer) | |
| I18n span emitter + `setLang()` JS | |
| CSS variable migration (~20 literal colors → tokens) | |
| `INFOGRAPHIC_SYSTEM_PROMPT` update (all 19 blocks) | |
| A2UI adapter `_Converter` extension for 4 new block types | |
| Declare `markdown-it-py`, `markupsafe`, `orjson` as explicit deps | |

---

## §4 Confidence Map

| Claim | Confidence | Evidence |
|---|---|---|
| ThemeConfig v2 backward-compatible (Optional fields, derived defaults) | **high** | [F108] — all new fields Optional with None defaults |
| New block models follow convention (no frozen, no extra) | **high** | [F108, F003] — verified: no block model uses frozen/extra |
| `I18nText` widening is backward-compatible (`str` still validates) | **high** | [F108] — Pydantic v2 `Union[str, Dict]` accepts plain str |
| `document_meta` optional field has zero cost for existing payloads | **high** | [F108] — `Optional[DocumentMeta] = None` |
| WS-C fully resolved by FEAT-273 (22 tasks, all done) | **high** | [F107] — verified task index, all done |
| SectionDescriptor / AuthoringMixin / RecipeRunner unaffected | **high** | [F102] — shape-based, block-agnostic |
| Thales InfographicNode unaffected (graceful degradation contract) | **high** | [F103] — delegates to toolkit, never inspects block types |
| A2UI adapter degrades new blocks to Card safely | **high** | [F100] — `_card_like` fallback is documented behavior |
| ~20 literal CSS colors need migration to variables | **high** | [F101] — counted: callouts, containers, th, tr:hover, print |
| Prompt gap: 7/19 undocumented blocks without update | **high** | [F104] — 3 existing + 4 new = 7 undocumented |
| Dependencies `markdown-it-py`, `markupsafe`, `orjson` undeclared | **high** | [F106] — imported but not in pyproject.toml |
| Micro-syntax is injection-safe (escape → markdown → expand order) | **high** | [F101] — consistent with existing escape-first policy |

---

## §5 Open Questions

### Resolved by Research

- [x] **Does FEAT-273 conflict with WS-C?** No — FEAT-273 **resolved** WS-C entirely. [F107]
- [x] **Do existing block models use `frozen=True`?** No. Plain `BaseModel` throughout. [F108]
- [x] **How many built-in themes exist?** 4 (light, dark, corporate, midnight). [F108]
- [x] **Are downstream consumers block-aware?** Only 3 of 8 need changes. [F100-F103]
- [x] **Has infographic.py changed since run-1?** No. Zero commits. [F108]
- [x] **Are dependencies declared?** No. `markdown-it-py`, `markupsafe`, `orjson` missing. [F106]

### Resolved by Human Decision

- [x] **U1 (run-1)**: WS-C deferred to FEAT-273. → **Resolved: FEAT-273 built it.**
- [x] **U2 (run-1)**: Migrate existing literal colors. → **Confirmed, still wanted.**
- [x] **U3 (run-1)**: Document all blocks in prompt. → **Confirmed, still wanted.**
- [x] **U1 (run-2)**: Include A2UI adapter extension in FEAT-301? → **Yes, include as task.**
- [x] **U2 (run-2)**: I18nText still wanted? → **Yes, bilingual EN/ES confirmed.**

---

## §6 Recommended Next Step

```
→ /sdd-spec FEAT-301   (WS-A + WS-B + A2UI adapter extension)
```

**Rationale**: High-confidence localization across all 9 findings. No conflicts.
All unknowns resolved. The scope is clean and narrower than run-1 (WS-C removed).
Three extension points identified with precise file/line targets. Ready for
formal spec → task decomposition.

**Alternatives**:
- `/sdd-brainstorm FEAT-301` → only if the I18nText widening or document chrome
  design needs multi-option exploration before committing
- Manual review → review this proposal and the run-2 findings before deciding

---

## §7 Research Audit

| Metric | Run 1 (2026-07-10) | Run 2 (2026-08-19) |
|---|---|---|
| Files read | 28 | 12 |
| Grep queries | 18 | 4 |
| Git queries | 4 | 1 |
| Wiki queries | 0 | 8 (free) |
| Findings | 13 (F001-F013) | 9 (F100-F108) |
| Budget | default | default |
| Truncated | No | No |
| Overall confidence | medium | **high** |
| State directory | `sdd/state/FEAT-301/` | `sdd/state/FEAT-301/` |

---

## §8 Spec Errata (carried from run-1, updated)

1. ~~**§2 WS-C**: entire workstream~~ → **Removed from scope.** FEAT-273 resolved.
2. **§2 WS-A**: "existing `light`/`dark`/`corporate` themes" → add `midnight`
   (4th built-in theme). Petrol will be the **5th**.
3. **§2 WS-B block models**: "`frozen=True` where the file uses it" → file
   convention is **no** `frozen`, **no** `extra="forbid"`. Remove from new models.
4. **§6 Codebase Contract**: `extract_infographic_data` line 51 → line 49.
5. **§6 Codebase Contract**: `markdown_it` and `markupsafe` → undeclared
   transitive deps. Declare explicitly.
6. ~~**§2 WS-C A2UIRenderer.render()**: `environment="default"`~~ → N/A (WS-C removed).
7. **NEW**: A2UI adapter `_Converter.walk()` must be extended for 4 new block
   types — currently falls through to generic `_card_like()` Card.
8. **NEW**: INFOGRAPHIC_SYSTEM_PROMPT needs **all 19** block types, not just
   the 4 new ones — 3 existing blocks (`accordion`, `checklist`, `tab_view`)
   are also undocumented.
