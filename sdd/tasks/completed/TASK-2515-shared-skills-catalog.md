# TASK-2515: Shared skills catalog — org-wide, category-ordered, owner-filterable

**Feature**: FEAT-467 — Agent Studio — Management API
**Spec**: `sdd/specs/agentstudio-management.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2511, TASK-2514
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7. Resolved in brainstorm: org-wide re-usable skills with
**hybrid storage** — extend `SkillRegistry` (shared org namespace + new
`owner_user_id` field) so embedding search and git-like versioning keep
working, AND persist every entry to the NEW Postgres table
`navigator.ai_skills_catalog`, the durable record and SQL query plane
(`ORDER BY category`, `WHERE owner`). Categories constrained to the
`SkillCategory` enum (out-of-vocabulary → `general`). Drift repaired by a
startup reconciliation pass + admin resync endpoint.

---

## Scope

- Core changes (`packages/ai-parrot`):
  - Add `owner_user_id: str = ""` to the `Skill` dataclass (models.py),
    incl. `to_dict`/`from_dict`.
  - Shared-namespace convention `"<org_id>/_shared"` documented and
    accepted by `SkillRegistry` (no behavioral special-case needed beyond
    allowing it).
- Server (`packages/ai-parrot-server`):
  - `SkillCatalogEntry` asyncdb `Model` (`navigator.ai_skills_catalog`):
    skill_id (uuid PK), name (unique), description, category, owner,
    triggers (JSONB), body, version, status, search_index_stale (bool),
    created_at/updated_at. Docstring DDL.
  - `StudioSkillsCatalogHandler` in `handlers/studio/skills_catalog.py`:
    - `GET /api/v1/astudio/skills?category=&owner=` — ordered by category
      then name; both filters optional; invalid category → 400 listing
      valid `SkillCategory` values.
    - `POST /api/v1/astudio/skills` — validate `SkillPublishRequest`
      (frontmatter fields; body ≤ token cap); PG insert FIRST, then
      best-effort `SkillRegistry.upload_skill` into the shared namespace;
      registry failure → `search_index_stale=true`, publish still 201.
      Owner = session user. Duplicate name → 409.
    - `GET /api/v1/astudio/skills/{id}` — entry + versions (registry).
    - `PUT/DELETE /api/v1/astudio/skills/{id}` — owner-or-admin.
    - `POST /api/v1/astudio/agents/{name}/skills/import/{id}` —
      materialize as `AGENTS_DIR/<agent>/skills/<name>.md` (frontmatter
      composed from the entry); collision → 409 unless `overwrite=true`;
      response flags `reload_required`.
    - `POST /api/v1/astudio/skills/resync` — admin-only: PG → registry for
      `search_index_stale` rows; returns counts.
  - Startup reconciliation hook (same resync routine) wired via
    `app.on_startup` in `setup_studio_routes`.
- Tests: ordering/filtering, dual-write drift, import flow, resync.

**NOT in scope**: per-agent skill file CRUD (TASK-2514); semantic-search
endpoint over the catalog (registry search stays internal for now).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/skills/models.py` | MODIFY | `Skill.owner_user_id` + (de)serialization |
| `packages/ai-parrot/src/parrot/skills/store.py` | MODIFY | accept/document shared namespace; owner passthrough on upload |
| `packages/ai-parrot-server/src/parrot/handlers/models/skills_catalog.py` | CREATE | `SkillCatalogEntry` model |
| `packages/ai-parrot-server/src/parrot/handlers/studio/skills_catalog.py` | CREATE | catalog handler + resync |
| `packages/ai-parrot-server/src/parrot/handlers/studio/__init__.py` | MODIFY | routes + on_startup hook |
| `packages/ai-parrot/tests/skills/test_skill_owner_field.py` | CREATE | dataclass round-trip |
| `packages/ai-parrot-server/tests/studio/test_skills_catalog.py` | CREATE | endpoint + drift tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.skills.store import SkillRegistry, create_skill_registry  # store.py:132 (+factory)
from parrot.skills.models import Skill, SkillCategory, SkillStatus    # models.py:158,29,21
from parrot.skills.parsers import parse_skill_file                    # parsers.py:37
from asyncdb.models import Model, Field                               # scheduler/models.py:4
from parrot.conf import AGENTS_DIR                                    # conf.py:175
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/skills/store.py
class SkillRegistry:  # Redis + file persistence, embedding search
    def __init__(self, namespace: str = "default",
                 embedding_model="sentence-transformers/all-mpnet-base-v2",
                 dimension: int = 768, redis_url: Optional[str] = None,
                 persistence_path: Optional[Path] = None,
                 extraction_llm=None, min_diff_threshold: int = 50): ...  # :132
    # async upload_skill / read_skill / search_skills / list_skills /
    # get_skill_versions / deprecate_skill / revoke_skill
    # (grep exact signatures in store.py before calling — params may carry
    #  category/tags kwargs; verify at implementation time)

# packages/ai-parrot/src/parrot/skills/models.py
class SkillCategory(str, Enum): ...  # :29 — tool_usage, workflow, domain,
    # error_handling, user_preference, integration, optimization, general
