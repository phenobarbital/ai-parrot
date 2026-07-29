---
type: Wiki Overview
title: 'Feature Specification: Themed Component Catalog — HTML Renderer v2 + A2UI
  Output'
id: doc:sdd-proposals-infographic-theme-catalog-a2ui-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The infographic pipeline guarantees *structural* consistency (typed Pydantic
  blocks) but
relates_to:
- concept: mod:parrot.models.infographic
  rel: mentions
- concept: mod:parrot.models.outputs
  rel: mentions
- concept: mod:parrot.outputs.formats
  rel: mentions
- concept: mod:parrot.outputs.formats.base
  rel: mentions
- concept: mod:parrot.outputs.formats.infographic
  rel: mentions
---

# Feature Specification: Themed Component Catalog — HTML Renderer v2 + A2UI Output

**Feature ID**: FEAT-XXX (assign on intake)
**Date**: 2026-07-10
**Author**: Jesus Lara
**Status**: draft
**Target version**: 1.x
**Related**: FEAT-094 (infographic-html-output), infographictoolkit.spec.md, multi-tab-infographic.spec.md

---

## 1. Motivation & Business Requirements

### Problem Statement

The infographic pipeline guarantees *structural* consistency (typed Pydantic blocks) but
only partial *visual* consistency: `ThemeConfig` covers 12 color tokens, while real
document families (FieldSync artifact kit reference) require a richer design system —
soft background variants, status semantics (ok / review / gap), HTTP method badges,
a dark code panel palette, a mono font stack, and document chrome (brand top bar,
version + changelog widget, EN/ES language toggle).

Separately, all interactive consumption today goes through frozen HTML blobs. The A2UI
protocol (v0.9.1) formalizes exactly our pattern — agent emits data, a client-owned
component **catalog** owns all styling — and adds streaming, data binding and actions.
`InfographicResponse` is already ~a catalog; it lacks the protocol envelope.

This feature has three workstreams over one shared domain model:

- **WS-A — Theme Schema v2**: extend `ThemeConfig` into a complete design-system schema
  (token groups), register a `petrol` theme replicating the FieldSync design system.
- **WS-B — HTML Renderer v2**: add the FieldSync block catalog (`chain`, `steps`,
  `code`, `card_grid`), inline components (status chips, method badges), bilingual
  text convention, and document chrome to `InfographicHTMLRenderer`.
- **WS-C — A2UI Output**: publish a versioned `parrot-catalog.json` (A2UI v0.9.1
  custom catalog) and an `A2UIRenderer` (`OutputMode.A2UI`) that deterministically
  translates `InfographicResponse` into A2UI envelope messages (JSONL).

### Goals
- One `InfographicResponse` → three surfaces: static HTML (S3/email), raw JSON (API),
  A2UI stream (live UI). No divergence between surfaces.
- Every visual decision lives in `ThemeConfig` v2 + renderer CSS. Configs/LLM output
  carry **zero** styling.
- FieldSync-family documents (dev guides, capability maps, workflow docs) become
  expressible as `InfographicResponse` — retiring the standalone generator.
- Bilingual (EN/ES) documents from a single response, toggleable client-side.
- A2UI translation is a pure function: `InfographicResponse -> list[EnvelopeMsg]`,
  fully testable without an LLM or HTTP context.

### Non-Goals (explicitly out of scope)
- Svelte 5 client renderer for the A2UI stream (separate navigator-frontend spec;
  this spec only guarantees the catalog schema + stream contract it will consume).
- A2UI *generative* mode (LLM emitting A2UI JSON directly with the catalog embedded
  in the prompt). Deferred; the deterministic path is the contract.
- Client→agent action round-trips (A2UI `action` handling in ai-parrot-server).
  The catalog declares actions; wiring the callback transport is a follow-up.
- PDF export; Adaptive Cards.
- Any change to `InfographicRenderer` (raw JSON) semantics.

---

## 2. Architectural Design

### Overview

```
InfographicResponse  (single domain model — Pydantic v2, closed contract)
        │
        ├── InfographicRenderer       → JSON            (unchanged)
        ├── InfographicHTMLRenderer   → static HTML     (WS-A + WS-B)
        │        └── ThemeConfig v2 → CSS :root variables (superset)
        └── A2UIRenderer              → JSONL envelopes (WS-C)
                 └── parrot-catalog.json (A2UI v0.9.1 custom catalog, versioned URL)
```

