# TASK-2462: Env resolution, overlay model, and effective config loader

**Feature**: FEAT-461 — wikitoolkit Environment Support (env-aware config + memory sync)
**Spec**: `sdd/specs/wikitoolkit-env-support.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §2 Overview + §3 Module 1. The foundation of FEAT-461: everything else
(CLI precedence, call-site migration, sync) consumes the env-aware
"effective config". Environments are per-env overlay files
(`.parrot/wiki.{env}.json`) shallow-merged over the committed base
`.parrot/wiki.json`; the active env resolves `WIKI_ENV` → `ENV` → `"local"`.

`project.py` is imported by the Claude Code PreToolUse hook — it MUST stay
stdlib + pydantic at module scope (navconfig only via the existing lazy
`_navconfig()`; TASK-2359 discipline).

---

## Scope

- Implement `resolve_wiki_env(env: str | None = None) -> str` in
  `project.py`: explicit arg > `WIKI_ENV` > `ENV` > `"local"`. Read the env
  vars on EVERY call (like `parrot_home()`, project.py:624) so tests can
  monkeypatch. Validate the value with the same charset rule as
  `validate_namespace_name` (safe overlay filenames); invalid → `WikiConfigError`.
- Implement `WikiEnvOverlay(BaseModel)`: a PARTIAL `WikiProjectConfig` —
  every field optional/None. Permitted fields ONLY: `backend`, `storage_dir`,
  `arango_database`, `arango_credentials_env`, `arango_text_analyzer`,
  `namespaces`, `vault_dir`, `sync_graph`, `body_max_chars`, `max_file_kb`,
  `include_suffixes`, `exclude_dirs`, `claude`. NO credential/host/port/
  password fields, ever. `model_config = ConfigDict(extra="forbid")` so
  unknown (and secret-like) keys fail loud.
- Implement `WikiEffectiveConfig(BaseModel)`: `config: WikiProjectConfig`
  (merged result), `env: str`, `overlay_path: Path | None` (None ⇒ base
  fallback).
- Implement `overlay_path(root: Path, env: str) -> Path` →
  `root/.parrot/wiki.{env}.json`.
- Implement `load_effective_config(root: Path, env: str | None = None) ->
  WikiEffectiveConfig`: load base via existing `load_project_config(root)`;
  if the overlay file exists, parse+validate as `WikiEnvOverlay` (invalid
  JSON/schema → `WikiConfigError` NAMING the overlay file — never silent
  fallback); shallow-merge set fields via
  `base.model_copy(update=overlay.model_dump(exclude_none=True))`, EXCEPT
  `namespaces` which merges per-key (overlay entries win, base entries not
  named by the overlay survive).
- Implement `derive_env_overlay(base: WikiProjectConfig, env: str) ->
  WikiEnvOverlay`: `"local"` → `WikiEnvOverlay(backend="sqlite")`; every
  other env → base's Arango settings verbatim (`backend`, `arango_database`,
  `arango_credentials_env`, `arango_text_analyzer`) — SAME database name (no
  env suffixing; separation lives in per-`ENV` credentials).
- Implement `save_env_overlay(root: Path, env: str, overlay: WikiEnvOverlay)
  -> Path`: atomic write (tmp file + `os.replace`), parent dirs created,
  serialize with `exclude_none=True`, `indent=2`, trailing newline.
- Write unit tests in `tests/knowledge/wiki/test_env_config.py` (see Test
  Specification).

**NOT in scope**: CLI wiring / precedence / build generation (TASK-2463),
migrating existing call sites (TASK-2464), sync (TASK-2466), any
`updated_at` work (TASK-2465), committing `.parrot/wiki.local.json`
(TASK-2468).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/project.py` | MODIFY | add env resolution + overlay model + effective config + derivation + atomic save |
| `tests/knowledge/wiki/test_env_config.py` | CREATE | unit tests for all of the above |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Everything this task extends lives in ONE file — project.py imports only
# stdlib + pydantic at module scope. Existing symbols to build on:
from parrot.knowledge.wiki.project import (   # all verified 2026-08-25
    PARROT_DIR,             # ".parrot"                       project.py:34
    CONFIG_FILENAME,        # "wiki.json"                     project.py:37
    WikiProjectConfig,      # project.py:295
    WikiNamespaceConfig,    # ~project.py:195-235 (FEAT-450)
    WikiConfigError,        # project.py:574 (subclass of ValueError)
    load_project_config,    # project.py:578
    config_path,            # project.py:546
    validate_namespace_name,  # FEAT-450 name charset validator (grep for def)
)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/project.py
class WikiProjectConfig(BaseModel):                    # line 295
    wiki_name: str = Field(default="codebase")         # line 325
    storage_dir: str                                   # line 326, default ".parrot/wiki"
    backend: Literal["sqlite", "memory", "arangodb"]   # line 327, default "sqlite"
    include_suffixes: list[str]                        # line 328
    exclude_dirs: list[str]                            # line 329
    body_max_chars: int                                # line 330
    max_file_kb: int                                   # line 331
    claude: ClaudeIntegrationConfig                    # line 332
    sync_graph: bool                                   # line 335
    arango_database: str | None                        # line 336
    arango_credentials_env: str                        # line 340, default "ARANGODB"
    arango_text_analyzer: str                          # line 347
    vault_dir: str | None                              # line 351
    namespaces: dict[str, WikiNamespaceConfig]         # FEAT-450

