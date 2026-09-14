# TASK-3222: WikiProjectConfig SQLite settings

**Feature**: FEAT-557 — wikitoolkit SQLite concurrency hardening
**Spec**: `sdd/specs/wikitoolkit-sqlite-optimizations.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 (the config half). FEAT-557's two operator-facing settings need to be
persisted in `.parrot/wiki.json` and validated. This task adds ONLY the two fields; the
forwarding of their values into store/manager constructors is TASK-3223.

It is fully **parallel-safe**: it touches only `project.py` and depends on nothing, so it
can run alongside the entire `store.py` chain.

---

## Scope

- Add `sqlite_busy_timeout: float = 15.0` (validated 1–120) to `WikiProjectConfig`.
- Add `sqlite_performance_pragmas: bool = False`.
- Guarantee legacy `.parrot/wiki.json` files (written before these fields existed)
  deserialize unchanged and pick up the defaults.

**NOT in scope**: forwarding these into any constructor (TASK-3223); the `status` display
(TASK-3225); `SQLitePragmaPolicy` itself (TASK-3216); the env overlay
(`WikiEnvOverlay`) unless the AC below forces it.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/project.py` | MODIFY | Two new validated fields on `WikiProjectConfig` |
| `tests/knowledge/wiki/test_project_sqlite_config.py` | CREATE | Defaults, bounds, legacy round-trip |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

Already present at the top of `project.py`: `json`, `Path`, `Literal`,
`BaseModel`, `Field`, `field_validator`. Add NO new imports.

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/project.py
PARROT_DIR = ".parrot"                                        # line 34
CONFIG_FILENAME = "wiki.json"                                 # line 37
LOCK_FILENAME = "wiki.lock"                                   # line 40

class WikiProjectConfig(BaseModel):                           # line 365
    # docstring 366-396; FIELD BLOCK is lines 398-458.
    # The LAST field in that block, and your insertion anchor:
    structural_backend: bool = Field(                         # line ~451
        default=True,
        description=(
            "Kill switch for the optional ast-grep structural extraction "
            "seam (FEAT-498). When False, scanners always use their "
            "tree-sitter/heuristic tiers even if ast-grep-py is installed."
        ),
    )                                                          # ends line 458

    @field_validator("namespaces")                            # line 460
    @classmethod
    def _validate_namespace_names(cls, ...):                  # line 462
    def graph_path(self, root: Path) -> Path:                 # line 468
    def storage_path(self, root: Path) -> Path:               # line 472
    def db_path(self, root: Path) -> Path:                    # line 477
    def is_built(self, root: Path) -> bool:                   # line 481

def config_path(root: Path) -> Path:                          # line 635
class WikiConfigError(ValueError):                            # line 663
def load_project_config(root: Path) -> WikiProjectConfig:     # line 667
def save_project_config(root: Path, config: WikiProjectConfig) -> Path:   # line 692
```

`load_project_config` body — **project.py:681-690**, verbatim:
```python
    path = config_path(root)
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return WikiProjectConfig.model_validate(data)
        except (OSError, ValueError) as exc:
            raise WikiConfigError(f"Invalid wiki config at {path} — fix or remove it: {exc}") from exc
    return WikiProjectConfig(wiki_name=root.name or "codebase")
```

`save_project_config` body — **project.py:701-708**:
```python
    path = config_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(config.model_dump(mode="json"), indent=2) + "\n",
        encoding="utf-8",
    )
    return path
