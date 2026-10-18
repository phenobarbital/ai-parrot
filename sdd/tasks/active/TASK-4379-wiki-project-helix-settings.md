# TASK-4379: `WikiProjectConfig` HelixDB fields and `resolve_helix_params`

**Feature**: FEAT-670 — HelixDB graph provider
**Spec**: `sdd/specs/helixdb-provider.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4372, TASK-4374
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4, first half ("fields first, rows last" — spec Worktree Strategy allows the
split). This task exposes the project-level HelixDB settings in `.parrot/wiki.json`
(`helix_database`, `helix_credentials_env`, `helix_mode`, next to the `arango_*` fields) and
the resolver `resolve_helix_params(config, *, root=None) -> HelixSettings`, the HelixDB
mirror of `resolve_arango_params`. The registry rows that consume it (`WikiBackendSpec`,
`GraphBackendSpec.project_options`, ontology / source rows, `register_all()`) are TASK-4392;
the ledger and schema services use the resolver in TASK-4381 / TASK-4382.

---

## Scope

- Add `helix_database`, `helix_credentials_env`, `helix_mode` to `WikiProjectConfig` (after
  `arango_text_analyzer`), with docstring `Attributes:` entries.
- Add the same three keys (all optional, `None` default) to `WikiEnvOverlay` so per-`ENV`
  overlays can retarget a HelixDB database; mirror them in `derive_env_overlay` for non-local envs.
- Add `resolve_helix_params(config, *, root=None) -> HelixSettings` after `resolve_arango_params`.
- Tests in `tests/knowledge/wiki/test_helix_project_settings.py`.

**NOT in scope**: any registry row or `"helixdb"` string in `wiki/store.py`,
`wiki/sources_backend.py`, `graphindex/backends.py`, `ontology/contracts.py` (TASK-4392);
the namespace-level options adapter for `WikiBackendSpec.resolve_options` (TASK-4392 — see
drift note); ledger / schema dispatch (TASK-4381 / TASK-4382); `WikiNamespaceConfig`
changes; touching `resolve_arango_params`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/project.py` | MODIFY | `helix_*` fields (config + overlay), `derive_env_overlay` mirror, `resolve_helix_params` |
| `packages/ai-parrot/tests/knowledge/wiki/test_helix_project_settings.py` | CREATE | field defaults, overlay merge, resolver precedence |

---

## Codebase Contract (Anti-Hallucination)

Verified on dev @ `1c239a5ca` (FEAT-540 merged; spec §6 line numbers were stale).

### Verified Imports
```python
from parrot.knowledge.wiki.project import (
    WikiProjectConfig,        # wiki/project.py:574 (spec said :561)
    WikiEnvOverlay,           # wiki/project.py:1082
    derive_env_overlay,       # wiki/project.py:1289
    load_effective_config,    # wiki/project.py:~1232 (generic overlay merge :1275-1280)
    resolve_arango_params,    # wiki/project.py:903 (spec said :851)
    resolve_setting,          # wiki/project.py:849 (FEAT-540 M4)
)
from parrot.knowledge.helix.settings import HelixSettings, resolve_helix_settings   # TASK-4372 — import LAZILY inside the function
```

### Existing Signatures to Use
```python
# wiki/project.py:574
class WikiProjectConfig(BaseModel):
    model_config = ConfigDict(validate_by_name=True, validate_by_alias=True, serialize_by_alias=True)  # :614
    wiki_name: str = Field(default="codebase")                      # :616
    storage_dir: str = Field(default=f"{PARROT_DIR}/wiki")          # :617
    backend: str = Field(default="sqlite")                          # :618 — registry-validated str (FEAT-540), no Literal
    arango_database: str | None = Field(...)                        # :629
    arango_credentials_env: str = Field(default="ARANGODB", ...)    # :633
    arango_text_analyzer: str = Field(default="text_en", ...)       # :637-640
    def storage_path(self, root: Path) -> Path                      # :761
    def is_built(self, root: Path) -> bool                          # ~:790; honours WikiBackendSpec.is_built hook called as hook(config, root) (:806-810)
# wiki/project.py:849
def resolve_setting(key, *, default=None, explicit=None, project_defaults=None) -> Any
# wiki/project.py:903
def resolve_arango_params(config: WikiProjectConfig) -> dict[str, Any]   # database = config.arango_database or f"wiki_{config.wiki_name}" (:936)
# wiki/project.py:1082
class WikiEnvOverlay(BaseModel):   # model_config = ConfigDict(extra="forbid"); arango_* overrides at :1121-1123
# wiki/project.py:1271-1280 — load_effective_config merges every non-None overlay field generically (model_fields loop)
# wiki/project.py:1289
def derive_env_overlay(base: WikiProjectConfig, env: str) -> WikiEnvOverlay   # non-local envs copy arango_* (:1307-1312)
# TASK-4372 (helix/settings.py)
def resolve_helix_settings(*, database: str, credentials_env: str = "HELIXDB", mode: str | None = None,
                           storage_dir: Path | None = None, read_only: bool = False) -> HelixSettings
```