def load_project_config(root: Path) -> WikiProjectConfig   # line 578
    # missing file → defaults (wiki_name=root.name); invalid → WikiConfigError
def save_project_config(root, config) -> Path               # line 605 (plain write —
    # your save_env_overlay must be ATOMIC instead; see save_global_registry)
def parrot_home() -> Path                                    # line 624 — reads
    # os.environ on EVERY call (the pattern resolve_wiki_env must follow)
def load_global_registry(path=None) -> GlobalWikiRegistry    # line 644
    # its save twin uses tmp-file + os.replace — copy that atomic pattern
def merge_namespaces(...)                                    # line 707 (repo wins;
    # reference for per-key dict merge semantics)
```

### Does NOT Exist
- ~~`resolve_wiki_env` / `WikiEnvOverlay` / `WikiEffectiveConfig` /
  `load_effective_config` / `overlay_path` / `derive_env_overlay` /
  `save_env_overlay`~~ — created by THIS task.
- ~~`WIKI_ENV` handling anywhere~~ — no env awareness exists in the wiki
  config layer today.
- ~~navconfig import at `project.py` module scope~~ — only the lazy
  `_navconfig()` helper exists (project.py:456 area). Do NOT add a
  module-scope import; this task does not need navconfig at all
  (`resolve_wiki_env` reads `os.environ` only).
- ~~`WikiProjectConfig.environments`~~ — no environments block; rejected
  design (spec Non-Goals).

---

## Implementation Notes

### Pattern to Follow
```python
# Per-call env reads — copy the parrot_home() discipline (project.py:624):
raw = os.environ.get("WIKI_ENV") or os.environ.get("ENV") or "local"