class SkillStatus(str, Enum): ...    # :21 — active, deprecated, revoked, draft
@dataclass
class Skill:  # :158
    skill_id: str; namespace: str = "default"   # "org_id/agent_id"
    owner_agent_id: str = ""                    # AGENT owner (existing)
    metadata: SkillMetadata; status: SkillStatus
    # to_dict :~195 / from_dict :~212 — extend BOTH for owner_user_id

# asyncdb Model pattern — scheduler/models.py:7 (Meta: driver='pg',
#   schema='navigator', strict=True); DB via request.app['database']
# Skill body cap: SkillDefinition.MAX_TOKENS = 1000 (models.py:76)
```

### Does NOT Exist
- ~~A Postgres table for skills~~ — `navigator.ai_skills_catalog` is NEW;
  `SkillRegistry` persists to Redis + `_save_to_disk` file only.
- ~~`Skill.owner_user_id`~~ — NEW here; today only `owner_agent_id`.
- ~~An org-wide shared namespace convention~~ — NEW (`"<org>/_shared"`);
  existing namespaces are per-agent `"org_id/agent_id"`.
- ~~A catalog/list endpoint over SkillRegistry~~ — the only listing today
  is toolkit-internal (`SkillRegistryToolkit.list_skills` for one agent).
- ~~`SkillCategory.OTHER`~~ — no such member; out-of-vocabulary maps to
  `SkillCategory.GENERAL`.

---

## Implementation Notes

### Pattern to Follow
Dual-write order (resolved): PG insert in a transaction FIRST (source of
truth), then `await registry.upload_skill(...)` wrapped in try/except →
on failure `UPDATE ... SET search_index_stale = true` + warning log.
Resync: `SELECT ... WHERE search_index_stale` → re-upload → clear flag.

### Key Constraints
- Listing: `ORDER BY category, name`; response grouped
  `{category: [entries...]}` plus a flat list — pick ONE shape and
  document it (grouped preferred per brainstorm "ordered/grouped").
- Never fail a publish because Redis is down (spec §7 risk).
- Import composes frontmatter (name, description, triggers, category,
  version) + body and validates the result with `parse_skill_file` before
  moving into the agent dir (reuse TASK-2514 helpers).
- Admin check for resync via `_require_owner`-style admin detection
  (TASK-2511 helper).
- org_id for the shared namespace: derive from session; when absent use
  `"default"` (matches SkillRegistry default namespace root).

### References in Codebase
- `parrot/skills/mixin.py:105 _configure_skill_registry` — how a registry
  instance is created/configured today (namespace, persistence_path).
- `handlers/credentials.py` — fire-and-forget secondary persistence
  pattern (session vault ↔ DocumentDB) analogous to PG↔registry here.

---

## Acceptance Criteria

- [ ] Publish → PG row + registry entry in `"<org>/_shared"`; owner from
      session; duplicate name → 409.
- [ ] List ordered/grouped by category; `?owner=`/`?category=` filters
      work; invalid category → 400 with valid values.
- [ ] Registry outage: publish still succeeds with
      `search_index_stale=true`; resync clears it.
- [ ] Import materializes a `parse_skill_file`-valid file in the agent's
      skills dir; collision → 409 unless `overwrite=true`.
- [ ] `Skill` dataclass round-trips `owner_user_id` (to_dict/from_dict).
- [ ] Tests pass: `pytest packages/ai-parrot-server/tests/studio/test_skills_catalog.py packages/ai-parrot/tests/skills/test_skill_owner_field.py -v`
- [ ] `ruff check` clean on touched paths.

---

## Test Specification

```python
# packages/ai-parrot-server/tests/studio/test_skills_catalog.py
class TestSkillsCatalog:
    async def test_publish_dual_write(self, studio_app): ...
    async def test_publish_registry_down_sets_stale(self, studio_app): ...
    async def test_list_grouped_by_category_ordered(self, studio_app): ...
    async def test_owner_and_category_filters(self, studio_app): ...
    async def test_invalid_category_400(self, studio_app): ...
    async def test_import_into_agent_and_collision(self, studio_app, tmp_agents_dir): ...
    async def test_resync_admin_only_and_clears_stale(self, studio_app): ...
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2511, TASK-2514 completed
3. **Verify the Codebase Contract** — especially grep the exact
   `upload_skill`/`list_skills` signatures in `skills/store.py` before use