Design invariant (inherited from the FieldSync kit): **authors/LLMs produce data;
renderers own presentation.** Text is *not* trusted HTML (deviation from the kit —
see Design Decisions).

### WS-A: Theme Schema v2

`ThemeConfig` grows from a flat 12-token model into grouped token sets. New fields
are optional with derived defaults, so the built-in `light`/`dark`/`corporate`
themes remain valid unchanged (backward compatible).

```python
class CodePalette(BaseModel):
    """Dark code-panel palette (FieldSync `code` block)."""
    model_config = ConfigDict(frozen=True, extra="forbid")
    bg: str = "#0C2321"
    ink: str = "#CFE3E0"
    keyword: str = "#5CC9B8"     # .k
    string: str = "#E6C07B"      # .s
    comment: str = "#5f7a76"     # .c (italic)
    dim: str = "#7FA6A1"         # .d
    border: str = "#143b38"

class MethodBadgePalette(BaseModel):
    """HTTP method badge colors (FieldSync `.m` component)."""
    model_config = ConfigDict(frozen=True, extra="forbid")
    get: str = "#2E7D5B"
    post: str = "#0E6E6E"
    patch: str = "#B7791F"
    put: str = "#3B4A8C"
    delete: str = "#C0492F"

class ThemeConfig(BaseModel):
    # ── existing 12 fields preserved verbatim ──────────────────────────
    name: str
    primary: str = "#6366f1"
    primary_dark: str = "#4f46e5"
    primary_light: str = "#818cf8"
    accent_green: str = "#10b981"
    accent_amber: str = "#f59e0b"
    accent_red: str = "#ef4444"
    neutral_bg: str = "#f8fafc"
    neutral_border: str = "#e2e8f0"
    neutral_muted: str = "#64748b"
    neutral_text: str = "#0f172a"
    body_bg: str = "#f1f5f9"
    font_family: str = "..."
    # ── v2 additions (all Optional[str] = None → derived) ──────────────
    primary_soft: Optional[str] = None        # default: mix(primary, bg)
    accent_green_soft: Optional[str] = None
    accent_amber_soft: Optional[str] = None
    accent_red_soft: Optional[str] = None
    surface: Optional[str] = None             # card bg   (default #fff / dark eq.)
    surface_alt: Optional[str] = None         # thead / inline-code bg
    ink_secondary: Optional[str] = None       # between text and muted
    border_strong: Optional[str] = None
    font_mono: str = 'ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace'
    code: CodePalette = CodePalette()
    methods: MethodBadgePalette = MethodBadgePalette()
```

- `to_css_variables()` emits the **superset**: the existing 12 vars (names unchanged)
  plus `--primary-soft`, `--surface`, `--surface-alt`, `--ink-2`, `--border-strong`,
  `--font-mono`, `--code-*` (7), `--m-get … --m-del` (5), `--accent-*-soft` (3).
- Derivation of unset soft/surface tokens uses a pure helper
  `derive_soft(color: str, bg: str, ratio: float) -> str` (hex-only sRGB mix;
  non-hex inputs → documented fallback constant, never an exception).
- All new color fields go through the existing `_CSS_COLOR_RE` validator.
- **New built-in theme `petrol`** — the FieldSync design system verbatim
  (`primary=#0E6E6E`, `body_bg=#F5F7F7`, `surface_alt=#EDF3F2`,
  `neutral_text=#0F1E1D`, `ink_secondary=#39504E`, `neutral_muted=#6B7B7A`,
  `neutral_border=#DCE5E4`, `border_strong=#C7D4D3`, accents
  `#2E7D5B/#B7791F/#C0492F` + soft variants `#E3F2EA/#FBEFD8/#FBE6DF`,
  `primary_soft=#E2F0EF`, default `CodePalette`/`MethodBadgePalette` values above).

### WS-B: HTML Renderer v2 — FieldSync block catalog

**New enum members** (`BlockType`): `CHAIN = "chain"`, `STEPS = "steps"`,
`CODE = "code"`, `CARD_GRID = "card_grid"`.

**New block models** (`parrot/models/infographic.py`, same conventions:
`frozen=True` where the file uses it, `extra="forbid"`, `type` discriminator):

