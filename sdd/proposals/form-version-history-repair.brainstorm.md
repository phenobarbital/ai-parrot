---
type: feature
base_branch: dev
---

# Brainstorm: Form Version History — repair the read path

**Date**: 2026-08-19
**Author**: Juan Ruffato (FieldSync)
**Status**: exploration
**Recommended Option**: Option C

---

## Problem Statement

`GET /api/v1/{tenant}/forms/{form_uid}/versions` (FEAT-300, TASK-007)
returns `{"versions": []}` for **every form that exists today**, in every
tenant. `POST /api/v1/{tenant}/forms/{form_uid}/publish` persists nothing.
Both have been dead since they were merged; no consumer noticed because
no UI had been built on top of them yet.

FieldSync is about to build that UI (form version history + diff between
versions, requested by the FieldSync product backlog). Before choosing
where to read the history from, we measured the parrot surface. It does
not work, and the reason is three independent defects stacked on the same
call path.

**Defect 1 — the service never receives a storage backend.**
`api/handlers.py:1810` constructs
`FormVersionService(self.registry)` with no `storage=` argument. With
`self._storage is None`, `FormVersionService._save_snapshot`
(`services/form_version.py:497`) writes the snapshot into an in-process
dict instead of Postgres, and `list_versions`
(`services/form_version.py:275`) never reaches storage at all. Every
published version is lost on process exit, and the history endpoint can
only ever report what the *current* process published.

**Defect 2 — the reconstruction filter rejects every real row.**
`_probe_storage_versions` (`services/form_version.py:316`) keeps a row
only when `snap.published_version == version`. Only `publish()` stamps
`published_version`; the form editor does not call `publish()` — it bumps
the version inline (`api/handlers.py:1282` and `:1358`, via
`api/_utils.py:61 _bump_version`) and calls `storage.save()`. Measured on
the FieldSync staging database, `published_version` is **NULL in all 105
rows** across `navigator.form_schemas` (34), `flexroc.form_schemas` (59)
and `epson.form_schemas` (12). The filter therefore discards 100% of
persisted versions.

**Defect 3 — history is reconstructed by probing.**
Even with defects 1 and 2 fixed, `_probe_storage_versions` enumerates the
history by issuing one `storage.load()` per candidate version, giving up
after two consecutive misses and capping at `_MAX_VERSION_PROBES = 200`
(`services/form_version.py:30`). A form with 15 versions costs ~16
sequential round-trips per request, and any two-version gap (a deleted
version) silently truncates the history from that point on.

**Why the test suite is green.** `test_list_versions_reconstructed_from_storage`
(`packages/parrot-formdesigner/tests/unit/test_feat300_review_fixes.py:179`)
creates its versions through `publish()` — the one code path that stamps
`published_version` — so the filter in defect 2 never fires there. The
tests exercise the service; nothing exercises the composition in
`_get_version_service()`.

### Reproduction

Measured against a scratch Postgres, using the real classes, with the
editor's write path (`_bump_version` + `storage.save`):

```
The editor saved: 1.0 1.1 1.2 1.3 1.4   (published_version NULL on all)

  today  FormVersionService(registry)                  -> []
  +R1    FormVersionService(registry, storage=st)      -> []
  +R1+R2+R3  one query, no published_version filter    -> ['1.0','1.1','1.2','1.3','1.4']
```

Restarting the process changes nothing: `FormRegistry.get()`
(`services/registry.py:895`) is read-through since 2026-08-13, so editing
and rendering a form survive a restart correctly. Only the version
history is affected.

## Constraints & Requirements

- The forms data model is unchanged: `<tenant>.form_schemas` already keys
  every version under `UNIQUE (form_uid, version)`. **No data migration
  should be required** to expose history that is already stored.
- Version ordering must never rely on the raw version string. `version`
  is `character varying(50)` holding `major.minor`; lexicographically
  `'1.9' > '1.14'`, and one FieldSync form already sits at `1.14`.
  Numeric coercion fails the same way (as a float, `1.9 > 1.14`). Only
  the `(major, minor)` int tuple orders correctly.
