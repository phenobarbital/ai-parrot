# Brainstorm: parrot-formdesigner Integration in navigator-api

**Date**: 2026-04-04
**Author**: Juan2coder
**Status**: exploration
**Recommended Option**: A

---

## Problem Statement

navigator-api has an existing form system (`FormModel` + `BaseModel`) tightly coupled to
specific workflows like Zammad ticket creation. That system covers basic use cases but
doesn't provide form discovery, dynamic rendering for multiple channels (web + MS Teams),
or a standalone form management API.

`parrot-formdesigner` provides all of that: canonical `FormSchema`, multi-channel renderers
(HTML5, Adaptive Cards), validation with dependency rules, and a complete HTTP API surface.

The source of truth for form definitions is the `networkninja` schema: NetworkNinja sends
forms to Navigator which stores them in `networkninja.forms` (with `question_blocks` JSONB
string) and `networkninja.form_metadata` (field types + options). Navigator then distributes
processed data to client schemas (flexroc, pokemon, etc.).

The goal is to expose those forms through parrot-formdesigner at a **separate** endpoint
(`/api/v3/forms`) — no overlap with existing `FormModel` handlers — supporting HTML5 rendering
for the navigator-next frontend and Adaptive Cards for MS Teams bots, with submissions
going back to `networkninja.form_responses`.

**Who is affected**: frontend web consumers (navigator-next), MS Teams bot users, API
integrators.

---

## Constraints & Requirements

- Must be a **separate segment** — no modifications to existing `FormModel`, `apps/support`,
  or any current navigator-api form handlers.
- Routes must live under `/api/v3/forms` (or configurable prefix).
- Form definitions come from `networkninja.forms` + `networkninja.form_metadata` — these
  are the authoritative sources; we do not create a parallel form definition system.
- `question_blocks` is stored as a JSON **string scalar** inside JSONB — requires
  `::text` cast and `json.loads()` on the Python side before processing.
- Must render to both **HTML5** (navigator-next web) and **Adaptive Cards** (MS Teams).
- Form submissions must go to `networkninja.form_responses` (existing EAV table).
- Multi-tenancy via `orgid` + `client_id` — all form queries must be scoped.
- PoC targets staging environment; a clean, demonstrable slice is the priority.
- Uses navigator-api's existing AsyncDB connection pool (no new connection management).
- `parrot-formdesigner` must be added as a dependency to navigator-api's `pyproject.toml`.

---

## Options Explored

### Option A: NetworkNinja Bridge — Custom Extractor + Full parrot Stack

Write a `NetworkNinjaExtractor` that reads `networkninja.forms` + `networkninja.form_metadata`
and converts them to `FormSchema`. Mount the full `setup_form_routes()` surface on
`/api/v3/forms`. Use `PostgresFormStorage` with a new `navigator.form_schemas` cache table
so converted schemas are stored and served fast. Submissions are handled by a thin custom
handler that writes to `networkninja.form_responses`.

The extractor mapping:
- `question_blocks[]` (blocks) → `FormSection[]`
- `question_block_logic_groups` → section `depends_on`
- `questions[]` → `FormField[]`
- `question_description` → `label`
- `question_column_name` → `field_id`
- `question_logic_groups[].conditions` → `DependencyRule` + `FieldCondition`
  (condition_logic "EQUALS" → `ConditionOperator.EQ`, etc.)
- `validations[].validation_type == "responseRequired"` → `required=True`
- `form_metadata.data_type` → `FieldType` mapping
- `form_metadata.options` (JSONB) → `FieldOption[]` for SELECT fields

✅ **Pros:**
- Fully leverages parrot's validation, rendering, registry, and HTTP surface — no reimplementation.
- `NetworkNinjaExtractor` is reusable for other consumers (bots, agents).
- `FormRegistry` + `PostgresFormStorage` cache means subsequent requests don't hit `networkninja.forms` every time.
- Both HTML5 and Adaptive Card rendering available out of the box.
- Clean separation: extractor bridges the schemas, parrot handles everything else.
- Directly uses the `setup_form_routes(prefix="/api/v3/forms")` pattern — minimal wiring in `app.py`.

