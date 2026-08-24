---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: wikitoolkit Environment Support (env-aware config + memory sync)

**Date**: 2026-08-25
**Author**: Jesus (with Claude)
**Status**: exploration
**Recommended Option**: A

---

## Problem Statement

`wikitoolkit` reads a single, hardcoded `.parrot/wiki.json`: one `backend`
(currently `arangodb`), one `arango_database` (`wiki_ai-parrot`, the **dev**
server), one credentials prefix. Meanwhile the rest of the repo is
environment-aware through **navconfig**: `ENV=prod wikitoolkit build` makes
navconfig load `env/prod/.env`, and no `ENV` loads `env/.env` (dev
credentials). The wiki config ignores this entirely, which produces concrete
pain:

- **Local development requires a VPN.** With `wiki.json` pinned to the dev
  ArangoDB, launching Claude Code offline (or off-VPN) strands every
  `wikitoolkit query` — the desired behavior is a **local sqlite plane** for
  the repo's own wiki, with only the *shared* team-KB namespaces reaching the
  cloud dev ArangoDB (and skipping gracefully when unreachable).
- **Credentials and plane selection are conflated.** navconfig already
  switches credentials per `ENV`, but the *backend/database choice* cannot
  follow it, so `ENV=prod wikitoolkit build` still writes to the dev database.
- **Local knowledge is trapped.** Memories, notes, and asserted links written
  on a local sqlite plane never reach the team's shared ArangoDB KB — there is
  no sync mechanism in either direction.

Affected: every developer running `wikitoolkit` / the Claude Code wiki hook /
the wiki MCP server locally, and the team sharing the cloud KB.

The `_open_store` docstring already carries a `TODO(follow-up)` describing
exactly this gap (`cli.py:352-377`), including the existing inconsistency that
`WIKI_STORE_BACKEND` is honoured by `_resolve_read_store` but ignored by
`build`.

## Constraints & Requirements

- **No secrets in JSON config.** Overlays hold only non-secret values
  (backend, database name, `credentials_env` prefix). Host/user/password
  always resolve via navconfig from `env/{ENV}/.env` — confirmed decision.
- **Default (no `ENV`) = local**: sqlite plane for the repo wiki, no VPN
  required; shared namespaces degrade gracefully (skip + one-line warning,
  short connect timeout) — confirmed decision.
- **Missing overlay falls back to base** `wiki.json`; `wikitoolkit build`
  under `ENV=x` auto-generates the missing overlay using **env-templated
  derivation** (not a blind clone of base) — confirmed decision.
- **Sync is in scope for v1**: explicit `wikitoolkit sync push` / `sync pull`
  subcommands, moving **memories** (remember/decisions/lessons) and **notes +
  asserted links** — NOT full repo-scan pages (remote can rebuild those) —
  confirmed decision.
- `project.py` is imported by the Claude Code PreToolUse hook and must stay
  lightweight (stdlib + pydantic; navconfig only via the existing lazy
  `_navconfig()` import — see TASK-2359 discipline).
- Backwards compatible: an existing `.parrot/wiki.json` with no overlays keeps
  working exactly as today.
- One precedence rule everywhere (per the `cli.py:352` TODO):
  `--backend` flag > environment (overlay / `WIKI_STORE_BACKEND`) > base
  `wiki.json` — applied consistently to `build`, `_open_store`,
  `_resolve_read_store`, and `_resolve_write_store`.

---

## Options Explored

### Option A: Per-environment overlay files (`.parrot/wiki.{env}.json`) + `sync push/pull`

