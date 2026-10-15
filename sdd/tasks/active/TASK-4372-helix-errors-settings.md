# TASK-4372: HelixDB error types and settings resolution

**Feature**: FEAT-670 — HelixDB graph provider
**Spec**: `sdd/specs/helixdb-provider.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

First brick of spec §3 Module 1 ("HelixDB client, settings, bootstrap, DSL helpers, extras").
Every other FEAT-670 module imports `parrot.knowledge.helix`; this task creates the two
SDK-free modules of that package: the error hierarchy (`errors.py`) and the connection
settings model + resolver (`settings.py`, spec §2 "Data Models" and §7 "Configuration
References"). Neither module imports `helixdb` — they must be importable without the extra.

---

## Scope

- Create `parrot/knowledge/helix/errors.py` with `HelixExtraMissing(ImportError)`,
  `HelixUnavailable(RuntimeError)`, `HelixWriteRejected(RuntimeError)` (the latter carries
  the offending `key`).
- Create `parrot/knowledge/helix/settings.py` with `HelixMode`, `HelixSettings`
  (fields exactly as spec §2 Data Models) plus `HelixSettings.with_database(name)`
  (a `model_copy` helper used later by the ledger / GraphIndex tenant mapping, TASK-4381/4384),
  and `resolve_helix_settings(...)`.
- Create the test package `packages/ai-parrot/tests/knowledge/helix/` (`__init__.py`) and
  `test_client_settings.py` covering settings resolution only.

**NOT in scope**: `client.py`, `bootstrap.py`, `dsl.py`, `helix/__init__.py` (TASK-4373/4374);
`WikiProjectConfig.helix_*` fields and `resolve_helix_params` (TASK-4379); extras /
`ruff.toml` (TASK-4373); `tests/knowledge/helix/conftest.py` (TASK-4373).
Do **not** create `parrot/knowledge/helix/__init__.py` here — TASK-4374 owns it (a package
without `__init__.py` is still importable as a PEP 420 namespace inside the worktree; the
tests import the submodules directly).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/helix/errors.py` | CREATE | HelixExtraMissing / HelixUnavailable / HelixWriteRejected |
| `packages/ai-parrot/src/parrot/knowledge/helix/settings.py` | CREATE | HelixMode, HelixSettings (+ with_database), resolve_helix_settings |
| `packages/ai-parrot/tests/knowledge/helix/__init__.py` | CREATE | test package marker (sibling dirs all have one) |
| `packages/ai-parrot/tests/knowledge/helix/test_client_settings.py` | CREATE | settings resolution tests |

---

## Codebase Contract (Anti-Hallucination)

Verified on dev @ `1c239a5ca` (FEAT-540 merged).

### Verified Imports
```python
from parrot.knowledge.wiki.project import resolve_setting      # verified: wiki/project.py:849
from parrot.knowledge.wiki.project import _env_credential      # verified: wiki/project.py:885 (thin wrapper: resolve_setting(key, default=default))
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/project.py:849
def resolve_setting(key: str, *, default: Any = None, explicit: Any = None,
                    project_defaults: Mapping[str, Any] | None = None) -> Any:
    # precedence: explicit → os.environ (membership, "" preserved) → navconfig → project_defaults → default
# packages/ai-parrot/src/parrot/knowledge/wiki/project.py:885
def _env_credential(key: str, default: Any) -> Any
# packages/ai-parrot/src/parrot/knowledge/wiki/project.py:903 — the model to mirror
def resolve_arango_params(config: WikiProjectConfig) -> dict[str, Any]   # prefix = config.arango_credentials_env; f"{prefix}_HOST" …
```
`wiki/project.py` stays importable on the hook path (module docstring :10); importing it from
`settings.py` is cheap (pydantic only), but `project.py` must NOT import `helix.settings` at
module scope (TASK-4379 imports it lazily inside `resolve_helix_params`).

### Does NOT Exist
- ~~`parrot.knowledge.helix`~~ (any module) — created by FEAT-670, starting here.
- ~~`HELIXDB_*` settings anywhere in the tree~~ — introduced by this task.
- ~~`resolve_helix_params`~~ — TASK-4379, not here.
- ~~A `helixdb` import in `settings.py` / `errors.py`~~ — forbidden; both are SDK-free.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/helix/errors.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/helix/settings.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/helix/__init__.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/helix/test_client_settings.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#resolve_setting",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#_env_credential"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Pydantic v2, Google docstrings, strict typing, 120 cols, no `print`.
- Env keys are `{credentials_env}_URL`, `{credentials_env}_API_KEY`, `{credentials_env}_MODE`
  (default prefix `HELIXDB`). Spec §7: `HELIXDB_MODE` **overrides** the project's `helix_mode`,
  so the `mode` argument is passed as a *project default* to `resolve_setting`, never as
  `explicit` (explicit would beat the environment).
- `HelixMode.EMBEDDED` requires `storage_dir`; the Disk root is `storage_dir / "helix"`.
  `HelixMode.MEMORY` (tests only) needs neither URL nor root.