### Edit anchors (`grep -c -F` on `packages/ai-parrot/src/parrot/knowledge/wiki/project.py`)
| Anchor | Count | Line |
|---|---|---|
| `    arango_text_analyzer: str = Field(` | 1 | :637 (block closes `    )` at :640) |
| `        arango_text_analyzer: ArangoSearch text analyzer used for the` | 1 | :597 (docstring) |
| `    arango_text_analyzer: str | None = None` | 1 | :1123 (WikiEnvOverlay) |
| `        arango_text_analyzer: ArangoSearch text analyzer override.` | 1 | :1100 (overlay docstring) |
| `        arango_text_analyzer=base.arango_text_analyzer,` | 1 | :1311 (derive_env_overlay) |
| `def resolve_arango_params(config: WikiProjectConfig) -> dict[str, Any]:` | 1 | :903 (function ends :937) |

### Does NOT Exist
- ~~`resolve_helix_params`, `helix_database`, `helix_credentials_env`, `helix_mode`~~ — created here.
- ~~`WikiProjectConfig.backend: Literal[...]`~~ — FEAT-540 made it a registry-validated `str` (:618); do not add a Literal.
- ~~a `"helixdb"` `WikiBackendSpec` row~~ — TASK-4392; until then `WikiProjectConfig(backend="helixdb")` may be
  rejected by the registry validator — tests here must not set `backend="helixdb"`.
- ~~module-scope `from parrot.knowledge.helix ...` in project.py~~ — forbidden (hook-path import cost, module docstring :1-12).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/project.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/test_helix_project_settings.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#WikiProjectConfig",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#WikiEnvOverlay",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#derive_env_overlay",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#resolve_arango_params",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#resolve_setting"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `helix_mode: Literal["server", "embedded"]` (spec §3 M4) — `memory` is a test-only
  `HelixMode`, never a project setting.
- `resolve_helix_params` delegates entirely to `resolve_helix_settings` (TASK-4372): database
  `config.helix_database or f"wiki_{config.wiki_name}"`, prefix `config.helix_credentials_env`,
  `mode=config.helix_mode` (as project default — `HELIXDB_MODE` env still wins),
  `storage_dir=config.storage_path(root) if root is not None else None`. Embedded mode without
  `root` therefore raises `ValueError` from the settings resolver.
- Shared file: `wiki/project.py` is also edited by FEAT-633 (merge-time reconciliation, spec §7) —
  keep the diff to the listed anchors.

### Drift vs spec (FEAT-540 real API)
- Spec §3 M4 sketches `WikiBackendSpec(..., resolve_options="parrot.knowledge.wiki.project:resolve_helix_params")`.
  The real `WikiBackendSpec.resolve_options` (`wiki/store.py:548-560`, used at `wiki/federation.py:420-422`) is
  `(WikiNamespaceConfig) -> dict` of **factory kwargs**, not `(WikiProjectConfig) -> HelixSettings`. So
  `resolve_helix_params` cannot be the `resolve_options` hook directly; TASK-4392 must add a small
  namespace adapter (e.g. `helix_namespace_options(cfg) -> {"settings": …}`). Recorded here so 4392 picks it up.
- The real `is_built` hook is called `hook(config, root)` (`project.py:806-810`) — the embedded-mode probe
  for TASK-4392 can reuse `resolve_helix_params(config, root=root).root / database`.
- `GraphBackendSpec.project_options` is `"module:callable"` taking `(config, root, tenant_id)`
  (`wiki/runtime.py:42-80`) — TASK-4392's mapper will call `resolve_helix_params(config, root=root).with_database(f"gi_{tenant}")`.
- Spec line numbers `project.py:561/616-627/851` are stale; real ones are listed above.

---

## Implementation Blueprint

### Steps (in order)
1. Add the three fields + docstring entries to `WikiProjectConfig` — *why*: spec §3 M4 skeleton.
2. Add overlay fields + `derive_env_overlay` mirror — *why*: per-ENV server/database switching, same as `arango_*`.
3. Add `resolve_helix_params` after `resolve_arango_params` — *why*: one resolver every plane maps from.
4. Write and run tests.