- Tenant resolution must stay in the URL (`/api/v1/{tenant}/...`,
  parrot FEAT-429 / fieldsync FEAT-494–495). Nothing here re-derives a
  tenant from session state.
- `PostgresFormStorage._resolve_schema` (`services/storage.py:135`)
  already maps a tenant slug onto its physical schema; every new query
  must go through `_qualified()` (`services/storage.py:147`) rather than
  interpolate a schema name.
- Backwards compatibility of the JSON response shape
  (`{"form_uid", "versions": [{version, published_at, published_by,
  is_current}]}`) — FieldSync will code against it.

---

## Options Explored

### Option A: Wire the storage backend only

Pass `storage=self.registry.storage` in `_get_version_service()`
(`api/handlers.py:1810`). `FormRegistry.storage` already exists as a
public property (`services/registry.py:1307`).

✅ **Pros:**
- One line. Fixes `POST /publish` losing data on restart.
- No semantic decision required.

❌ **Cons:**
- **Does not fix the endpoint** — measured, still `[]` (defect 2 stands).
- Leaves the probing cost and gap-fragility untouched.

📊 **Effort:** Low

🔗 **Existing Code to Reuse:**
- `services/registry.py:1307` — `FormRegistry.storage` property

---

### Option B: Option A + backfill `published_version`

Wire the storage, then run the existing
`scripts/backfill_published_versions.py` for every tenant so stored rows
gain a `published_version`, satisfying the filter in defect 2.

✅ **Pros:**
- Preserves the published/draft distinction the FEAT-300 design intended.
- Uses tooling that already exists.

❌ **Cons:**
- `FormVersionService.backfill_published` (`services/form_version.py:~400`)
  iterates *forms*, not versions: it stamps each form's **current**
  version only. A form with 15 stored versions would report a history of
  one entry. It does not solve the problem it appears to solve.
- Requires a write migration against every tenant schema in every
  environment, for data that is already correct.
- Leaves probing (defect 3) in place.

📊 **Effort:** Medium (plus an operational rollout per tenant)

---

### Option C: Storage-level version listing, and treat every stored row as a version

Three coordinated changes:

1. Wire the storage backend (Option A).
2. Add a first-class `list_versions()` to the `FormStorage` protocol and
   `PostgresFormStorage`: a single query per form,
   `WHERE form_uid = $1 ORDER BY split_part(version,'.',1)::int,
   split_part(version,'.',2)::int`, alongside the existing `_list_sql`
   (`services/storage.py:217`).
3. Retire the `published_version == version` filter. Every row in
   `<tenant>.form_schemas` **is** an immutable version — that is what the
   editor's save path produces and what `UNIQUE (form_uid, version)`
   enforces. `published_version` stays on the model and keeps feeding
   `is_current`, but stops acting as a visibility gate.

✅ **Pros:**
- Verified to return the true history for rows written by the real
  editor path, with **no data migration** (see Reproduction above).
- One query replaces ~16 round-trips; ordering is correct by
  construction, so the `1.10 < 1.9` trap cannot reach a consumer.
- A deleted version no longer truncates everything after it.
- `_probe_storage_versions` and `_MAX_VERSION_PROBES` disappear.

❌ **Cons:**
- Changes what "a version" means in the API: drafts and published
  snapshots become indistinguishable in the listing. If parrot wants that
  distinction it needs an explicit column/flag, not the absence of a
  field no writer sets.
- Touches assertions among the 40 `published_version` references in the
  parrot test suite.

📊 **Effort:** Medium

🔗 **Existing Code to Reuse:**
- `services/storage.py:217` — `_list_sql`, the shape to mirror
- `services/storage.py:135,147` — `_resolve_schema` / `_qualified`
- `services/form_version.py:69` — `_parse_major_minor`, the only correct
  ordering key in the codebase

---

## Recommendation

**Option C** is recommended.