- An invalid mode string raises `ValueError` naming the accepted values.
- `api_key` empty string ⇒ `None` (an `export HELIXDB_API_KEY=` must not send an empty bearer).

### Drift vs spec
- Spec §3 M1 says settings resolve "through `_env_credential`"; FEAT-540 made
  `_env_credential` a one-line wrapper over `resolve_setting` (`project.py:885-900`), and
  `resolve_setting` is the one that accepts `project_defaults`. Use `resolve_setting`.
- `with_database()` is not in the spec skeleton; it is added here per the task plan
  (needed by TASK-4381 `ledger_<name>` and TASK-4384 `gi_<tenant>` mappings).

---

## Implementation Blueprint

### Steps (in order)
1. Write `errors.py` — *why*: every later module maps SDK errors onto these three types (spec §7 "Errors").
2. Write `settings.py` — *why*: one resolver for every plane (spec G6).
3. Write the tests and run them — *why*: AC3/AC15 rely on the settings contract being stable.

### `packages/ai-parrot/src/parrot/knowledge/helix/errors.py` (CREATE)
```python
"""HelixDB error types shared by every FEAT-670 backend (no SDK import)."""
from __future__ import annotations


class HelixExtraMissing(ImportError):
    """``helixdb`` (or ``helixdb_uniffi`` for embedded modes) is not installed.

    The message always names the extra to install: ``ai-parrot[helixdb]`` or
    ``ai-parrot[helixdb-embedded]``.
    """


class HelixUnavailable(RuntimeError):
    """Server not reachable / not ready after the bounded probe, or embedded source refused."""


class HelixWriteRejected(RuntimeError):
    """A write batch was rejected (e.g. ``active_text_mutation_limit_exceeded``).

    Args:
        message: Human-readable reason.
        key: The record key (concept id, node id, …) that caused the rejection, when known.
    """

    def __init__(self, message: str, *, key: str | None = None) -> None:
        super().__init__(message if key is None else f"{message} (key={key!r})")
        self.key = key
```
**Why this shape**: spec §3 M1 fixes the three names and base classes; `HelixExtraMissing`
subclasses `ImportError` so existing `except ImportError` optional-extra guards keep working.

### `packages/ai-parrot/src/parrot/knowledge/helix/settings.py` (CREATE)
```python
"""HelixDB connection settings (FEAT-670 M1). SDK-free: never imports ``helixdb``."""
from __future__ import annotations

from enum import Enum
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from parrot.knowledge.wiki.project import resolve_setting  # verified: wiki/project.py:849

DEFAULT_URL = "http://127.0.0.1:6969"
DEFAULT_CREDENTIALS_ENV = "HELIXDB"


class HelixMode(str, Enum):
    """Deployment mode of one HelixDB database."""

    SERVER = "server"
    EMBEDDED = "embedded"
    MEMORY = "memory"  # tests only


class HelixSettings(BaseModel):
    """Resolved connection settings for one HelixDB database."""

    model_config = ConfigDict(frozen=True)

    mode: HelixMode = HelixMode.SERVER
    url: str = DEFAULT_URL
    api_key: str | None = None
    root: Path | None = None
    database: str
    read_only: bool = False
    probe_timeout_s: float = 5.0
    probe_retries: int = 3
    index_ready_timeout_s: float = 120.0

    def with_database(self, name: str) -> "HelixSettings":
        """Return a copy pointing at database ``name`` (same server / root / mode)."""
        return self.model_copy(update={"database": name})


def resolve_helix_settings(
    *,
    database: str,
    credentials_env: str = DEFAULT_CREDENTIALS_ENV,
    mode: str | None = None,
    storage_dir: Path | None = None,
    read_only: bool = False,
) -> HelixSettings:
    """Resolve ``{prefix}_URL`` / ``{prefix}_API_KEY`` / ``{prefix}_MODE`` into settings.

    Precedence per key (``resolve_setting``): os.environ → navconfig → ``mode`` argument
    (project default) → built-in default. ``HELIXDB_MODE`` therefore overrides a project's
    ``helix_mode``.

    Args:
        database: Logical database name (``wiki_<name>``, ``gi_<tenant>``, …).
        credentials_env: Env-var prefix.
        mode: Project-configured mode (``server`` | ``embedded`` | ``memory``).
        storage_dir: Wiki storage dir; required for embedded mode (Disk root = ``storage_dir/"helix"``).
        read_only: Open a reader (embedded) / refuse writes (server).

    Returns:
        The resolved, frozen settings.

    Raises:
        ValueError: Unknown mode, or embedded mode without ``storage_dir``.
    """
    prefix = credentials_env
    raw_mode = resolve_setting(f"{prefix}_MODE", project_defaults={f"{prefix}_MODE": mode}, default="server")
    # FILL IN: coerce raw_mode (str, case-insensitive, stripped) to HelixMode; on failure raise ValueError
    #          listing [m.value for m in HelixMode] — bounded by AC3 (never a silent fallback)
    # FILL IN: url = str(resolve_setting(f"{prefix}_URL", default=DEFAULT_URL)).rstrip("/");
    #          api_key = resolve_setting(f"{prefix}_API_KEY") with "" → None
    # FILL IN: EMBEDDED and storage_dir is None → ValueError naming f"{prefix}_MODE" and server mode;
    #          root = Path(storage_dir) / "helix" for EMBEDDED, else None
    # FILL IN: return HelixSettings(mode=..., url=..., api_key=..., root=..., database=database, read_only=read_only)
```
**Why this shape**: matches spec §2 Data Models field-for-field (frozen so a settings object
can be shared between stores safely); env-key naming mirrors `resolve_arango_params`
(`project.py:903`, prefix + suffix).

