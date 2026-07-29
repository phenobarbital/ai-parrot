---
type: Wiki Overview
title: 'Proposal: Themed Component Catalog — HTML Renderer v2 + A2UI Output'
id: doc:sdd-proposals-infographic-theme-catalog-a2ui-proposal-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Source file: `sdd/proposals/infographic-theme-catalog-a2ui.spec.md` (draft
  spec, author:'
relates_to:
- concept: mod:parrot.outputs.a2ui.models
  rel: mentions
---

---
id: FEAT-301
title: "Themed Component Catalog — HTML Renderer v2 + A2UI Output"
type: feature
mode: enrichment
status: review
source:
  kind: file
  path: sdd/proposals/infographic-theme-catalog-a2ui.spec.md
base_branch: dev
confidence: medium
research_state: sdd/state/FEAT-301/
related:
  - FEAT-094 (infographic-html-output)
  - FEAT-273 (a2ui-implementation — approved, active)
---

# Proposal: Themed Component Catalog — HTML Renderer v2 + A2UI Output

**FEAT-301** | Mode: enrichment | Overall confidence: **medium**

---

## §0 Origin

Source file: `sdd/proposals/infographic-theme-catalog-a2ui.spec.md` (draft spec, author:
Jesus Lara, 2026-07-10).

Three workstreams over one shared domain model:

- **WS-A — Theme Schema v2**: extend `ThemeConfig` into a grouped design-system schema,
  register a `petrol` theme replicating the FieldSync design system.
- **WS-B — HTML Renderer v2**: add FieldSync block catalog (`chain`, `steps`, `code`,
  `card_grid`), inline components (chips, method badges), bilingual text convention
  (`I18nText`), and document chrome to `InfographicHTMLRenderer`.
- **WS-C — A2UI Output**: publish a versioned `parrot-catalog.json` and an `A2UIRenderer`
  that deterministically translates `InfographicResponse` into A2UI envelope messages.

---

## §1 Synthesis Summary

The spec is well-structured and its WS-A/WS-B workstreams are solidly grounded in the
existing codebase. However, **WS-C has a significant architectural conflict** with the
already-approved FEAT-273 (A2UI Protocol Integration), which establishes a centralized
A2UI architecture targeting v1.0. The spec targets A2UI v0.9.1 and creates a standalone
renderer — this will produce parallel, incompatible A2UI infrastructure.

**Recommendation**: split the spec into two features:
1. **FEAT-301** (this proposal): WS-A + WS-B only (theme v2, new blocks, i18n, chrome).
   High confidence, no conflicts, immediately shippable value.
2. **WS-C deferred to FEAT-273**: the A2UI translation of InfographicResponse becomes
   a concrete renderer inside FEAT-273's centralized architecture (using v1.0 envelope
   models and `@register_component`), not a standalone A2UIRenderer.

---

## §2 Codebase Findings

### §2.1 Localization