Option A is necessary but provably insufficient — we ran it. Option B
buys the published/draft distinction at the price of a per-tenant write
migration that still yields a one-entry history, because the backfill
operates per form rather than per version.

Option C is the only one that makes the endpoint report what the database
already contains. The honest framing is that FEAT-300 designed a
publish-driven lifecycle, and the product then evolved a save-driven one:
every editor save already writes an immutable, uniquely-versioned row.
Option C aligns the read path with the write path that actually exists.

The trade-off is real and is Jesús's call: it gives up the ability to
distinguish a draft from a published snapshot *in the listing*. Our
position is that this distinction is not currently expressible in the
data (100% NULL across 105 rows), so nothing is lost today — but if the
lifecycle is meant to come back, it should return as an explicit column.

---

## Feature Description

### User-Facing Behavior

`GET /api/v1/{tenant}/forms/{form_uid}/versions` returns every stored
version of the form, oldest first, each with its publication timestamp,
with `is_current` marking the newest. `GET /api/v1/{tenant}/forms/{form_uid}/versions/{version}`
continues to return the frozen snapshot at that tag.

`POST /api/v1/{tenant}/forms/{form_uid}/publish` persists to Postgres and
survives a restart.

### Internal Behavior

`FormVersionService` gains a storage backend from the API layer.
`list_versions` asks storage for the version list in one query instead of
probing, and no longer filters rows by `published_version`. Ordering is
done in SQL on the parsed `(major, minor)` integers; the service keeps
`_parse_major_minor` as the single ordering rule for anything it merges
in memory.

### Edge Cases & Error Handling

- **Non-`major.minor` version strings.** `api/_utils.py:61 _bump_version`
  accepts and produces three-component versions (`1.2.3` → `1.2.4`),
  which `_SEMVER_RE` (`services/form_version.py:66`) does not match —
  `_parse_major_minor` then silently degrades that row to `(1, 0)` and
  misorders the whole history. No such row exists today (all 105 match
  `^\d+\.\d+$`), but the two bumpers must be unified so it stays that way.
- **Form with no stored versions**: empty list, 200 (not 404) — the form
  itself 404s earlier via `registry.get`.
- **Gaps in the chain** (a deleted version): listed as-is; no truncation.
- **Unknown tenant / schema absent**: surfaces as today, through
  `_qualified()` and asyncpg's `InvalidSchemaNameError`.

---

## Capabilities

### New Capabilities
- `form-version-history-repair`: the version-history read path returns
  the versions actually stored, in correct order, in one query.

### Modified Capabilities
- `form-builder-parity` (FEAT-300) — the publish/versions surface it
  introduced is repaired, and the meaning of a listed version is widened.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `api/handlers.py` `_get_version_service` (`:1802`) | modifies | pass `storage=` |
| `services/form_version.py` `list_versions` (`:275`) | modifies | delegate to storage; drop filter |
| `services/form_version.py` `_probe_storage_versions` (`:316`) | removes | replaced by one query |
| `services/storage.py` `PostgresFormStorage` | extends | new `list_versions()` + SQL |
| `api/_utils.py` `_bump_version` (`:61`) | modifies | unify with `_bump` |
| `POST /forms/{uid}/publish` (`api/routes.py:411`) | fixes | persisted for the first time |
| FieldSync `navigator-svelte` | depends on | consumer of the repaired endpoint |
| parrot test suite | modifies | 40 `published_version` references |

No database migration. No change to `<tenant>.form_schemas`.

---

## Code Context

### Verified Codebase References

#### Classes & Signatures
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/services/form_version.py
_MAX_VERSION_PROBES = 200                                        # line 30
_SEMVER_RE = re.compile(r"^(\d+)\.(\d+)$")                       # line 66
def _parse_major_minor(version: str) -> tuple[int, int]: ...     # line 69
def _bump(current: str, bump: str = "minor") -> str: ...         # line 85