```python
class ChainNode(BaseModel):
    title: I18nText
    annotation: Optional[str] = None          # mono, e.g. "POST /api/v1/visits"
    description: Optional[I18nText] = None

class ChainBlock(BaseModel):
    type: Literal["chain"]
    nodes: List[ChainNode] = Field(min_length=2, max_length=8)

class StepsBlock(BaseModel):
    type: Literal["steps"]
    items: List[I18nText] = Field(min_length=1)   # auto-numbered by renderer

class CodeBlock(BaseModel):
    type: Literal["code"]
    code: str                                  # rendered verbatim, HTML-escaped
    language: Optional[str] = None             # hint for client-side highlighting
    label: Optional[I18nText] = None

class CardGridItem(BaseModel):
    title: I18nText
    role: Optional[I18nText] = None
    items: List[I18nText] = []

class CardGridBlock(BaseModel):
    type: Literal["card_grid"]
    items: List[CardGridItem] = Field(min_length=1)
```

All four join the `InfographicBlock` union and the `INFOGRAPHIC_SYSTEM_PROMPT`
block list (with a one-line usage rule each, hero_card-style).

**Bilingual text convention** — `I18nText`:

```python
I18nText = Union[str, Dict[str, str]]   # "text" | {"en": "...", "es": "..."}
```

- Applies to the user-visible text fields of **all** blocks (existing blocks widen
  from `str` to `I18nText`; plain strings still validate → backward compatible).
- Validator: dict form requires non-empty values and keys ⊆ {`en`, `es`} (extensible
  constant `SUPPORTED_LANGS`).
- HTML renderer: dict values emit `<span class="i18n en">…</span><span class="i18n
  es">…</span>`; a document is bilingual iff `document_meta.bilingual` is true.
- A2UI renderer: dict values become data-model bindings (see WS-C) — the language
  toggle is a `dataModelUpdate`, no re-render.

**Document chrome** — new optional `document_meta` on `InfographicResponse`:

```python
class ChangelogEntry(BaseModel):
    version: str
    date: str
    description: I18nText

class DocumentMeta(BaseModel):
    brand: Optional[I18nText] = None           # top-bar label
    eyebrow: Optional[I18nText] = None         # uppercase kicker above title
    version: Optional[str] = None
    date: Optional[str] = None
    changelog: List[ChangelogEntry] = []       # newest first
    bilingual: bool = False
    default_lang: str = "en"
    footer_left: Optional[I18nText] = None
    footer_right: Optional[I18nText] = None
    pills: List[I18nText] = []                 # meta pills under the title
```

When present, `InfographicHTMLRenderer` emits: sticky top bar (brand + version
button), collapsible changelog panel, EN/ES toggle (only if `bilingual`), hero
pills, footer. The only inline JS added is `setLang()` + `toggleChangelog()`
(no external requests — CSP posture per `infographic_csp_and_signed_urls.md`
unchanged).

**Inline components (chips / method badges / component names)** — closed contract,
not trusted HTML. A post-markdown inline micro-syntax processed by the renderer:

| Syntax in any text field | Rendered as |
|---|---|
| `[[chip:ok Implemented]]` | `<span class="chip ok">Implemented</span>` |
| `[[chip:review …]]`, `[[chip:gap …]]` | amber / red chips |
| `[[m:GET]]` … `[[m:DELETE]]` | method badge `<span class="m get">GET</span>` |
| `[[comp:Form Builder]]` | `<span class="comp">Form Builder</span>` |

Processing order: escape → markdown (safe mode, as today) → micro-syntax expansion
(regex on escaped output; payload text remains escaped). Unknown variants render as
literal text. This replaces the FieldSync kit's "trusted HTML" escape hatch: same
expressiveness, zero injection surface. There is deliberately **no** `html` block.

**CSS**: `BASE_CSS` gains the component styles ported from the FieldSync kit
(`.chip`, `.m`, `.flowchain/.node/.arrow`, `.steps/.st`, `.code` + highlight
classes, `.topbar`, `.changelog`, `.toggle`, `.pill`, `.i18n` visibility rules),
expressed **only** against ThemeConfig v2 variables — no literal colors.

### WS-C: A2UI catalog + renderer

**Catalog** — `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui/parrot-catalog.json`,
a self-contained JSON Schema per A2UI v0.9.1 catalog rules:

- Child references use `common_types.json#/$defs/ComponentId`; child lists use
  `ChildList` (mandatory for tree-integrity validation per spec §catalog typing).