❌ **Cons:**
- Requires writing `NetworkNinjaExtractor` — moderate effort to map all field types and
  logic conditions correctly.
- `question_blocks` scalar-JSONB quirk requires careful parsing (must cast to text first).
- `PostgresFormStorage` creates a new `navigator.form_schemas` table — small schema migration needed.
- No built-in refresh mechanism when NetworkNinja updates a form (cache invalidation needed in v2).

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `parrot-formdesigner>=0.1.0` | FormSchema, renderers, validators, HTTP handlers | From `packages/parrot-formdesigner` in this monorepo |
| `asyncpg` | PostgreSQL access for extractor and storage | Already in navigator-api via asyncdb |
| `aiohttp>=3.9` | HTTP routing | Already in navigator-api |

🔗 **Existing Code to Reuse:**
- `packages/parrot-formdesigner/src/parrot/formdesigner/handlers/routes.py` — `setup_form_routes()` for one-liner route registration with prefix
- `packages/parrot-formdesigner/src/parrot/formdesigner/services/storage.py` — `PostgresFormStorage` for FormSchema caching
- `packages/parrot-formdesigner/src/parrot/formdesigner/services/registry.py` — `FormRegistry` for in-memory serving
- `packages/parrot-formdesigner/src/parrot/formdesigner/renderers/html5.py` — `HTML5Renderer`
- `packages/parrot-formdesigner/src/parrot/formdesigner/renderers/adaptive_card.py` — `AdaptiveCardRenderer`
- `packages/parrot-formdesigner/src/parrot/formdesigner/services/validators.py` — `FormValidator` + `ValidationResult`
- `navigator-api/app.py` — `AppHandler.configure()` pattern for registering the new sub-app

---

### Option B: Thin Proxy — Raw NetworkNinja Format + Renderer Layer Only

Skip `FormSchema` entirely. Build a minimal aiohttp handler that reads `networkninja.forms`
raw and passes `question_blocks` directly to custom rendering functions that produce HTML5
or Adaptive Cards natively from the NetworkNinja JSON format. No `FormRegistry`, no
`FormValidator`, no parrot service layer.

✅ **Pros:**
- Simpler to start — no extractor mapping work.
- No new tables needed.

❌ **Cons:**
- Throws away parrot-formdesigner completely — defeats the purpose of the integration.
- Duplicates rendering logic that already exists and is tested in parrot.
- No validation, no dependency rule enforcement, no multi-channel abstraction.
- Not reusable for agents or bots that expect `FormSchema`.
- Technical debt from day one.

📊 **Effort:** Low (initially) — High (when requirements grow)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `aiohttp` | HTTP handlers | Already available |
| `jinja2` | Custom HTML rendering | Would duplicate parrot's renderer |

🔗 **Existing Code to Reuse:**
- `apps/support/views.py` — FormModel pattern (for reference only, not reuse)

---

### Option C: New `apps/forms` Module — Manual parrot Integration per Endpoint

Create `apps/forms/` in navigator-api following the existing app pattern. Each endpoint
manually calls specific parrot-formdesigner components (extractor, renderer, validator)
without using `setup_form_routes()`. Full control over each route but assembled by hand.

✅ **Pros:**
- Fits exactly in navigator-api's existing app module structure (`models.py`, `views.py`, `urls.py`).
- Fine-grained control over each endpoint — easier to add navigator-specific middleware
  (auth decorators, session injection) per route.
- No parrot HTTP layer involved — only parrot's data/service layer.

❌ **Cons:**
- Significant boilerplate: must manually wire every endpoint that `setup_form_routes()` gives for free.
- Duplication risk — reimplementing routing logic that parrot already tests.
- Harder to keep in sync as parrot-formdesigner evolves.
- More code to maintain for PoC with no clear advantage over Option A.

📊 **Effort:** Medium-High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `parrot-formdesigner>=0.1.0` | Service layer only (extractor, renderer, validator) | Handlers NOT used |
| `aiohttp` | Custom routing | Already available |