4. **Update status** in `sdd/tasks/index/agentstudio-management.json` → `"in-progress"`
5. **Implement**, **verify** acceptance criteria
6. **Move this file** to `sdd/tasks/completed/`
7. **Update index** → `"done"`, fill Completion Note

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-08-27
**Notes**:
- Core: `Skill.owner_user_id: str = ""` added (distinct from the existing
  AGENT-identity `owner_agent_id`); `to_dict()` includes it, `from_dict()`
  needed NO change (generic `cls(**data)` passthrough already round-trips
  any field present, and defaults `""` when absent — verified backward
  compatible with pre-existing persisted records missing the key).
  `upload_skill()`/`_create_new_skill()` gained `owner_user_id=` and a
  `skill_id=` passthrough for NEW skills (previously `skill_id` was only
  ever used to look up an EXISTING skill; a not-yet-existing id was
  silently discarded and a fresh uuid4 generated instead) — required so
  the Postgres catalog row and the registry `Skill` can share one id
  (spec §2: "skill_id ... mirrors SkillRegistry skill_id"). `_create_new
  _version` (the update path) intentionally does NOT touch ownership —
  verified via `test_upload_skill_update_preserves_owner_user_id`.
  Shared-namespace convention (`"<org_id>/_shared"`) documented on the
  class docstring; genuinely needed zero behavioral special-casing (`/`
  in a namespace string works fine as both a Redis-key and filesystem-
  path segment).
- Server: `SkillCatalogEntry` model (`navigator.ai_skills_catalog`),
  `StudioSkillsCatalogHandler` (list/publish/read+versions/update/
  delete), `StudioSkillsImportHandler` (materialize into an agent's
  `skills/` dir), `StudioSkillsResyncHandler` (admin-only), plus the
  standalone `reconcile_skills_catalog(app)` function wired via
  `app.on_startup.append(...)`.
- Dual-write: PG insert/update ALWAYS happens first (source of truth);
  the registry write is wrapped in `_dual_write_to_registry()`, which
  NEVER raises — on failure it returns `True` and the caller flags
  `search_index_stale`. `POST /skills/resync` and the startup hook share
  the identical "select stale → re-upload → clear flag" routine.
  Route-order note: `/skills/resync` is registered BEFORE the dynamic
  `/skills/{id}` (aiohttp matches in registration order — `{id}` would
  otherwise swallow "resync" as an id).
- **Two real bugs found and fixed while implementing (not the task's own
  code, but blocking it):**
  1. **`from __future__ import annotations` breaks asyncdb Model
     construction.** Empirically confirmed: `SkillCatalogEntry(...)` (and
     TASK-2513's `StudioDraft(...)`, which had the SAME latent bug,
     undetected because that task's tests only ever used a hand-rolled
     fake row, never the real model class) raised `TypeError: Expected
     type, got str` from `datamodel.validation` — the Cython field
     processor reads `__annotations__` directly without
     `typing.get_type_hints()` resolution, so postponed-evaluation string
     annotations break it. Fixed by removing the future-import from BOTH
     `handlers/models/skills_catalog.py` and `handlers/models/
     studio_drafts.py` (the latter is a TASK-2513 file, out of THIS
     task's Files table, but the bug directly blocks constructing a real
     `SkillCatalogEntry`/any future asyncdb Model built the same way, so
     it had to be fixed now). Matches the working, future-import-free
     `scheduler/models.py::AgentSchedule` pattern. Python 3.12 natively
     supports the `X | None` syntax already in use, so no future import
     is needed for that either.
  2. `parse_skill_file`'s frontmatter `source` field only accepts
     `SkillSource.AUTHORED`/`LEARNED` — my first draft of
     `_compose_skill_markdown` wrote `source: shared_catalog`, an
     invalid value that made EVERY import fail validation. Fixed to
     `"authored"` (a catalog import is developer-authored content).
- Tests: catalog handler tests fake DB persistence via monkeypatched
  `_get_entry_by_id`/`_get_entry_by_name`/`_list_entries`/
  `_insert_entry`/`_update_entry`/`_delete_entry` mixin methods (added
  during implementation specifically for this testability, mirroring
  TASK-2513's `_FakeDraftStore` pattern) holding REAL `SkillCatalogEntry`
  instances — exercises the real model end to end (which is exactly how
  the `from __future__ import annotations` bug above was caught). The
  shared `SkillRegistry` is faked via the module-level, monkeypatchable
  `_get_shared_skill_registry(app, org_id)` function so tests never load
  a real embedding model; `packages/ai-parrot/tests/skills/
  test_skill_owner_field.py` instead uses a REAL `SkillRegistry`
  configured with `configure(embedding_model=<8-dim fake async fn>)` —
  a genuine seam `configure()` already exposed, no test-only code path
  needed in `store.py`.

**Deviations from spec**: none functionally. One necessary out-of-table
fix: `handlers/models/studio_drafts.py` (TASK-2513) — see bug #1 above.

Verification: `pytest packages/ai-parrot-server/tests/studio/
test_skills_catalog.py packages/ai-parrot/tests/skills/
test_skill_owner_field.py -v` → 18 + 8 = 26/26 passed. Full regression
sweep: ai-parrot-server (`tests/studio/`, `tests/manager/`,
ephemeral-owner, DB-bot fallback) → 121/121 passed; ai-parrot skills
(`tests/skills/` + integration/unit skill suites) → 46/46 passed.
`ruff check` on every touched path → clean except intentional
`BLE001`/`S112` best-effort/fail-open patterns matching established
convention (verified no NEW violation categories were introduced).
`git status --porcelain` on the main repo checked clean before and
after the full run.
