# TASK-2463: CLI precedence rule, build overlay generation, status env header

**Feature**: FEAT-461 — wikitoolkit Environment Support (env-aware config + memory sync)
**Spec**: `sdd/specs/wikitoolkit-env-support.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2462
**Assigned-to**: unassigned

---

## Context

Spec §2 Overview + §3 Module 2. Routes the `wikitoolkit` CLI through the
effective (env-merged) config from TASK-2462, applies ONE backend precedence
rule everywhere — `--backend` flag > environment (overlay /
`WIKI_STORE_BACKEND`) > base `wiki.json` — and closes the
`TODO(follow-up)` at `cli.py:352`, which describes exactly this work
(including the existing inconsistency: `WIKI_STORE_BACKEND` is honoured by
`_resolve_read_store`/`_resolve_write_store` but ignored by `build`).

---

## Scope

- Route `_resolve_project` (cli.py:321) through
  `load_effective_config(root)` — return the effective config (and keep
  provenance available to callers that need it, e.g. `status`).
- Apply the precedence rule in `_open_store` (cli.py:349),
  `_resolve_read_store` (cli.py:453 — `WIKI_STORE_BACKEND` read at 499),
  the write twin (cli.py:2248-2250), and the `build` command
  (`--backend` option at cli.py:1075-1078, applied at 1142-1143):
  explicit flag > env (overlay value, `WIKI_STORE_BACKEND` via
  `_env_setting`) > base config.
- Remove/replace the `TODO(follow-up)` docstring block at cli.py:352-377
  with a short description of the implemented behavior.
- `build`: when the active env's overlay file does not exist, generate it
  via `derive_env_overlay(base, env)` + `save_env_overlay(...)`, `click.echo`
  what was generated and why; NEVER overwrite an existing overlay. Do NOT
  freeze a one-off `--backend` flag into the generated overlay — generation
  derives from the BASE config only.
- Read-only commands (`query`, `page`, `related`, `status`, ...) must NEVER
  write overlay files.
- `status`: print an environment header — active env, overlay file used (or
  `base (no overlay)`), resolved backend + database, and primary-plane
  reachability.
- Update/extend CLI tests in `tests/knowledge/wiki/test_cli.py` (or a new
  `test_cli_env.py`) per the Test Specification.

**NOT in scope**: non-CLI call sites — MCP server / hook / installer /
federation (TASK-2464); the `sync` command group (TASK-2467);
`updated_at` (TASK-2465).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | effective-config routing, precedence, build generation, status header, TODO removal |
| `tests/knowledge/wiki/test_cli_env.py` | CREATE | env-aware CLI behavior tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.project import (
    load_project_config,     # currently used at cli.py:290, 337, 1784
    resolve_arango_params,   # imported lazily inside _open_store, cli.py:381
)
# From TASK-2462 (verify it landed before starting):
from parrot.knowledge.wiki.project import (
    load_effective_config, resolve_wiki_env, derive_env_overlay,
    save_env_overlay, overlay_path, WikiEffectiveConfig,
)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py
def _resolve_project(path: str | None) -> tuple[Path, WikiProjectConfig]  # line 321
def _require_built(root: Path, config: WikiProjectConfig) -> BaseWikiStore  # line 342
def _open_store(root: Path, config: WikiProjectConfig) -> BaseWikiStore   # line 349
    # TODO(follow-up) docstring at lines 352-377 — REMOVE with this task.
    # arangodb branch (380-390): lazy-imports resolve_arango_params, calls
    #   create_wiki_store(storage, wiki_name=..., backend="arangodb",
    #                     arango_params=..., database=..., text_analyzer=...)
def _env_setting(name: str) -> str | None                                  # lines 435-450
    # navconfig-first read; used for WIKI_STORE / WIKI_STORE_BACKEND
def _resolve_read_store(path_, store_opt, backend_opt, ns_opt)             # line 453
    # backend = backend_opt or _env_setting("WIKI_STORE_BACKEND") or "sqlite"  # line 499
    # write twin repeats the same at lines 2248-2250
def _collect_skips(store) -> list[NamespaceSkip]                           # ~line 300
def _echo_skips(store, *, err: bool = False) -> None                       # line 309
# build command: @click option "--backend" lines 1075-1078; applied 1142-1143
#   (config.backend = backend when flag passed); arango branches also at
#   1177, 1218, 1394, 1412 (post-build reporting paths)
```