🔗 **Existing Code to Reuse:**
- `apps/support/urls.py` — `crud_url()` routing pattern
- `apps/support/views.py` — `FormModel` / `ModelView` handler pattern
- `packages/parrot-formdesigner/src/parrot/formdesigner/services/` — validators, registry

---

## Recommendation

**Option A** is recommended because:

The whole point of this integration is to bring parrot-formdesigner's capabilities into
navigator-api — throwing away the HTTP layer (Option C) or the schema layer (Option B)
defeats that purpose. Option A uses everything parrot provides and keeps the navigator-api
side thin: one `NetworkNinjaExtractor`, one `PostgresFormStorage` init, one
`setup_form_routes(prefix="/api/v3/forms")` call.

The extractor work is the only custom effort needed, and it's well-scoped: the
NetworkNinja format is straightforward (blocks → sections, questions → fields, logic
groups → DependencyRules). The `question_blocks` scalar-JSONB quirk is a one-line
workaround.

For the PoC the cache table is a clean win: forms convert once, serve fast. Cache
invalidation can be manual (admin endpoint) for now.

---

## Feature Description

### User-Facing Behavior

- **GET `/api/v3/forms`** — lists all available forms (from registry, loaded from
  `networkninja.forms` on first access), scoped by `orgid`.
- **GET `/api/v3/forms/{form_id}/html`** — returns HTML5 form fragment ready to embed in
  navigator-next. Supports `?prefilled={json}` and `?locale=en|es` query params.
- **GET `/api/v3/forms/{form_id}/schema`** — returns the canonical `FormSchema` as JSON,
  used by MS Teams bot to request Adaptive Cards.
- **GET `/api/v3/forms/{form_id}`** with `Accept: application/vnd.microsoft.card.adaptive`
  header (or `?renderer=adaptive_card`) — returns Adaptive Card JSON v1.5 for MS Teams.
- **POST `/api/v3/forms/{form_id}/validate`** — validates a JSON payload against the form's
  field constraints and dependency rules. Returns `{"valid": true}` or
  `{"valid": false, "errors": {...}}`.
- **POST `/api/v3/forms`** (internal/admin) — triggers extraction of a form from
  `networkninja.forms` by `formid` + `orgid` and stores in the cache.

### Internal Behavior

1. On navigator-api startup, a `FormRegistry` is initialized with `PostgresFormStorage`
   pointing to the existing asyncpg pool (`navigator.form_schemas` cache table).
2. When a form is requested by `form_id`, the registry checks its in-memory cache first,
   then falls back to `PostgresFormStorage`.
3. If not found in storage, the `NetworkNinjaExtractor` is called: it queries
   `networkninja.forms` by `formid` (parsing `question_blocks::text` → JSON), then fetches
   `networkninja.form_metadata` rows for field types and options, and produces a `FormSchema`.
   The result is registered and persisted to `navigator.form_schemas`.
4. Rendering is performed on-demand: `HTML5Renderer` or `AdaptiveCardRenderer` receives
   the `FormSchema` and returns a `RenderedForm`. The content type determines the response.
5. On form submission (POST to the page handler), `FormValidator.validate()` runs first.
   If valid, a custom `NinjaSubmissionHandler` writes each field response to
   `networkninja.form_responses` (inserting rows with `formid`, `form_id`, `column_name`,
   `data`, `orgid`, `client_id`).
6. Authentication follows the existing navigator-api pattern: `@ModelView.service_auth`
   decorator on protected routes; `orgid` extracted from the session.

### Edge Cases & Error Handling

- **`question_blocks` is NULL**: form has no questions — return empty `FormSchema` with
  a single section containing zero fields. Log a warning.
- **Unknown `data_type` in `form_metadata`**: fall back to `FieldType.TEXT`. Log at DEBUG.
- **Unknown `condition_logic` value**: skip that condition, log a warning. Don't fail
  the entire extraction.