class FormVersionService:
    async def publish(self, form_uid, *, tenant, bump="minor") -> str: ...      # line 158
    async def list_versions(self, form_uid, *, tenant) -> list[VersionMeta]: ...# line 275
    async def _probe_storage_versions(self, form_uid, *, tenant) -> list[str]: ...# line 316
    async def _save_snapshot(self, snapshot, *, tenant) -> None: ...            # line 497

# packages/parrot-formdesigner/src/parrot_formdesigner/services/storage.py
class PostgresFormStorage:
    def _resolve_schema(self, tenant: str | None) -> str: ...     # line 135
    def _qualified(self, tenant: str | None) -> str: ...          # line 147
    def _list_sql(self, tenant: str | None) -> str: ...           # line 217

# packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py
class FormRegistry:
    async def get(self, form_uid, *, tenant=None) -> FormSchema | None: ...  # line 895 (read-through)
    @property
    def storage(self) -> "FormStorage | None": ...                # line 1307

# packages/parrot-formdesigner/src/parrot_formdesigner/api/_utils.py
def _bump_version(version: str) -> str: ...                       # line 61

# packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py
    def _get_version_service(self) -> "FormVersionService": ...   # line 1802
        self._version_service = FormVersionService(self.registry) # line 1810  <-- defect 1
    body["version"] = _bump_version(existing.version)             # line 1282  <-- editor write path
    merged["version"] = _bump_version(existing.version)           # line 1358  <-- editor write path
    version = await svc.publish(form_uid, tenant=tenant)          # line 1857
```

#### Route grammar (tenant-in-URL, already compliant)
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py
tp = f"{bp}/{{tenant}}"                                           # line 281 (bp = "/api/v1")
app.router.add_get(f"{tp}/forms/{{form_uid}}/versions", ...)      # line 420
app.router.add_get(f"{tp}/forms/{{form_uid}}/versions/{{version}}", ...)  # line 423
```

#### Measured facts (FieldSync staging, 2026-08-19)
- `navigator.form_schemas.version` → `character varying(50)`, default `'1.0'`
- `UNIQUE (form_uid, version)` and `UNIQUE (tenant, form_id, version)` present
- `published_version` (inside `schema_json`) is **NULL in 105/105 rows**
  across `navigator` (34), `flexroc` (59), `epson` (12)
- All 105 version strings match `^\d+\.\d+$`
- One form reaches `1.14`; ordering it by the raw string yields `1.9`

### Does NOT Exist (Anti-Hallucination)
- ~~`FormStorage.list_versions()`~~ — no version-listing API exists; that
  is precisely why `_probe_storage_versions` was written
- ~~a `published_version` **column**~~ — it lives inside `schema_json`,
  not as a table column
- ~~`form_schemas.is_published` / `is_draft`~~ — no such column
- ~~`FormRegistry.list_versions()`~~ — not a registry responsibility

---

## Parallelism Assessment

- **Internal parallelism**: low — three changes on one call path; a
  single worktree is correct.
- **Cross-feature independence**: touches `services/form_version.py`,
  `services/storage.py`, `api/handlers.py`. Check against any in-flight
  formdesigner branch before starting (`feat/formdesigner-tenant-context`,
  `feat-429-fieldsync-tenant-url`).
- **Recommended isolation**: per-spec
- **Rationale**: small, coherent, one reviewer.

---

## Open Questions

- [ ] Should a listed version distinguish *published* from *saved*? Option C
      says every stored row is a version; if the FEAT-300 publish lifecycle
      is meant to return, it needs an explicit column rather than the
      absence of `published_version` — *Owner: Jesús*
- [ ] `POST /publish` currently persists nothing. Once wired, it starts
      writing rows. Is publish still a wanted operation given the editor
      already versions on save, or should it be retired? — *Owner: Jesús*
- [ ] Which of the 40 `published_version` test references encode a real
      requirement vs. the current behavior? — *Owner: Jesús*
- [ ] Do we unify the two bumpers (`_bump_version` vs `_bump`) in this
      feature or split it out? — *Owner: Jesús*