### `packages/ai-parrot/src/parrot/knowledge/wiki/project.py` (MODIFY) — fields
```python
# occurrences: 1 (verified: grep -c -F '    arango_text_analyzer: str = Field(' wiki/project.py)
# AFTER — insert below the closing `    )` of that Field block (verified: project.py:637-640)
    helix_database: str | None = Field(
        default=None,
        description="HelixDB database name; defaults to wiki_{wiki_name}",
    )
    helix_credentials_env: str = Field(
        default="HELIXDB",
        description="Env var prefix (HELIXDB -> HELIXDB_URL, HELIXDB_API_KEY, HELIXDB_MODE)",
    )
    helix_mode: Literal["server", "embedded"] = Field(
        default="server",
        description="HelixDB deployment mode; HELIXDB_MODE overrides it",
    )
```
```python
# occurrences: 1 (verified: grep -c -F '        arango_text_analyzer: ArangoSearch text analyzer used for the' wiki/project.py)
# AFTER — the docstring entry continues on :598 (`            pages view's full-text search (e.g. ``"text_en"``).`); insert after that line
        helix_database: HelixDB database for the ``helixdb`` backend;
            defaults to ``wiki_{wiki_name}``.
        helix_credentials_env: Env var prefix resolving ``<prefix>_URL``,
            ``<prefix>_API_KEY`` and ``<prefix>_MODE``.
        helix_mode: ``server`` (default) or ``embedded``.
```

### `packages/ai-parrot/src/parrot/knowledge/wiki/project.py` (MODIFY) — overlay
```python
# occurrences: 1 (verified: grep -c -F '    arango_text_analyzer: str | None = None' wiki/project.py)
# AFTER (verified: project.py:1123)
    helix_database: str | None = None
    helix_credentials_env: str | None = None
    helix_mode: Literal["server", "embedded"] | None = None

# occurrences: 1 (verified: grep -c -F '        arango_text_analyzer: ArangoSearch text analyzer override.' wiki/project.py)
# AFTER (verified: project.py:1100)
        helix_database: HelixDB database name override.
        helix_credentials_env: HelixDB env var prefix override.
        helix_mode: HelixDB deployment mode override.

# occurrences: 1 (verified: grep -c -F '        arango_text_analyzer=base.arango_text_analyzer,' wiki/project.py)
# AFTER (verified: project.py:1311, inside derive_env_overlay's non-local return)
        helix_database=base.helix_database,
        helix_credentials_env=base.helix_credentials_env,
        helix_mode=base.helix_mode,
```
**Why**: `load_effective_config` merges every non-None overlay field generically (:1275-1280), so no merge code changes.

### `packages/ai-parrot/src/parrot/knowledge/wiki/project.py` (MODIFY) — resolver
```python
# occurrences: 1 (verified: grep -c -F 'def resolve_arango_params(config: WikiProjectConfig) -> dict[str, Any]:' wiki/project.py)
# AFTER — insert below the end of resolve_arango_params (its `return {...}` closes at :937), before `def resolve_vault_dir(`
def resolve_helix_params(config: WikiProjectConfig, *, root: Path | None = None) -> "HelixSettings":
    """Resolve HelixDB connection settings for a wiki project.

    Mirror of :func:`resolve_arango_params`: only the database name, env prefix and mode live in
    ``wiki.json``; URL / API key / mode override resolve through :func:`resolve_setting`
    (os.environ → navconfig → project value → default).

    Args:
        config: Project configuration.
        root: Project root; required for ``embedded`` mode (Disk root = ``storage_path(root)/"helix"``).

    Returns:
        The resolved :class:`~parrot.knowledge.helix.settings.HelixSettings`.

    Raises:
        ValueError: Embedded mode without ``root``, or an invalid ``<prefix>_MODE`` value.
    """
    from parrot.knowledge.helix.settings import resolve_helix_settings  # lazy: hook-path import cost

    return resolve_helix_settings(
        database=config.helix_database or f"wiki_{config.wiki_name}",
        credentials_env=config.helix_credentials_env,
        mode=config.helix_mode,
        storage_dir=config.storage_path(root) if root is not None else None,
    )
```
Add `HelixSettings` to the existing `if TYPE_CHECKING:` block (project.py:33-37):
```python
# occurrences: 2 (verified: grep -c -F '    from parrot.knowledge.wiki.store import SQLitePragmaPolicy' wiki/project.py)
# — the second hit is the deferred runtime import inside sqlite_policy_from_config(). Disambiguated anchor (project.py:33-37):
#     if TYPE_CHECKING:
#         # Import only for the annotation below — the real (runtime) import in
#         # sqlite_policy_from_config() is deferred to avoid a module-load cycle
#         # (store.py and project.py are mutually reachable).
#         from parrot.knowledge.wiki.store import SQLitePragmaPolicy
# AFTER the last line of that TYPE_CHECKING block (:37):
    from parrot.knowledge.helix.settings import HelixSettings