- **Form not found in `networkninja.forms`**: return HTTP 404 with `{"error": "form not found"}`.
- **Validation failure on submission**: return HTTP 422 with the `ValidationResult.errors` dict.
- **`form_metadata` rows missing for a `question_column_name`**: field renders as TEXT
  with no options — safe default.
- **Registry cold start**: first request per form pays the extraction cost; subsequent
  requests are served from memory.

---

## Capabilities

### New Capabilities

- `networkninja-form-extractor`: `NetworkNinjaExtractor` class that converts
  `networkninja.forms` + `networkninja.form_metadata` rows to `FormSchema`.
- `formdesigner-api-mount`: navigator-api wiring that mounts `setup_form_routes()` at
  `/api/v3/forms` with a shared `FormRegistry` + `PostgresFormStorage`.
- `ninja-submission-handler`: async handler that writes validated form responses to
  `networkninja.form_responses`.
- `form-schema-cache-table`: `navigator.form_schemas` DDL migration for storing
  converted `FormSchema` objects.

### Modified Capabilities

- `navigator-api/app.py` — adds `setup_form_routes()` call and registry/storage
  initialization in `AppHandler.configure()`.
- `navigator-api/pyproject.toml` — adds `parrot-formdesigner>=0.1.0` dependency.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `navigator-api/app.py` | extends | Adds `setup_form_routes()` and startup init |
| `navigator-api/pyproject.toml` | extends | New dependency: `parrot-formdesigner` |
| `networkninja.forms` | depends on | Read-only; source of form definitions |
| `networkninja.form_metadata` | depends on | Read-only; source of field types and options |
| `networkninja.form_responses` | extends | New writes from submission handler |
| `navigator.form_schemas` (new table) | new | Cache for converted `FormSchema` objects |
| `packages/parrot-formdesigner` | depends on | Used as library — no modifications needed |
| Existing `apps/support`, `FormModel` | none | Zero overlap; completely separate segment |

---

## Code Context

### User-Provided Code

```json
// Source: networkninja.forms.question_blocks (real data, 2026-04-04)
// question_blocks is stored as a JSON string scalar inside JSONB
// Must be extracted with: SELECT question_blocks::text FROM networkninja.forms
[
  {
    "question_block_id": 60,
    "question_block_type": "simple",
    "question_block_logic_groups": [],
    "questions": [
      {
        "question_id": 1106,
        "question_column_name": "9514",
        "question_description": "Model 58R6: Is this model displayed on the sales floor?",
        "question_logic_groups": [],
        "validations": [
          {
            "validation_id": 701,
            "validation_type": "responseRequired",
            "validation_logic": null,
            "validation_comparison_value": null,
            "validation_question_reference_id": null
          }
        ]
      },
      {
        "question_id": 1107,
        "question_column_name": "9515",
        "question_description": "Model 58R6: Is this model's correct price listed as $238?",
        "question_logic_groups": [
          {
            "logic_group_id": 2233,
            "conditions": [
              {
                "condition_id": 2373,
                "condition_logic": "EQUALS",
                "condition_comparison_value": "1",
                "condition_question_reference_id": 1106,
                "condition_option_id": null
              }
            ]
          }
        ],
        "validations": [{"validation_id": 702, "validation_type": "responseRequired", ...}]
      }
    ]
  }
]
```

### Verified Codebase References

#### Classes & Signatures