# Atomic write — copy save_global_registry's pattern (tmp + os.replace):
tmp = path.with_suffix(".tmp")
tmp.write_text(payload, encoding="utf-8")
os.replace(tmp, path)
```

### Key Constraints
- Fail LOUD on invalid overlay: `WikiConfigError(f"Invalid wiki overlay at
  {path} — fix or remove it: {exc}")` — mirroring `load_project_config`
  (project.py:598-601). A typo must never silently retarget prod to dev.
- `extra="forbid"` on `WikiEnvOverlay` is the no-secrets enforcement: a
  `password`/`host` key in an overlay must raise, not pass through.
- The merge is SHALLOW except `namespaces` (per-key union, overlay wins).
- Google-style docstrings + strict type hints; no logging framework changes.

### References in Codebase
- `project.py:578-602` — load/fail-loud contract to mirror.
- `project.py:624-644` — env-read + atomic-write patterns.
- `tests/knowledge/wiki/test_project_namespaces.py` — existing test style
  for project.py models (monkeypatch, tmp_path fixtures).

---

## Acceptance Criteria

- [ ] `resolve_wiki_env()` precedence: explicit arg > `WIKI_ENV` > `ENV` >
  `"local"`; per-call env reads; invalid charset → `WikiConfigError`.
- [ ] `load_effective_config`: no overlay → base config + `overlay_path=None`;
  overlay present → merged config + provenance; invalid overlay →
  `WikiConfigError` naming the file.
- [ ] `namespaces` merges per-key; other fields shallow-override.
- [ ] `WikiEnvOverlay` rejects unknown keys (incl. `password`, `host`).
- [ ] `derive_env_overlay`: local → sqlite; non-local → base Arango settings
  verbatim (same `arango_database`).
- [ ] `save_env_overlay` is atomic and round-trips through
  `load_effective_config`.
- [ ] `project.py` module scope still imports only stdlib + pydantic
  (verify: no new top-level imports).
- [ ] All tests pass: `pytest tests/knowledge/wiki/test_env_config.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/knowledge/wiki/project.py`

---

## Test Specification

```python
# tests/knowledge/wiki/test_env_config.py
import pytest
from parrot.knowledge.wiki.project import (
    WikiConfigError, WikiEnvOverlay, derive_env_overlay,
    load_effective_config, overlay_path, resolve_wiki_env, save_env_overlay,
)


class TestResolveWikiEnv:
    def test_default_is_local(self, monkeypatch):
        monkeypatch.delenv("WIKI_ENV", raising=False)
        monkeypatch.delenv("ENV", raising=False)
        assert resolve_wiki_env() == "local"

    def test_env_var_used(self, monkeypatch):
        monkeypatch.setenv("ENV", "prod")
        assert resolve_wiki_env() == "prod"

    def test_wiki_env_beats_env(self, monkeypatch):
        monkeypatch.setenv("ENV", "prod")
        monkeypatch.setenv("WIKI_ENV", "dev")
        assert resolve_wiki_env() == "dev"

    def test_invalid_charset_rejected(self, monkeypatch):
        monkeypatch.setenv("WIKI_ENV", "../evil")
        with pytest.raises(WikiConfigError):
            resolve_wiki_env()


class TestEffectiveConfig:
    def test_no_overlay_is_base(self, tmp_path): ...
    def test_overlay_merges_shallow(self, tmp_path): ...
    def test_namespaces_merge_per_key(self, tmp_path): ...
    def test_invalid_overlay_fails_loud_naming_file(self, tmp_path): ...
    def test_overlay_rejects_secret_keys(self, tmp_path): ...


class TestDeriveAndSave:
    def test_local_template_is_sqlite(self): ...
    def test_other_env_mirrors_base_same_database(self): ...
    def test_save_round_trips_and_is_atomic(self, tmp_path): ...
```

---

## Agent Instructions

1. **Read the spec** at `sdd/specs/wikitoolkit-env-support.spec.md` (§2, §3 Module 1, §6, §7).
2. **Check dependencies** — none.
3. **Verify the Codebase Contract** before writing ANY code (grep/read each
   listed symbol; update the contract first if drifted).
4. **Update status** in `sdd/tasks/index/wikitoolkit-env-support.json` → `"in-progress"`.
5. **Implement**, then verify all acceptance criteria.
6. **Move this file** to `sdd/tasks/completed/`.
7. **Update index** → `"done"` and fill in the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude, Sonnet)
**Date**: 2026-08-27
**Notes**: Implemented `resolve_wiki_env`, `WikiEnvOverlay`, `WikiEffectiveConfig`,
`overlay_path`, `load_effective_config`, `derive_env_overlay`, and
`save_env_overlay` in `project.py`, inserted between `save_project_config`
and `parrot_home`. `resolve_wiki_env` reuses `_NAMESPACE_NAME_RE` directly
(not `validate_namespace_name`, since that rejects `"local"` as a reserved
namespace name — the exact default env value) and wraps failures in
`WikiConfigError`. `load_effective_config` merges via
`model_copy(update=...)` excluding `namespaces`, then merges `namespaces`
per-key from the validated `WikiEnvOverlay.namespaces` dict (already typed
`WikiNamespaceConfig` instances, avoiding a re-serialize/re-validate
round-trip). `save_env_overlay` copies the `save_global_registry` tmp-file +
`os.replace` atomic-write pattern. 18 new unit tests added in
`tests/knowledge/wiki/test_env_config.py`, all passing; `ruff check` clean;
module-scope imports unchanged (stdlib + pydantic only, verified). Full
`tests/knowledge/wiki/` suite run: 1080 passed, 1 pre-existing failure
(`test_claude_code.py::TestInstaller::test_fresh_install_writes_all_artifacts`,
confirmed unrelated via `git stash` — fails identically without this
change), 7 skipped (ArangoDB integration, no test server configured).

**Deviations from spec**: none