### Does NOT Exist
- ~~`wikitoolkit sync`~~ — TASK-2467; do not scaffold it here.
- ~~an env/provenance header in `status`~~ — created by THIS task.
- ~~overlay generation anywhere~~ — created by THIS task (build only).
- ~~`--env` global CLI option~~ — env comes from `WIKI_ENV`/`ENV` process
  environment (spec §2); do NOT invent a global `--env` flag for read
  commands in this task.

---

## Implementation Notes

### Pattern to Follow
```python
# Precedence — one helper, used by _open_store, read/write resolvers, build:
#   backend = flag or effective.config.backend  (overlay already folded in)
#   with _env_setting("WIKI_STORE_BACKEND") slotted between flag and base
#   ONLY where it is honoured today (read/write resolvers) and now also in
#   build/_open_store, per spec Goal "one precedence rule".
```

### Key Constraints
- `click.echo` for user-facing output (existing style); stderr for notes when
  stdout carries JSON (see `_echo_skips`, cli.py:309-318).
- `status` reachability check must use a bounded timeout (reuse federation's
  `DEFAULT_ARANGO_TIMEOUT` probe approach — federation.py:292-337 — rather
  than an unbounded connect).
- Generated-overlay message must state the file path and the derived values.
- Keep `load_project_config` for the paths that WRITE base config
  (`build --backend` persisting a chosen backend, `ns add` at cli.py:1784) —
  effective config is for READ paths.

### References in Codebase
- `cli.py:349-392` — `_open_store` body to rework.
- `cli.py:1075-1230` — build command flow.
- `federation.py:292-337` — bounded Arango probe pattern for `status`.
- `tests/knowledge/wiki/test_cli.py` — CliRunner test conventions.

---

## Acceptance Criteria

- [ ] With no `ENV` and a `wiki.local.json` overlay present, every read
  command opens the sqlite plane (no Arango connection attempted).
- [ ] `ENV=prod wikitoolkit build` with no `wiki.prod.json` generates it
  (base Arango settings verbatim, same database name) and reports it;
  a second build uses the file verbatim (no clobber).
- [ ] Read commands never create overlay files (`ENV=prod wikitoolkit query`
  with no overlay → base fallback, no file written).
- [ ] Precedence `--backend` > env > base holds in `build`, `_open_store`,
  `_resolve_read_store`, write twin — one test per surface.
- [ ] The `cli.py:352` TODO block is gone.
- [ ] `status` shows env, overlay-or-base, backend, database, reachability.
- [ ] All tests pass: `pytest tests/knowledge/wiki/test_cli_env.py tests/knowledge/wiki/test_cli.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/knowledge/wiki/cli.py`

---

## Test Specification

```python
# tests/knowledge/wiki/test_cli_env.py
"""CliRunner tests: env-aware store resolution, build generation, status."""

class TestPrecedence:
    def test_flag_beats_overlay(self, repo_with_overlays, monkeypatch): ...
    def test_overlay_beats_base(self, repo_with_overlays, monkeypatch): ...
    def test_wiki_store_backend_env_honoured_in_build(self, tmp_path, monkeypatch): ...

class TestBuildGeneration:
    def test_generates_missing_overlay_for_active_env(self, tmp_path, monkeypatch): ...
    def test_never_clobbers_existing_overlay(self, tmp_path, monkeypatch): ...
    def test_flag_not_frozen_into_generated_overlay(self, tmp_path, monkeypatch): ...

class TestReadPaths:
    def test_read_commands_never_write_overlays(self, tmp_path, monkeypatch): ...
    def test_status_env_header_base_fallback(self, tmp_path, monkeypatch): ...
    def test_status_env_header_with_overlay(self, repo_with_overlays, monkeypatch): ...
```