```python
# From packages/parrot-formdesigner/src/parrot/formdesigner/handlers/routes.py:20
def setup_form_routes(
    app: web.Application,
    *,
    registry: FormRegistry | None = None,
    client: "AbstractClient | None" = None,
    api_key: str | None = None,
    prefix: str = "",
) -> None: ...

# From packages/parrot-formdesigner/src/parrot/formdesigner/services/storage.py:39
class PostgresFormStorage(FormStorage):
    def __init__(self, pool: Any) -> None: ...
    async def initialize(self) -> None: ...  # creates form_schemas table via CREATE TABLE IF NOT EXISTS
    async def save(self, form: FormSchema, style: StyleSchema | None = None, *, created_by: str | None = None) -> str: ...
    async def load(self, form_id: str, version: str | None = None) -> FormSchema | None: ...
    async def delete(self, form_id: str) -> bool: ...
    async def list_forms(self) -> list[dict[str, str]]: ...

# From packages/parrot-formdesigner/src/parrot/formdesigner/services/registry.py
class FormRegistry:
    async def register(self, form: FormSchema, persist: bool = False, overwrite: bool = True) -> None: ...
    async def get(self, form_id: str) -> FormSchema | None: ...
    async def list_forms(self) -> list[FormSchema]: ...
    async def load_from_storage(self) -> None: ...

# From packages/parrot-formdesigner/src/parrot/formdesigner/services/validators.py
class FormValidator:
    async def validate(self, form: FormSchema, data: dict, locale: str = "en") -> ValidationResult: ...

class ValidationResult:
    is_valid: bool
    errors: dict[str, list[str]]
    sanitized_data: dict[str, Any]

# From packages/parrot-formdesigner/src/parrot/formdesigner/core/schema.py
class FormSchema(BaseModel):
    form_id: str
    version: str
    title: LocalizedString
    description: LocalizedString | None
    sections: list[FormSection]
    submit: SubmitAction | None
    cancel_allowed: bool
    meta: dict[str, Any]

class FormSection(BaseModel):
    section_id: str
    title: LocalizedString | None
    description: LocalizedString | None
    fields: list[FormField]
    depends_on: list[DependencyRule]
    meta: dict[str, Any]

class FormField(BaseModel):
    field_id: str
    field_type: FieldType
    label: LocalizedString
    required: bool
    constraints: FieldConstraints | None
    options: list[FieldOption]
    depends_on: list[DependencyRule]

class DependencyRule(BaseModel):
    conditions: list[FieldCondition]
    logic: str  # "and" | "or"
    effect: str  # "show" | "hide" | "require" | "disable"

class FieldCondition(BaseModel):
    field_id: str
    operator: ConditionOperator
    value: Any

# From packages/parrot-formdesigner/src/parrot/formdesigner/core/constraints.py
class ConditionOperator(str, Enum):
    EQ = "eq"
    NEQ = "neq"
    GT = "gt"
    LT = "lt"
    GTE = "gte"
    LTE = "lte"
    IN = "in"
    NOT_IN = "not_in"
    IS_EMPTY = "is_empty"
    IS_NOT_EMPTY = "is_not_empty"
```

#### Verified Imports

```python
# All confirmed via packages/parrot-formdesigner/src/parrot/formdesigner/__init__.py
from parrot.formdesigner import (
    FormSchema, FormSection, FormField, FieldType,
    FieldOption, FieldConstraints, DependencyRule, FieldCondition, ConditionOperator,
    FormRegistry, PostgresFormStorage, FormValidator, ValidationResult,
    HTML5Renderer, AdaptiveCardRenderer,
    setup_form_routes,
)
```

#### Key Attributes & Constants

- `PostgresFormStorage.CREATE_TABLE_SQL` — DDL for `form_schemas` table
  (`packages/parrot-formdesigner/src/parrot/formdesigner/services/storage.py:58`)
- `ConditionOperator.EQ` — maps from NetworkNinja `"EQUALS"` condition_logic
- `FieldType.TEXT` — safe fallback for unknown `data_type` values from `form_metadata`

#### NetworkNinja → parrot FieldType Mapping (verified from live DB, 2026-04-04)

Complete `data_type` values from `networkninja.form_metadata` and their `FieldType` mapping:

| NetworkNinja `data_type` | parrot `FieldType` | Notes |
|---|---|---|
| `FIELD_TEXT` | `FieldType.TEXT` | Single-line text |
| `FIELD_TEXTAREA` | `FieldType.TEXT_AREA` | Multi-line text |
| `FIELD_INTEGER` | `FieldType.INTEGER` | Integer number |
| `FIELD_FLOAT2` | `FieldType.NUMBER` | Decimal number (2 decimals) |
| `FIELD_MONEY` | `FieldType.NUMBER` | Currency — add `$` prefix in style |
| `FIELD_DATE` | `FieldType.DATE` | Date picker |
| `FIELD_TIME` | `FieldType.TIME` | Time picker |
| `FIELD_DATETIME` | `FieldType.DATETIME` | Date + time picker |
| `FIELD_DURATION` | `FieldType.TEXT` | No direct equivalent — render as text |
| `FIELD_PHONENUMBER` | `FieldType.PHONE` | Phone number |
| `FIELD_HYPERLINK` | `FieldType.URL` | URL input |
| `FIELD_SELECT` | `FieldType.SELECT` | Single-select dropdown; options from `form_metadata.options` |
| `FIELD_SELECT_RADIO` | `FieldType.SELECT` | Single-select rendered as radio buttons |
| `FIELD_MULTISELECT` | `FieldType.MULTI_SELECT` | Multi-select; options from `form_metadata.options` |
| `FIELD_YES_NO` | `FieldType.BOOLEAN` | Boolean toggle / yes-no |
| `FIELD_AGREEMENT_CHECKBOX` | `FieldType.BOOLEAN` | Checkbox agreement — set `required=True` |
| `FIELD_IMAGE_UPLOAD` | `FieldType.IMAGE` | Single image upload |
| `FIELD_IMAGE_UPLOAD_MULTIPLE` | `FieldType.IMAGE` | Multiple images — set `constraints.max_items` |
| `FIELD_SIGNATURE_CAPTURE` | `FieldType.FILE` | Signature as file/canvas |
| `FIELD_DISPLAY_TEXT` | `FieldType.HIDDEN` | Read-only display text; not submitted |
| `FIELD_DISPLAY_IMAGE` | `FieldType.HIDDEN` | Read-only image display; not submitted |
| `FIELD_SUBSECTION` | `FieldType.GROUP` | Visual grouping of child fields |
| `FIELD_TOTAL` | `FieldType.NUMBER` | Computed total — mark `read_only=True` |
| `FIELD_FORMULA` | `FieldType.NUMBER` | Computed formula — mark `read_only=True` |

#### Database Schema: networkninja (verified 2026-04-04)

```sql
-- networkninja.forms (source of form definitions)
-- question_blocks: JSONB storing a JSON *string* — must cast: question_blocks::text
formid          integer     PK
form_name       varchar(125)
client_id       integer
client_name     varchar(60)
orgid           integer     (default: hisense.get_organization())
active          boolean
question_blocks jsonb       -- scalar JSON string, parse with json.loads(row['question_blocks'])
last_modified_by varchar
inserted_at     timestamp

-- networkninja.form_metadata (field types and options)
column_id       integer     PK (with column_name)
column_name     varchar(20) -- maps to question_column_name in question_blocks
formid          integer
data_type       varchar(40) -- see FieldType mapping table above
description     text
options         jsonb       -- FieldOption[] for SELECT/MULTISELECT/RADIO fields
orgid           integer
client_id       integer

-- networkninja.form_responses (submission target)
form_id         integer     PK (with formid, column_name)
formid          integer
event_id        integer
column_name     varchar     -- question_column_name
data            varchar     -- submitted value
orgid           integer
client_id       integer
is_archived     boolean
is_deleted      boolean
```

#### Authentication: navigator_auth (verified 2026-04-04)

```python
# Package: navigator_auth (installed at .venv/lib/python3.11/site-packages/navigator_auth)
# Only public export:
from navigator_auth import AuthHandler  # registers auth backends at app startup

# Decorator for protecting individual handlers:
from navigator_auth.decorators import is_authenticated, allow_anonymous

@is_authenticated(content_type="application/json")
async def my_handler(request: web.Request) -> web.Response:
    # User is guaranteed authenticated at this point
    user = request.user           # AuthUser instance set by middleware
    # or via session:
    from navigator_session import get_session
    session = await get_session(request, new=False)
    user = session.decode("user")  # AuthUser

# AuthUser key attributes:
user.organizations          # list[Organization]
user.organizations[0].org_id   # int — tenant scope for form queries
user.username               # str
user.email                  # str

# @ModelView.service_auth is in navigator.views.model, NOT navigator_auth
# For plain aiohttp handlers (not ModelView), use @is_authenticated instead
```