Keep `.parrot/wiki.json` as the committed base. Add optional overlay files
`.parrot/wiki.local.json`, `.parrot/wiki.dev.json`, `.parrot/wiki.prod.json`
that are shallow-merged **on top of** the base at load time. The effective
environment name is resolved as: `WIKI_ENV` (explicit escape hatch) →
`ENV` (navconfig's own selector) → `"local"` when neither is set. A new
env-aware loader wraps `load_project_config()`; all call sites (CLI, MCP
server, Claude hook, installer, federation) go through it.

- Missing overlay → effective config **is** the base (never an error).
- `wikitoolkit build` generates the missing overlay for the active env using
  templated derivation: `local` → `{"backend": "sqlite"}`; `dev` → mirrors the
  base Arango settings; `prod` (and other named envs) → base Arango settings
  with the database name suffixed (`wiki_ai-parrot_prod`), `credentials_env`
  unchanged (navconfig already resolves different credentials per `ENV`).
- `status` prints the active env, the overlay file used (or "base fallback"),
  and the resolved backend/database.
- New `wikitoolkit sync push|pull` copies authored knowledge (pages with
  `origin="memory"`, attributed notes, `asserted` edges) between the local
  sqlite plane and the shared ArangoDB plane (target resolved from a named
  env's overlay, default `dev`), last-write-wins per page via a new
  `updated_at` stamp.

✅ **Pros:**
- Matches the user's chosen model exactly (fallback-to-base + build-time
  generation came from discovery answers).
- Committed base stays canonical for the team; `wiki.local.json` can be
  gitignored for personal setups while `wiki.prod.json` is committed and
  reviewed.
- Diffable, explicit files — easy to answer "what does prod use?" without
  running anything.
- Zero migration: repos without overlays behave exactly as today.

❌ **Cons:**
- Up to four config files to keep coherent; auto-generation mitigates but
  drift between overlays is possible.
- A second resolution layer (env → overlay → merge) that every tool/hook/MCP
  entry point must consistently use — a missed call site silently uses the
  base.
- "No `ENV` ⇒ local" intentionally diverges from navconfig's "no `ENV` ⇒
  `env/.env` (dev)" convention for *credentials*; must be clearly documented
  (plane selection ≠ credential selection).

📊 **Effort:** Medium (config layer: Low-Medium; sync v1: Medium)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `navconfig` | Loads `env/{ENV}/.env`; credential source of truth | already a dependency; lazily imported in `project.py` |
| `pydantic` v2 | Overlay model + `model_copy(update=...)` merge | already the config layer's base |
| `click` | New `sync` command group, `--env` option | CLI already click-based |
| `asyncdb` (`arangodb` driver) | Remote plane connection for sync | already used by `ArangoDBWikiStore` |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/knowledge/wiki/project.py` — `WikiProjectConfig`, `load_project_config()`, `resolve_arango_params()`, `_env_credential()` (os.environ > navconfig precedence already implemented)
- `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` — `_open_store()` (the TODO site), `_resolve_read_store()` / `_env_setting()` (`WIKI_STORE_BACKEND` plumbing), `_collect_skips()` / `_echo_skips()` (graceful namespace-skip UX)
- `packages/ai-parrot/src/parrot/knowledge/wiki/federation.py` — namespace store opening + skip machinery (the "degrade gracefully offline" behavior largely exists here for namespaces)
- `packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py` — `remember()` (deterministic `mem-*` ids, `origin="memory"`, `asserted_by`) defines exactly the record set `sync` must move
- `packages/ai-parrot/src/parrot/knowledge/wiki/bookkeeper.py` — audited operation log; `sync` operations must be logged the same way

---

### Option B: `environments:` block inside the single `wiki.json`

One committed `.parrot/wiki.json` grows an `environments: {local: {...},
dev: {...}, prod: {...}}` section; base keys remain shared defaults; the
active env's sub-object overrides them. Same env-name resolution and same
sync subsystem as Option A.

✅ **Pros:**
- Single file — no overlay-drift, one place to read the whole matrix.
- Same schema/merge code as A internally (an env sub-model), slightly less
  file-handling code.

❌ **Cons:**
- Cannot gitignore just the local section — personal local tweaks (e.g. a
  different sqlite path) force edits to the committed file.
- The user's discovery answers (missing-file fallback, build-time overlay
  generation) presuppose per-file overlays; this shape answers those
  questions differently than the user chose.
- Noisier diffs: prod changes and local changes land in the same file.

📊 **Effort:** Medium (marginally lower than A)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic` v2 | Nested env sub-models | same as A |
| `navconfig` | Credential resolution | same as A |

🔗 **Existing Code to Reuse:** same set as Option A.

---

### Option C: Pure navconfig — `WIKI_*` keys in `env/{ENV}/.env`, minimal `wiki.json`

Remove backend/database values from JSON entirely. `wiki.json` keeps only
identity + scan settings; plane selection comes from navconfig keys
(`WIKI_STORE_BACKEND`, `WIKI_ARANGO_DATABASE`, …) defined per environment in
`env/.env`, `env/prod/.env`, etc. This generalizes the existing (partial)
`WIKI_STORE_BACKEND` support in `_resolve_read_store`.

✅ **Pros:**
- One mechanism for everything env-shaped: exactly how the rest of the repo
  handles per-env values; the smallest conceptual footprint.
- No new files, no merge logic — `_env_setting()` already implements the
  lookup pattern.

❌ **Cons:**
- `env/*/.env` files are (correctly) untracked/secret-adjacent — putting
  *structural* config there makes the wiki's shape invisible in the repo and
  hard to review; a fresh clone has no discoverable wiki config.
- No natural place for the "generate missing env config at build time"
  behavior the user asked for.
- The Claude hook / MCP server would depend on navconfig being importable to
  know even the backend (today the hook path deliberately minimizes imports).

📊 **Effort:** Low-Medium (config); sync effort unchanged.

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `navconfig` | Sole source of env values | becomes load-bearing for the hook path |

🔗 **Existing Code to Reuse:** `_env_setting()` (`cli.py:435-450`), `_env_credential()` (`project.py:440-464`), plus the same store/sync surfaces as A.

---

### Option D (unconventional): Environments as federation namespaces

Reuse FEAT-450 federation instead of adding a config layer: the local sqlite
plane is always the primary store; the shared dev/prod ArangoDB planes are
registered as **namespaces** (`team-dev`, `team-prod`) in
`.parrot/wiki.json` / `~/.parrot/wikis.json`. `ENV` only flips which
namespace is treated as the *write-through* target; `sync` becomes a
cross-namespace copy inside the already-existing `FederatedWikiStore`.

✅ **Pros:**
- Almost no new machinery: namespace declaration (`WikiNamespaceConfig`
  already supports `backend`, `database`, `credentials_env`), federated
  reads, and graceful skips all exist today.
- "Local plane + shared KB" stops being a special case — it is just
  federation, which is the mental model the user already described.

❌ **Cons:**
- Conflates two axes: a namespace is a *different corpus*; an environment is
  the *same corpus on different infrastructure*. `ENV=prod build` writing to
  a "namespace" bends FEAT-450 semantics (namespaces are read-oriented;
  ranking, `--ns` filters, and id-qualification would all leak into what
  should be a deployment concern).
- Repo-scan pages of the same repo would exist in two namespaces with
  different qualified ids (`team-dev::file:x` vs `file:x`) — confusing
  query results.
- Doesn't remove the hardcoded base `backend` problem: something must still
  say "primary = sqlite locally, arango in prod" — an env layer sneaks back
  in anyway.

📊 **Effort:** Medium-High (semantics untangling costs more than the code saved)

📦 **Libraries / Tools:** none new.

🔗 **Existing Code to Reuse:** `federation.py` (`FederatedWikiStore`, namespace opening at line 194 passing `arango_credentials_env=cfg.credentials_env`), `project.py` `WikiNamespaceConfig` / `merge_namespaces()`.

---

## Recommendation

**Option A** is recommended because:

- It is the shape the user converged on during discovery: missing overlay →
  base fallback, and `ENV=prod wikitoolkit build` generating
  `.parrot/wiki.prod.json` via env-templated derivation were explicit
  decisions that only make sense with per-env files.
- It keeps the committed base reviewable (unlike C, where structure hides in
  untracked `.env` files) while still letting `wiki.local.json` be a
  personal, gitignored file (unlike B, where local tweaks dirty the shared
  file).
- It composes cleanly with FEAT-450 instead of bending it (unlike D):
  environments select *infrastructure for the primary plane*; namespaces
  remain *additional corpora*. Overlays may also override namespace entries
  when an env genuinely needs it.
- The cost accepted: a merge/resolution layer that every entry point must
  route through, and possible overlay drift. Mitigations: a single
  `load_effective_config(root)` choke point that all call sites are migrated
  to (there are exactly 11, all identified below), and `wikitoolkit status`
  always printing which env/overlay produced the effective config.
- Option C's `WIKI_STORE_BACKEND` unification is folded in anyway (the
  `cli.py:352` TODO asks for one precedence rule): flag > env overlay /
  `WIKI_STORE_BACKEND` > base.

