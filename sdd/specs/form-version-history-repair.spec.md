---
type: feature
base_branch: dev
---

# Feature Specification: Form Version History — repair the read path

**Feature ID**: FEAT-433
**Date**: 2026-08-19
**Author**: Juan Ruffato (FieldSync)
**Status**: approved — decomposed into TASK-2264…TASK-2269
**Target version**: parrot-formdesigner 0.9.2

> Source brainstorm: `sdd/proposals/form-version-history-repair.brainstorm.md`
> Submitted by the FieldSync team for review.
> **Reviewed by the parrot maintainer on 2026-08-19** — §0 records the
> decisions, §1.1 the resulting front-end contract, and Modules 5–6 two
> defects the submission did not cover. Q1 and Q2 are closed; Module 3 is
> no longer gated.
> **Accepted by the submitter on 2026-08-19** (§0.1). Every maintainer
> decision is adopted without objection; the two threads FieldSync had
> open are closed there. Decomposed into TASK-2264…TASK-2269.

---

## 0. Maintainer Decisions (2026-08-19, binding)

These close §8 Q1 and Q2. They change Module 3 and add Modules 5 and 6.

**D1 — The draft/published distinction MUST be preserved.** It is wanted,
it is not going away, and it is not deferred. The brainstorm's inference
("`published_version` is NULL in 105/105 rows, therefore nothing is
lost") reads the causality backwards: the field is NULL because *no
writer ever sets it* — the editor deliberately carries the previous value
forward (`api/handlers.py:1284-1285`, `:1361-1363`, comment: *"published_version
is immutable from the API surface — only FormVersionService.publish() may
set it"*). An unexercised lifecycle is not a rejected one.

**D2 — Preserving it requires no migration and no new column.** The
distinction is already fully expressible in the stored data:

```
is_published(row)  ==  (row.schema_json ->> 'published_version') = row.version
```

A row written by `publish()` carries its own tag in `published_version`; a
row written by an editor save carries the *previous* published tag (or
NULL). That is a complete, per-row, two-state label sitting in the table
right now. §6's "no `is_published` column" note therefore stands — the
label is **derived**, never stored.

**D3 — The filter is demoted, not retired.** `published_version ==
version` stops deciding *whether a row is visible* and starts deciding
*how a row is labelled*. Every stored row is listed; each carries
`is_published`. This is what makes D1 and the FieldSync history UI
compatible: the UI gets the whole chain **and** can render "draft" vs
"published" without a second call.

**D4 — `POST /publish` stays (closes Q2).** It is the only writer of the
published state, so retiring it would retire D1. It is currently
unreachable-by-default (no storage wired) and its immutability guard does
not actually hold on Postgres — see Module 6.

**D5 — The front editor MUST comply.** See §1.1. The distinction is only
meaningful if the client that owns the "Publish" affordance actually calls
the publish endpoint. A parrot-side fix cannot manufacture publish events
that the editor never sends.

### 0.1 Submitter acceptance (FieldSync, 2026-08-19)

D1–D5 are adopted in full. Modules 5 and 6 are accepted as correct and in
scope: the `get_published()` filter would have shipped a history list whose
every entry 404s, and Module 1 does make the `ON CONFLICT DO UPDATE` hole
reachable, so repairing it inside this feature is the right call rather
than a follow-up.

Two threads FieldSync had open are closed here, so they are not reopened
during implementation:

**S1 — The version format is parrot's, and stays as it is.** FieldSync
raised that `version` is a `VARCHAR` holding `major.minor`, which sorts
wrongly as a string (`'1.9' > '1.14'`) and as a float (`1.9 > 1.14`). The
maintainer's design keeps the format and handles ordering by parsing to
`(major, minor)` — in SQL for the listing (§2, guarded `CASE`) and via
`_parse_major_minor` in Python. FieldSync accepts this: the format is
parrot's domain, the ordering rule is correct, and the §1 non-goal stands.
No format change is requested now or later as part of this feature.

**S2 — Existing development data stays; test histories are a FieldSync
concern.** A parallel thread proposed deleting the current rows on the
grounds that they are development data. Measured 2026-08-19, what hangs
off those `form_uid`s is 9 `actions` rows, 4 `fs_form_data` rows and 3
`form_activity_types` tags — disposable. It is nonetheless **out of scope
here**: this feature repairs a read path and needs no data change to do
it, and the rows are well-formed (all 105 versions match `^\d+\.\d+$` —
what they lack is `published_version`, not a version). Fabricating a
mixed draft/published history to exercise the FieldSync UI is a FieldSync
task, solved on our side, and MUST NOT become a prerequisite of this spec.

---

## 1. Motivation & Business Requirements

### Problem Statement

`GET /api/v1/{tenant}/forms/{form_uid}/versions` returns
`{"versions": []}` for every form that exists today, and
`POST /api/v1/{tenant}/forms/{form_uid}/publish` persists nothing. Three
independent defects stack on the same call path:

1. **No storage backend.** `api/handlers.py:1809` builds
   `FormVersionService(self.registry)` without `storage=`. With
   `_storage is None`, `_save_snapshot` (`services/form_version.py:497`)
   writes to an in-process dict and `list_versions`
   (`services/form_version.py:275`) never reaches Postgres.
2. **The reconstruction filter rejects every real row.**
   `_probe_storage_versions` (`services/form_version.py:316`) keeps a row
   only when `snap.published_version == version`. Only `publish()` stamps
   that field; the editor bumps inline (`api/handlers.py:1281`, `:1357`)
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

### 1.1 Front-end contract (normative, follows from D1/D5)

The repaired endpoint is only half of the lifecycle. The editor —
`navigator-svelte` today, any future client tomorrow — **MUST** honour the
following. These are requirements on the consumer, not suggestions; a
client that ignores them produces a history in which every entry is a
draft, which is exactly the state this spec is repairing.

1. **A save is a draft.** `PUT`/`PATCH /api/v1/{tenant}/forms/{uid}` bump
   the version and write a *draft* row. The editor MUST NOT present a save
   as a publish, and MUST NOT attempt to set `published_version` in the
   body — the handler strips it (`api/handlers.py:1284`).
2. **A publish is an explicit call.** Marking a version as published is
   done **only** through `POST /api/v1/{tenant}/forms/{uid}/publish`. The
   editor MUST expose a "Publish" action distinct from "Save", and MUST
   call this endpoint when it is used.
3. **The UI MUST render the two states differently.** Each entry of
   `GET .../versions` carries `is_published`. A version-history view that
   ignores it is non-compliant: it would show 105 identical-looking
   entries where none are published.
4. **`is_current` and `is_published` are independent.** `is_current`
   marks the version the live form sits at; `is_published` marks whether
   that version was ever published. The newest version is normally a
   *current draft*, and the newest published version is normally an
   *older* entry. The UI MUST NOT collapse the two flags.
5. **Publish-before-release.** Whatever consumes forms in production
   (rendering, dispatch to field devices) SHOULD pin a published version
   rather than "latest", otherwise the distinction buys nothing
   operationally. Out of scope for this feature; recorded so it is not
   lost.

> **Note for the FieldSync team**: this is a deliberate answer to §8 Q1,
> not a default. The lifecycle FEAT-300 designed is the one parrot wants.
> The gap is that the editor evolved a save-driven flow and never adopted
> the publish call — the fix is on both sides, and the parrot side alone
> cannot close it.

### Goals

- `GET .../versions` returns every stored version of a form, correctly
  ordered, in a single query.
- Every listed version is labelled `is_published` (D1/D3), derived from
  the data already stored — no migration.
- `GET .../versions/{version}` returns the snapshot for **any** listed
  version, draft or published (Module 5).
- `POST .../publish` persists, and a published snapshot can no longer be
  silently overwritten (Module 6).
- Version ordering never depends on the raw version string or on a
  numeric coercion of it.
- No database migration and no change to `<tenant>.form_schemas`.

### Non-Goals (explicitly out of scope)

- Changing the `version` column type or format. It stays
  `character varying(50)` holding `major.minor`. (FieldSync raised this;
  the format is parrot's call and we are not proposing to change it.)
- Building any UI. The consumer lives in `navigator-svelte`.
- Adding an `is_published` / `is_draft` **column**. The distinction is
  preserved (D1) but derived (D2); the table is untouched.
- Changing what `publish()` versions — whether publish should promote the
  current version in place instead of bumping to a new tag is a real
  question, raised as §8 Q5, and deliberately out of this feature.
- Building any UI. §1.1 states the contract the UI must meet; the UI
  itself lives in `navigator-svelte`.
- Backfilling `published_version` (Option B in the brainstorm: rejected,
  it stamps one version per *form*, not per version).

---

## 2. Architectural Design

### Overview

Give `FormVersionService` the storage backend the API layer already
holds, move version enumeration from probing into a first-class
`FormStorage.list_versions()` implemented as one ordered SQL query, and
**demote** `published_version` from a visibility gate to a per-row label
(D3). Every stored row is listed; each is tagged `is_published`.
`published_version` keeps driving `is_current` on the live form.

Two further sites are in scope, both missed by the original submission:
`get_published()` carries the *same* filter and currently 404s every
draft version (Module 5), and `publish()`'s documented immutability
guard does not hold against the real Postgres UPSERT (Module 6). Module 6
matters precisely *because* Module 1 wires the backend: the hole is
unreachable today and becomes reachable the moment the storage is
connected.

### Component Diagram

```
GET /api/v1/{tenant}/forms/{uid}/versions
        │
        ▼
FormDesignerHandler.list_versions            api/handlers.py:1910
        │  _get_version_service()            api/handlers.py:1801   ← Module 1
        ▼
FormVersionService.list_versions             services/form_version.py:275  ← Modules 2+3
        │  (was: _probe_storage_versions, N round-trips)
        ▼
PostgresFormStorage.list_versions            services/storage.py (new)     ← Module 2
        │  ORDER BY (major, minor)::int, guarded cast
        ▼
   <tenant>.form_schemas
───────────────────────────────────────────────────────────────────────

GET /api/v1/{tenant}/forms/{uid}/versions/{version}
        │
        ▼
FormDesignerHandler.get_version               api/handlers.py:1946
        ▼
FormVersionService.get_published              services/form_version.py:243  ← Module 5
        │  same published_version filter → 404s every draft row today
        ▼
PostgresFormStorage.load(version=...)         services/storage.py:368

───────────────────────────────────────────────────────────────────────

POST /api/v1/{tenant}/forms/{uid}/publish
        ▼
FormVersionService.publish                    services/form_version.py:158  ← Module 6
        │  _save_snapshot → storage.save() → _upsert_sql
        ▼
ON CONFLICT (form_uid, version) DO UPDATE     services/storage.py:187
        │  overwrites the frozen snapshot; never raises a unique violation
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `FormRegistry.storage` (`services/registry.py:1307`) | uses | public property, already returns `FormStorage \| None` |
| `PostgresFormStorage._qualified` (`services/storage.py:147`) | uses | schema resolution; never interpolate a schema name |
| `_parse_major_minor` (`services/form_version.py:69`) | uses | the one correct ordering rule in the codebase |
| `FormRegistry.get` (`services/registry.py:895`) | unchanged | read-through; already restart-safe |
| `FormVersionService.get_published` (`services/form_version.py:243`) | modifies | second filter site (Module 5) |
| `PostgresFormStorage._upsert_sql` (`services/storage.py:173`) | reads | `ON CONFLICT (form_uid, version) DO UPDATE` (`:187`) — the reason Module 6 exists |
| routes `api/routes.py:420,423` | unchanged | already tenant-in-URL (`tp = f"{bp}/{{tenant}}"`, `:281`) |

### Data Models

No database change (D2). `VersionMeta` (`services/form_version.py`) gains
one derived field and one corrected one:

```python
class VersionMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")
    form_id: str
    version: str
    published_at: datetime
    tenant: str
    is_published: bool = False   # NEW (D1/D3) — derived, never stored:
                                 #   schema_json->>'published_version' == version
    is_frozen: bool = False      # CHANGED — was `True` unconditionally.
                                 #   Only a published snapshot is frozen; a
                                 #   draft row is rewritable in place (4/34
                                 #   navigator rows already have
                                 #   updated_at > created_at). Set it equal
                                 #   to is_published rather than hardcoding.
```

`extra="forbid"` is retained, so every construction site must pass the new
field.

Response envelope — **additive only**, so FieldSync's existing coding
against it keeps working:

```jsonc
{
  "form_uid": "…",
  "versions": [
    {
      "version": "1.4",
      "published_at": "…",
      "published_by": null,
      "is_current": false,
      "is_published": true     // NEW
    }
  ]
}
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
        Rows of ``{"version", "created_at", "updated_at", "form_id",
        "published_version", "published_at"}`` — the projected fields,
        NOT the whole ``schema_json``.
    """
```

Backing SQL, mirroring `_list_sql` (`services/storage.py:217`):

```sql
SELECT version,
       created_at,
       updated_at,
       schema_json ->> 'form_id'                AS form_id,
       schema_json ->> 'published_version'      AS published_version,
       schema_json -> 'meta' ->> 'published_at' AS published_at
FROM <qualified>
WHERE form_uid = $1
ORDER BY CASE WHEN version ~ '^[0-9]+\.[0-9]+$'
              THEN split_part(version, '.', 1)::int END NULLS LAST,
         CASE WHEN version ~ '^[0-9]+\.[0-9]+$'
              THEN split_part(version, '.', 2)::int END NULLS LAST,
         version
```

Two deliberate departures from the submitted SQL:

- **Project, do not haul.** The original selected `schema_json` whole. A
  15-version form would then transfer 15 complete form schemas to compute
  six scalars. `published_version` and the `meta.published_at` stamp are
  the only two things the service reads out of the payload — extract them
  server-side. `is_published` is then computed in Python
  (`published_version == version`) rather than in SQL, so the rule lives in
  one place, next to `_parse_major_minor`.
- **Guard the cast.** A bare `split_part(version,'.',2)::int` raises
  `22P02 invalid_text_representation` on any version that is not
  `[0-9]+\.[0-9]+` — and `version` is a free `VARCHAR(50)` with no CHECK
  constraint. That failure mode is worse than the bug being fixed: the
  endpoint would 500 for the entire form instead of mis-sorting one row.
  The `CASE` confines the cast to rows that match; unparseable rows sort
  last, deterministically, by raw string. Module 4 stops such rows from
  being created — this stops one that already exists from taking the
  endpoint down.

---

## 3. Module Breakdown

### Module 1: Wire the storage backend
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py`
- **Responsibility**: `_get_version_service()` (`:1801`) passes
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
- **Note**: the storage row is authoritative on conflict. A `_meta` entry
  is an in-process echo of a publish that already wrote a row; when both
  exist for the same version, the row's `published_version` decides
  `is_published`, so a restart never changes an answer.

### Module 3: Demote `published_version` from visibility gate to label
- **Path**: `.../services/form_version.py`, `.../api/handlers.py`
- **UNGATED — §8 Q1 is closed by D1/D2/D3.** The submitted version of this
  module ("retire the filter, every row is just a version") is **not**
  what ships. The draft/published distinction is kept.
- **Responsibility**:
  1. `list_versions` (`:275`) stops using `published_version == version`
     to *drop* rows. Every stored row becomes a `VersionMeta`.
  2. The same comparison now *labels* each row:
     `is_published = (row["published_version"] == row["version"])`, and
     `is_frozen = is_published`. One helper, one place — put it next to
     `_parse_major_minor` so the two derivation rules live together.
  3. `published_at` per row: the `meta.published_at` stamp when present
     (published rows have it, written by `publish()`), otherwise the
     row's `created_at`. Keep `_published_at_from_snapshot`'s precedence,
     but feed it the projected columns instead of a whole `FormSchema`.
     **Do not fall back to `datetime.now()`** — the current fallback makes
     every draft in the list report "published just now", which the
     history UI would render as a wall of identical timestamps.
  4. `api/handlers.py:1936-1941` emits the new `is_published` key.
     `is_current` keeps its existing rule
     (`form.published_version or form.version`, `:1931`) — the two flags
     are independent and both are needed (§1.1 item 4).
- **Depends on**: Module 2.
- **Blast radius**: the subset of the 40 `published_version` test
  references that assert *invisibility* of unpublished rows. Those
  assertions are now wrong by decision, not by accident: rewrite them to
  assert `is_published is False` instead of absence. Any assertion about
  `publish()` stamping the field is still correct and must stay green —
  that is the lifecycle D1 preserves (see §8 Q3).

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
  `^\d+\.\d+$`. This closes the door before it opens. Module 2's guarded
  `CASE` cast is the belt to this braces: Module 4 stops bad rows being
  written, the guard stops one that slips through from 500-ing the
  endpoint.
- **Q4 answered**: keep it in. It is cheap, and it is the only thing
  standing between `_bump_version("1.2.3")` and a silently misordered
  history.

### Module 5: `get_published()` — the second filter site *(new, maintainer review)*
- **Path**: `.../services/form_version.py:243`
- **Responsibility**: `get_published` applies the identical filter
  (`if snap is not None and snap.published_version == version`) before
  returning a snapshot. Consequence today: `GET /api/v1/{tenant}/forms/{uid}/versions/{version}`
  (`api/handlers.py:1946`) returns **404 for every version the editor ever
  saved** — i.e. for all 105 measured rows. The submitted spec asserts
  this endpoint "continues to return the frozen snapshot"; it does not,
  and Modules 1–3 alone would ship a repaired history list in which every
  entry 404s when clicked. Drop the filter here too and return the stored
  snapshot for any version, draft or published; the returned `FormSchema`
  already carries `published_version`, so the caller can still tell the
  two apart.
- **Also fixes**: `publish()`'s fast-path immutability pre-check
  (`:193`) calls `get_published`. With the filter in place that check
  returns `None` for an existing *draft* row at the target tag, so the
  pre-check silently passes on a collision. Module 5 makes the fast path
  honest; Module 6 makes the real guard exist.
- **Depends on**: nothing (independently mergeable, but pointless without
  Modules 1–3).
- **Rename note**: with the filter gone the method name `get_published` is
  a misnomer — it returns any version. Renaming is optional and out of
  scope; if done, keep an alias, it is public API.

### Module 6: make publish's immutability guard real *(new, maintainer review)*
- **Path**: `.../services/storage.py`, `.../services/form_version.py`
- **Problem**: `publish()` documents *"the database UNIQUE constraint is
  the authoritative immutability guard — two concurrent publishes cannot
  both succeed"* (`services/form_version.py:209-211`) and wraps
  `_save_snapshot` in an `is_unique_violation` handler. Against
  `PostgresFormStorage` that guarantee **does not exist**:
  `_upsert_sql` (`services/storage.py:173`) ends in
  `ON CONFLICT (form_uid, version) DO UPDATE` (`:187`) — a collision is an
  overwrite, never a violation, so `is_unique_violation` never fires and a
  frozen published snapshot is silently replaced.
- **Why the suite is green on this too**: the only backend the test
  exercises is the `InMemoryStorage` double at
  `tests/unit/test_feat300_review_fixes.py:53`, whose `save()` *raises*
  `RuntimeError("duplicate key value violates unique constraint …")` on a
  duplicate. `test_unique_violation_surfaces_as_frozen_error` (`:224`)
  therefore asserts a behaviour the production SQL does not have. The
  double is stricter than the real thing — the inverse of what a test
  double may be.
- **Why it becomes urgent now**: with `_storage is None`, publish writes
  to a dict and the hole is unreachable. **Module 1 makes it reachable.**
  This is a regression introduced by the fix if not addressed in the same
  feature.
- **Responsibility**:
  1. Add an insert-only write path used by snapshot publication —
     `INSERT … ON CONFLICT (form_uid, version) DO NOTHING RETURNING id`;
     an empty result means the tag exists → raise the frozen `ValueError`.
     Keep the existing UPSERT for the editor's save path, which legitimately
     rewrites a draft in place.
  2. Point `_save_snapshot` (`:497`) at the insert-only path.
  3. Align the `InMemoryStorage` double with whichever contract the
     protocol ends up declaring, so the double stops being the stricter
     of the two.
- **Depends on**: Module 1 (it is Module 1 that exposes the hole).
- **Note**: this is what makes D1 enforceable. "Published" is only a
  meaningful state if a published row cannot be quietly rewritten.

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
| `test_list_versions_orders_unparseable_last` | 2 | a row with `version='draft-x'` sorts last and the query does **not** raise `22P02` |
| `test_list_versions_projects_not_hauls` | 2 | the SQL selects the six projected columns, not `schema_json` whole |
| `test_list_versions_includes_editor_saved_rows` | 3 | rows written via `_bump_version` + `storage.save` (no `published_version`) appear |
| `test_editor_saved_rows_are_labelled_draft` | 3 | those same rows come back with `is_published is False` / `is_frozen is False` |
| `test_published_rows_are_labelled_published` | 3 | a row written by `publish()` comes back `is_published is True` |
| `test_draft_and_published_coexist_in_one_history` | 3 | publish, save twice, publish again → labels alternate correctly across the chain |
| `test_is_current_marks_highest_version` | 3 | `is_current` true for the highest `(major, minor)`, false elsewhere |
| `test_is_current_independent_of_is_published` | 3 | the newest row is `is_current=True, is_published=False` while an older row is `is_current=False, is_published=True` (§1.1 item 4) |
| `test_draft_published_at_is_not_now` | 3 | a draft's `published_at` equals its stored `created_at`, never wall-clock now |
| `test_bump_grammar_is_single` | 4 | both call sites produce identical output for `1.0`, `1.9`, `1.14`; three-part input handled by one documented rule |
| `test_get_published_returns_draft_version` | 5 | `get_published()` returns a row whose `published_version != version` instead of `None` |
| `test_get_version_endpoint_serves_every_listed_version` | 5 | every entry returned by `GET .../versions` resolves 200 on `GET .../versions/{version}` — the anti-regression for "list works, clicking 404s" |
| `test_publish_over_existing_tag_raises_not_overwrites` | 6 | seed a row at the tag `publish()` will compute, publish, assert `ValueError` **and** that the stored row is unchanged |
| `test_snapshot_write_is_insert_only` | 6 | the snapshot path emits `ON CONFLICT … DO NOTHING`, not `DO UPDATE` |
| `test_inmemory_double_matches_postgres_contract` | 6 | the `InMemoryStorage` double and `PostgresFormStorage` agree on duplicate-key behaviour for both write paths |

### Integration Tests

| Test | Description |
|---|---|
| `test_versions_endpoint_returns_editor_history` | Save a form 5× through the PATCH/PUT handlers, then `GET /api/v1/{tenant}/forms/{uid}/versions` returns all 5 in order |
| `test_versions_endpoint_after_restart` | Same, with the handler and registry rebuilt between write and read |
| `test_versions_endpoint_tenant_isolation` | A form under `epson` is invisible to `GET /api/v1/pokemon/forms/{uid}/versions` |
| `test_versions_endpoint_labels_lifecycle` | Save 3×, `POST /publish`, save 2× more → the response labels exactly one entry `is_published: true`, and `is_current` sits on the newest draft |
| `test_every_listed_version_is_retrievable` | Against real Postgres: for each entry of `GET .../versions`, `GET .../versions/{version}` returns 200 (Module 5) |
| `test_publish_twice_same_tag_does_not_overwrite` | Against real Postgres: the second publish at an existing tag raises and leaves the stored row byte-identical (Module 6) |

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


@pytest.fixture
async def form_with_mixed_history(pg_storage, registry):
    """The shape D1 exists to represent: drafts and one published row.

    Writes through BOTH real writers — the editor's bump+save and
    FormVersionService.publish() — because a fixture that uses only one of
    them is exactly how the original defect stayed invisible.
    """
    svc = FormVersionService(registry, storage=pg_storage)
    form = FormSchema(form_id="mixed", title="Mixed", tenant="t1", sections=[])
    await registry.register(form, tenant="t1")
    await pg_storage.save(form, tenant="t1")            # 1.0  draft
    await svc.publish(form.form_uid, tenant="t1")       # 1.1  PUBLISHED
    cur = (await pg_storage.load(form.form_uid, tenant="t1"))
    for _ in range(2):                                  # 1.2, 1.3  drafts
        cur = cur.model_copy(deep=True,
                             update={"version": _bump_version(cur.version)})
        await pg_storage.save(cur, tenant="t1")
    return form
```

> **Fixture rule for this feature**: no test may build its history through
> `publish()` alone. That single habit is what kept defect 2 invisible
> through an entire review cycle (`test_feat300_review_fixes.py:179`).
> Every history fixture uses the editor path, and the lifecycle fixtures
> use both.

---

## 5. Acceptance Criteria

- [ ] `GET /api/v1/{tenant}/forms/{uid}/versions` returns every stored
      version for a form written exclusively through the editor path
      (no `publish()` call anywhere in the fixture)
- [ ] The response is ordered so that `1.14` follows `1.10` follows `1.9`
- [ ] Listing a form's versions issues exactly one storage query
- [ ] `_probe_storage_versions` and `_MAX_VERSION_PROBES` no longer exist
- [ ] A published snapshot survives rebuilding the service (Module 1)

**Draft vs published (D1) — the decisive criteria**

- [ ] Every listed version carries `is_published`, derived from
      `published_version == version`, with **no new column and no
      migration**
- [ ] In a history containing both, editor-saved rows report
      `is_published: false` and `publish()`-written rows report
      `is_published: true`
- [ ] `is_current` and `is_published` can differ on the same response —
      the newest row may be an unpublished draft while an older row is
      the published one
- [ ] A draft's `published_at` is its stored `created_at`, never the
      wall-clock time of the request
- [ ] `is_frozen` is `True` only for published rows

**Modules 5–6 (maintainer findings)**

- [ ] Every version returned by `GET .../versions` resolves `200` on
      `GET .../versions/{version}` — no listed entry 404s
- [ ] `GET .../versions/{version}` returns a draft snapshot instead of 404
- [ ] Publishing over an existing tag raises the frozen `ValueError` and
      leaves the stored row byte-identical, verified against real
      Postgres — not only against `InMemoryStorage`
- [ ] The snapshot write path uses `ON CONFLICT … DO NOTHING`; the editor
      save path keeps `DO UPDATE`
- [ ] A malformed `version` string sorts last and does not raise `22P02`

**Unchanged guarantees**

- [ ] All unit tests pass (`pytest packages/parrot-formdesigner/tests/unit/ -v`)
- [ ] All integration tests pass (`pytest packages/parrot-formdesigner/tests/integration/ -v`)
- [ ] No database migration is introduced
- [ ] Response envelope is **extended additively** — every key FieldSync
      already reads (`version`, `published_at`, `published_by`,
      `is_current`) keeps its name, type and meaning; `is_published` is
      added
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

> **Line numbers corrected 2026-08-19.** Every `api/handlers.py` citation
> in the submitted draft was off by one against `dev@28e84a440`
> (`:1810`→`:1809`, `:1802`→`:1801`, `:1282`→`:1281`, `:1358`→`:1357`,
> `:1932`→`:1931`). The referenced code is the right code; the anchors are
> now exact. Re-verify before implementing if `dev` has moved.

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
    #   :193  existing = await self.get_published(...)   ← fast-path pre-check
    #   :209  "the database UNIQUE constraint is the authoritative
    #          immutability guard"                       ← NOT TRUE (Module 6)
    async def get_published(self, form_uid, *, version, tenant) -> FormSchema | None: ...  # line 243
    #   :265  if snap is not None and snap.published_version == version:
    #                                                    ← 2nd filter site (Module 5)
    async def list_versions(self, form_uid, *, tenant) -> list[VersionMeta]: ...  # line 275
    #   :305  if snap is None or snap.published_version != version: continue
    async def _probe_storage_versions(self, form_uid, *, tenant) -> list[str]: ...# line 316
    #   :339  if snap is not None and snap.published_version == version:
    async def _save_snapshot(self, snapshot, *, tenant) -> None: ...              # line 497

# packages/parrot-formdesigner/src/parrot_formdesigner/services/storage.py
class PostgresFormStorage:
    def _resolve_schema(self, tenant: str | None) -> str: ...        # line 135
    def _qualified(self, tenant: str | None) -> str: ...             # line 147
    def _upsert_sql(self, tenant: str | None) -> str: ...            # line 173
    #   :187  ON CONFLICT (form_uid, version) DO UPDATE  ← overwrite (Module 6)
    def _load_version_sql(self, tenant: str | None) -> str: ...      # line 205
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

# packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py
class FormDesignerHandler:
    def _get_version_service(self) -> FormVersionService: ...        # line 1801
    #   :1809  FormVersionService(self.registry)         ← defect 1
    #   :1829  _make_question_bank passes storage=self.registry.storage
    #          — the same handler already does it correctly one method below
    async def publish_form(self, request) -> web.Response: ...       # line 1838
    async def list_versions(self, request) -> web.Response: ...      # line 1909
    #   :1931  current_version = form.published_version or form.version
    async def get_version(self, request) -> web.Response: ...        # line 1946
    #   editor write path: :1281 body["version"] = _bump_version(...)
    #                      :1285 body["published_version"] = existing.published_version
    #                      :1357 / :1363 same, PATCH

# packages/parrot-formdesigner/tests/unit/test_feat300_review_fixes.py
class InMemoryStorage(FormStorage):
    async def save(self, form, style=None, *, tenant=None) -> str: ...  # line 53
    #   :55-58  raises on duplicate (form_uid, version) — STRICTER than the
    #           production UPSERT; the divergence Module 6 closes
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| Module 1 | `FormRegistry.storage` | property read | `services/registry.py:1307` |
| Module 2 | `PostgresFormStorage._qualified()` | SQL builder | `services/storage.py:147` |
| Module 2 | `_parse_major_minor` | in-memory sort key | `services/form_version.py:69` |
| Module 3 | handler `is_current` computation | `form.published_version or form.version` | `api/handlers.py:1931` |
| Module 3 | handler response dict | new `is_published` key | `api/handlers.py:1936-1941` |
| Module 5 | `FormVersionService.get_published` | filter removal | `services/form_version.py:265` |
| Module 6 | `PostgresFormStorage._upsert_sql` | insert-only sibling | `services/storage.py:173,187` |
| Module 6 | `InMemoryStorage` test double | contract alignment | `tests/unit/test_feat300_review_fixes.py:53` |

### Does NOT Exist (Anti-Hallucination)
- ~~`FormStorage.list_versions()`~~ — this spec introduces it; the absence
  is why `_probe_storage_versions` was written
- ~~`form_schemas.published_version`~~ — not a column; it lives inside
  `schema_json`
- ~~`form_schemas.is_published` / `is_draft`~~ — no such columns, and this
  spec does **not** add them. `is_published` is a derived response field
  (D2), computed from data already stored
- ~~a working `GET .../versions/{version}` for editor-saved versions~~ —
  it 404s today; Module 5 is what makes it work
- ~~an enforced immutability guarantee on published snapshots~~ — the
  docstring claims one, the SQL does not provide it; Module 6 creates it
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
  test suite; Module 3 touches the subset asserting *invisibility* of
  unpublished rows. Under D1 those become `is_published is False`
  assertions — the references do not disappear, they change meaning.
  Assertions about `publish()` stamping the field are still correct.
- **The doubles are stricter than production.** `InMemoryStorage`
  (`tests/unit/test_feat300_review_fixes.py:53`) raises on a duplicate
  `(form_uid, version)`; `PostgresFormStorage` overwrites. Every
  conclusion this suite has ever drawn about immutability came from the
  double, not from Postgres. Treat any remaining "verified by unit test"
  claim about storage semantics as unverified until it runs against a
  real pool (Module 6).
- **`_published_at_from_snapshot` falls back to `datetime.now()`**
  (`services/form_version.py:348`, fallback at `:356`). Harmless while the list only ever
  contained rows written by `publish()` (which always stamp
  `meta.published_at`); actively misleading the moment drafts are listed,
  because every draft would report "published now". Module 3 replaces the
  fallback with the row's `created_at`, which `PostgresFormStorage.load`
  already surfaces (`services/storage.py:409`).
- **`_probe_storage_versions` never looked at major 0.** It iterates
  `range(1, latest_major + 1)`, so a form at `0.x` would have reported an
  empty history even with defects 1 and 2 fixed. Noted for completeness —
  the method is deleted by Module 2, but it is a third independent reason
  the probing approach could not be trusted.
- **Ordering across writers.** `publish()` bumps from the *live* form's
  version, the editor bumps from the *stored* row's version. Both feed the
  same `UNIQUE (form_uid, version)`. With Module 6 an overlap now raises
  instead of silently overwriting — a behaviour change that is the point,
  but a behaviour change: publish can start returning `ValueError` where
  it previously appeared to succeed.
- **Double-encoded `schema_json` and the new label.** The projected SQL
  reads `schema_json ->> 'published_version'`. If a row were ever stored
  double-encoded (`jsonb_typeof = 'string'`), that extraction returns
  NULL and the row silently labels as a draft. Measured 0/105 today; the
  `->>`-based label makes the regression *observable* (everything looks
  like a draft) rather than *fatal*, which is the right tradeoff — but
  `tests/test_jsonb_object_storage.py` is now load-bearing for the label,
  not just for reads.

### External Dependencies

None. No new packages, no migration.

---

## 8. Open Questions

> Q1, Q2 and Q4 are **closed** by the maintainer review of 2026-08-19
> (§0). Q3 is narrowed to a mechanical pass. Q5 is new and is the only
> thing that could still change the shape of this feature.

- [x] **Q1 — Should a listed version distinguish *published* from
      *saved*? → YES. Decided 2026-08-19 (D1).** The distinction is kept
      and is a hard requirement, not a deferral. It costs no migration and
      no column: `is_published = (published_version == version)` is
      already fully determined by the stored data (D2). The submitted
      reasoning inverted the causality — the field is NULL in 105/105 rows
      because no writer sets it, and no writer sets it because the editor
      never adopted the publish call, not because the lifecycle was
      rejected. The front editor is now on the hook for the other half
      (§1.1, D5).
- [x] **Q2 — Is `POST /publish` still wanted? → YES. Decided 2026-08-19
      (D4).** It is the only writer of the published state; retiring it
      retires Q1's answer. It is also the endpoint whose immutability
      guarantee turns out not to exist (Module 6).
- [ ] **Q3 — Which `published_version` test assertions encode a real
      requirement** versus the current behavior? Narrowed by D1: any
      assertion that an *unpublished row is invisible* encoded the bug and
      is rewritten to assert `is_published is False`; any assertion that
      `publish()` stamps the field, or that a published snapshot is
      immutable, encodes a real requirement and must stay green. Expected
      to be mechanical — raise it only if a reference resists this
      classification — *Owner: implementer, escalate on ambiguity*
- [x] **Q4 — Module 4 in or out? → IN. Decided 2026-08-19.** Cheap, and
      the only thing between `_bump_version("1.2.3")` and a silently
      misordered history.
- [ ] **Q5 (NEW) — Should `publish()` promote the current version in
      place instead of bumping to a new tag?** Today publish computes
      `_bump(live.version)` and writes a *new* row, so publishing draft
      `1.5` produces published `1.6` — a content-identical twin, and `1.5`
      stays a draft forever. Under D1 that is version inflation: every
      publish doubles a row and the history alternates draft/published
      copies of the same form. The alternative — stamp
      `published_version = version` on the existing row and let the next
      editor save bump to a new draft — matches "publish the version I am
      looking at", produces one row per actual change, and is what a
      version-history UI naturally renders. It is **out of scope here**
      (this feature repairs the read path; changing publish's write
      semantics is a separate decision with its own blast radius), but it
      should be settled before the FieldSync UI ships, because the two
      models produce visibly different histories —
      *Owner: Jesús, before FieldSync UI freeze*

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-19 | Juan Ruffato (FieldSync) | Initial draft from `form-version-history-repair.brainstorm.md`; submitted for parrot maintainer review |
| 0.3 | 2026-08-19 | Juan Ruffato (FieldSync) | Submitter acceptance (§0.1): D1–D5 and Modules 5–6 adopted; S1 closes the version-format thread, S2 keeps test-data fabrication out of scope. Status → approved; decomposed into TASK-2264…TASK-2269 |
| 0.2 | 2026-08-19 | Jesús Lara (maintainer) | **Review pass.** Defects 1–3 confirmed against `dev@28e84a440` — the diagnosis is correct and `PostgresFormStorage` versioning was never the problem; the bug is entirely on the read path. Changes: §0 maintainer decisions (D1–D5); §1.1 normative front-editor contract; Q1 closed **preserving draft/published** as a derived label with no migration, Q2 and Q4 closed, Q5 raised; Module 3 rewritten from "retire the filter" to "demote gate → label" and ungated; **Module 5 added** — `get_published()` carries the same filter, so `GET .../versions/{version}` 404s every editor-saved version (missed by the submission, which claims it works); **Module 6 added** — `publish()`'s documented immutability guard does not hold, `_upsert_sql` is `ON CONFLICT DO UPDATE` and the `InMemoryStorage` double is stricter than production, a hole that Module 1 makes reachable; SQL hardened (projected columns instead of whole `schema_json`, guarded `::int` cast against `22P02`); `VersionMeta` gains `is_published`, `is_frozen` stops being hardcoded `True`; draft `published_at` no longer falls back to wall-clock now; `api/handlers.py` line anchors corrected (off by one throughout); tests, fixtures and acceptance criteria extended accordingly |
