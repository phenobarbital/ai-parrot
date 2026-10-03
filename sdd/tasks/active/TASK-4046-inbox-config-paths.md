# TASK-4046: Add inbox configuration and safe path resolution

**Feature**: FEAT-626 — wikitoolkit inbox autonomous ingestion
**Spec**: `sdd/specs/wikitoolkit-new-ingestion.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

## Context

Implements spec §3 M2 for FEAT-626. Source contracts reverified at `18c22a3fd1af1ccf6692be6f795388189e295a76`.
This is a planning artifact; implementation occurs through `$sdd-start` in the feature worktree.

## Scope

- AC18: Add InboxConfig, WikiProjectConfig.inbox, WikiEnvOverlay.inbox, the three path helpers, and validate_inbox_paths.
- Use the exact defaults and bounds in M2. Reject empty input/archive directory strings and rejected_subdir containing separators or ..; resolve all three paths inside root and reject equal or nested paths (including symlink-resolved nesting).
- Insert the project field only after the complete sqlite_performance_pragmas Field expression. Keep the generic overlay behavior; an inbox-only overlay replaces that nested model with its own defaults as other non-namespace settings do.

**NOT in scope**: unrelated refactors, dependency changes, provider SDK calls, MCP implementation, or changes outside the declared files.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/project.py` | MODIFY | Scoped M2 deliverable |
| `packages/ai-parrot/tests/knowledge/wiki/inbox/test_inbox_config.py` | CREATE | Focused tests/fixtures |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.knowledge.wiki.project import InboxConfig, WikiProjectConfig, validate_inbox_paths
```
Verified: planned in TASK-4046: packages/ai-parrot/src/parrot/knowledge/wiki/project.py#InboxConfig; packages/ai-parrot/src/parrot/knowledge/wiki/project.py:382; planned in TASK-4046: packages/ai-parrot/src/parrot/knowledge/wiki/project.py#validate_inbox_paths.

```python
from pathlib import Path
```
Verified: stdlib or existing dependency (pydantic/click/PyYAML/pytest/pytest-asyncio verified in workspace metadata).

```python
from pydantic import BaseModel, Field, model_validator
```
Verified: stdlib or existing dependency (pydantic/click/PyYAML/pytest/pytest-asyncio verified in workspace metadata).

```python
import pytest
```
Verified: stdlib or existing dependency (pydantic/click/PyYAML/pytest/pytest-asyncio verified in workspace metadata).


### Existing Signatures to Use

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#WikiConfigError`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/project.py:768
class WikiConfigError(ValueError):
```

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#WikiEnvOverlay`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/project.py:816
class WikiEnvOverlay(BaseModel):
    backend: Literal['sqlite', 'memory', 'arangodb'] | None = None
    storage_dir: str | None = None
    arango_database: str | None = None
    arango_credentials_env: str | None = None
    arango_text_analyzer: str | None = None
    namespaces: dict[str, WikiNamespaceConfig] | None = None
    vault_dir: str | None = None
    obsidian_sync: ObsidianSyncConfig | None = None
    sync_graph: bool | None = None
    body_max_chars: int | None = Field(default=None, ge=1000)
    max_file_kb: int | None = Field(default=None, ge=1)
    include_suffixes: list[str] | None = None
    exclude_dirs: list[str] | None = None
    claude: ClaudeIntegrationConfig | None = None