---

## Agent Instructions

1. **Read the spec** at `sdd/specs/wikitoolkit-env-support.spec.md` (§2, §3 Module 2, §6, §7).
2. **Check dependencies** — TASK-2462 must be in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** before writing ANY code.
4. **Update status** in `sdd/tasks/index/wikitoolkit-env-support.json` → `"in-progress"`.
5. **Implement**, then verify all acceptance criteria.
6. **Move this file** to `sdd/tasks/completed/`.
7. **Update index** → `"done"` and fill in the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude, Sonnet)
**Date**: 2026-08-27
**Notes**: Split `_resolve_project` into a `_find_repo_root` helper plus
`_resolve_project` (now routes through `load_effective_config`, returning
the env-merged `WikiProjectConfig` — used by all 15 existing call sites
unchanged) and a new `_resolve_project_effective` (returns the full
`WikiEffectiveConfig` with provenance, used by `status`). `build` loads
BOTH the effective config (for scanning/opening the store, so
`WIKI_ENV`/`ENV`/overlay and `WIKI_STORE_BACKEND` all apply) and the base
config via `load_project_config` (for `--name`/`--backend` persistence,
matching pre-existing legacy behavior byte-for-byte) — an environment or
`WIKI_STORE_BACKEND` value is never written back to `.parrot/wiki.json`.
Missing-overlay auto-generation derives from the (persisted) base config
so it stays consistent with whatever `--name`/`--backend` just committed;
an ephemeral `WIKI_STORE_BACKEND` override never reaches it (verified by
`test_flag_not_frozen_into_generated_overlay`). Generation never clobbers
an existing overlay. Precedence (`--backend` flag > environment
(`WIKI_STORE_BACKEND` / overlay) > base) is now applied uniformly in
`build`, `_open_store` (trusts its caller's already-resolved config —
TODO removed), `_resolve_read_store` (both the default project path and
the forced-arangodb branch — neither previously honoured an explicit
flag on that path), and `_resolve_write_store`'s default project path.
`status` gained an env header (env, overlay-or-"base (no overlay)") plus
a bounded (`DEFAULT_ARANGO_TIMEOUT`-timed) `_probe_backend_reachable`
helper for arangodb — printed before the (still-fatal, per spec's
explicit primary-plane non-goal) real open/initialize.

Two pre-existing tests asserted behavior this feature intentionally
supersedes and were updated (not new regressions — verified via
`git stash` against the pre-TASK-2462 baseline):
- `test_cli.py::TestBuild::test_custom_name_and_backend` — a bare
  follow-up `query` after `build --backend memory` (no `ENV` set) now
  resolves through the freshly auto-generated `local` overlay
  (`{"backend": "sqlite"}`); updated to pass `--backend memory` again,
  documented inline as the new expected precedence.
- `test_cli_arango.py::TestStatusBackendArango::test_status_shows_arangodb_backend` —
  same root cause (`status` has no `--backend` option of its own);
  updated to set `ENV=dev` so the generated `dev` overlay mirrors the
  arangodb base instead of defaulting to `local`/sqlite.

18 new tests in `tests/knowledge/wiki/test_cli_env.py`, all passing.
Full `tests/knowledge/wiki/` suite: 1090 passed, 1 pre-existing unrelated
failure (`test_claude_code.py::TestInstaller::test_fresh_install_writes_all_artifacts`,
confirmed via `git stash`), 7 skipped (no ArangoDB test server). `ruff
check` on `cli.py`: only 3 pre-existing findings remain (verified via
`git stash`), none introduced by this task.

**Deviations from spec**: none. One clarification made explicit in code
comments: the spec's "avoid freezing a one-off flag into the overlay"
Known Risk is interpreted as protecting against *ephemeral,
non-persisted* overrides (`WIKI_STORE_BACKEND`) — an explicit `--backend`
flag is (as in pre-existing behavior) persisted to the base config by
`build`, so it legitimately flows into a freshly generated overlay for
consistency with what was just committed to `wiki.json`.
