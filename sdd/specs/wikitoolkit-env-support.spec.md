---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: wikitoolkit Environment Support (env-aware config + memory sync)

**Feature ID**: FEAT-461
**Date**: 2026-08-25
**Author**: Jesus (with Claude)
**Status**: approved
**Target version**: 0.28.0

**Brainstorm**: `sdd/proposals/wikitoolkit-env-support.brainstorm.md` (Option A accepted; all 10 open questions resolved)

---

## 1. Motivation & Business Requirements

### Problem Statement

`wikitoolkit` reads a single, hardcoded `.parrot/wiki.json`: one `backend`
(currently `arangodb`), one `arango_database` (`wiki_ai-parrot`, the **dev**
server), one credentials prefix. Meanwhile the rest of the repo is
environment-aware through **navconfig**: `ENV=prod wikitoolkit build` makes
navconfig load `env/prod/.env`, and no `ENV` loads `env/.env` (dev
credentials). The wiki config ignores this entirely:

- **Local development requires a VPN.** With `wiki.json` pinned to the dev
  ArangoDB, launching Claude Code offline (or off-VPN) strands every
  `wikitoolkit query`. The desired behavior is a **local sqlite plane** for
  the repo's own wiki, with only the *shared* team-KB namespaces reaching the
  cloud dev ArangoDB (and skipping gracefully when unreachable).
- **Credentials and plane selection are conflated.** navconfig already
  switches credentials per `ENV`, but the *backend/database choice* cannot
  follow it, so `ENV=prod wikitoolkit build` still writes to the dev database.
- **Local knowledge is trapped.** Memories, notes, and asserted links written
  on a local sqlite plane never reach the team's shared ArangoDB KB — there is
  no sync mechanism in either direction.

The `_open_store` docstring already carries a `TODO(follow-up)` describing
exactly this gap (`cli.py:352-377`), including the existing inconsistency that
`WIKI_STORE_BACKEND` is honoured by `_resolve_read_store` but ignored by
`build`.

### Goals

- Environment-aware wiki configuration via per-env overlay files
  (`.parrot/wiki.{env}.json`) shallow-merged over the committed base
  `.parrot/wiki.json`, with the env resolved as `WIKI_ENV` → `ENV` → `local`.
- **No `ENV` = local development**: sqlite plane, zero VPN dependency; shared
  namespaces degrade gracefully (skip + one-line warning, bounded timeout).
- Missing overlay falls back to base for read commands; `wikitoolkit build`
  auto-generates the missing overlay via env-templated derivation
  (`local` → sqlite; every other env → base Arango settings verbatim, same
  database name — separation lives in the per-`ENV` credentials).
- **No secrets in JSON**: overlays hold only non-secret values; host/user/
  password always resolve via navconfig from `env/{ENV}/.env`.
- One backend precedence rule everywhere (closes the `cli.py:352` TODO):
  `--backend` flag > environment (overlay / `WIKI_STORE_BACKEND`) > base
  `wiki.json` — applied to `build`, `_open_store`, `_resolve_read_store`,
  `_resolve_write_store`.
- **v1 sync**: explicit `wikitoolkit sync push` / `sync pull` moving memories
  (`origin="memory"`), attributed notes, and `asserted` edges between the
  local sqlite plane and a shared ArangoDB plane — last-write-wins via a new
  `updated_at` stamp; `pull` excludes own-authored records by default
  (`--all` overrides); notes merge append-if-absent.
- Backwards compatible: a repo with only `.parrot/wiki.json` and no overlays
  behaves exactly as today.

### Non-Goals (explicitly out of scope)

- Syncing full repo-scan pages (the remote can rebuild those) — resolved in
  brainstorm: sync content is memories + notes/asserted links only.
- Delete propagation / tombstones in sync v1 — documented limitation.
- Per-env database name suffixing (`wiki_ai-parrot_prod`) — rejected:
  same database name in every env; separation comes from server/credentials.
- Restricting local-machine writes to the shared dev ArangoDB — rejected:
  `ENV=dev` stays a full read-write plane; sole-writer discipline is social.
- An `environments:` block inside `wiki.json`, pure-navconfig structural
  config, and environments-as-namespaces — rejected as brainstorm Options
  B/C/D (see `proposals/wikitoolkit-env-support.brainstorm.md`).
- Automatic runtime fallback from unreachable Arango to a stale local plane
  for the PRIMARY store (would answer queries from a stale corpus without
  saying so — flagged by the `cli.py:352` TODO itself). Graceful degradation
  applies to *namespaces*, not to the primary plane.

---

## 2. Architectural Design

### Overview

