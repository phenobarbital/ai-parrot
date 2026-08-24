---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: Relational Field Cardinality for parrot-formdesigner (Many2one / One2many / Many2many)

**Date**: 2026-08-24
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: Option C

---

## Problem Statement

`FormSchema` cannot express **relational fields** — a field whose value is a
reference to a record in another entity (Odoo's `Many2one`), a list of such
references (`Many2many`), or a set of embedded child rows owned by the parent
record (`One2many`). The current vocabulary stops at:

- `FieldType.SELECT` / `MULTI_SELECT` / `DYNAMIC_SELECT` — choose from options,
  but the schema does not know the options *are records of another entity*.
- `OptionsSource` — knows *where* to fetch options (tool / endpoint / query)
  but carries no cardinality, no target-entity identity, and no semantics
  beyond "list of value/label pairs".
- `FieldType.ARRAY` + `item_template` — embedded repeating rows, but with no
  way to state "these rows are child records of entity X related back to the
  parent".

This blocks three concrete consumers (agreed in discovery, Round 1):

1. **Future Odoo renderer/toolkit** — the primary motivation. Generating an
   Odoo model + form view (or driving `ir.model.fields` via JSON-RPC) requires
   knowing that a field is `Many2one('res.partner')`, not "a select".
2. **Database-driven form extraction** — a DB-schema → `FormSchema` path
   should turn foreign keys into relational fields automatically instead of
   plain selects. (Note: today's `DatabaseFormTool` is a *service dispatcher*
   over stored form definitions, not a table-schema extractor — see Code
   Context. The FK story lands in the extraction layer / form services.)
3. **Current web renderers** — HTML5 / JSON Schema / Adaptive Card should
   render relations as selects fed by `OptionsSource` (v1: existing snapshot
   mechanism only; lazy server-side autocomplete deferred, Round 2 decision).

Without a first-class relational concept, every consumer would invent its own
convention inside `FormField.meta`, fragmenting the semantics the abstraction
layer exists to unify.

## Constraints & Requirements

- **Discovery decisions (Rounds 1–2):**
  - One2many reuses the existing `ARRAY` + `item_template` machinery — a
    relational One2many is "ARRAY plus relation metadata", not a new embedded
    row engine.
  - v1 option fetching uses the existing `OptionsSource`/`OptionsLoader`
    snapshot mechanism; paginated server-side autocomplete is out of scope.
  - `FormValidator` validates **shape only** in v1 (well-formed ID or list of
    IDs); existence checks are the target system's job.
  - Migration of persisted schemas is **acceptable** — no hard zero-migration
    constraint (but cheaper is still better).
- All 7 renderers (`adaptive_card`, `html5`, `jsonschema`, `telegram`, `pdf`,
  `xforms`, `audio`) must keep working; renderers that cannot express a
  relation degrade to their SELECT/MULTI_SELECT/ARRAY handling via the
  existing `FallbackRenderer` pattern.
- `FormField` uses `model_config = ConfigDict(extra="forbid")` — any new
  schema data must be a declared field, not ad-hoc keys.
- The control catalog (`controls/builtin.py`) registers one
  `FieldControlMetadata` per `FieldType`; new types must be seeded there or
  the `/api/v1/form-controls` catalog breaks.
- Extractor mappings (`extractors/yaml.py`, `extractors/jsonschema.py`) must
  round-trip the relational concept.
- Async-first, Pydantic models, Google-style docstrings (project standard).

---

## Options Explored

### Option A: Three New FieldTypes (`MANY_TO_ONE`, `ONE_TO_MANY`, `MANY_TO_MANY`)

Mirror Odoo's vocabulary directly in the `FieldType` enum. Each new type gets
a `RelationSpec` payload (new model in `core/`) holding target entity,
display field, and filters. `ONE_TO_MANY` internally behaves like `ARRAY`
(reuses `item_template`), the other two like `SELECT`/`MULTI_SELECT`.

✅ **Pros:**
- Maximally explicit — a consumer switch()ing on `field_type` immediately
  knows the cardinality; no secondary inspection.
- Odoo renderer mapping is 1:1 trivial.
- Matches the precedent of how the enum has grown (FEAT-167/448 added 20+
  types the same way).

❌ **Cons:**
- Three new enum members × 7 renderers × control catalog × 2 extractor
  mappings × validators = the widest touch surface of the three options.
- Duplicates existing semantics: `ONE_TO_MANY` is `ARRAY` with metadata,
  `MANY_TO_ONE` is `SELECT` with metadata — parallel types that renderers
  must keep behaviorally in sync with their non-relational twins forever.
- Contradicts the Round 1 decision to *reuse* ARRAY+GROUP for One2many
  (this option forks it instead).
- LLM form generation (`CreateFormTool`) must learn when to pick
  `MANY_TO_ONE` vs `SELECT` — a fuzzy boundary that invites inconsistent
  generated schemas.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic>=2.0` | `RelationSpec` model | already in project |

🔗 **Existing Code to Reuse:**
- `packages/parrot-formdesigner/src/parrot_formdesigner/core/types.py` — enum growth pattern (FEAT-167/448 phases)
- `packages/parrot-formdesigner/src/parrot_formdesigner/controls/builtin.py` — per-type metadata seeding pattern

---

### Option B: Extend `OptionsSource` with Relation Metadata (no new types, no new model)

Add optional fields to `OptionsSource` itself: `target_entity`,
`entity_namespace`, `relation_kind` (`"one" | "many"`). A `SELECT` whose
`options_source.target_entity` is set ≡ Many2one; `MULTI_SELECT` ≡ Many2many;
`ARRAY` whose `item_template` carries a back-reference ≡ One2many.

✅ **Pros:**
- Smallest diff: one model grows, zero renderer changes (they already ignore
  unknown `OptionsSource` fields), zero control-catalog changes.
- Persisted schemas need no migration at all.

❌ **Cons:**
- **Semantic overloading**: `OptionsSource` is a *fetch mechanism* ("where do
  options come from") and would now also carry *data semantics* ("this value
  is a foreign key"). A Many2one with **static** `options` (small fixed
  entity) has no `OptionsSource` at all — the relation metadata has no home,
  forcing a dummy source. This is a real modeling hole, not a corner case.
- One2many can't be expressed here at all (`ARRAY` has no options) — needs a
  second, different convention anyway, so the design fragments.
- Cardinality lives implicitly in the SELECT/MULTI_SELECT split; consumers
  must correlate two places to know what a field means.

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic>=2.0` | extended `OptionsSource` | already in project |

🔗 **Existing Code to Reuse:**
- `packages/parrot-formdesigner/src/parrot_formdesigner/core/options.py:32` — `OptionsSource` (already grew via "Phase 2 additions (FEAT-167)": `http_method`, `auth_ref`)
- `packages/parrot-formdesigner/src/parrot_formdesigner/services/options_loader.py` — fetch/cache machinery, untouched

---

### Option C: Orthogonal `RelationSpec` on `FormField` (relation as an *aspect*, not a type)

Relations are modeled as a new optional field `FormField.relation:
RelationSpec | None` — orthogonal to `field_type`, exactly like
`constraints`, `options_source`, and `depends_on` already are. A new
`core/relations.py` defines:

- `RelationSpec`: `cardinality` (`"one" | "many"`), `target`
  (`EntityRef`), `mode` (`"reference" | "embed"`), `display_field`,
  `inverse_field` (for embed/One2many), `on_delete` hint, `filters`.
- `EntityRef`: `namespace: str` (e.g. `"odoo"`, `"db"`, `"api"`,
  `"formdesigner"`) + `entity: str` (e.g. `"res.partner"`,
  `"public.customers"`, a `form_id`) + optional `key_field`. Free-form
  namespace, no central registry (both worlds from the Round 2 "explore"
  answer: an external entity string AND an optional pointer back into the
  FormRegistry via `namespace="formdesigner"`).

Canonical combinations (validated by a Pydantic model-validator):

| Odoo concept | field_type | relation |
|---|---|---|
| Many2one | `SELECT` (or `DYNAMIC_SELECT`) | `cardinality="one", mode="reference"` |
| Many2many | `MULTI_SELECT` / `TAGS` / `TRANSFER_LIST` | `cardinality="many", mode="reference"` |
| One2many | `ARRAY` + `item_template` | `cardinality="many", mode="embed", inverse_field=...` |

Renderers need **zero changes to keep working**: a relational SELECT is still
a SELECT (options via static `options` or `OptionsSource`, as today). The
relation is extra semantics consumed by the parties that care (Odoo renderer,
DB extraction, JSON Schema renderer surfacing it as an `x-relation`
extension). Persisted-schema migration is a no-op (new optional field,
defaults to `None`) even though migration was allowed.

✅ **Pros:**
- Honors both Round 1 decisions natively: ARRAY+GROUP reuse for One2many,
  and current renderers keep functioning untouched.
- Follows the schema's own architecture — `FormField` already composes
  orthogonal aspects (`constraints`, `options_source`, `depends_on`,
  `post_depends`); relation is one more.
- Handles the static-options Many2one that breaks Option B.
- `EntityRef.namespace` gives Odoo (`res.partner`), DB (`schema.table`), and
  formdesigner-internal (`form_id`) targets one uniform shape without a
  central registry.
- `CreateFormTool`/LLM guidance stays simple: pick the visual type as today,
  attach `relation` when the prompt implies a reference to another entity.
- No control-catalog or enum churn; opt-in surfacing per renderer.

❌ **Cons:**
- Cardinality is not visible in `field_type` alone — consumers wanting
  relational awareness must check `field.relation` (mitigated by the
  validator constraining legal combinations, and by a helper predicate).
- Illegal combinations (e.g. `relation` on `BOOLEAN`) must be actively
  rejected by validation — the enum approach makes them unrepresentable.
- One more optional field on an already wide `FormField`.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic>=2.0` | `RelationSpec`, `EntityRef` + model-validators | already in project |

🔗 **Existing Code to Reuse:**
- `packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py:44` — `FormField` composition pattern (`constraints`/`options_source`/`depends_on` as optional aspects)
- `packages/parrot-formdesigner/src/parrot_formdesigner/core/options.py:32` — `OptionsSource` continues to serve option fetching for `mode="reference"` fields
- `packages/parrot-formdesigner/src/parrot_formdesigner/services/options_loader.py` — unchanged runtime fetching
- `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/jsonschema.py` — extension-key pattern (`x-*`) for surfacing relation metadata to frontends
- `packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py` — shape validation hook for ID / list-of-IDs values

---

## Recommendation

**Option C** is recommended because:

1. **It is the only option consistent with both discovery decisions at once.**
   Round 1 fixed One2many = existing `ARRAY`+`item_template`; Option A forks
   that machinery into a parallel type, and Option B cannot express embed at
   all. Option C decorates the existing types instead of duplicating them.
2. **It matches the schema's own composition architecture.** `FormField`
   already treats validation, option sourcing, and dependency rules as
   orthogonal optional aspects. Relation semantics are the same kind of
   thing: *what the value means*, independent of *which widget renders it*.
3. **Blast radius is honest.** Option B is cheaper but leaves the
   static-options Many2one and the whole One2many case unmodeled — its "Low"
   effort buys an incomplete feature. Option A's explicitness costs a
   7-renderer × catalog × extractors sweep and a permanent SELECT/MANY_TO_ONE
   duplication. Option C sits between: new `core/relations.py`, a validator,
   two extractor mappings, and *opt-in* surfacing in the renderers that care.
4. **The tradeoff accepted**: relational awareness requires checking
   `field.relation` instead of the enum. A `FormField.is_relational` helper
   and strict combination validation keep this cheap and safe.

---

## Feature Description

### User-Facing Behavior

- **Form authors (YAML / JSON Schema / API)** declare a relation on a field:
  a `relation:` block with `cardinality`, `target` (`namespace` + `entity`),
  `mode`, and optionally `display_field` / `inverse_field`. Visual type stays
  what it is today (`select`, `multi_select`, `tags`, `array`).
- **LLM-driven creation** (`CreateFormTool`): prompts like "a customer field
  referencing res.partner" produce a `SELECT` with
  `relation={cardinality: one, target: {namespace: odoo, entity: res.partner}}`.
- **Web renderers**: nothing visibly changes in v1 — a relational SELECT
  renders as the same select fed by `OptionsSource`; the JSON Schema renderer
  additionally emits an `x-relation` extension so frontends can build richer
  pickers later.
- **Odoo consumer (future feature)**: reads `relation` to emit
  `fields.Many2one("res.partner")` / `One2many(..., inverse_field)` /
  `Many2many` instead of `Selection` — the entire point of this feature.

### Internal Behavior

- `core/relations.py` defines `EntityRef` and `RelationSpec` (Pydantic,
  `extra="forbid"`).
- `FormField` gains `relation: RelationSpec | None = None`. A model-validator
  enforces legal (field_type × cardinality × mode) combinations:
  - `mode="reference"` requires an option-bearing type (`SELECT`,
    `DYNAMIC_SELECT`, `MULTI_SELECT`, `TAGS`, `TRANSFER_LIST`, `TREE_SELECT`);
    `cardinality` must match the single/multi nature of the type.
  - `mode="embed"` requires `field_type=ARRAY` with an `item_template`, and
    `inverse_field` naming the child field that points back to the parent.
- Option fetching for `mode="reference"` is *delegated to the existing
  mechanism*: static `options` or `OptionsSource` + `OptionsLoader`
  (snapshot, TTL cache) — no new runtime service in v1.
- `FormValidator` (services/validators.py) validates shape only: reference
  values must be a scalar ID (cardinality one) or a list of IDs (many);
  embed values validate recursively through the existing ARRAY path.
- Extractors: `yaml.py` and `jsonschema.py` gain parse/emit for the
  `relation` block (`x-relation` on the JSON Schema side). `pydantic.py` and
  `tool.py` are untouched in v1 (no relational inference from type hints).
- JSON Schema renderer emits `x-relation`; all other renderers ignore
  `relation` in v1 (documented no-op, same convention the XForms renderer
  uses for `style`/`prefilled`).
- A follow-up feature (out of scope here) adds the FK-aware DB-schema
  extraction and the Odoo renderer/toolkit that consume `RelationSpec`.

### Edge Cases & Error Handling

- **Illegal combination** (`relation` on `BOOLEAN`; `cardinality="one"` on
  `MULTI_SELECT`; `mode="embed"` without `ARRAY`/`item_template`): rejected
  at model-validation time with a message naming field_id and the rule.
- **`inverse_field` missing or naming a nonexistent child field** in embed
  mode: rejected by a form-level check in the resolution pass (same boundary
  where `resolve_rule_references` runs).
- **Relational field with neither `options` nor `options_source`**
  (reference mode): allowed — the relation is still meaningful to Odoo/DB
  consumers; web renderers render an empty select and log a warning (existing
  `OptionsLoader` failure-safe convention: degrade, never raise).
- **Unknown namespace**: allowed (free-form by design); consumers that don't
  recognize a namespace ignore the relation. Namespaces are documented, not
  enforced.
- **Persisted schemas (PostgreSQL / registry)**: load unchanged —
  `relation=None` default; `model_dump()` round-trips. No migration script
  required despite migration being permitted.
- **`extra="forbid"` interaction**: old readers of new schemas (a deployed
  older parrot-formdesigner loading a schema that has `relation`) will
  reject it — acceptable per the migration-allowed decision, but noted for
  release ordering.

---

## Capabilities

### New Capabilities
- `formfield-relation-spec`: `RelationSpec`/`EntityRef` core models, the
  `FormField.relation` aspect, and combination validation
- `relation-extractor-mappings`: YAML and JSON Schema extractor support for
  declaring/round-tripping relations (`x-relation` extension)
- `relation-shape-validation`: `FormValidator` shape checks for reference
  IDs / ID lists

### Modified Capabilities
- `form-abstraction-layer` (FEAT — `sdd/specs/form-abstraction-layer.spec.md`):
  `FormSchema` vocabulary grows one orthogonal aspect; renderer contract note
  ("ignore `relation` unless you consume it")

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot_formdesigner/core/relations.py` | new | `EntityRef`, `RelationSpec` |
| `parrot_formdesigner/core/schema.py` | extends | `FormField.relation` + combination validator; `model_rebuild()` already in place |
| `parrot_formdesigner/core/__init__.py` | extends | export new models |
| `parrot_formdesigner/core/resolution.py` | extends | form-level `inverse_field` existence check alongside rule resolution |
| `parrot_formdesigner/extractors/yaml.py` | extends | parse `relation:` block |
| `parrot_formdesigner/extractors/jsonschema.py` | extends | parse/emit `x-relation` |
| `parrot_formdesigner/renderers/jsonschema.py` | extends | emit `x-relation` |
| `parrot_formdesigner/services/validators.py` | extends | ID / ID-list shape validation |
| other renderers (html5, adaptive_card, telegram, pdf, xforms, audio) | none (documented no-op) | relation ignored in v1; existing SELECT/ARRAY paths render the field |
| `controls/builtin.py`, `FieldType` enum | none | no new types — deliberate |
| persisted `FormSchema` storage | compatible | optional field, `None` default; no migration script |
| future Odoo renderer/toolkit, DB-schema FK extractor | depends on | separate follow-up features consuming `RelationSpec` |

---

## Code Context

### User-Provided Code

*(none — user provided the framing note: "FieldType no tiene equivalente de
Many2one/One2many; OptionsSource (opciones dinámicas) es el candidato natural
a mapear a Many2one")*

### Verified Codebase References

#### Classes & Signatures
```python
# From packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py:44
class FormField(BaseModel):
    model_config = ConfigDict(extra="forbid")        # line 78
    field_uid: uuid.UUID                              # line 80 (FEAT-393, default_factory=uuid4)
    field_id: str                                     # line 81
    field_type: FieldType                             # line 82
    required: bool = False                            # line 86
    constraints: FieldConstraints | None = None       # line 89
    options: list[FieldOption] | None = None          # line 90
    options_source: OptionsSource | None = None       # line 91
    depends_on: DependencyRule | None = None          # line 92
    post_depends: list[PostDependency] | None = None  # line 93
    children: list[FormField] | None = None           # line 94  (GROUP)
    item_template: FormField | None = None            # line 95  (ARRAY)
    meta: dict[str, Any] | None = None                # line 96
# FormField.model_rebuild() at schema.py:100

# From packages/parrot-formdesigner/src/parrot_formdesigner/core/options.py:32
class OptionsSource(BaseModel):
    source_type: str                                  # line 45  ("tool" | "endpoint" | "query")
    source_ref: str                                   # line 46
    value_field: str = "value"                        # line 47
    label_field: str = "label"                        # line 48
    cache_ttl_seconds: int | None = None              # line 49
    http_method: Literal["GET", "POST"] = "GET"       # line 51  (FEAT-167)
    auth_ref: str | None = None                       # line 52

# From packages/parrot-formdesigner/src/parrot_formdesigner/core/types.py:16
class FieldType(str, Enum):
    SELECT = "select"                 # line 27
    MULTI_SELECT = "multi_select"     # line 28
    GROUP = "group"                   # line 37
    ARRAY = "array"                   # line 38
    DYNAMIC_SELECT = "dynamic_select" # line 41 (FEAT-167)
    TRANSFER_LIST = "transfer_list"   # line 42
    TAGS = "tags"                     # line 46
    TREE_SELECT = "tree_select"       # line 62 (FEAT-448)
    # 45+ members total — no relational types exist

# From packages/parrot-formdesigner/src/parrot_formdesigner/renderers/base.py
class AbstractFormRenderer(ABC):                      # line ~57
    @abstractmethod
    async def render(self, form: FormSchema, style: StyleSchema | None = None,
                     *, locale: str = "en", prefilled: dict[str, Any] | None = None,
                     errors: dict[str, str] | None = None) -> RenderedForm: ...
class FallbackRenderer:                               # degraded-representation hook

# From packages/parrot-formdesigner/src/parrot_formdesigner/services/options_loader.py:30
class OptionsLoader:
    # aiohttp-based fetch of FieldOption lists from OptionsSource endpoints;
    # TTL cache keyed by (source_ref, auth_ref); single-flight; failure-safe
    # (returns [] and logs — never raises)

# From packages/parrot-formdesigner/src/parrot_formdesigner/core/resolution.py:28
def resolve_rule_references(form: FormSchema) -> FormSchema:
    # build-time field_id → field_uid rewriting; the natural boundary for a
    # form-level inverse_field existence check
```

#### Verified Imports
```python
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection, RenderedForm
from parrot_formdesigner.core.types import FieldType, LocalizedString
from parrot_formdesigner.core.options import FieldOption, OptionsSource
from parrot_formdesigner.core.constraints import FieldConstraints
from parrot_formdesigner.renderers.base import AbstractFormRenderer, FallbackRenderer
```

#### Key Attributes & Constants
- `FormField.meta` → `dict[str, Any] | None` (schema.py:96) — the escape
  hatch Option C deliberately avoids for relations (typed model instead)
- `controls/builtin.py` seeds one `FieldControlMetadata` **per FieldType
  member** (45 `FieldType.` references) — the hidden cost of any new-enum
  option
- `extractors/jsonschema.py:245` builds `OptionsSource` from an `x-`
  extension key — the precedent for `x-relation`
- `renderers/xforms.py:83` maps `DYNAMIC_SELECT` like `SELECT` — the
  degrade-to-select precedent for relation-unaware renderers

### Does NOT Exist (Anti-Hallucination)
- ~~Any relational `FieldType`~~ (`MANY_TO_ONE`, `RELATION`, `REFERENCE`,
  `FOREIGN_KEY`) — no such enum members
- ~~`RelationSpec` / `EntityRef` / `core/relations.py`~~ — to be created by
  this feature
- ~~`OptionsSource.target_entity` / `.relation_kind` / `.cardinality`~~ —
  `OptionsSource` has exactly the 7 fields listed above
- ~~A DB-table-schema → FormSchema extractor with FK awareness~~ —
  `DatabaseFormTool` (tools/database_form.py:76) is a dispatcher over
  registered `AbstractFormService`s (e.g. networkninja) that fetch *stored
  form definitions*, not table schemas; extractors/ contains only
  `jsonschema.py`, `pydantic.py`, `tool.py`, `yaml.py`
- ~~An Odoo renderer or Odoo toolkit~~ — nothing Odoo-related exists in the
  repo yet (separate follow-up feature)
- ~~Server-side paginated option search endpoint~~ — `OptionsLoader` fetches
  full snapshot lists only

---

## Parallelism Assessment

- **Internal parallelism**: Low-to-moderate. The core models + `FormField`
  change is the foundation and gates everything. After it lands, the two
  extractor mappings, the JSON Schema renderer extension, and the validator
  shape checks are four small independent tasks — but each is hours, not
  days, so worktree-per-task overhead is not justified.
- **Cross-feature independence**: touches `core/schema.py`, which most
  formdesigner features graze — check for in-flight formdesigner worktrees
  before starting. No conflict with the SDD/docs features currently on dev.
- **Recommended isolation**: `per-spec` (one worktree, sequential tasks).
- **Rationale**: single foundational schema change with thin dependent
  edits; sequential execution in one worktree avoids merge churn on
  `core/schema.py`.

---

## Open Questions

- [x] ¿Modelado: nuevos FieldTypes, extender OptionsSource, o aspecto ortogonal? — *Owner: Jesus Lara*: explorado aquí; recomendación = Option C (aspecto `relation` ortogonal).
- [x] ¿One2many: embed vs referencias? — *Owner: Jesus Lara*: reusar ARRAY+item_template (embed) con `inverse_field`; referencias cubiertas por cardinality="many" + mode="reference".
- [x] ¿Autocomplete server-side para tablas grandes en v1? — *Owner: Jesus Lara*: no — v1 usa el snapshot de OptionsSource/OptionsLoader existente; búsqueda paginada es feature posterior.
- [x] ¿Validación de existencia del ID referenciado? — *Owner: Jesus Lara*: no en v1 — solo shape (ID escalar / lista de IDs); la existencia la verifica el sistema destino.
- [x] ¿Migración de schemas persistidos aceptable? — *Owner: Jesus Lara*: sí, aceptable — aunque Option C termina sin requerir migración (campo opcional, default None).
- [ ] ¿Debe `PydanticExtractor`/`ToolExtractor` inferir relaciones desde type hints (p.ej. un campo tipado como otro modelo) en una fase posterior? — *Owner: Jesus Lara*
- [ ] Catálogo de namespaces de `EntityRef` (`odoo`, `db`, `api`, `formdesigner`): ¿documentación libre o constantes exportadas? — *Owner: Jesus Lara*
- [ ] ¿El renderer HTML5 debería emitir `data-relation-*` attributes (como hace con `data-depends-on`) ya en v1, o esperar al feature de autocomplete? — *Owner: Jesus Lara*
- [ ] Semántica de `on_delete` hint (restrict/cascade/set-null): ¿se incluye en RelationSpec v1 o se difiere al consumidor Odoo? — *Owner: Jesus Lara*