---

## Feature Description

### User-Facing Behavior

- **`wikitoolkit <anything>` with no `ENV`** resolves environment `local`:
  the repo wiki opens on local sqlite (`.parrot/wiki/wiki.db`). No VPN, no
  ArangoDB. Shared namespaces (e.g. `issues`, team KB) still point wherever
  they point; if unreachable, each is skipped with the existing one-line
  `(namespace 'x' skipped: ...)` note and a short connect timeout.
- **`ENV=prod wikitoolkit build`**: navconfig loads `env/prod/.env`
  (credentials), the wiki layer loads `.parrot/wiki.prod.json` (plane). If
  the overlay does not exist, build **creates it** from the env template
  (prod → arango, database `wiki_{wiki_name}_prod`, same `credentials_env`),
  prints what it generated, then builds against it. `ENV=dev` behaves the
  same with the dev template (mirrors base Arango settings). Read-only
  commands never generate files — they fall back to base silently.
- **`WIKI_ENV=prod`** overrides `ENV` for the wiki layer only (escape hatch
  when navconfig env and wiki plane must differ).
- **`wikitoolkit status`** gains an environment header: active env, overlay
  file used (or `base (no overlay)`), resolved backend + database, and
  whether the plane is reachable.
- **`wikitoolkit sync push [--env dev] [--dry-run]`** uploads local authored
  knowledge — memory pages (`origin="memory"`), attributed notes, and
  `asserted` edges — to the shared plane of the named env (default `dev`).
  **`wikitoolkit sync pull [--env dev] [--dry-run]`** downloads the same
  record classes from the shared plane into the local sqlite plane. Both
  print a per-category summary (created / updated / skipped-older) and log
  to the bookkeeper audit trail.