Per-environment overlay files, merged over the committed base at load time
(brainstorm Option A):

- `.parrot/wiki.json` stays the committed base (team dev Arango for this
  repo). Optional overlays `.parrot/wiki.local.json`, `.parrot/wiki.dev.json`,
  `.parrot/wiki.prod.json` are validated as *partial* configs (all fields
  optional) and shallow-merged on top (`model_copy(update=...)`; the
  `namespaces` dict merges per-key with overlay entries winning).
- Environment resolution (stdlib-only, hook-safe):
  `resolve_wiki_env() -> str` = `WIKI_ENV` or `ENV` or `"local"`. `WIKI_ENV`
  is the escape hatch when the navconfig env and the wiki plane must differ.
  This intentionally diverges from navconfig's "no `ENV` ⇒ `env/.env` (dev)"
  convention **for plane selection only** — credential resolution is
  untouched (plane selection ≠ credential selection; must be documented).
- A single choke point `load_effective_config(root, env=None) ->
  WikiEffectiveConfig` replaces `load_project_config()` at all 11 existing
  call sites (CLI, MCP server, Claude hook, installer, federation);
  `load_project_config` remains for raw base access (save paths, `ns add`).
  The effective config records provenance (env name, overlay path or None).
- `wikitoolkit build` generates a missing overlay for the active env via
  `derive_env_overlay(base, env)`: `local` → `{"backend": "sqlite"}`; every
  other env → base Arango settings verbatim (same database name, same
  `credentials_env`). Generation only fills absence — an existing overlay is
  used verbatim, never clobbered. Read-only commands never write files.
- `wikitoolkit status` prints an environment header: active env, overlay file
  used (or `base (no overlay)`), resolved backend + database, reachability.
- **This repo commits** `.parrot/wiki.local.json` = `{"backend": "sqlite"}`
  so every teammate gets the no-VPN sqlite default out of the box (resolved
  in brainstorm).
- **Sync v1** (`wiki/sync.py` + CLI group): `sync push [--env dev]
  [--dry-run]` uploads local authored knowledge (memory pages, attributed
  notes, `asserted` edges) to the shared plane of the named env (default
  `dev`); `sync pull [--env dev] [--dry-run] [--all]` downloads the same
  record classes, by default excluding records whose `asserted_by` matches
  the local identity (own memories stay authoritative; `--all` → pure LWW).
  Conflict rule: last-write-wins per record by a new `updated_at` stamp on
  `WikiPageRecord`; notes merge append-if-absent (identity hash of
  author + date + text; union of note sets, date-ordered — a note can never
  be dropped by a merge). Every applied change is bookkeeper-logged
  (`SYNC_PUSH` / `SYNC_PULL`); summaries report created / updated /
  skipped-older / skipped-own.

### Component Diagram

```
                 ┌─ WIKI_ENV / ENV / "local" ─┐
                 ▼                            │
        resolve_wiki_env()                    │
                 │                            │
                 ▼                            │
   load_effective_config(root)                │
     base .parrot/wiki.json                   │
       + .parrot/wiki.{env}.json (partial)    │
                 │ (provenance: env, overlay) │
   ┌─────────────┼────────────────┬───────────┴──────┐
   ▼             ▼                ▼                  ▼
 cli.py     mcp_server.py   claude_code/       federation.py
 (_open_store,  (serve)     hook.py+installer  (namespaces —
  read/write                                    NamespaceSkip
  stores, build,                                degradation)
  status, sync)
   │
   ▼ build only, overlay missing
 derive_env_overlay(base, env) ──▶ atomic write .parrot/wiki.{env}.json

 sync push/pull (wiki/sync.py):
   local plane (env "local", sqlite) ◀──▶ remote plane (target env overlay
        │                                   + resolve_arango_params under
        │  select origin="memory" pages,    that env's credentials)
        │  notes, asserted edges
        └─ LWW by updated_at · pull filters own asserted_by · notes
           append-if-absent · bookkeeper SYNC_PUSH/SYNC_PULL
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `wiki/project.py` | extends | `resolve_wiki_env()`, overlay partial model, `WikiEffectiveConfig`, `load_effective_config()`, `derive_env_overlay()`; stays hook-safe (stdlib+pydantic, lazy navconfig) |
| `wiki/cli.py` | modifies | `_resolve_project`/`_open_store`/`_resolve_read_store`/`_resolve_write_store` route through effective config; `build` gains overlay generation; new `sync` group; `status` env header; closes `cli.py:352` TODO |
| `wiki/store.py` | modifies | `WikiPageRecord.updated_at`; sqlite persistence of the stamp |
| `wiki/arango_store.py` | modifies | persist/return `updated_at` |
| `wiki/sync.py` | new | push/pull engine (LWW, author-filtered pull, append-if-absent notes) |
| `wiki/toolkit.py` | modifies | `remember()` (and note/link writers) stamp `updated_at` |
| `wiki/federation.py` | depends on | opens namespaces from the *effective* config; `NamespaceSkip` machinery reused for offline local mode |
| `wiki/mcp_server.py`, `wiki/claude_code/hook.py`, `wiki/claude_code/installer.py`, `wiki/claude_code/cli.py` | modifies | swap `load_project_config` → `load_effective_config` (env from process environment only) |
| `wiki/bookkeeper.py` | uses | `SYNC_PUSH`/`SYNC_PULL` operation logging via existing `log_operation` |
| `.parrot/wiki.json` (this repo) | modifies | base keeps team dev Arango; **commit** `.parrot/wiki.local.json` = `{"backend": "sqlite"}` |
| `docs/runbooks/jira-issues-namespace.md` + wiki docs | modifies | document env model + sync workflow |

### Data Models

```python
# wiki/project.py — NEW (names normative, bodies illustrative)

