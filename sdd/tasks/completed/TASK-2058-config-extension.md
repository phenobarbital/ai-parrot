# TASK-2058: Extend Config Models for ArangoDB Backend

**Feature**: FEAT-400 — WikiToolkit ArangoDB Backend
**Spec**: `sdd/specs/wikitoolkit-arangodb-backend.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Extends the two config models (`WikiProjectConfig` for `.parrot/wiki.json`
and `WikiConfig` for runtime) to accept `"arangodb"` as a backend value
and adds ArangoDB-specific connection fields. Corresponds to Module 2 in
the spec.

---

## Scope

- Extend `WikiProjectConfig.backend` from `Literal["sqlite", "memory"]` to
  `Literal["sqlite", "memory", "arangodb"]` in `project.py`.
- Add optional fields to `WikiProjectConfig`: `arango_database`,
  `arango_credentials_env`, `arango_text_analyzer`.
- Extend `WikiConfig.storage_backend` from `Literal["sqlite", "memory"]` to
  `Literal["sqlite", "memory", "arangodb"]` in `models.py`.
- Add a credential resolution helper function that reads `ARANGODB_*` env
  vars (or custom-prefixed env vars via `arango_credentials_env`).
- Write unit tests for the new config fields.

**NOT in scope**:
- ArangoDBWikiStore implementation (TASK-2057)
- Factory wiring (TASK-2059)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/project.py` | MODIFY | Extend `WikiProjectConfig` backend + add arango fields |
| `packages/ai-parrot/src/parrot/knowledge/wiki/models.py` | MODIFY | Extend `WikiConfig.storage_backend` |
| `tests/knowledge/wiki/test_config_arango.py` | CREATE | Tests for new config fields |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.knowledge.wiki.project import WikiProjectConfig  # verified: project.py:121
from parrot.knowledge.wiki.project import load_project_config  # verified: project.py:203
from parrot.knowledge.wiki.project import save_project_config  # verified: project.py:230
from parrot.knowledge.wiki.models import WikiConfig            # verified: models.py
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/project.py
class WikiProjectConfig(BaseModel):  # line 121
    wiki_name: str = Field(default="codebase")                          # line 139
    storage_dir: str = Field(default=".parrot/wiki")                    # line 140
    backend: Literal["sqlite", "memory"] = Field(default="sqlite")     # line 141
    include_suffixes: list[str] = Field(default_factory=list)           # line 142
    exclude_dirs: list[str] = Field(default_factory=list)               # line 143
    body_max_chars: int = Field(default=16_000, ge=1_000)               # line 144
    max_file_kb: int = Field(default=512, ge=1)                         # line 145
    claude: ClaudeIntegrationConfig = Field(...)                        # line 146
    sync_graph: bool = Field(default=False)                             # line 149

# packages/ai-parrot/src/parrot/knowledge/wiki/models.py
class WikiConfig(BaseModel):
    storage_backend: Literal["sqlite", "memory"] = Field(default="sqlite")
```

### Does NOT Exist

- ~~`WikiProjectConfig.arango_database`~~ — does not exist yet; this task adds it
- ~~`WikiProjectConfig.arango_credentials_env`~~ — does not exist yet
- ~~`WikiProjectConfig.arango_text_analyzer`~~ — does not exist yet
- ~~`WikiConfig.arango_params`~~ — does not exist; connection params resolved at wiring time

---

## Implementation Notes

### Changes to WikiProjectConfig

```python
class WikiProjectConfig(BaseModel):
    # ... existing fields unchanged ...
    backend: Literal["sqlite", "memory", "arangodb"] = Field(default="sqlite")
    arango_database: Optional[str] = Field(
        default=None,
        description="ArangoDB database name; defaults to wiki_{wiki_name}",
    )
    arango_credentials_env: str = Field(
        default="ARANGODB",
        description="Env var prefix for credentials (e.g. ARANGODB → ARANGODB_HOST, ARANGODB_PASSWORD)",
    )
    arango_text_analyzer: str = Field(
        default="text_en",
        description="ArangoSearch text analyzer for FTS",
    )
```

### Credential Resolution Helper

Add a function (in `project.py` or a new small helper):
```python
def resolve_arango_params(config: WikiProjectConfig) -> dict[str, Any]:
    prefix = config.arango_credentials_env
    return {
        "host": os.environ.get(f"{prefix}_HOST", "127.0.0.1"),
        "port": int(os.environ.get(f"{prefix}_PORT", "8529")),
        "protocol": os.environ.get(f"{prefix}_PROTOCOL", "http"),
        "username": os.environ.get(f"{prefix}_USERNAME", "root"),
        "password": os.environ.get(f"{prefix}_PASSWORD", ""),
        "database": config.arango_database or f"wiki_{config.wiki_name}",
    }
```

### Key Constraints

- Default backend must remain `"sqlite"` — no behavior change for existing users
- New fields must be `Optional` or have defaults so existing `wiki.json` files parse
- `arango_credentials_env` defaults to `"ARANGODB"` matching the existing convention

---

## Acceptance Criteria

- [ ] `WikiProjectConfig(backend="arangodb")` parses without error
- [ ] `WikiProjectConfig(backend="sqlite")` still works (default)
- [ ] `arango_database`, `arango_credentials_env`, `arango_text_analyzer` fields accepted
- [ ] Existing `.parrot/wiki.json` files without arango fields still parse
- [ ] `WikiConfig(storage_backend="arangodb")` accepted
- [ ] `resolve_arango_params()` reads env vars with configurable prefix
- [ ] Tests pass: `pytest tests/knowledge/wiki/test_config_arango.py -v`
- [ ] No linting errors

---

## Test Specification

```python
# tests/knowledge/wiki/test_config_arango.py
import pytest
from parrot.knowledge.wiki.project import WikiProjectConfig


class TestWikiProjectConfigArango:
    def test_default_backend_unchanged(self):
        config = WikiProjectConfig()
        assert config.backend == "sqlite"

    def test_arangodb_backend_accepted(self):
        config = WikiProjectConfig(backend="arangodb")
        assert config.backend == "arangodb"

    def test_arango_fields_defaults(self):
        config = WikiProjectConfig(backend="arangodb")
        assert config.arango_database is None
        assert config.arango_credentials_env == "ARANGODB"
        assert config.arango_text_analyzer == "text_en"

    def test_existing_config_no_arango_fields(self):
        config = WikiProjectConfig(wiki_name="test", backend="sqlite")
        assert config.arango_database is None
```

---

## Completion Note

Extended `WikiProjectConfig.backend` (`project.py`) and
`WikiConfig.storage_backend` (`models.py`) Literals to include
`"arangodb"`, added `arango_database`/`arango_credentials_env`/
`arango_text_analyzer` fields (all defaulted, so existing `wiki.json`
files parse unchanged and `backend="sqlite"` stays the default), and
added `resolve_arango_params(config) -> dict` in `project.py` that reads
`ARANGODB_*` (or a custom-prefixed) env vars plus the config's
`arango_database`/`wiki_name` for the default database name — mirroring
`graphindex/loader.py`'s `_resolve_arango()` convention. No credentials
are hardcoded.

13 unit tests added in `tests/knowledge/wiki/test_config_arango.py`
(config parsing, defaults, round-trip, env-var resolution with/without
overrides), all passing. Full `tests/knowledge/wiki/` suite (629 tests)
re-run to confirm no regressions from the Literal/field extensions.
`ruff check` on the two modified files shows only a single pre-existing
`UP045` finding on an unrelated line in `project.py` (`git_root:
Optional[Path]` in `find_project_root`, confirmed present before this
task's changes) — not a regression.
