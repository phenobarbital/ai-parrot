---
type: feature
base_branch: dev
---

# Feature Specification: Form Version History — repair the read path

**Feature ID**: FEAT-433
**Date**: 2026-08-19
**Author**: Juan Ruffato (FieldSync)
**Status**: draft
**Target version**: parrot-formdesigner 0.9.2

> Source brainstorm: `sdd/proposals/form-version-history-repair.brainstorm.md`
> Submitted by the FieldSync team for review. Section 8 carries four
> decisions that belong to the parrot maintainer; Module 3 is gated on the
> first of them.

---

## 1. Motivation & Business Requirements

### Problem Statement

`GET /api/v1/{tenant}/forms/{form_uid}/versions` returns
`{"versions": []}` for every form that exists today, and
`POST /api/v1/{tenant}/forms/{form_uid}/publish` persists nothing. Three
independent defects stack on the same call path:

1. **No storage backend.** `api/handlers.py:1810` builds
   `FormVersionService(self.registry)` without `storage=`. With
   `_storage is None`, `_save_snapshot` (`services/form_version.py:497`)
   writes to an in-process dict and `list_versions`
   (`services/form_version.py:275`) never reaches Postgres.
2. **The reconstruction filter rejects every real row.**
   `_probe_storage_versions` (`services/form_version.py:316`) keeps a row
   only when `snap.published_version == version`. Only `publish()` stamps
   that field; the editor bumps inline (`api/handlers.py:1282`, `:1358`)
   and calls `storage.save()`. Measured on FieldSync staging,
   `published_version` is NULL in **105 of 105 rows** across
   `navigator` (34), `flexroc` (59) and `epson` (12).
3. **History is reconstructed by probing.** One `storage.load()` per
   candidate version, giving up after two consecutive misses, capped at
   `_MAX_VERSION_PROBES = 200` (`services/form_version.py:30`). ~16
   sequential round-trips for a 15-version form; a two-version gap
   truncates the history silently.

The suite is green because `test_feat300_review_fixes.py:179` creates its
versions through `publish()` — the only path that stamps
`published_version` — so defect 2 never fires in tests. Nothing exercises
the composition in `_get_version_service()`.

### Goals

- `GET .../versions` returns every stored version of a form, correctly
  ordered, in a single query.
- `POST .../publish` persists.
- Version ordering never depends on the raw version string or on a
  numeric coercion of it.
- No database migration and no change to `<tenant>.form_schemas`.

### Non-Goals (explicitly out of scope)