class WikiEnvOverlay(BaseModel):
    """Partial WikiProjectConfig: every field optional.

    Only non-secret values are permitted (backend, storage_dir,
    arango_database, arango_credentials_env, arango_text_analyzer,
    namespaces, ...). Unknown keys are rejected (fail loud).
    """
    backend: Literal["sqlite", "memory", "arangodb"] | None = None
    storage_dir: str | None = None
    arango_database: str | None = None
    arango_credentials_env: str | None = None
    arango_text_analyzer: str | None = None
    namespaces: dict[str, WikiNamespaceConfig] | None = None
    # (subset of WikiProjectConfig — NO password/host/port fields, ever)

class WikiEffectiveConfig(BaseModel):
    """Merged view + provenance. Field-compatible with WikiProjectConfig."""
    config: WikiProjectConfig          # the merged result
    env: str                           # "local" | "dev" | "prod" | ...
    overlay_path: Path | None          # None => base fallback

# wiki/store.py — MODIFIED
class WikiPageRecord(BaseModel):
    ...                                # existing fields unchanged
    updated_at: str | None = None      # ISO-8601 UTC; None (legacy) sorts oldest

# wiki/sync.py — NEW
class SyncReport(BaseModel):
    direction: Literal["push", "pull"]
    env: str
    created: int
    updated: int
    skipped_older: int
    skipped_own: int                   # pull only (author filter)
    dry_run: bool
```

### New Public Interfaces

```python
# wiki/project.py
def resolve_wiki_env(env: str | None = None) -> str:
    """WIKI_ENV > ENV > 'local'; validates against the namespace charset rule."""

def load_effective_config(root: Path, env: str | None = None) -> WikiEffectiveConfig:
    """Base wiki.json + optional .parrot/wiki.{env}.json overlay, merged."""

def overlay_path(root: Path, env: str) -> Path:
    """root/.parrot/wiki.{env}.json"""

def derive_env_overlay(base: WikiProjectConfig, env: str) -> WikiEnvOverlay:
    """local -> sqlite; other envs -> base Arango settings verbatim."""

def save_env_overlay(root: Path, env: str, overlay: WikiEnvOverlay) -> Path:
    """Atomic write (tmp + os.replace), same pattern as save_global_registry."""

# wiki/sync.py
async def sync_push(root: Path, *, target_env: str = "dev", dry_run: bool = False) -> SyncReport: ...
async def sync_pull(root: Path, *, target_env: str = "dev", include_own: bool = False, dry_run: bool = False) -> SyncReport: ...
```

```
# CLI (wikitoolkit)
wikitoolkit sync push [--env dev] [--dry-run]
wikitoolkit sync pull [--env dev] [--dry-run] [--all]
wikitoolkit status          # gains env header (env, overlay, backend, database, reachable)
wikitoolkit build           # gains overlay auto-generation for the active env
```

---

## 3. Module Breakdown

### Module 1: Env resolution + overlay model + effective config
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/project.py`
- **Responsibility**: `resolve_wiki_env()`, `WikiEnvOverlay`,
  `WikiEffectiveConfig`, `load_effective_config()`, `overlay_path()`,
  `derive_env_overlay()`, `save_env_overlay()`. Shallow merge semantics
  (per-key for `namespaces`); fail-loud `WikiConfigError` naming the overlay
  file on invalid JSON/schema. MUST stay hook-safe: stdlib + pydantic only,
  navconfig only via the existing lazy `_navconfig()`.