```

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#WikiProjectConfig`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/project.py:382
class WikiProjectConfig(BaseModel):
    wiki_name: str = Field(default='codebase')
    storage_dir: str = Field(default=f'{PARROT_DIR}/wiki')
    backend: Literal['sqlite', 'memory', 'arangodb'] = Field(default='sqlite')
    include_suffixes: list[str] = Field(default_factory=list)
    exclude_dirs: list[str] = Field(default_factory=list)
    body_max_chars: int = Field(default=16000, ge=1000)
    max_file_kb: int = Field(default=512, ge=1)
    claude: ClaudeIntegrationConfig = Field(default_factory=ClaudeIntegrationConfig)
    sync_graph: bool = Field(default=False)
    arango_database: str | None = Field(default=None, description='ArangoDB database name; defaults to wiki_{wiki_name}')
    arango_credentials_env: str = Field(default='ARANGODB', description='Env var prefix for credentials (e.g. ARANGODB -> ARANGODB_HOST, ARANGODB_PASSWORD)')
    arango_text_analyzer: str = Field(default='text_en', description='ArangoSearch text analyzer for FTS')
    vault_dir: str | None = Field(default=None, description='Obsidian vault directory served by the wiki MCP server; absolute, or relative to the project root. When omitted, the project root itself is used if it is a vault (.obsidian/).')
    namespaces: dict[str, WikiNamespaceConfig] = Field(default_factory=dict, description='Federated namespaces declared by this repo, keyed by name. Repo entries override same-named global registry entries.')
    obsidian_sync: ObsidianSyncConfig | None = Field(default=None, description='Settings for `wikitoolkit sync obsidian`: which categories sync into the vault and which folder each one maps onto.')
    symbol_depth: int = Field(default=2, ge=1, le=6, description='Maximum symbol nesting depth persisted as sym: pages (FEAT-498) — 1 = top-level declarations only, 2 = top-level plus direct members.')
    structural_backend: bool = Field(default=True, description='Kill switch for the optional ast-grep structural extraction seam (FEAT-498). When False, scanners always use their tree-sitter/heuristic tiers even if ast-grep-py is installed.')
    decisions: DecisionConfig = Field(default_factory=DecisionConfig, description='ADR decision-plane settings (FEAT-578): discovery globs, inventory bound, and the opt-in candidate-generation budget. Generation is disabled by default.')
    schema_plane: SchemaPlaneConfig = Field(default_factory=SchemaPlaneConfig, alias='schema', description='SQL schema plane settings (FEAT-600): declared sources (env NAMES only), staleness policy.')
    sqlite_busy_timeout: float = Field(default=15.0, ge=1.0, le=120.0, description="Seconds a SQLite connection waits for the writer lock before giving up (FEAT-557). Bounds the wait for every wiki reader and writer on this plane; an exhausted wait surfaces as a typed WikiStoreBusy rather than 'database is locked'.")
    sqlite_performance_pragmas: bool = Field(default=False, description='Opt-in memory-oriented SQLite pragmas (mmap_size, cache_size, temp_store) (FEAT-557). Off by default so that N concurrent agents do not each map excessive memory. The safe pragmas (busy_timeout, synchronous=NORMAL, 64 MiB journal_size_limit) are always applied and are not gated by this flag.')
```

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#WikiProjectConfig.db_path`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/project.py:560
    def db_path(self, root: Path) -> Path:
```

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#WikiProjectConfig.storage_path`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/project.py:555
    def storage_path(self, root: Path) -> Path:
```

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#load_effective_config`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/project.py:933
def load_effective_config(root: Path, env: str | None = None) -> WikiEffectiveConfig:
```


### Does NOT Exist

- InboxConfig and the three inbox path helpers do not exist before this task.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/project.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/inbox/test_inbox_config.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#WikiConfigError",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#WikiEnvOverlay",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#WikiProjectConfig",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#WikiProjectConfig.db_path",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#WikiProjectConfig.storage_path",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#load_effective_config"
  ]
}
```

## Implementation Notes

Independent M2 deliverable; owns packages/ai-parrot/src/parrot/knowledge/wiki/project.py. No prerequisite-created symbol is consumed.

Follow Python 120-column black formatting, strict annotations and Google-style docstrings. Keep I/O off the event loop. Merge imports into the existing import groups; do not duplicate them. All FILL IN markers are planning-only and must be removed from completed implementation.

## Implementation Blueprint

### Steps (in order)

1. Reverify the quoted contracts and dependency outputs before editing — because concurrently landing features may move anchors.
2. Apply the declared per-file blocks and complete only the bounded gaps in Scope — because public signatures and ownership are fixed.
3. Implement the named failure-path tests using temporary resources and fake model responses — because success-only coverage misses the lifecycle guarantees.
4. Run the exact Validation Commands and lint touched Python files — because unchanged defaults and failure behavior are the acceptance evidence.

### `packages/ai-parrot/src/parrot/knowledge/wiki/project.py` (MODIFY)

Verified attachment points (literal `grep -F -c` counts):

- `class ObsidianSyncConfig(BaseModel):` — occurrences: 1; `packages/ai-parrot/src/parrot/knowledge/wiki/project.py:283`.
- `    sqlite_performance_pragmas: bool = Field(` — occurrences: 1; `packages/ai-parrot/src/parrot/knowledge/wiki/project.py:509`.
- `    def db_path(self, root: Path) -> Path:` — occurrences: 1; `packages/ai-parrot/src/parrot/knowledge/wiki/project.py:560`.
- `    claude: ClaudeIntegrationConfig | None = None` — occurrences: 1; `packages/ai-parrot/src/parrot/knowledge/wiki/project.py:864`.

