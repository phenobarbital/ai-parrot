# TASK-2359: Namespace configuration model + global registry (`project.py`)

**Feature**: FEAT-450 — Namespaces for `wikitoolkit` (multi-wiki federation)
**Spec**: `sdd/specs/wiki-namespaces.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1. Namespaces must be *declared* in two places — `.parrot/wiki.json`
(`namespaces`) and a global user registry `~/.parrot/wikis.json` — and merged with repo entries
winning (spec G2, U1). The declaration layer lives in `project.py`, which the Claude PreToolUse hook
imports, so it must remain **stdlib + pydantic only** (no `store` / `search` / `vault_scan`
imports — `project.py:1-40`, `resolve_vault_dir` shows the lazy-import discipline at 245-289).
Resolution into opened stores is NOT this task (TASK-2362).

---

## Scope

- Add `WikiNamespaceConfig(BaseModel)` with fields `path`, `store`, `backend`
  (`Literal["sqlite","memory","arangodb"]`, default `sqlite`), `database`, `credentials_env`
  (default `"ARANGODB"`), `vault`, `description` (default `""`), `weight` (`0.0..1.0`, default `1.0`);
  a `kind` property returning `"path" | "store" | "database" | "vault"`; a model validator enforcing
  **exactly one** of `path` / `store` / `database` / `vault`; `database` forces backend `arangodb`.
- Add `namespaces: dict[str, WikiNamespaceConfig] = Field(default_factory=dict)` to
  `WikiProjectConfig`. Validate keys with `validate_namespace_name(name)`: regex
  `^[A-Za-z0-9][A-Za-z0-9_.:-]*$`, must not contain `::`, must not be `all` or `local`.
- Add `GlobalWikiRegistry(BaseModel)` (`version: int = 1`, `namespaces: dict[...]`).
- Add `GLOBAL_REGISTRY_PATH` resolution: `Path(os.environ.get("PARROT_HOME") or "~/.parrot").expanduser() / "wikis.json"`
  computed by a function `global_registry_path()` (not a module constant evaluated at import, so
  tests can monkeypatch `PARROT_HOME`).
- Add `load_global_registry(path=None) -> GlobalWikiRegistry` (missing file → empty registry;
  invalid JSON/schema → `WikiConfigError`) and `save_global_registry(registry, path=None) -> Path`
  (create parent dirs, write `json.dumps(model_dump(mode="json"), indent=2)` atomically via a temp
  file + `os.replace`, `chmod 0o600`).
- Add `merge_namespaces(repo, global_) -> dict[str, tuple[WikiNamespaceConfig, str]]` returning
  `name -> (config, origin)` with `origin in {"repo", "global"}`; repo wins on clash.
- Add `resolve_entry_base(config_origin, root) -> Path` helper: relative `path`/`store`/`vault`
  values resolve against the repo root for repo entries and against the registry file's directory
  for global entries (document this on the model).
- Write unit tests in `tests/knowledge/wiki/test_project_namespaces.py`.

**NOT in scope**: opening stores, `FederatedWikiStore`, CLI `ns` commands (TASK-2362/2364),
`.obsidian` probing (TASK-2364).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/project.py` | MODIFY | models, registry helpers, name validation |
| `tests/knowledge/wiki/test_project_namespaces.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.project import (   # project.py
    PARROT_DIR, CONFIG_FILENAME, WikiProjectConfig, WikiConfigError,
    config_path, find_project_root, load_project_config, save_project_config,
)                                              # 125, 319, 291, 296, 323, 350
from pydantic import BaseModel, Field, field_validator, model_validator   # pydantic v2 (already used in project.py:21)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/project.py
PARROT_DIR = ".parrot"; CONFIG_FILENAME = "wiki.json"                      # module constants
class WikiProjectConfig(BaseModel):                                           # 125
    wiki_name: str = Field(default="codebase")
    storage_dir: str = Field(default=f"{PARROT_DIR}/wiki")                   # 152
    backend: Literal["sqlite", "memory", "arangodb"] = Field(default="sqlite")
    ...  # include_suffixes, exclude_dirs, body_max_chars, max_file_kb, claude, sync_graph,
         # arango_database, arango_credentials_env, arango_text_analyzer, vault_dir (177-186)
    def storage_path(self, root: Path) -> Path                               # 190
    def is_built(self, root: Path) -> bool                                   # 199
class WikiConfigError(ValueError)                                             # 319
def load_project_config(root: Path) -> WikiProjectConfig                      # 323 — json.loads + model_validate (341-342); missing → defaults (347); bad → WikiConfigError
def save_project_config(root: Path, config: WikiProjectConfig) -> Path        # 350 — write_text(json.dumps(config.model_dump(mode="json"), indent=2) + "\n") (362-363)
```
Module imports today (`project.py:13-21`): `json, logging, os, time, collections.abc.Iterator,
contextlib.contextmanager, pathlib.Path, typing.{Any, Literal, Optional}, pydantic.{BaseModel, Field}`,
optional `fcntl`. Keep it that way.

### Does NOT Exist
- ~~`WikiNamespaceConfig`~~, ~~`GlobalWikiRegistry`~~, ~~`WikiProjectConfig.namespaces`~~,
  ~~`load_global_registry`~~, ~~`save_global_registry`~~, ~~`merge_namespaces`~~ — you create them.