- **Depends on**: existing `WikiProjectConfig` / `load_project_config`.

### Module 2: CLI plumbing — precedence, build generation, status header
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py`
- **Responsibility**: route `_resolve_project` / `_open_store` /
  `_resolve_read_store` / `_resolve_write_store` through
  `load_effective_config`; apply the single precedence rule
  (flag > env > base) including in `build` (remove the `cli.py:352` TODO);
  `build` generates a missing overlay for the active env (prints what it
  generated; never clobbers); `status` env header incl. reachability.
- **Depends on**: Module 1.

### Module 3: Call-site migration (MCP server, Claude hook, installer, federation)
- **Path**: `wiki/mcp_server.py`, `wiki/claude_code/hook.py`,
  `wiki/claude_code/installer.py`, `wiki/claude_code/cli.py`,
  `wiki/federation.py`
- **Responsibility**: swap the remaining `load_project_config()` call sites
  to `load_effective_config()` (env from process environment only — no
  prompts, no file generation in these paths). Federation opens namespaces
  from the effective config; verify `NamespaceSkip` degradation covers the
  offline-local scenario with a bounded connect timeout.
- **Depends on**: Module 1.

### Module 4: `updated_at` schema delta
- **Path**: `wiki/store.py`, `wiki/arango_store.py`, `wiki/toolkit.py`
- **Responsibility**: add `updated_at: str | None` to `WikiPageRecord`;
  persist/return it in the sqlite and Arango backends (additive column /
  attribute — legacy rows read as `None` and sort oldest); authoring
  surfaces (`remember()`, note and link writers) stamp ISO-8601 UTC now.
- **Depends on**: none (parallel-safe with Modules 1–3 in principle, but
  sequential per Worktree Strategy).

### Module 5: Sync engine + CLI group
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/sync.py` (new),
  `wiki/cli.py` (sync command group)