Insert the project field after the Field expression closes at line 519, not directly after its opening line. Add methods after the complete db_path method.
```python
# MODIFY: InboxConfig before ObsidianSyncConfig; helpers beside storage_path/db_path.
from pathlib import Path
from pydantic import BaseModel, Field, model_validator

class InboxConfig(BaseModel):
    """Repository-contained inbox, archive and projection settings."""
    dir: str = Field(default="inbox")
    archive_dir: str = Field(default=f"{PARROT_DIR}/archive")
    rejected_subdir: str = Field(default="rejected")
    markdown_dir: str | None = Field(default=None)
    date_format: str = Field(default="%Y-%m-%d")
    stage_git: bool = Field(default=True)
    max_candidates: int = Field(default=20, ge=1, le=100)
    lock_timeout: float = Field(default=30.0, ge=0.0)
    @model_validator(mode="after")
    def _validate_layout(self) -> "InboxConfig":
        """Reject empty paths and unsafe rejected subdirectory names."""
        # FILL IN: M2 layout validation; retain root-dependent checks below.
        raise NotImplementedError

def validate_inbox_paths(root: Path, inbox: Path, archive: Path, markdown: Path) -> None:
    """Raise WikiConfigError for escapes, equality or nested output/input directories."""
    # FILL IN: resolve paths and compare containment pairwise (AC18).
    raise NotImplementedError

# In WikiProjectConfig after the complete sqlite_performance_pragmas Field:
# inbox: InboxConfig = Field(default_factory=InboxConfig)
# Add the following methods inside WikiProjectConfig after db_path:
def inbox_path(self, root: Path) -> Path:
    """Resolve inbox.dir against the repository root."""
    path = Path(self.inbox.dir)
    return path if path.is_absolute() else root / path

def archive_path(self, root: Path) -> Path:
    """Resolve inbox.archive_dir against the repository root."""
    path = Path(self.inbox.archive_dir)
    return path if path.is_absolute() else root / path

def inbox_markdown_path(self, root: Path) -> Path:
    """Resolve explicit projection path or use storage_path(root)/inbox."""
    # FILL IN: preserve the None default and absolute paths (M2).
    raise NotImplementedError

# In WikiEnvOverlay after claude:
# inbox: InboxConfig | None = None
```

**Why**: Keep path validation independent of directory creation so invalid configuration cannot write outside the repository.

### `packages/ai-parrot/tests/knowledge/wiki/inbox/test_inbox_config.py` (CREATE)

```python
"""Focused FEAT-626 regression and failure-path tests."""
from pathlib import Path
import pytest
from parrot.knowledge.wiki.project import InboxConfig, WikiProjectConfig, validate_inbox_paths


def test_inbox_config_defaults_and_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Cover default, relative and absolute repository-contained paths."""
    # FILL IN: Arrange isolated fakes and assert this named behavior; see Test Specification.
    raise NotImplementedError

def test_env_overlay_merges_inbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify an inbox.dir-only overlay retains model defaults."""
    # FILL IN: Arrange isolated fakes and assert this named behavior; see Test Specification.
    raise NotImplementedError

def test_validate_inbox_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Reject escapes, equality, nesting, symlinks and unsafe rejected_subdir."""
    # FILL IN: Arrange isolated fakes and assert this named behavior; see Test Specification.
    raise NotImplementedError
```

**Why**: Use temporary files and stub adapters; assert observable state and side effects, never call providers.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/project.py` — complete the bounded behavior and test assertions above; preserve fixed signatures and remove planning markers.
- [ ] `packages/ai-parrot/tests/knowledge/wiki/inbox/test_inbox_config.py` — complete the bounded behavior and test assertions above; preserve fixed signatures and remove planning markers.

## Acceptance Criteria

- [ ] AC18: Add InboxConfig, WikiProjectConfig.inbox, WikiEnvOverlay.inbox, the three path helpers, and validate_inbox_paths.
- [ ] Use the exact defaults and bounds in M2. Reject empty input/archive directory strings and rejected_subdir containing separators or ..; resolve all three paths inside root and reject equal or nested paths (including symlink-resolved nesting).
- [ ] Insert the project field only after the complete sqlite_performance_pragmas Field expression. Keep the generic overlay behavior; an inbox-only overlay replaces that nested model with its own defaults as other non-namespace settings do.
- [ ] All declared tests pass; no unfinished implementation placeholders remain; touched Python files pass ruff check.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/inbox/test_inbox_config.py -q`
- `pytest tests/knowledge/wiki/test_project_sqlite_config.py -q`

Run in the activated repository environment; in a feature worktree set `PYTHONPATH=packages/ai-parrot/src`. Store test logs under `artifacts/logs/`.

## Test Specification

- Use tmp_path and explicit custom storage_dir. Check no filesystem writes occur during validation.
- Parametrize every ordered pair of equal/nested paths; include absolute outside-root paths and symlink escapes.

## Agent Instructions

1. Use `$sdd-start TASK-4046`; let it provision the feature worktree. Do not implement on dev.
2. Read the spec and this task; verify dependencies are done in `sdd/tasks/index/wikitoolkit-new-ingestion.json`.
3. Reverify source contracts before writing. Record discovered drift and refresh this task before relying on a changed API.
4. Implement only declared files. Run the focused validation commands and the normal lint gate.
5. Commit scoped implementation and finalize through `scripts.sdd.finalize_task` with real `TaskCompletionEvidence` and the exact implementation HEAD, following the Codex adaptation contract. Do not manually move task files or use legacy close_task.sh.

## Completion Note

Pending. Populated by the finalizer from implementation and validation evidence.