| File | Symbol | Lines | Role | Evidence |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/models/infographic.py` | `ThemeConfig` | 1033-1095 | Theme model — extension target for WS-A | [F001] |
| `packages/ai-parrot/src/parrot/models/infographic.py` | `ThemeRegistry`, `theme_registry` | 1098-1228 | Theme registry + 4 built-in themes | [F002] |
| `packages/ai-parrot/src/parrot/models/infographic.py` | `BlockType`, block union | 71-825 | 15 block types — extension target for WS-B | [F003] |
| `packages/ai-parrot/src/parrot/models/infographic.py` | `InfographicResponse` | 848-935 | Domain model — add `document_meta` (WS-B) | [F004] |
| `packages/ai-parrot-visualizations/.../infographic_html.py` | `InfographicHTMLRenderer` | 632-766 | HTML renderer — add block renderers, chrome (WS-B) | [F005] |
| `packages/ai-parrot-visualizations/.../infographic.py` | `extract_infographic_data` | 49 | Input normalization — reused by new renderer | [F006] |
| `packages/ai-parrot/src/parrot/models/outputs.py` | `OutputMode` | 36-69 | Enum — add A2UI member (WS-C, if not deferred) | [F007] |
| `packages/ai-parrot/src/parrot/outputs/formats/__init__.py` | `_MODULE_MAP`, `register_renderer` | 19-105 | Lazy renderer registry | [F007] |
| `packages/ai-parrot/src/parrot/outputs/formats/base.py` | `BaseRenderer.render()` | 448-465 | Abstract interface | [F008] |
| `packages/ai-parrot-visualizations/.../infographic.py` | `INFOGRAPHIC_SYSTEM_PROMPT` | 16-46 | LLM prompt — documents only 12/15 blocks | [F009] |
| `packages/ai-parrot/src/parrot/models/infographic.py` | `_CSS_COLOR_RE` | 46-50 | Color validator regex | [F001] |

### §2.2 Constraints Discovered

1. **No frozen/extra convention.** No block model uses `model_config = ConfigDict(frozen=True)`
   or `extra="forbid"`. The spec claims "frozen=True where the file uses it" — the file
   does NOT use it. New models should be plain `BaseModel` to match. [F003]

2. **4 built-in themes, not 3.** The spec omits `midnight` from its awareness. The
   `petrol` theme will be the 5th, not the 4th. [F002]

3. **INFOGRAPHIC_SYSTEM_PROMPT gap.** Only 12 of 15 block types documented in the LLM
   prompt — `accordion`, `checklist`, `tab_view` are missing. Adding 4 new blocks expands
   the gap to 7 undocumented blocks if the existing 3 aren't also added. [F009]

4. **BaseRenderer.render() default is `environment='terminal'`**, not `'default'` as
   the spec's A2UIRenderer signature claims. The A2UIRenderer must match the abstract
   signature. [F008]

5. **Undeclared transitive dependencies.** `markdown_it` and `markupsafe` are used by
   `InfographicHTMLRenderer` but not declared in `ai-parrot-visualizations`'s
   `pyproject.toml`. `jsonschema` would be new. All three should be declared explicitly. [F011]

6. **Existing BASE_CSS has literal colors.** The spec mandates "no literal colors" for
   new CSS, which is correct — but the existing CSS already has ~15 literal color values
   in callout backgrounds, card backgrounds, and print styles. The spec should decide
   whether to migrate these as part of WS-B or leave them. [F005]

7. **`extract_infographic_data` is at line 49**, not line 51 as stated. Minor. [F006]

### §2.3 FEAT-273 Architecture Conflict (Critical)

FEAT-273 (`sdd/specs/a2ui-implementation.spec.md`, **status: approved**) is the
platform-wide A2UI adoption spec. It establishes: [F012]

| Aspect | FEAT-273 (approved) | This spec (draft) |
|---|---|---|
| A2UI version | **v1.0** (locked decision D3) | v0.9.1 |
| Envelope models | Centralized `parrot.outputs.a2ui.models` | Inline in `a2ui.py` |
| Catalog | `@register_component` registry, 9 semantic types | Standalone `parrot-catalog.json` |
| Renderer | Catalog → mandatory lowering → Basic Catalog tree | Direct `InfographicResponse → JSONL` |
| First task | TASK-1720 (pending): envelope models | — |

The spec's WS-C creates a parallel A2UI pipeline that would need to be **ripped out and
re-integrated** once FEAT-273 lands. This is wasted work.

**Resolution**: WS-C should become a downstream deliverable of FEAT-273 — specifically,
a concrete `InfographicCatalogRenderer` that registers its components
(`Chain`, `Steps`, `CodePanel`, `CardGrid` etc.) via FEAT-273's `@register_component`
and uses FEAT-273's shared envelope models. The `to_envelopes()` pure-function design
from WS-C is correct in principle and can be adapted to FEAT-273's architecture.

### §2.4 Recent History

- `d73e0368` (HEAD): `sdd: approve spec for FEAT-273 — a2ui-implementation`
- `f2d21016`: `feat(a2a-protocol-compatibility): port JSON-RPC streaming` (FEAT-272)
- TASK-1720 (pending): first task from FEAT-273, implementing A2UI envelope models

---

## §3 Hypothesis & Scope

### Primary Hypothesis

WS-A (theme v2) and WS-B (HTML renderer v2) are **independently shippable**, high-value
features that extend the infographic pipeline without conflicting with any active work.
WS-C (A2UI output) should be deferred to FEAT-273's architecture.

**Confidence: high** — localization is precise, no active conflicts for WS-A/WS-B,
FEAT-273 conflict for WS-C is clear.

### Recommended Scope for FEAT-301

| In scope | Out of scope (deferred) |
|---|---|
| `ThemeConfig` v2 fields (CodePalette, MethodBadgePalette, soft/surface tokens) | `A2UIRenderer` class |
| `derive_soft()` helper | `parrot-catalog.json` |
| `petrol` built-in theme | `OutputMode.A2UI` |
| `to_css_variables()` extension | Vendored A2UI schemas |
| `I18nText` type + validator | JSONL envelope serialization |
| `ChainBlock`, `StepsBlock`, `CodeBlock`, `CardGridBlock` models | |
| `DocumentMeta`, `ChangelogEntry` models | |
| `InfographicResponse.document_meta` field | |
| 4 new block renderers in `InfographicHTMLRenderer` | |
| Micro-syntax expander (`[[chip:…]]`, `[[m:…]]`, `[[comp:…]]`) | |
| Document chrome (top bar, changelog, pills, footer) | |
| I18n span emitter + `setLang()` JS | |
| BASE_CSS additions (only CSS variables, no literal colors) | |
| `INFOGRAPHIC_SYSTEM_PROMPT` update (all 19 blocks) | |
| Declare `markdown-it-py` and `markupsafe` as explicit deps | |
| Migrate existing literal colors in BASE_CSS to CSS variables | |
| Document all 19 blocks in INFOGRAPHIC_SYSTEM_PROMPT | |

---

## §4 Confidence Map

| Claim | Confidence | Evidence |
|---|---|---|
| ThemeConfig v2 is backward compatible (optional fields, derived defaults) | **high** | [F001] — all new fields are Optional with None defaults; existing themes validate unchanged |
| New block models follow file conventions (no frozen, no extra) | **high** | [F003] — verified: no block model uses frozen/extra |
| `I18nText` widening is backward-compatible (str still validates) | **high** | [F003, F004] — Pydantic v2 Union[str, Dict] accepts plain str |
| `document_meta` optional field has zero cost for existing payloads | **high** | [F004] — Optional[DocumentMeta] = None adds nothing to serialization if absent |
| Micro-syntax is injection-safe (escape → markdown → expand order) | **high** | [F005] — consistent with existing escape-first policy; regex on escaped output |
| Existing literal colors in BASE_CSS won't conflict with new variable-only CSS | **medium** | [F005] — new CSS rules only use vars, but callout/card backgrounds remain literal |
| WS-C's `to_envelopes()` pure-function design adapts to FEAT-273 | **medium** | [F012] — the function signature is correct but must use FEAT-273's models |
| `markdown-it-py` and `markupsafe` will remain available as transitives | **medium** | [F011] — likely stable, but declaring explicitly removes the risk |
| A2UI v0.9.1 catalog schema is compatible with v1.0 | **low** | [F012] — FEAT-273 explicitly rejected v0.9.1 (locked decision D3) |
| INFOGRAPHIC_SYSTEM_PROMPT update won't degrade LLM output quality | **medium** | [F009] — adding 7 block rules to a prompt that already has 12; may need tuning |

---

## §5 Open Questions

### Resolved by Research

- [x] **Do existing block models use `frozen=True`?** No. Plain `BaseModel` throughout. [F003]
- [x] **How many built-in themes exist?** 4 (light, dark, corporate, midnight). [F002]
- [x] **Is `I18nText` used anywhere?** No. Forms have `LocalizedString` separately. [F010]
- [x] **Is `jsonschema` available?** Yes (v4.26.0, transitive), but undeclared. [F011]
- [x] **Does FEAT-273 conflict with WS-C?** Yes, significantly. [F012]

### Resolved by Human Decision

- [x] **U1**: WS-C deferred to FEAT-273. FEAT-301 scoped to WS-A + WS-B only.
      WS-C's `to_envelopes()` design carries into FEAT-273 as a concrete renderer.
- [x] **U2**: Yes — migrate existing literal colors in BASE_CSS to CSS variables as
      part of WS-B. Adds ~15 values to the migration but ensures a clean, complete
      variable-only CSS surface.
- [x] **U3**: Yes — document all 19 block types in INFOGRAPHIC_SYSTEM_PROMPT (the 3
      existing undocumented blocks + 4 new ones).

---

## §6 Recommended Next Step

Given the FEAT-273 conflict on WS-C, the recommended path is:

```
→ /sdd-spec FEAT-301   (scoped to WS-A + WS-B only)
```

**Rationale**: WS-A and WS-B are high-confidence, independently shippable, and have no
conflicts. A clean spec scoped to theme v2 + HTML renderer v2 can proceed immediately
to `/sdd-task` decomposition. WS-C's design (pure-function `to_envelopes()`, deterministic
translation) is sound and should be carried into FEAT-273 as a concrete renderer, not
duplicated here.

**Alternatives**:
- `/sdd-spec FEAT-301` including WS-C → if FEAT-273 is deprioritized or abandoned
- `/sdd-brainstorm FEAT-301` → if the I18nText widening or chrome design needs
  multi-option exploration before committing
- Manual review → review this proposal and the FEAT-273 relationship before deciding

---

## §7 Research Audit

| Metric | Value |
|---|---|
| Files read | 28 |
| Grep queries | 18 |
| Git queries | 4 |
| Findings | 13 |
| Budget | default (40/25/10) |
| Truncated | No |
| Duration | ~2 min |
| State directory | `sdd/state/FEAT-301/` |

---

## §8 Spec Errata (for correction if proceeding to `/sdd-spec`)

These inaccuracies were found in the source spec and should be corrected:

1. **§2 WS-A**: "existing `light`/`dark`/`corporate` themes remain valid" → add `midnight`
   (4th built-in theme).
2. **§2 WS-B block models**: "`frozen=True` where the file uses it" → file convention is
   NO `frozen`, NO `extra="forbid"` on any block model. Remove `frozen=True` from new
   model definitions.
3. **§2 WS-C A2UIRenderer.render()**: `environment="default"` → should be
   `environment='terminal'` to match `BaseRenderer` abstract signature.
4. **§6 Codebase Contract**: `extract_infographic_data  # line 51` → line 49.
5. **§6 Codebase Contract**: `markdown_it` "verified per FEAT-094" and `markupsafe` →
   both are undeclared transitive dependencies. Should be declared in
   `ai-parrot-visualizations` pyproject.toml.
6. **§2 WS-C**: A2UI v0.9.1 → conflicts with FEAT-273's locked decision D3 (v1.0).
   If WS-C proceeds, must target v1.0.
7. **§3 Module 5**: `register_renderer(OutputMode.INFOGRAPHIC, ...)` in existing code →
   the decorator uses `OutputMode.INFOGRAPHIC` without `system_prompt`. The spec shows
   `system_prompt=INFOGRAPHIC_SYSTEM_PROMPT` on InfographicRenderer — verify this is
   actually set for the JSON renderer vs the HTML renderer.