- **Responsibility**: `sync_push` / `sync_pull` — open local plane (env
  `local`) and remote plane (target env's effective config +
  `resolve_arango_params` under that env's credentials); select pages with
  `origin="memory"` (and authored notes) + `asserted` edges touching them;
  LWW by `concept_id` + `updated_at` (equal/older → skip); pull filters out
  local-identity `asserted_by` unless `--all`; notes merged append-if-absent
  (identity hash author+date+text, date-ordered union, bodies never
  rewritten); `--dry-run`; bookkeeper `SYNC_PUSH`/`SYNC_PULL` per applied
  change; per-category summary output.
- **Depends on**: Modules 1, 4.

### Module 6: Repo config, docs, end-to-end tests
- **Path**: `.parrot/wiki.local.json` (new, committed), wiki docs +
  `docs/runbooks/jira-issues-namespace.md`, `tests/knowledge/wiki/`
- **Responsibility**: commit `{"backend": "sqlite"}` local overlay for this
  repo; document the env model (incl. the plane-vs-credentials divergence
  for unset `ENV`) and the sync workflow; end-to-end tests for env
  resolution, overlay generation, precedence, and a two-plane sync
  round-trip.
- **Depends on**: Modules 1–5.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_resolve_wiki_env_precedence` | 1 | `WIKI_ENV` > `ENV` > `"local"`; invalid charset rejected |
| `test_effective_config_no_overlay_is_base` | 1 | missing overlay → base config, `overlay_path=None` |
| `test_effective_config_overlay_merges_shallow` | 1 | overlay keys win; unset overlay keys inherit base; `namespaces` merges per-key |
| `test_effective_config_invalid_overlay_fails_loud` | 1 | bad JSON/schema → `WikiConfigError` naming the overlay file (no silent base fallback) |
| `test_overlay_rejects_secret_like_keys` | 1 | unknown/secret keys (e.g. `password`) rejected by the partial model |
| `test_derive_env_overlay_local_is_sqlite` | 1 | `local` template = `{"backend": "sqlite"}` |
| `test_derive_env_overlay_other_env_mirrors_base` | 1 | non-local template = base Arango settings verbatim (same database name) |
| `test_save_env_overlay_atomic_and_never_clobbers` | 1/2 | atomic write; build path skips generation when file exists |
| `test_open_store_precedence_flag_env_base` | 2 | `--backend` flag > overlay/`WIKI_STORE_BACKEND` > base, incl. `build` |
| `test_build_generates_missing_overlay` | 2 | `ENV=prod build` with no overlay writes `wiki.prod.json` and reports it |
| `test_read_commands_never_generate_overlay` | 2 | `ENV=prod query` with no overlay → base fallback, no file written |
| `test_status_env_header` | 2 | shows env, overlay-or-base, backend, database |
| `test_hook_and_mcp_use_effective_config` | 3 | hook/MCP resolve env from process env; no prompts/writes |
| `test_page_record_updated_at_roundtrip` | 4 | stamp persisted and returned by sqlite + Arango stores; legacy `None` sorts oldest |
| `test_remember_stamps_updated_at` | 4 | authoring surfaces set ISO-8601 UTC |
| `test_sync_push_selects_only_authored_knowledge` | 5 | memory pages + notes + asserted edges; repo-scan pages excluded |
| `test_sync_lww_skips_equal_or_older` | 5 | older/equal `updated_at` → skipped_older |
| `test_sync_pull_excludes_own_authored_by_default` | 5 | local-identity records skipped_own; `--all` includes them |
| `test_sync_notes_append_if_absent` | 5 | two-sided note additions union (date-ordered), no note dropped |
| `test_sync_dry_run_applies_nothing` | 5 | dry-run reports but writes nothing; no bookkeeper entries |
| `test_sync_unreachable_remote_clean_error` | 5 | error names host/env; no partial unlogged writes |

### Integration Tests

| Test | Description |
|---|---|
| `test_e2e_local_default_no_arango` | no `ENV`, committed local overlay → sqlite plane opens; queries work fully offline |
| `test_e2e_offline_namespace_skip` | local mode + unreachable Arango namespace → `NamespaceSkip` note, local results still returned, bounded timeout |
| `test_e2e_env_prod_build_generates_and_uses_overlay` | `ENV=prod build` creates `wiki.prod.json` (base Arango settings verbatim) and builds against it |
| `test_e2e_sync_roundtrip_two_planes` | remember on local sqlite → `sync push` to an Arango (or fake remote) plane → mutate remote → `sync pull` back; LWW + author filter + note union all observed |
| `test_e2e_backward_compat_no_overlays` | repo with only base `wiki.json` (arangodb) + explicit `WIKI_ENV=dev` behaves exactly as before the feature |

### Test Data / Fixtures

```python
@pytest.fixture
def repo_with_overlays(tmp_path, monkeypatch):
    """Repo root with base wiki.json (arangodb) + wiki.local.json (sqlite).

    monkeypatch clears WIKI_ENV/ENV; PARROT_HOME redirected under tmp_path
    (parrot_home() reads it per-call — safe to monkeypatch).
    """

@pytest.fixture
def two_planes(tmp_path):
    """A local sqlite store and a second store acting as 'remote' for sync
    tests (sqlite or memory backend standing in for Arango — the sync engine
    talks BaseWikiStore APIs, not raw Arango)."""
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `wikitoolkit query`/`page`/`related`/`status` with no `ENV` exported use
  the local sqlite plane — no ArangoDB connection attempted for the primary
  plane, fully functional off-VPN.
- [ ] Env resolution is exactly `WIKI_ENV` > `ENV` > `"local"`, values
  validated against the namespace charset rule.
- [ ] Missing overlay → read commands fall back to base silently; `status`
  shows `base (no overlay)`.
- [ ] `wikitoolkit build` under `ENV=x` generates a missing
  `.parrot/wiki.x.json` via env-templated derivation (`local` → sqlite;
  others → base Arango settings verbatim, **same database name**) and never
  clobbers an existing overlay.
- [ ] Overlays carry no secrets: the partial model has no credential fields
  and rejects unknown keys; credentials resolve only via navconfig
  `env/{ENV}/.env` (`resolve_arango_params` unchanged in contract).
- [ ] One precedence rule — `--backend` flag > environment > base — holds in
  `build`, `_open_store`, `_resolve_read_store`, `_resolve_write_store`; the
  `cli.py:352` TODO is removed.
- [ ] All 11 `load_project_config()` consumer call sites route through
  `load_effective_config()` (raw base access remains only for save paths /
  `ns add`).
- [ ] In local mode an unreachable shared namespace degrades gracefully:
  skipped with the existing one-line note, bounded connect timeout, local
  results still returned.
- [ ] Invalid overlay JSON/schema raises `WikiConfigError` naming the overlay
  file — never a silent fallback.
- [ ] `WikiPageRecord.updated_at` persisted and returned by sqlite + Arango
  backends; authoring surfaces stamp it; legacy rows (`None`) sort oldest.
- [ ] `wikitoolkit sync push` moves memory pages, attributed notes, and
  `asserted` edges to the target env's plane (default `dev`); repo-scan pages
  are never synced.
- [ ] `wikitoolkit sync pull` excludes records with the local identity's
  `asserted_by` by default; `--all` switches to pure LWW.
- [ ] Sync conflict rule: last-write-wins by `updated_at` per record; notes
  merge append-if-absent (no note ever dropped); deletes NOT propagated
  (documented).
- [ ] Both sync directions support `--dry-run`, log applied changes to the
  bookkeeper (`SYNC_PUSH`/`SYNC_PULL`), and print created / updated /
  skipped-older / skipped-own counts.
- [ ] `.parrot/wiki.local.json` (`{"backend": "sqlite"}`) is committed in this
  repo.
- [ ] Backwards compatible: a repo with only `.parrot/wiki.json` and no
  overlays behaves exactly as today (given the equivalent env selection).
- [ ] `project.py` remains hook-safe: no module-scope navconfig/store imports
  added.
- [ ] Docs updated (env model incl. plane-vs-credentials divergence; sync
  workflow).
- [ ] All unit + integration tests above pass (`pytest tests/knowledge/wiki/ -v`).
- [ ] No breaking changes to existing public API.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.
> All references below re-verified 2026-08-25 on `dev`.

### Verified Imports

```python
# Confirmed working (used at the listed call sites):
from parrot.knowledge.wiki.project import (
    load_project_config,        # federation.py:228, claude_code/cli.py:95,
                                # claude_code/hook.py:186,
                                # claude_code/installer.py:494 & 670,
                                # mcp_server.py:108 & 214,
                                # cli.py:290, 337, 1784
    resolve_arango_params,      # cli.py:381 (lazy, inside _open_store)
)
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/project.py
PARROT_DIR = ".parrot"                      # line 34
CONFIG_FILENAME = "wiki.json"               # line 37

class WikiNamespaceConfig(BaseModel):       # ~line 195-235 (FEAT-450)
    credentials_env: str                    # line 224, default "ARANGODB"

class WikiProjectConfig(BaseModel):         # line 295
    wiki_name: str                          # line 325, default "codebase"
    storage_dir: str                        # line 326, default ".parrot/wiki"
    backend: Literal["sqlite", "memory", "arangodb"]  # line 327, default "sqlite"
    sync_graph: bool                        # line 335
    arango_database: str | None             # line 336
    arango_credentials_env: str             # line 340, default "ARANGODB"
    arango_text_analyzer: str               # line 347
    vault_dir: str | None                   # line 351
    namespaces: dict[str, WikiNamespaceConfig]  # (FEAT-450)

def config_path(root: Path) -> Path        # line 546  → root/.parrot/wiki.json
def find_project_root(start: Path | None = None) -> Path | None  # line 551
class WikiConfigError(ValueError)           # line 574
def load_project_config(root: Path) -> WikiProjectConfig  # line 578
    # missing file → defaults; invalid file → WikiConfigError (fail loud)
def save_project_config(root: Path, config: WikiProjectConfig) -> Path  # line 605
def parrot_home() -> Path                   # line 624 (PARROT_HOME override, read per-call)
def global_registry_path() -> Path          # line 639
def load_global_registry(path: Path | None = None) -> GlobalWikiRegistry  # line 644
def merge_namespaces(...)                   # line 707 (repo wins over global)
# _env_credential(key, default): os.environ FIRST, then lazy navconfig  # lines 440-464
def resolve_arango_params(config: WikiProjectConfig) -> dict[str, Any]  # line 467
    # returns host/port/protocol/username/password/database from
    # {config.arango_credentials_env}_* vars; database falls back to
    # f"wiki_{config.wiki_name}"                                # lines 489-497
```

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py
def _resolve_project(path: str | None) -> tuple[Path, WikiProjectConfig]  # line 321
def _open_store(root: Path, config: WikiProjectConfig) -> BaseWikiStore   # line 349
    # carries TODO(follow-up) at line 352: "let the navconfig environment
    # pick the backend" + notes WIKI_STORE_BACKEND inconsistency and the
    # target precedence: --backend flag > environment > wiki.json (line 371)
def _env_setting(name: str) -> str | None   # lines 435-450
    # navconfig-first read of WIKI_STORE / WIKI_STORE_BACKEND
def _resolve_read_store(...)                # line 453
    # honours WIKI_STORE_BACKEND at lines 499, 2250 (write twin at 2248-2250)
def _collect_skips(store) -> list[NamespaceSkip]  # ~line 300
def _echo_skips(store, *, err: bool = False)      # line 309
    # prints "(namespace 'x' skipped: reason — hint)" — reuse for offline mode
# build command: --backend option at lines 1075-1078; applied at 1142-1143
```

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/store.py:215
class WikiPageRecord(BaseModel):
    concept_id: str          # line 234 (primary key)
    node_id: Optional[str]   # line 235
    title: str               # line 236
    category: str            # line 237
    summary: str             # line 238
    body: str                # line 239
    source_id: Optional[str] # line 240
    token_count: int         # line 241
    origin: str              # line 242 — "ingest" | "authored" | "memory"
    asserted_by: Optional[str]  # line 243 — "agent:<id>" / "human:<user>"
    # NOTE: NO timestamp fields — see Does NOT Exist
```

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py:944
async def remember(self, wiki_name, text, title=None, category="note",
                   related_pages=None) -> dict[str, Any]:
    # page_id = "mem-" + sha1(f"{title}::{category}")[:12]  (deterministic)
    # writes WikiPageRecord(origin="memory", asserted_by=f"agent:{self.agent_id}")
    # related pages → add_edges([(page_id, rp, "references", "asserted")])
    # bookkeeper.log_operation(storage_dir, "REMEMBER", ...)
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `load_effective_config()` | `load_project_config()` | wraps + merges overlay | `project.py:578` |
| `load_effective_config()` | 11 consumer call sites | drop-in replacement | see Verified Imports |
| `derive_env_overlay()` / `save_env_overlay()` | `build` command | called when overlay missing | `cli.py:1075-1143` (build) |
| store resolution precedence | `_open_store` / `_resolve_read_store` / write twin | effective config + `_env_setting` | `cli.py:349, 453, 499, 2248-2250` |
| sync remote plane | `resolve_arango_params(config)` | per-target-env credentials | `project.py:467` |
| sync record selection | `WikiPageRecord.origin == "memory"` / `asserted_by` | store query APIs (`upsert_pages`, `add_edges`) | `store.py:242-243`, `toolkit.py:944` |
| sync audit | `bookkeeper.log_operation` | `SYNC_PUSH` / `SYNC_PULL` ops | `toolkit.py` remember body (usage pattern) |
| offline namespace degradation | `NamespaceSkip` + `_collect_skips`/`_echo_skips` | existing skip path | `cli.py:300-318` |

### Key Attributes & Constants

- `WikiProjectConfig.backend` → `Literal["sqlite","memory","arangodb"]` (project.py:327)
- `WikiProjectConfig.arango_credentials_env` → `str`, default `"ARANGODB"` (project.py:340)
- Env-var precedence contract: `os.environ` wins over navconfig
  (project.py:441-444) — an exported `ENV`/`WIKI_ENV` always beats file values
- `.parrot/wiki.json` in THIS repo currently: `backend="arangodb"`,
  `arango_database="wiki_ai-parrot"` (the dev server), `namespaces={}`
- 11 `load_project_config()` call sites total (see Verified Imports) — the
  complete migration surface for `load_effective_config`

### Does NOT Exist (Anti-Hallucination)

- ~~`WikiPageRecord.updated_at` / `created_at`~~ — the record model has NO
  timestamp fields (store.py:215-243). Module 4 adds `updated_at`; do not
  assume backends already return it.
- ~~`wikitoolkit sync`~~ — no sync command, module, or `wiki/sync.py` exists.
- ~~`.parrot/wiki.{env}.json` overlays / `environments:` key / `WIKI_ENV`~~ —
  no env awareness anywhere in the wiki config layer today; only the partial
  `WIKI_STORE` / `WIKI_STORE_BACKEND` support in `_resolve_read_store` /
  `_resolve_write_store` (and `build` ignores even that — cli.py:367-370).
- ~~`load_effective_config` / `resolve_wiki_env` / `derive_env_overlay` /
  `WikiEnvOverlay` / `WikiEffectiveConfig` / `SyncReport`~~ — created by
  this feature.
- ~~navconfig import at `project.py` module scope~~ — navconfig is only
  lazily imported inside `_navconfig()` (hook-safety discipline; keep it so).

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Hook safety**: `project.py` is imported by the Claude Code PreToolUse
  hook — stdlib + pydantic only at module scope; navconfig only via the
  existing lazy `_navconfig()` (TASK-2359 discipline).
- **Atomic writes**: `save_env_overlay` uses the tmp-file + `os.replace`
  pattern of `save_global_registry` (project.py:~644ff).
- **Fail loud on bad config**: mirror `load_project_config`'s contract —
  invalid overlay raises `WikiConfigError` naming the file; never silently
  substitute defaults (a typo must not silently retarget prod to dev).
- **Per-call env reads**: read `WIKI_ENV`/`ENV` on every call (like
  `parrot_home()`, project.py:624) so tests can `monkeypatch.setenv`.
- **Sync talks `BaseWikiStore` APIs** (`upsert_pages`, `add_edges`,
  page queries) — never raw Arango/sqlite, so tests can fake the remote with
  a sqlite/memory store.
- Google-style docstrings + strict type hints; async/await throughout the
  sync engine; `self.logger`/module logger, no prints (click.echo for CLI UX).

### Known Risks / Gotchas

- **Missed call-site = silent base config.** The choke-point migration must
  cover all 11 sites; the acceptance criterion pins this, and a grep for
  remaining consumer `load_project_config(` calls should gate `/sdd-done`.
- **`ENV` unset divergence**: plane selection says `local` while navconfig
  credential loading still reads `env/.env` (dev). This is by design
  (resolved in brainstorm) but MUST be documented prominently — shared
  namespaces in local mode still use dev credentials.
- **Sync id collision**: two devs remembering the same title+category produce
  the same deterministic `mem-*` id — LWW by `updated_at`; loser recoverable
  from the audit trail. Clock skew is accepted risk in v1 (author filter on
  pull mitigates the worst case: your own records can't be overwritten by
  default).
- **Deletes not propagated** (no tombstones in v1) — a memory deleted locally
  reappears on the next `pull` if it still exists remotely. Document.
- **Overlay generation never clobbers**; generation happens only in `build`,
  read paths never write. Guard with tests.
- **Bounded offline timeouts**: local-mode queries with unreachable shared
  namespaces must stay fast — reuse/verify the federation skip path's connect
  timeout rather than inheriting driver defaults.
- **`build --backend` flag interaction**: an explicit flag wins over overlay;
  ensure the generated overlay records the *effective* choice only when the
  user didn't pass a flag (avoid freezing a one-off flag into the overlay).
- **Arango schema is additive**: `updated_at` lands as a new document
  attribute (Arango is schemaless) and a new sqlite column with `ALTER TABLE
  ... ADD COLUMN` (nullable) — no destructive migration.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| — (none new) | — | navconfig, pydantic v2, click, asyncdb already in the dependency set |

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` — all tasks sequential in ONE
  worktree (`.claude/worktrees/feat-461-wikitoolkit-env-support`).
- **Rationale**: Modules 1–3 and 5 all touch `cli.py` and `project.py`
  (the two hottest files); Module 4 touches `store.py`/`toolkit.py` that
  Module 5 then consumes. Parallel worktrees would conflict near-certainly;
  sequential order (M1 → M2 → M3 → M4 → M5 → M6) is cheaper than conflict
  resolution.
- **Cross-feature dependencies**: builds on FEAT-450 (wiki namespaces —
  merged). No in-flight spec known to touch `wiki/project.py` or
  `wiki/cli.py`; re-verify against `sdd/tasks/index/*.json` at `/sdd-task`
  time.

---

## 8. Open Questions

> All brainstorm questions were resolved before this spec was written; they
> are echoed here for the audit trail.

- [x] Gitignore policy for `.parrot/wiki.local.json` — *Resolved in
  brainstorm*: COMMIT it (`{"backend": "sqlite"}`) so every teammate gets the
  no-VPN sqlite default; `wiki.prod.json` also committed and reviewed.
- [x] Derived database naming for generated overlays — *Resolved in
  brainstorm*: SAME database name in every env (`wiki_ai-parrot`);
  separation comes from the per-`ENV` server/credentials, not the name. No
  `_prod` suffixing.
- [x] `sync pull` scope — *Resolved in brainstorm*: exclude records authored
  by the local identity by default; `--all` overrides to pure LWW.
- [x] `ENV=dev` writes to the shared dev ArangoDB — *Resolved in brainstorm*:
  keep it — full read-write plane from any machine; sole-writer discipline is
  social, not enforced.
- [x] Note-sync fidelity — *Resolved in brainstorm*: append-if-absent — notes
  are an append-only set keyed by identity hash (author + date + text);
  missing notes added date-ordered; bodies never rewritten.
- [x] Sync direction model — *Resolved in brainstorm*: explicit `sync push` /
  `sync pull` subcommands, deterministic direction, LWW per record.
- [x] Sync content — *Resolved in brainstorm*: memories + notes/asserted
  links; NOT full repo-scan pages.
- [x] Default env with no `ENV` — *Resolved in brainstorm*: `local` (sqlite
  plane, no VPN); shared namespaces degrade gracefully.
- [x] Secrets placement — *Resolved in brainstorm*: only navconfig
  `env/{ENV}/.env`; overlays carry non-secret values only.
- [x] Missing overlay behavior — *Resolved in brainstorm*: read commands fall
  back to base; `build` generates the overlay via env-templated derivation.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-25 | Jesus (with Claude) | Initial draft from brainstorm (Option A, all questions resolved) |