```

### Does NOT Exist

- ~~`WikiProjectConfig.sqlite_busy_timeout` / `.sqlite_performance_pragmas`~~ — neither
  exists today; this task creates them.
- ~~`model_config = ConfigDict(extra="forbid")` on `WikiProjectConfig`~~ — it is a plain
  `BaseModel`, so Pydantic v2's default `extra="ignore"` applies. That is exactly why a
  legacy file loads fine; do not add `extra="forbid"`, it would break older configs.
- ~~`save_project_config` being atomic~~ — it is a direct `write_text`, no temp-file +
  rename. Do not change that here; it is out of scope.
- ~~`model_dump(exclude_defaults=True)`~~ — `save_project_config` uses
  `model_dump(mode="json")`, which writes ALL fields including defaults. Your two new
  fields WILL therefore appear in every config rewritten after this change. That is
  intended and is what AC-2 ("persists `sqlite_busy_timeout=15.0` by default") asks for.

> **Docstring drift, verified.** The class docstring's Attributes section (project.py:
> 368-396) is already stale — it omits `vault_dir`, `symbol_depth` and
> `structural_backend`. Document your two new fields via each `Field(description=...)`
> (as `structural_backend` does) rather than extending the stale block.

---

## Implementation Blueprint

### Steps (in order)
1. Append both fields at the END of the field block, after `structural_backend` — *why*:
   Pydantic field order determines `model_dump` key order and therefore the JSON key order
   written to `.parrot/wiki.json`; appending keeps every existing file's diff minimal.
2. Use `ge=1.0, le=120.0` on the timeout — *why*: AC-2 states the 1–120 window, and it must
   match `SQLitePragmaPolicy`'s bounds exactly so a config that loads can never build a
   policy that fails.
3. Give each field a `description=` — *why*: it is the repo's convention for operator-facing
   config (see `structural_backend`) and the class docstring is already stale.
4. Add NO validator and NO `__init__` override — *why*: Pydantic's `ge`/`le` already do the
   whole job; a custom validator would be a second place for the bounds to drift.
5. Test the legacy round-trip explicitly — *why*: AC-2 calls it out, and it is the one
   failure mode that would break every existing checkout on upgrade.

### `packages/ai-parrot/src/parrot/knowledge/wiki/project.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -c 'seam (FEAT-498). When False, scanners always use their ' packages/ai-parrot/src/parrot/knowledge/wiki/project.py)
# AFTER — append below the closing `    )` of the `structural_backend` field
#         (verified: project.py:451-458, the last field in the block), and BEFORE
#         `    @field_validator("namespaces")` (verified: project.py:460).

    sqlite_busy_timeout: float = Field(
        default=15.0,
        ge=1.0,
        le=120.0,
        description=(
            "Seconds a SQLite connection waits for the writer lock before "
            "giving up (FEAT-557). Bounds the wait for every wiki reader "
            "and writer on this plane; an exhausted wait surfaces as a "
            "typed WikiStoreBusy rather than 'database is locked'."
        ),
    )
    sqlite_performance_pragmas: bool = Field(
        default=False,
        description=(
            "Opt-in memory-oriented SQLite pragmas (mmap_size, cache_size, "
            "temp_store) (FEAT-557). Off by default so that N concurrent "
            "agents do not each map excessive memory. The safe pragmas "
            "(busy_timeout, synchronous=NORMAL, 64 MiB journal_size_limit) "
            "are always applied and are not gated by this flag."
        ),
    )