- Components (name → source block): `Title`, `HeroCard`, `Summary`, `Chart`,
  `BulletList`, `Table`, `Image`, `Quote`, `Callout`, `Divider`, `Timeline`,
  `Progress`, `Accordion`, `Checklist`, `TabView`, `Chain`, `Steps`, `CodePanel`,
  `CardGrid` — plus layout primitives `Row`, `Column`, `Card`, `Text` mirroring
  the Basic catalog signatures (so generic A2UI tooling/examples remain usable).
- All user-visible text props are typed as the catalog's bindable-string type
  (accept `literalString` or `path`).
- Theme schema section of the catalog mirrors ThemeConfig v2 token names 1:1, so a
  `ThemeConfig` serializes into the catalog theme with a pure function.
- Catalog is **versioned by URL** (`catalogId`), vendored in-repo; spec version
  pinned to `v0.9.1`. Envelope message names/shapes are taken from the pinned
  vendored schema, never from memory (`sdd` finding to record during T1).

**Renderer** — `parrot/outputs/formats/a2ui.py`:

```python
@register_renderer(OutputMode.A2UI, system_prompt=INFOGRAPHIC_SYSTEM_PROMPT)
class A2UIRenderer(BaseRenderer):
    """Deterministic InfographicResponse → A2UI v0.9.1 envelope translation."""

    async def render(self, response, environment="default", **kwargs
                     ) -> Tuple[str, Optional[Any]]:
        """Returns (jsonl_string, list[dict]) — one envelope per line."""

    def to_envelopes(self, data: InfographicResponse | dict,
                     surface_id: str = "main",
                     lang: str | None = None) -> list[dict]:
        """Pure translation. No I/O, no LLM, no HTTP context."""
```

Translation contract:

1. `createSurface` — `surfaceId`, `catalogId` (vendored catalog URL), theme payload
   from the resolved `ThemeConfig`.
2. `updateComponents` — flat adjacency list: a `root` Column whose `children`
   `ChildList` references one component per block, ids `blk-000`, `blk-001`, …
   (stable, deterministic ordering = `blocks` order). Container blocks
   (`TabView`, `Accordion`, `CardGrid`, `Chain`) expand into parent + child
   component entries with `ComponentId` links.
3. `updateDataModel` — (a) chart data series under `/charts/blk-NNN/…`;
   (b) bilingual texts: every `I18nText` dict contributes `/i18n/<field-id>` with
   the value for the active language; the full `{en, es}` map is included under
   `/i18n_all/…` so the client can switch languages with a local
   `dataModelUpdate` and zero round-trips.
4. Final message per pinned envelope schema signalling render start (name per
   vendored v0.9.1 schema).
5. Micro-syntax (`[[chip:…]]`, `[[m:…]]`) maps to catalog components `StatusChip`
   / `MethodBadge` when it is the entire field value; when embedded mid-text it
   degrades to plain text (documented limitation; rich inline flows deferred).
6. Reuses `extract_infographic_data()` (module-level, `infographic.py:51`) for
   input normalization — identical fallback semantics to the other renderers.