```

### FILL IN checklist
- [ ] none beyond the mechanical edits above (insert only inside the TYPE_CHECKING block, never the runtime import site)

---

## Acceptance Criteria

- [ ] `WikiProjectConfig()` defaults: `helix_database is None`, `helix_credentials_env == "HELIXDB"`, `helix_mode == "server"`;
      `helix_mode="cloud"` fails validation.
- [ ] `resolve_helix_params(cfg)` → `HelixSettings(database="wiki_<wiki_name>", mode=SERVER)`; `helix_database` wins when set;
      `HELIXDB_URL` / custom prefix honoured; `HELIXDB_MODE=embedded` overrides `helix_mode="server"`.
- [ ] Embedded with `root` → `settings.root == config.storage_path(root) / "helix"`; embedded without `root` → `ValueError`.
- [ ] A `.parrot/wiki.<env>.json` overlay with `helix_database` is merged by `load_effective_config`; `derive_env_overlay(base, "prod")` copies `helix_*`.
- [ ] `import parrot.knowledge.wiki.project` does not import `parrot.knowledge.helix` (check `sys.modules`).
- [ ] Existing `tests/knowledge/wiki/test_resolve_setting.py` still passes.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_helix_project_settings.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_resolve_setting.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/wiki/test_helix_project_settings.py
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from parrot.knowledge.helix.settings import HelixMode
from parrot.knowledge.wiki.project import WikiEnvOverlay, WikiProjectConfig, derive_env_overlay, resolve_helix_params


@pytest.fixture(autouse=True)
def _no_ambient(monkeypatch):
    for k in ("HELIXDB_URL", "HELIXDB_API_KEY", "HELIXDB_MODE"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr("parrot.knowledge.wiki.project._navconfig", lambda: None)


def test_defaults_and_validation():
    cfg = WikiProjectConfig()
    assert (cfg.helix_database, cfg.helix_credentials_env, cfg.helix_mode) == (None, "HELIXDB", "server")
    with pytest.raises(ValidationError):
        WikiProjectConfig(helix_mode="cloud")


def test_resolve_defaults_and_override(monkeypatch):
    s = resolve_helix_params(WikiProjectConfig(wiki_name="t"))
    assert s.database == "wiki_t" and s.mode is HelixMode.SERVER
    assert resolve_helix_params(WikiProjectConfig(helix_database="x")).database == "x"
    monkeypatch.setenv("HELIXDB_MODE", "server")
    assert resolve_helix_params(WikiProjectConfig(helix_mode="embedded")).mode is HelixMode.SERVER


def test_embedded_root(tmp_path: Path):
    cfg = WikiProjectConfig(helix_mode="embedded")
    assert resolve_helix_params(cfg, root=tmp_path).root == cfg.storage_path(tmp_path) / "helix"
    with pytest.raises(ValueError):
        resolve_helix_params(cfg)


def test_overlay_fields():
    assert WikiEnvOverlay(helix_database="d").helix_database == "d"
    ov = derive_env_overlay(WikiProjectConfig(helix_database="d", helix_mode="embedded"), "prod")
    assert (ov.helix_database, ov.helix_mode) == ("d", "embedded")


def test_project_module_does_not_import_helix():
    code = "import sys, parrot.knowledge.wiki.project; print('parrot.knowledge.helix' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout
    assert out.strip() == "False"
```
(Add a `load_effective_config` overlay-merge test using `tmp_path` with a base `.parrot/wiki.json` and an
env overlay file, following the existing overlay tests' fixture pattern in `tests/knowledge/wiki/`.)

---

## Agent Instructions

1. **Work in the feature worktree** `feat-FEAT-670-helixdb-provider`, never on `dev`.
2. Read spec §3 Module 4 and §7 "Env resolution".
3. `TASK-4372` must be `done` in `sdd/tasks/index/helixdb-provider.json`.
4. Re-run every `grep -c -F` anchor check above (each must print `1`); FEAT-633 may have moved lines.
5. Mark `in-progress`; commit only the index file.
6. Implement exactly the listed edits; do not touch any registry file (TASK-4392).
7. Validate with `PYTHONPATH=packages/ai-parrot/src`; `ruff check --fix` the touched files.
8. Commit only the listed files: `feat(helixdb-provider): TASK-4379 — WikiProjectConfig helix fields and resolve_helix_params`.
9. `scripts/sdd/close_task.sh TASK-4379 helixdb-provider verified`, fill the Completion Note (mention the
   resolve_options drift for TASK-4392), commit.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