- Existing repos with only `.parrot/wiki.json` and no overlays: behavior is
  unchanged until an overlay exists (except that unset `ENV` now means the
  *local* overlay is looked up first — for this repo that overlay will be
  committed as sqlite, delivering the no-VPN default).

### Internal Behavior

- **Env resolution** (new, in `project.py`, stdlib-only):
  `resolve_wiki_env() -> str` = `WIKI_ENV` or `ENV` or `"local"`.
- **Effective config** (new choke point): `load_effective_config(root, env=None)
  -> WikiEffectiveConfig` = parse base `wiki.json` → if
  `.parrot/wiki.{env}.json` exists, validate it as a partial overlay model
  (all fields optional) → shallow-merge (`model_copy(update=...)`; the
  `namespaces` dict merges per-key, overlay entries winning) → record
  provenance (env name, overlay path or None). All 11 current
  `load_project_config()` call sites migrate to it; `load_project_config`
  itself remains for raw base access (save paths, `ns add` writes).
- **Precedence** applied uniformly in CLI store resolution: explicit
  `--backend`/`--store` flag > overlay value / `WIKI_STORE_BACKEND` > base
  `wiki.json` — `build` included (closing the `cli.py:352` TODO).
- **Overlay generation** (build only): `derive_env_overlay(base, env)`
  produces `local` → `{"backend": "sqlite"}`; `dev` → base's Arango
  settings verbatim; other envs → base Arango settings with database
  `wiki_{wiki_name}_{env}`. Written via the same atomic-write pattern as
  `save_global_registry`.