### `packages/ai-parrot/tests/knowledge/helix/__init__.py` (CREATE)
Empty file, or a one-line docstring like the sibling `tests/knowledge/wiki/__init__.py`.

### FILL IN checklist
- [ ] `settings.py::resolve_helix_settings` — mode coercion + ValueError text; bounded by AC3
- [ ] `settings.py::resolve_helix_settings` — URL/API key resolution, "" → None
- [ ] `settings.py::resolve_helix_settings` — embedded root / storage_dir guard

---

## Acceptance Criteria

- [ ] `from parrot.knowledge.helix.settings import HelixSettings, HelixMode, resolve_helix_settings` and
      `from parrot.knowledge.helix.errors import HelixExtraMissing, HelixUnavailable, HelixWriteRejected`
      work **without** `helix-db` installed (spec AC3 precondition).
- [ ] `test_resolve_helix_settings_env_chain` (spec §4, M1): os.environ → navconfig → project mode → default;
      embedded requires `storage_dir`.
- [ ] `HELIXDB_MODE` env beats the `mode` argument; `with_database()` returns a new frozen copy.
- [ ] `ruff check` clean on the two new modules.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/helix/test_client_settings.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/helix/test_client_settings.py
from pathlib import Path

import pytest

from parrot.knowledge.helix.errors import HelixExtraMissing, HelixWriteRejected
from parrot.knowledge.helix.settings import HelixMode, HelixSettings, resolve_helix_settings


@pytest.fixture(autouse=True)
def _no_ambient(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("HELIXDB_URL", "HELIXDB_API_KEY", "HELIXDB_MODE"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr("parrot.knowledge.wiki.project._navconfig", lambda: None)


def test_resolve_helix_settings_env_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    s = resolve_helix_settings(database="wiki_t")
    assert s.mode is HelixMode.SERVER and s.url == "http://127.0.0.1:6969" and s.api_key is None
    monkeypatch.setattr("parrot.knowledge.wiki.project._navconfig", lambda: {"HELIXDB_URL": "http://nav:1"})
    assert resolve_helix_settings(database="d").url == "http://nav:1"
    monkeypatch.setenv("HELIXDB_URL", "http://env:2/")
    assert resolve_helix_settings(database="d").url == "http://env:2"


def test_env_mode_overrides_project_mode(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HELIXDB_MODE", "server")
    assert resolve_helix_settings(database="d", mode="embedded").mode is HelixMode.SERVER


def test_embedded_requires_storage_dir(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        resolve_helix_settings(database="d", mode="embedded")
    s = resolve_helix_settings(database="d", mode="embedded", storage_dir=tmp_path)
    assert s.root == tmp_path / "helix"


def test_unknown_mode_rejected() -> None:
    with pytest.raises(ValueError, match="server"):
        resolve_helix_settings(database="d", mode="cloud")


def test_empty_api_key_is_none(monkeypatch) -> None:
    monkeypatch.setenv("HELIXDB_API_KEY", "")
    assert resolve_helix_settings(database="d").api_key is None


def test_custom_prefix_and_with_database(monkeypatch) -> None:
    monkeypatch.setenv("HX_URL", "http://h:3")
    s = resolve_helix_settings(database="a", credentials_env="HX")
    t = s.with_database("b")
    assert (s.database, t.database, t.url) == ("a", "b", "http://h:3")


def test_error_types() -> None:
    assert issubclass(HelixExtraMissing, ImportError)
    assert HelixWriteRejected("rejected", key="c1").key == "c1"
```

---

## Agent Instructions

1. **Work in the feature worktree** `feat-FEAT-670-helixdb-provider`
   (`python -m scripts.sdd.ensure_worktree --slug helixdb-provider --feature-id FEAT-670`), never on `dev`.
2. Read spec §2 (Data Models), §3 Module 1, §7 Configuration References.
3. Check `Depends-on` in `sdd/tasks/index/helixdb-provider.json` (none for this task).
4. Re-verify the Codebase Contract (`grep -n 'def resolve_setting' packages/ai-parrot/src/parrot/knowledge/wiki/project.py`).
5. Mark `in-progress` in the per-spec index; commit only that file.
6. Implement from the blueprint; complete every `# FILL IN:`; keep both modules SDK-free.
7. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`; `ruff check --fix` the new files.
8. Commit only the files in the table: `feat(helixdb-provider): TASK-4372 — HelixDB error types and settings resolution`.
9. `scripts/sdd/close_task.sh TASK-4372 helixdb-provider verified`, fill the Completion Note, commit SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