Environment wrapping follows the existing pattern: `terminal` → rich Panel,
`default` → `list[dict]`, `html` → n/a (raise `ValueError`, HTML is WS-B's job).

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `ThemeConfig` / `ThemeRegistry` | extends | v2 fields optional; existing themes valid |
| `InfographicResponse` | extends | `document_meta` optional; `I18nText` widening |
| `BlockType` + block union | extends | +4 members; existing 15 untouched |
| `InfographicHTMLRenderer` | modifies | +4 block renderers, chrome, i18n, micro-syntax |
| `INFOGRAPHIC_SYSTEM_PROMPT` | modifies | +4 block rules, I18nText rule, micro-syntax rule |
| `InfographicRenderer` (JSON) | preserved | Serializes new fields transparently |
| `OutputMode` | extends | `A2UI = "a2ui"` |
| `register_renderer` / lazy-load map | uses | Register `A2UIRenderer` |
| `extract_infographic_data` | uses | Shared input normalization |
| `InfographicTemplateRegistry` | extends (optional) | `TEMPLATE_DEVGUIDE` preset using new blocks |

### Design Decisions

1. **Escaping over trusted HTML.** The FieldSync kit trusts text as HTML; ai-parrot
   escapes (FEAT-094 AC). We keep escaping and recover expressiveness via the
   closed micro-syntax. LLM output must never be an injection vector.
2. **Deterministic A2UI first, generative later.** The LLM keeps targeting the
   Pydantic contract that already works; the protocol layer is a pure function.
   Matches the DeterministicGuard philosophy and keeps envelope-spec churn
   (v0.9.1 → v1.0) isolated in one module.
3. **i18n rides the data model in A2UI.** Language toggle = `dataModelUpdate`
   against `/i18n/*`, not component regeneration.
4. **Charts stay data in A2UI.** ECharts option-building moves client-side for the
   A2UI surface (the `Chart` catalog component receives labels/series via data
   binding). Inline-ECharts remains exclusive to the static HTML surface.
5. **No `html` escape-hatch block.** The kit needed one; a versioned catalog must
   not. New layouts are new catalog components (new spec, new version).

---

## 3. Module Breakdown

### Module 1: Theme Schema v2  *(WS-A)*
- **Path**: `packages/ai-parrot/src/parrot/models/infographic.py`
- **Responsibility**: `CodePalette`, `MethodBadgePalette`, ThemeConfig v2 fields,
  `derive_soft()`, extended `to_css_variables()`, register built-in `petrol` theme.
- **Depends on**: existing `_CSS_COLOR_RE`, `ThemeRegistry`.

### Module 2: Block Models + Document Chrome models  *(WS-B)*
- **Path**: `parrot/models/infographic.py`
- **Responsibility**: `I18nText` + validator, `ChainBlock`, `StepsBlock`,
  `CodeBlock`, `CardGridBlock` (+ supporting models), `DocumentMeta`,
  `ChangelogEntry`; widen text fields on existing blocks; update block union,
  `BlockType`, `INFOGRAPHIC_SYSTEM_PROMPT`.
- **Depends on**: Module 1 (none hard; same file).

### Module 3: HTML Renderer v2  *(WS-B)*
- **Path**: `parrot/outputs/formats/infographic_html.py`
- **Responsibility**: `_render_chain`, `_render_steps`, `_render_code`,
  `_render_card_grid`; `_i18n()` span emitter; micro-syntax expander
  (`_expand_inline_components`, ordered escape→markdown→expand); document chrome
  (`_render_topbar`, `_render_changelog`, footer, pills); `BASE_CSS` additions
  bound to v2 variables only.
- **Depends on**: Modules 1–2, `markupsafe`, `markdown_it`.

### Module 4: A2UI Catalog  *(WS-C)*
- **Path**: `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui/`
  (`parrot-catalog.json`, `common_types.json` vendored, `envelope.schema.json`
  vendored from A2UI v0.9.1).
- **Responsibility**: catalog schema (23 components + StatusChip + MethodBadge),
  theme schema mirroring ThemeConfig v2, README with catalogId versioning policy.
- **Depends on**: A2UI v0.9.1 published schemas (vendored, not fetched at runtime).

### Module 5: A2UIRenderer  *(WS-C)*
- **Path**: `parrot/outputs/formats/a2ui.py`; `parrot/models/outputs.py`
  (`OutputMode.A2UI`); `parrot/outputs/formats/__init__.py` (registration).
- **Responsibility**: `to_envelopes()` pure translation, JSONL serialization
  (orjson), block→component mapping table, i18n data-model packing, jsonschema
  validation of every emitted envelope against the vendored schemas (debug mode:
  always; production: sampled/flagged).
- **Depends on**: Modules 1, 2, 4; `extract_infographic_data`; `orjson`;
  `jsonschema` (verify availability — see Codebase Contract).

### Module 6: Tests
- **Paths**: `tests/test_theme_v2.py`, `tests/test_infographic_fieldsync_blocks.py`,
  `tests/test_infographic_i18n.py`, `tests/test_a2ui_renderer.py`
- **Depends on**: Modules 1–5.

### Suggested phasing
`P1` = Modules 1+2 (models; everything else builds on them) →
`P2` = Module 3 (HTML v2, immediately shippable value) →
`P3` = Modules 4+5 (A2UI) → `P4` = Module 6 rounds out coverage per phase
(tests land *with* each phase, not after).

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_theme_v2_backward_compat` | 1 | Existing light/dark/corporate validate; superset CSS vars emitted; original 12 var names unchanged |
| `test_theme_petrol_tokens` | 1 | `petrol` theme emits exact FieldSync values (`--primary:#0E6E6E`, `--surface-alt:#EDF3F2`, …) |
| `test_derive_soft_defaults` | 1 | Unset `*_soft`/`surface` derive deterministically; non-hex input → fallback, no raise |
| `test_code_method_palettes_css` | 1 | `--code-*` (7) and `--m-*` (5) variables present and validated |
| `test_theme_invalid_color_v2_fields` | 1 | Bad color in any v2 field raises ValueError |
| `test_i18ntext_plain_and_dict` | 2 | `str` and `{"en","es"}` both validate; empty value / unknown lang key rejected |
| `test_new_blocks_validate` | 2 | Chain (2–8 nodes), Steps, Code, CardGrid accept valid / reject extra fields |
| `test_existing_blocks_widened` | 2 | Pre-existing payloads (plain strings) still validate unchanged |
| `test_document_meta_optional` | 2 | Responses without `document_meta` unchanged end-to-end |
| `test_render_chain_block` | 3 | Nodes + arrows; annotation in mono; last node has no arrow |
| `test_render_steps_block` | 3 | CSS-counter numbered steps |
| `test_render_code_block` | 3 | Content HTML-escaped verbatim; label rendered; no script execution |
| `test_render_card_grid_block` | 3 | Grid of cards with title/role/items |
| `test_inline_chip_badge_expansion` | 3 | `[[chip:ok X]]`, `[[m:GET]]`, `[[comp:X]]` expand; payload stays escaped |
| `test_inline_unknown_variant_literal` | 3 | `[[chip:bogus X]]` renders as literal text |
| `test_micro_syntax_after_escape` | 3 | `<script>` inside chip payload is escaped in output |
| `test_bilingual_spans_and_toggle` | 3 | i18n spans + `setLang` JS present iff `bilingual`; `default_lang` applied |
| `test_monolingual_dict_fallback` | 3 | `bilingual=False` + dict text → renders `en` only, no toggle |
| `test_topbar_changelog_render` | 3 | Version button, newest-first changelog, first entry highlighted |
| `test_no_literal_colors_in_new_css` | 3 | New CSS rules reference only `var(--…)` tokens |
| `test_outputmode_a2ui_registered` | 5 | `OutputMode.A2UI` resolves via `get_renderer` |
| `test_envelopes_schema_valid` | 5 | Every emitted envelope validates against vendored v0.9.1 schemas |
| `test_adjacency_list_integrity` | 5 | Every `ComponentId`/`ChildList` reference targets an emitted component; ids stable across runs |
| `test_block_component_mapping_complete` | 5 | All 19 block types produce a catalog component (parametrized) |
| `test_container_blocks_expand` | 5 | TabView/Accordion/CardGrid/Chain expand to parent+children entries |
| `test_chart_data_in_datamodel` | 5 | Chart labels/series under `/charts/blk-NNN`, bound via `path` |
| `test_i18n_datamodel_packing` | 5 | Active lang under `/i18n/*`; full map under `/i18n_all/*`; toggle = data-only update |
| `test_to_envelopes_pure` | 5 | Same input → byte-identical JSONL (determinism) |
| `test_jsonl_framing` | 5 | One compact JSON object per line; parseable line-by-line |
| `test_a2ui_html_environment_raises` | 5 | `environment='html'` raises ValueError |

### Integration Tests

| Test | Description |
|---|---|
| `test_fieldsync_devguide_roundtrip` | A config equivalent to a FieldSync dev-guide (chain + steps + code + chips + bilingual + changelog) renders to HTML: tags balanced, both lang spans present, petrol tokens applied |
| `test_three_surfaces_one_response` | Same `InfographicResponse` through JSON / HTML / A2UI renderers — no mutation of input; JSON output unchanged vs pre-feature snapshot |
| `test_a2ui_stream_replay` | Envelope sequence applied to a minimal in-test surface state machine reconstructs the full component tree (create → components → data → begin) |

### Test Data / Fixtures

```python
@pytest.fixture
def devguide_response():
    """FieldSync-style bilingual dev guide exercising WS-B blocks."""
    return InfographicResponse(
        theme="petrol",
        document_meta=DocumentMeta(
            brand={"en": "FieldSync · Dev Guide", "es": "FieldSync · Guía Dev"},
            version="v2.1", date="2026-07-10", bilingual=True, default_lang="en",
            changelog=[ChangelogEntry(version="v2.1", date="2026-07-10",
                                      description={"en": "A2UI surface", "es": "Superficie A2UI"})],
        ),
        blocks=[

…(truncated)…