- Nothing in the wiki package reads `~/.parrot` today (only `expanduser()` on `vault_dir`,
  `project.py:270-274`). There is no `PARROT_HOME` handling anywhere — you introduce it.
- ~~`project.py` importing `vault_scan` / `store` / `search`~~ — forbidden (hook import path).

---

## Implementation Notes

### Pattern to Follow
```python
# project.py:323-347 — load with defaults, wrap validation errors
try:
    data = json.loads(path.read_text(encoding="utf-8"))
    return WikiProjectConfig.model_validate(data)
except (OSError, ValueError, ValidationError) as exc:
    raise WikiConfigError(f"...") from exc
```

### Key Constraints
- `namespaces` must default to `{}` so every existing `wiki.json` still validates (spec AC).
- `extra="forbid"` on `WikiNamespaceConfig` so a typo like `"vaults"` fails loudly.
- Pure-sync file I/O is fine here (the CLI calls it from sync click commands).
- Google-style docstrings + strict typing.

### References in Codebase
- `project.py:245-289` `resolve_vault_dir` — precedence + relative-path resolution style.
- `project.py:47-107` `wiki_write_lock` — module stays dependency-light.

---

## Acceptance Criteria

- [ ] `WikiNamespaceConfig` with exactly-one-source validation and `kind`
- [ ] `WikiProjectConfig.namespaces` defaults to `{}`; old configs load unchanged
- [ ] `validate_namespace_name` rejects `all`, `local`, `a::b`, `""`, `-x`; accepts `legal:civil`, `asyncdb`
- [ ] `load_global_registry` / `save_global_registry` round-trip under `PARROT_HOME`; file mode `0o600`
- [ ] `merge_namespaces` — repo wins, origin tagged
- [ ] `python -X importtime -c "import parrot.knowledge.wiki.project" 2>&1 | grep -E "wiki\.(store|search|vault_scan)"` prints nothing
- [ ] `pytest tests/knowledge/wiki/test_project_namespaces.py tests/knowledge/wiki/test_project_lock.py tests/knowledge/wiki/test_claude_code.py -v` passes
- [ ] `ruff check packages/ai-parrot/src/parrot/knowledge/wiki/project.py`

---

## Test Specification

```python
# tests/knowledge/wiki/test_project_namespaces.py
import json, os, stat
import pytest
from pydantic import ValidationError
from parrot.knowledge.wiki.project import (
    GlobalWikiRegistry, WikiNamespaceConfig, WikiProjectConfig,
    global_registry_path, load_global_registry, merge_namespaces,
    save_global_registry, validate_namespace_name,
)

def test_exactly_one_source():
    WikiNamespaceConfig(path="../asyncdb")
    with pytest.raises(ValidationError): WikiNamespaceConfig()
    with pytest.raises(ValidationError): WikiNamespaceConfig(path="a", vault="b")

def test_database_forces_arangodb():
    assert WikiNamespaceConfig(database="wiki_legal").backend == "arangodb"

@pytest.mark.parametrize("bad", ["all", "local", "a::b", "", "-x"])
def test_reserved_and_invalid_names(bad):
    with pytest.raises(ValueError): validate_namespace_name(bad)

def test_legacy_config_without_namespaces_loads(tmp_path):
    cfg = WikiProjectConfig.model_validate({"wiki_name": "x"})
    assert cfg.namespaces == {}

def test_registry_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("PARROT_HOME", str(tmp_path / "home"))
    assert load_global_registry().namespaces == {}
    p = save_global_registry(GlobalWikiRegistry(namespaces={"n": WikiNamespaceConfig(store="/s")}))
    assert p == global_registry_path()
    assert stat.S_IMODE(p.stat().st_mode) == 0o600
    assert load_global_registry().namespaces["n"].kind == "store"

def test_merge_repo_wins():
    m = merge_namespaces({"a": WikiNamespaceConfig(path="r")}, {"a": WikiNamespaceConfig(path="g"), "b": WikiNamespaceConfig(path="g")})
    assert m["a"][0].path == "r" and m["a"][1] == "repo" and m["b"][1] == "global"
```

---

## Agent Instructions

1. Read the spec §2 Data Models, §3 Module 1, §6, §7.
2. Verify the contract above (`grep`/`read`) before writing code.
3. Implement; run the tests listed in Acceptance Criteria.
4. Update `sdd/tasks/index/wiki-namespaces.json` → `in-progress` then `done`; move this file to
   `sdd/tasks/completed/`; fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: Claude Code (main session)
**Date**: 2026-08-23
**Notes**: WikiNamespaceConfig (+kind/target, exactly-one validator, database->arangodb), WikiProjectConfig.namespaces with key validation, GlobalWikiRegistry, parrot_home()/global_registry_path() (PARROT_HOME, read per call), atomic 0o600 save_global_registry, load_global_registry, merge_namespaces, resolve_entry_base, validate_namespace_name. 26 new unit tests. project.py stays stdlib+pydantic.

**Deviations from spec**: Applied ruff --fix UP045 (Optional -> X | None) across project.py so 'ruff check project.py' is clean; 8 of those violations pre-existed this task.