- Changing the `version` column type or format. It stays
  `character varying(50)` holding `major.minor`. (FieldSync raised this;
  the format is parrot's call and we are not proposing to change it.)
- Building any UI. The consumer lives in `navigator-svelte`.
- Reintroducing a draft/published lifecycle as a data model change —
  see §8 Q1.
- Backfilling `published_version` (Option B in the brainstorm: rejected,
  it stamps one version per *form*, not per version).

---

## 2. Architectural Design

### Overview

Give `FormVersionService` the storage backend the API layer already
holds, move version enumeration from probing into a first-class
`FormStorage.list_versions()` implemented as one ordered SQL query, and
stop using `published_version` as a visibility gate. `published_version`
remains on the model and keeps driving `is_current`.

### Component Diagram

```
GET /api/v1/{tenant}/forms/{uid}/versions
        │
        ▼
FormDesignerHandler.list_versions            api/handlers.py:1910
        │  _get_version_service()            api/handlers.py:1802   ← Module 1
        ▼
FormVersionService.list_versions             services/form_version.py:275  ← Module 2
        │  (was: _probe_storage_versions, N round-trips)
        ▼
PostgresFormStorage.list_versions            services/storage.py (new)     ← Module 2
        │  ORDER BY (major, minor)::int
        ▼
   <tenant>.form_schemas
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `FormRegistry.storage` (`services/registry.py:1307`) | uses | public property, already returns `FormStorage \| None` |
| `PostgresFormStorage._qualified` (`services/storage.py:147`) | uses | schema resolution; never interpolate a schema name |
| `_parse_major_minor` (`services/form_version.py:69`) | uses | the one correct ordering rule in the codebase |
| `FormRegistry.get` (`services/registry.py:895`) | unchanged | read-through; already restart-safe |
| routes `api/routes.py:420,423` | unchanged | already tenant-in-URL (`tp = f"{bp}/{{tenant}}"`, `:281`) |

### Data Models

Unchanged. `VersionMeta` (`services/form_version.py`) keeps its shape:

```python
class VersionMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")
    form_id: str
    version: str
    published_at: datetime
    tenant: str
    is_frozen: bool = True
```

### New Public Interfaces

```python
# services/storage.py — added to the FormStorage protocol and to
# PostgresFormStorage.
async def list_versions(
    self, form_uid: uuid.UUID, *, tenant: str | None = None
) -> list[dict[str, Any]]:
    """Every stored version of one form, oldest first.

    Ordered by the parsed (major, minor) integers, never by the raw
    string: lexicographically '1.9' > '1.14', and float coercion fails
    the same way.

    Returns:
        Rows of ``{"version", "created_at", "updated_at", "schema_json"}``.
    """
```

Backing SQL, mirroring `_list_sql` (`services/storage.py:217`):

```sql
SELECT version, created_at, updated_at, schema_json
FROM <qualified>
WHERE form_uid = $1
ORDER BY split_part(version, '.', 1)::int,
         split_part(version, '.', 2)::int
```

---

## 3. Module Breakdown

### Module 1: Wire the storage backend
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py`
- **Responsibility**: `_get_version_service()` (`:1802`) passes
  `storage=self.registry.storage`. Fixes `POST /publish` losing every
  snapshot on process exit.
- **Depends on**: nothing.
- **Note**: necessary but not sufficient — verified to still return `[]`
  on its own (brainstorm, Reproduction).

### Module 2: `FormStorage.list_versions()` and its use
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/services/storage.py`,
  `.../services/form_version.py`
- **Responsibility**: add the protocol method, the `PostgresFormStorage`
  implementation and the SQL above; rewrite
  `FormVersionService.list_versions` (`:275`) to call it; delete
  `_probe_storage_versions` (`:316`) and `_MAX_VERSION_PROBES` (`:30`).
  In-memory `_meta` entries are still merged, keyed by version, and the
  merged result is sorted with `_parse_major_minor`.
- **Depends on**: Module 1.

### Module 3: Retire the `published_version` visibility filter
- **Path**: `.../services/form_version.py`
- **Responsibility**: stop dropping rows whose `published_version` does
  not equal their `version`. Every row in `<tenant>.form_schemas` is an
  immutable version — that is what the editor's save path produces and
  what `UNIQUE (form_uid, version)` enforces. `published_version` keeps
  driving `is_current` in the handler's response.
- **Depends on**: Module 2.
- **GATED on §8 Q1.** This is the one semantic change in the feature. If
  the maintainer wants the draft/published distinction preserved, this
  module is replaced by an explicit column and the feature grows a
  migration.

### Module 4: Unify the two version bumpers
- **Path**: `.../api/_utils.py`, `.../services/form_version.py`
- **Responsibility**: `_bump_version` (`api/_utils.py:61`) increments the
  last component and accepts three-part versions (`1.2.3` → `1.2.4`);
  `_SEMVER_RE` (`services/form_version.py:66`) matches only `^(\d+)\.(\d+)$`
  and `_parse_major_minor` silently degrades anything else to `(1, 0)`,
  misordering an entire history. Collapse to one implementation with one
  documented grammar.
- **Depends on**: nothing (independently mergeable).
- **Note**: no such row exists today — all 105 measured versions match
  `^\d+\.\d+$`. This closes the door before it opens.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_version_service_receives_storage` | 1 | `_get_version_service()` returns a service whose `_storage` is the registry's backend |
| `test_publish_persists_across_service_instances` | 1 | publish, discard the service, rebuild it, snapshot still loadable from storage |
| `test_list_versions_single_query` | 2 | listing a 15-version form issues exactly one storage call (spy/counter) |
| `test_list_versions_orders_past_ten` | 2 | `1.0…1.14` returns in that order, i.e. `1.14` last and `1.9` before `1.10` |
| `test_list_versions_survives_gaps` | 2 | deleting `1.2` and `1.3` still lists `1.4`+ (the old probe stopped there) |
| `test_list_versions_includes_editor_saved_rows` | 3 | rows written via `_bump_version` + `storage.save` (no `published_version`) appear |
| `test_is_current_marks_highest_version` | 3 | `is_current` true for the highest `(major, minor)`, false elsewhere |
| `test_bump_grammar_is_single` | 4 | both call sites produce identical output for `1.0`, `1.9`, `1.14`; three-part input handled by one documented rule |

### Integration Tests

| Test | Description |
|---|---|
| `test_versions_endpoint_returns_editor_history` | Save a form 5× through the PATCH/PUT handlers, then `GET /api/v1/{tenant}/forms/{uid}/versions` returns all 5 in order |
| `test_versions_endpoint_after_restart` | Same, with the handler and registry rebuilt between write and read |
| `test_versions_endpoint_tenant_isolation` | A form under `epson` is invisible to `GET /api/v1/pokemon/forms/{uid}/versions` |

### Test Data / Fixtures

```python
@pytest.fixture
async def form_with_history(pg_storage):
    """A form saved the way the editor saves it: no published_version."""
    form = FormSchema(form_id="hist", title="Hist", tenant="t1", sections=[])
    await pg_storage.save(form, tenant="t1")
    cur = form
    for _ in range(14):                       # reaches 1.14 — past the '1.9' trap
        cur = cur.model_copy(deep=True,
                             update={"version": _bump_version(cur.version)})
        await pg_storage.save(cur, tenant="t1")
    return form
```

---

## 5. Acceptance Criteria

- [ ] `GET /api/v1/{tenant}/forms/{uid}/versions` returns every stored
      version for a form written exclusively through the editor path
      (no `publish()` call anywhere in the fixture)
- [ ] The response is ordered so that `1.14` follows `1.10` follows `1.9`
- [ ] Listing a form's versions issues exactly one storage query
- [ ] `_probe_storage_versions` and `_MAX_VERSION_PROBES` no longer exist
- [ ] A published snapshot survives rebuilding the service (Module 1)
- [ ] All unit tests pass (`pytest packages/parrot-formdesigner/tests/unit/ -v`)
- [ ] All integration tests pass (`pytest packages/parrot-formdesigner/tests/integration/ -v`)
- [ ] No database migration is introduced
- [ ] Response envelope unchanged: `{"form_uid", "versions":[{version,
      published_at, published_by, is_current}]}`
- [ ] Tenant resolution stays in the URL; no session-derived tenancy

---

## 6. Codebase Contract

### Verified Imports
```python
from parrot_formdesigner.services.form_version import FormVersionService, VersionMeta
from parrot_formdesigner.services.registry import FormRegistry
from parrot_formdesigner.services.storage import PostgresFormStorage
from parrot_formdesigner.api._utils import _bump_version
from parrot_formdesigner.core.schema import FormSchema
```

### Existing Class Signatures
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/services/form_version.py
_MAX_VERSION_PROBES = 200                                          # line 30
_SEMVER_RE = re.compile(r"^(\d+)\.(\d+)$")                         # line 66
def _parse_major_minor(version: str) -> tuple[int, int]: ...       # line 69
def _bump(current: str, bump: str = "minor") -> str: ...           # line 85

class FormVersionService:
    def __init__(self, registry, storage=None, *, has_responses=None) -> None: ...
    async def publish(self, form_uid, *, tenant, bump="minor") -> str: ...        # line 158
    async def list_versions(self, form_uid, *, tenant) -> list[VersionMeta]: ...  # line 275
    async def _probe_storage_versions(self, form_uid, *, tenant) -> list[str]: ...# line 316
    async def _save_snapshot(self, snapshot, *, tenant) -> None: ...              # line 497

# packages/parrot-formdesigner/src/parrot_formdesigner/services/storage.py
class PostgresFormStorage:
    def _resolve_schema(self, tenant: str | None) -> str: ...        # line 135
    def _qualified(self, tenant: str | None) -> str: ...             # line 147
    def _list_sql(self, tenant: str | None) -> str: ...              # line 217
    async def initialize(self, *, tenant=None) -> None: ...          # line 270
    async def save(self, ...) -> None: ...                           # line 316
    async def load(self, ...) -> FormSchema | None: ...              # line 368

# packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py
class FormRegistry:
    async def get(self, form_uid, *, tenant=None) -> FormSchema | None: ...  # line 895
    @property
    def storage(self) -> "FormStorage | None": ...                   # line 1307
    def set_storage(self, storage: FormStorage) -> None: ...         # line 604

# packages/parrot-formdesigner/src/parrot_formdesigner/api/_utils.py
def _bump_version(version: str) -> str: ...                          # line 61
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| Module 1 | `FormRegistry.storage` | property read | `services/registry.py:1307` |
| Module 2 | `PostgresFormStorage._qualified()` | SQL builder | `services/storage.py:147` |
| Module 2 | `_parse_major_minor` | in-memory sort key | `services/form_version.py:69` |
| Module 3 | handler `is_current` computation | `form.published_version or form.version` | `api/handlers.py:1932` |

### Does NOT Exist (Anti-Hallucination)
- ~~`FormStorage.list_versions()`~~ — this spec introduces it; the absence
  is why `_probe_storage_versions` was written
- ~~`form_schemas.published_version`~~ — not a column; it lives inside
  `schema_json`
- ~~`form_schemas.is_published` / `is_draft`~~ — no such columns
- ~~`FormRegistry.list_versions()`~~ — not a registry responsibility
- ~~a version-history UI in parrot~~ — the consumer is `navigator-svelte`

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Async-first; asyncpg through the existing pool, never a new connection
- All SQL through `_qualified()` — never interpolate a schema or table name
- Pydantic models for structured returns; `VersionMeta` stays `extra="forbid"`
- Google-style docstrings and strict type hints, per the repo standard

### Known Risks / Gotchas
- **Ordering is the whole point.** `version` is a string holding
  `major.minor`. Lexicographically `'1.9' > '1.14'`; as a float,
  `1.9 > 1.14`. Only the `(major, minor)` int tuple orders correctly.
  A FieldSync form already sits at `1.14`, and an `epson` form is at
  `1.8` — two saves from the same trap.
- **Two writers.** `publish()` and the editor's `_bump_version` +
  `storage.save()` both create versions. Any change to one must be read
  against the other.
- **`schema_json` double encoding.** Historically some rows were written
  double-encoded. Measured 2026-08-19: 0 of 105 rows affected — all
  `jsonb_typeof = 'object'`. Do not add a decoding shim on the strength
  of the folklore; do not assume it can never come back either.
- **Snapshots are documented as immutable but are not.** 4 of 34 rows in
  `navigator.form_schemas` have `updated_at > created_at`. Ordering by
  `updated_at` would therefore reorder history when an old row is
  touched; ordering by `(major, minor)` is immune. Worth surfacing
  `updated_at` in the payload so rewrites are visible.
- **Test blast radius**: 40 `published_version` references in the parrot
  test suite; Module 3 touches the subset asserting invisibility of
  unpublished forms.

### External Dependencies

None. No new packages, no migration.

---

## 8. Open Questions

> These four are the reason this spec is submitted as `draft`. Q1 gates
> Module 3.

- [ ] **Q1 — Should a listed version distinguish *published* from *saved*?**
      Module 3 says every stored row is a version, because that is what
      the data is (105/105 rows have no `published_version`). If the
      FEAT-300 lifecycle is meant to return, it needs an explicit column
      and this feature grows a migration — *Owner: Jesús*
- [ ] **Q2 — Is `POST /publish` still wanted?** Once Module 1 lands it
      starts persisting for the first time. Given the editor already
      versions on every save, publish may be redundant rather than
      broken — *Owner: Jesús*
- [ ] **Q3 — Which `published_version` test assertions encode a real
      requirement** versus the current behavior? — *Owner: Jesús*
- [ ] **Q4 — Module 4 in or out?** Unifying the two bumpers is
      independently mergeable and could ship separately — *Owner: Jesús*

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-19 | Juan Ruffato (FieldSync) | Initial draft from `form-version-history-repair.brainstorm.md`; submitted for parrot maintainer review |