```
**Why this shape**: the bounds mirror `SQLitePragmaPolicy` exactly (TASK-3216) so the two
validation layers can never disagree — a config that loads always yields a constructible
policy. Appending after `structural_backend` and before the `@field_validator` keeps the
field block contiguous, which is how this class is organized. Both defaults match spec §2
verbatim and are NOT renegotiable: TASK-3223 and TASK-3225 read these exact names.

### `tests/knowledge/wiki/test_project_sqlite_config.py` (CREATE)

```python
"""FEAT-557 — WikiProjectConfig SQLite settings."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from parrot.knowledge.wiki.project import (
    WikiProjectConfig,
    config_path,
    load_project_config,
    save_project_config,
)


class TestSQLiteConfigFields:
    def test_defaults(self) -> None:
        """Spec §2 defaults (AC-2)."""
        config = WikiProjectConfig()
        assert config.sqlite_busy_timeout == 15.0
        assert config.sqlite_performance_pragmas is False

    @pytest.mark.parametrize("value", [0.5, 0.0, 120.5, -1.0])
    def test_rejects_out_of_range(self, value: float) -> None:
        """Validated to 1-120 seconds (AC-2)."""
        with pytest.raises(ValidationError):
            WikiProjectConfig(sqlite_busy_timeout=value)

    @pytest.mark.parametrize("value", [1.0, 120.0])
    def test_accepts_bounds(self, value: float) -> None:
        """Both bounds are inclusive."""
        assert WikiProjectConfig(sqlite_busy_timeout=value).sqlite_busy_timeout == value

    def test_legacy_config_loads_with_defaults(self, tmp_path: Path) -> None:
        """A wiki.json written before FEAT-557 still loads (AC-2)."""
        path = config_path(tmp_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"wiki_name": "legacy", "backend": "sqlite"}),
            encoding="utf-8",
        )
        config = load_project_config(tmp_path)
        assert config.wiki_name == "legacy"
        assert config.sqlite_busy_timeout == 15.0
        assert config.sqlite_performance_pragmas is False

    def test_round_trip_persists_both_fields(self, tmp_path: Path) -> None:
        """Saving then loading preserves a non-default value."""
        # FILL IN: save a config with sqlite_busy_timeout=30.0 and
        # sqlite_performance_pragmas=True, reload it, and assert both survive —
        # bounded by AC-2 ("persists ... by default").

    def test_invalid_persisted_value_raises_wiki_config_error(self, tmp_path: Path) -> None:
        """An out-of-range value on disk is a clear config error, not a crash."""
        # FILL IN: write sqlite_busy_timeout: 999 into wiki.json and assert
        # load_project_config raises WikiConfigError — bounded by the existing
        # `except (OSError, ValueError)` wrapper at project.py:686-687 (Pydantic's
        # ValidationError subclasses ValueError, so this already works; the test
        # pins the behaviour).
```

### FILL IN checklist
- [ ] `test_round_trip_persists_both_fields`; bounded by AC-2.
- [ ] `test_invalid_persisted_value_raises_wiki_config_error`; bounded by project.py:686.

---

## Acceptance Criteria

- [ ] `WikiProjectConfig().sqlite_busy_timeout == 15.0` and
      `.sqlite_performance_pragmas is False`.
- [ ] Values below 1.0 or above 120.0 raise `ValidationError`; 1.0 and 120.0 are accepted.
- [ ] A `.parrot/wiki.json` containing none of the new keys loads and gets the defaults.
- [ ] A round-trip through `save_project_config` / `load_project_config` preserves
      non-default values.
- [ ] An out-of-range persisted value surfaces as `WikiConfigError`.
- [ ] No regression: `pytest tests/knowledge/wiki/test_env_config.py
      tests/knowledge/wiki/test_config_arango.py tests/knowledge/wiki/test_project_namespaces.py -q`
- [ ] Tests pass: `pytest tests/knowledge/wiki/test_project_sqlite_config.py -v`
- [ ] `ruff check packages/ai-parrot/src/parrot/knowledge/wiki/project.py tests/knowledge/wiki/test_project_sqlite_config.py`

---

## Test Specification

See the blueprint — the file is a complete scaffold with two `FILL IN` bodies.

---

## Agent Instructions

1. **Read the spec** — §2 Data Models (the `WikiProjectConfig` paragraph), §3 Module 3, AC-2.
2. **Check dependencies** — none. This task can run first or in parallel with any other.
3. **Verify the Codebase Contract** — confirm `WikiProjectConfig` is still at project.py:365
   and that `structural_backend` is still the last field before `@field_validator`
   (project.py:460). Update this contract FIRST if they moved.
4. **Implement** from the blueprint; complete both `FILL IN`s.
5. **Verify** every acceptance criterion.
6. **Move this file** to `sdd/tasks/completed/`; update the per-spec index; fill the note.

---

## Completion Note

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