**Auth strategy for `/api/v3/forms` routes:**
- All routes protected with `@is_authenticated`
- `orgid` extracted from `request.user.organizations[0].org_id`
- `client_id` extracted from session/user attributes as needed
- No separate `api_key` needed — session middleware (`navigator_client`) already runs globally

### Does NOT Exist (Anti-Hallucination)

- ~~`networkninja` schema in trocdataset SQL dumps~~ — schema exists in the live DB but was
  not included in the provided SQL dump files; all schema info is from live queries.
- ~~`networkninja.forms.question_blocks` as a JSONB object/array~~ — it is a scalar JSONB
  (JSON string); `jsonb_array_length()` and `jsonb_object_keys()` both fail on it.
- ~~`parrot.formdesigner.extractors.NetworkNinjaExtractor`~~ — does NOT exist yet; must be
  created as part of this feature.
- ~~`setup_form_routes()` as a class method~~ — it is a standalone function, not a class method.
- ~~`FormRegistry.persist()`~~ — method is `register(form, persist=True)`, not a separate
  `persist()` call.
- ~~`networkninja` schema in `packages/parrot-formdesigner/src/parrot/formdesigner/tools/database_form.py`~~
  — `DatabaseFormTool` references `networkninja.forms` but assumes `question_blocks` is a
  standard JSONB object; it will need adaptation for the scalar-string quirk.

---

## Parallelism Assessment

- **Internal parallelism**: The feature has 4 tasks that can be split by concern:
  1. `NetworkNinjaExtractor` class (pure parrot-side, no navigator-api dependency)
  2. `navigator.form_schemas` DDL migration + `PostgresFormStorage` wiring
  3. `setup_form_routes()` mount + app.py wiring
  4. `NinjaSubmissionHandler` for `networkninja.form_responses` writes
  Tasks 1 and 2 are independent and can run in separate worktrees. Tasks 3 and 4 depend
  on Task 1 being done.
- **Cross-feature independence**: No shared files with in-flight specs. `app.py` is
  touched but only to add a new `setup_form_routes()` call — low conflict risk.
- **Recommended isolation**: `per-spec` — tasks are sequential enough that a single
  worktree is cleaner. The extractor lives in `navigator-api/apps/forms/`; all tasks
  are in navigator-api.
- **Rationale**: The feature is small (4 focused tasks), the extractor is navigator-api
  specific (decided: lives in `apps/forms/`), and the wiring is minimal. Per-spec avoids
  unnecessary worktree ceremony for a PoC.

---

## Open Questions

- [x] ~~Does the `NetworkNinjaExtractor` live in `packages/parrot-formdesigner` or
  `navigator-api/apps/forms/`?~~ — **Resolved: lives in `navigator-api/apps/forms/`** (PoC scope)
- [x] ~~What is the full set of `data_type` values in `networkninja.form_metadata`?~~
  — **Resolved: 24 types confirmed** (see FieldType mapping table above)
- [x] ~~Should `navigator.form_schemas` live in the `navigator` schema or a new `formdesigner` schema?~~
  — **Resolved: `navigator` schema** (`navigator.form_schemas`)
- [x] ~~Cache invalidation strategy?~~
  — **Resolved: manual for PoC** — a `DELETE /api/v3/forms/{form_id}/cache` admin endpoint
  drops the entry from `navigator.form_schemas` and evicts from `FormRegistry` memory;
  next request re-extracts from `networkninja.forms`.
- [x] ~~Auth on the new routes?~~
  — **Resolved: use `@is_authenticated` decorator from `navigator_auth`** (see auth context below).
  `orgid` is extracted from `request.user.organizations[0].org_id` (AuthUser model).
  The existing `navigator_client` middleware already runs on all routes and sets `request[AUTH_SESSION_OBJECT]`.