- **Sync engine** (new module, e.g. `wiki/sync.py`): opens the local plane
  (env `local`) and the remote plane (target env's overlay +
  `resolve_arango_params` under that env's credentials); selects syncable
  records — pages with `origin="memory"` (and authored notes), `asserted`
  edges touching them; compares by `concept_id` + `updated_at`
  (last-write-wins; equal/older → skip); upserts via the existing
  `upsert_pages` / `add_edges` store APIs; every applied change logged via
  `bookkeeper.log_operation` (`SYNC_PUSH` / `SYNC_PULL`).
- **Schema delta for LWW**: `WikiPageRecord` gains `updated_at`
  (ISO-8601, set by authoring surfaces like `remember()`), persisted by both
  sqlite and Arango backends; records without it (legacy rows) sort oldest.

### Edge Cases & Error Handling

- `ENV=prod` + no `wiki.prod.json` + read command → base config, no file
  written, no warning spam (status shows `base (no overlay)`).
- Invalid overlay JSON/schema → `WikiConfigError` naming the overlay file
  (same fail-loud contract as base config; never silently fall back, so a
  typo can't silently retarget prod traffic to dev).
- Overlay generation must never clobber: if the file exists, build uses it
  verbatim (generation only fills absence).
- Local mode with unreachable shared namespace → existing `NamespaceSkip`
  path (skip + hint), bounded connect timeout so queries stay fast offline.
- `sync push` with unreachable remote → clean error naming host/env; nothing
  partially applied without being audit-logged; `--dry-run` always available.
- `sync` collision on the same memory id (two devs, same title+category ⇒
  same deterministic `mem-*` hash): last-write-wins by `updated_at`;
  the loser's content is still recoverable from the audit trail. Deletes are
  NOT propagated in v1 (no tombstones) — documented limitation.
- Hook/MCP paths (`claude_code/hook.py`, `mcp_server.py`) resolve env from
  process environment only — no interactive prompts, no file generation.
- `WIKI_ENV`/`ENV` values are validated with the same charset rule as
  namespace names to keep overlay filenames safe.

---

## Capabilities

### New Capabilities
- `wiki-env-overlays`: per-environment overlay files with base fallback,
  env-templated generation at build time, uniform backend precedence, and
  env provenance in `status`.
- `wiki-memory-sync`: explicit `sync push` / `sync pull` of memories, notes,
  and asserted links between the local sqlite plane and a shared ArangoDB
  plane, last-write-wins with audit logging.

(Both land in a single spec: `sdd/specs/wikitoolkit-env-support.spec.md`.)

### Modified Capabilities
- `wiki-namespaces` (FEAT-450, `sdd/specs/wiki-namespaces.spec.md`): overlays
  may override per-namespace entries; local-mode degradation reuses and
  slightly extends the `NamespaceSkip` machinery.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `wiki/project.py` | extends | `resolve_wiki_env()`, overlay model, `load_effective_config()`, `derive_env_overlay()`; stays hook-safe (stdlib+pydantic, lazy navconfig) |
| `wiki/cli.py` | modifies | `_resolve_project`/`_open_store`/`_resolve_read_store`/`_resolve_write_store` route through effective config; `build` gains overlay generation; new `sync` group; `status` env header; closes `cli.py:352` TODO |
| `wiki/store.py` | modifies | `WikiPageRecord.updated_at`; sqlite persistence of the stamp |
| `wiki/arango_store.py` | modifies | persist/return `updated_at` |
| `wiki/sync.py` | new | push/pull engine (memories, notes, asserted edges; LWW) |
| `wiki/toolkit.py` | modifies | `remember()` (and note/link writers) stamp `updated_at` |
| `wiki/federation.py` | depends on | opens namespaces from the *effective* config; skip machinery reused for offline local mode |
| `wiki/mcp_server.py`, `wiki/claude_code/hook.py`, `wiki/claude_code/installer.py` | modifies | swap `load_project_config` → `load_effective_config` (env from process env) |
| `wiki/bookkeeper.py` | depends on | `SYNC_PUSH`/`SYNC_PULL` operation logging |
| `.parrot/wiki.json` (this repo) | modifies | add committed `wiki.local.json` (sqlite) + keep base pointing at team dev Arango; decide gitignore policy for `wiki.local.json` |
| `docs/runbooks/jira-issues-namespace.md` + wiki docs | modifies | document env model + sync workflow |

No breaking changes for repos without overlays; no new external dependencies.

---

## Code Context

### User-Provided Code

(No code snippets were provided during discovery — requirements were given as
prose; captured in Problem Statement / Constraints.)

### Verified Codebase References

#### Classes & Signatures
```python
# From packages/ai-parrot/src/parrot/knowledge/wiki/project.py
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
# From packages/ai-parrot/src/parrot/knowledge/wiki/cli.py
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
# From packages/ai-parrot/src/parrot/knowledge/wiki/store.py:215
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
# From packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py:944
async def remember(self, wiki_name, text, title=None, category="note",
                   related_pages=None) -> dict[str, Any]:
    # page_id = "mem-" + sha1(f"{title}::{category}")[:12]  (deterministic)
    # writes WikiPageRecord(origin="memory", asserted_by=f"agent:{self.agent_id}")
    # related pages → add_edges([(page_id, rp, "references", "asserted")])
    # bookkeeper.log_operation(storage_dir, "REMEMBER", ...)
```

#### Verified Imports
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

#### Key Attributes & Constants
- `WikiProjectConfig.backend` → `Literal["sqlite","memory","arangodb"]` (project.py:327)
- `WikiProjectConfig.arango_credentials_env` → `str`, default `"ARANGODB"` (project.py:340)
- Env-var precedence contract: `os.environ` wins over navconfig (project.py:441-444) — an exported `ENV`/`WIKI_ENV` always beats file values
- `.parrot/wiki.json` in THIS repo currently: `backend="arangodb"`, `arango_database="wiki_ai-parrot"` (the dev server), `namespaces={}` — the exact pain point
- 11 `load_project_config()` call sites total (see Verified Imports) — the complete migration surface for `load_effective_config`

### Does NOT Exist (Anti-Hallucination)
- ~~`WikiPageRecord.updated_at` / `created_at`~~ — the record model has NO
  timestamp fields (store.py:215-243). LWW sync requires adding one; do not
  assume backends already return it.
- ~~`wikitoolkit sync`~~ — no sync command, module, or `wiki/sync.py` exists.
- ~~`.parrot/wiki.{env}.json` overlays / `environments:` key / `WIKI_ENV`~~ —
  no env awareness anywhere in the wiki config layer today; only the partial
  `WIKI_STORE` / `WIKI_STORE_BACKEND` support in `_resolve_read_store` /
  `_resolve_write_store` (and `build` ignores even that — cli.py:367-370).
- ~~`load_effective_config` / `resolve_wiki_env` / `derive_env_overlay`~~ —
  to be created by this feature.
- ~~navconfig import in `project.py` module scope~~ — navconfig is only
  lazily imported inside `_navconfig()` (hook-safety discipline; keep it so).

---

## Parallelism Assessment

- **Internal parallelism**: Two natural lanes — (1) env-overlay config layer
  (`project.py` + call-site migration + build generation + status) and
  (2) sync engine (`updated_at` schema delta + `sync.py` + CLI group). Lane 2
  depends on lane 1 only for resolving the remote target env, and both lanes
  edit `cli.py` and `project.py`, so parallel worktrees would conflict on the
  two hottest files.
- **Cross-feature independence**: Builds directly on FEAT-450 (namespaces,
  merged) — no in-flight spec is known to touch `wiki/project.py` or
  `wiki/cli.py`. Verify against `sdd/tasks/index/*.json` at `/sdd-task` time.
- **Recommended isolation**: `per-spec` (one worktree, tasks sequential).
- **Rationale**: Shared hot files (`cli.py`, `project.py`, `store.py`) across
  both lanes make merge conflicts near-certain in parallel worktrees; the
  feature is medium-sized and sequential tasks with the config layer first is
  cheaper than conflict resolution.

---

## Open Questions

- [ ] Gitignore policy: is `.parrot/wiki.local.json` committed (team default:
  sqlite for everyone) or gitignored (personal)? Recommendation: commit it
  for this repo so the no-VPN default is shared; keep `wiki.prod.json`
  committed and reviewed. — *Owner: Jesus*
- [ ] Derived database naming for generated overlays: proposal is `dev` →
  mirror base (`wiki_ai-parrot`), other envs → `wiki_{wiki_name}_{env}`.
  Confirm prod DB name convention with whoever owns the prod ArangoDB. —
  *Owner: Jesus*
- [ ] `sync pull` scope: pull ALL remote memories/notes, or only records not
  authored by the local `asserted_by` identity? (Affects whether pull can
  overwrite your own newer local edits — LWW protects, but filtering by
  author is safer.) — *Owner: Jesus*
- [ ] Should `ENV=dev` (explicit) keep writing to the SHARED dev ArangoDB
  from local machines (current behavior via base config), or should team
  members build only via CI and treat dev-Arango as pull-only? — *Owner: Jesus*
- [ ] Note-sync fidelity: notes attach to page bodies of possibly-ingest
  pages; concept ids from repo scans are deterministic, but confirm note
  extraction/merge strategy (append-if-absent vs body-diff) during spec. —
  *Owner: implementer (spec phase)*
- [x] Sync direction model — *Owner: Jesus*: explicit `sync push` / `sync pull`
  subcommands, deterministic direction, LWW per record.
- [x] Sync content — *Owner: Jesus*: memories + notes/asserted links; NOT full
  repo-scan pages.
- [x] Default env with no `ENV` — *Owner: Jesus*: `local` (sqlite plane, no
  VPN); shared namespaces degrade gracefully.
- [x] Secrets placement — *Owner: Jesus*: only navconfig `env/{ENV}/.env`;
  overlays carry non-secret values only.
- [x] Missing overlay behavior — *Owner: Jesus*: read commands fall back to
  base; `build` generates the overlay via env-templated derivation.
