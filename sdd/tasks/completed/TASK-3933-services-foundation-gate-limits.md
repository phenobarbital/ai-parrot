# TASK-3933: Services foundation: StudioLimits, class allowlist, StudioToolingGate, StudioServices factory

**Feature**: FEAT-621 — Agent Studio — Database-Backed Storage
**Spec**: `sdd/specs/agentstudio-db-storage.spec.md`
**Spec wave**: W2 — Agent/asset/tooling services (M5, part 1: foundation)
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3930
**Assigned-to**: unassigned

---

## Context

Spec §2.5 (service constructor, `StudioLimits`, bot-class allowlist), §2.5b (`StudioToolingGate` — the storage-side
call into the host-owned tenant tooling policy), §2.4 (`STUDIO_TENANT_CONFIG_KEYS`), §3 Module 5. Module 6 allows
splitting services into a `services/` package when it exceeds 500 lines; the four services plus helpers clearly do,
so the package is created up front (import path `parrot.handlers.studio.storage.services` unchanged).

---

## Scope

- `services/__init__.py`: module-level `__getattr__` lazy export table mapping every public service name to its
  submodule (`StudioAgentService`→`agents`, `StudioAssetService`→`assets`, `StudioToolingService`→`tooling`,
  `StudioDraftService`→`drafts`, `StudioSkillCatalogService`→`catalog`, foundation names→`_common`), so later tasks
  never edit this file.
- `services/_common.py`: `StudioLimits` (from config, defaults per §2.5 table), `StudioClassAllowlist`
  (`parrot.bots.__all__` + `app["studio_class_allowlist"]`; tenant partitions only), `StudioToolingGate`
  (`enforce(part, tooling, *, agent_id, actor, phase)` → `StudioToolingRefused`), `validate_definition_for(part, d)`
  (bot class, tenant config keys → 422 `unsupported_config_key`, visibility domain, tenant None ⇒ private),
  `validate_asset_input(limits, asset)` (per-kind size → 413, text only → 415, identity/kb/skills filename rules,
  skill frontmatter), `normalized_tooling_for(definition, tooling_rows)` (same `normalize_tooling` the builder uses,
  with `definition.tools`), `studio_runtime_dir()` (resolves `STUDIO_RUNTIME_DIR`, default
  `<tempdir>/parrot-studio-<pid>`, never under `AGENTS_DIR` — shared by the catalogue index and the runtime),
  `StudioServices` dataclass and `build_studio_services(app, repos)`.

**NOT in scope**: The service classes themselves (TASK-3934..17); defining the tooling policy (TOOLKITS).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/studio/storage/services/__init__.py` | CREATE | lazy export table (PEP 562 __getattr__) |
| `packages/ai-parrot-server/src/parrot/handlers/studio/storage/services/_common.py` | CREATE | limits, allowlist, gate, validators, StudioServices, build_studio_services |
| `packages/ai-parrot-server/tests/studio/storage/test_service_common.py` | CREATE | DB-free unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified code references. Use these exact imports, names and signatures. Anything not listed:
> verify it exists (`grep`/`read`) before using it.

### Verified Imports
```python
import parrot.bots as bots_module                   # catalog.py:23 — `bots_module.__all__` is the allowlist source (catalog.py:96-104)
from parrot.tools.spec import NormalizedTooling, normalize_tooling, ToolkitSpec, AgentMCPServerSpec   # tooling_store.py:23-33
from parrot.bots.prompts.identity import IDENTITY_FILES          # files.py:19 ; tuple at identity.py:27
from parrot.handlers.studio.files import _StudioFilesMixin       # staticmethods _validate_kind_filename :120, _validate_skill_content :130
from parrot.handlers.studio.storage.repositories import StudioRepositories   # TASK-3930
from parrot.handlers.studio.storage.models import (StudioPartition, StudioAgentDefinition, StudioAssetInput,
    StudioAssetTooLarge, StudioToolingRefused, STUDIO_TENANT_CONFIG_KEYS)    # TASK-3922
from navconfig import config                                      # conf.py:6
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/manager/manager.py
    def get_bot_class(self, bot_name: str) -> Optional[Type]   # :267 — imports parrot.agents.<name.lower()> (:291-296);
                                                               #   GLOBAL partition only (today's resolution)
```

### Does NOT Exist
- ~~`parrot.tools.tooling_policy`~~ (`TenantToolingPolicy`, `enforce_tenant_tooling`, `ToolingSubject`,
  `TenantToolingRefused`, `get_tenant_tooling_policy`) — **not on `dev` @ 32b1a45d4**; provided by TOOLKITS Wave 1
  (M7 core). Verify the merged signatures before coding: `enforce_tenant_tooling(app, tooling, *, subject)`,
  `ToolingSubject(tenant, agent_id, actor, phase)`, refusal code `tooling_not_permitted`.
- ~~`StudioLimits`, `StudioClassAllowlist`, `StudioToolingGate`, `StudioServices`~~ — created here.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/storage/services/__init__.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/storage/services/_common.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/tests/studio/storage/test_service_common.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/files.py#_StudioFilesMixin._validate_kind_filename",
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/files.py#_StudioFilesMixin._validate_skill_content",
    "sym:packages/ai-parrot/src/parrot/tools/spec.py#normalize_tooling"
  ]
}
```

---

## Implementation Notes

- Parallelism: types StudioServices over StudioRepositories from TASK-3930 (storage/repositories.py); creates services/__init__.py (lazy export table, written once) and services/_common.py that TASK-3934..19 import
- Cross-feature ordering: X16 "Cross-spec waits" — STORAGE W2 services need TOOLKITS Wave 1 (M7 core: `parrot/tools/tooling_policy.py` with `enforce_tenant_tooling`, `ToolingSubject`, `TenantToolingRefused`, `get_tenant_tooling_policy`) merged first. Do not start before it is on `dev`.
- Error → HTTP mapping is the handlers' (W3): 413 `asset_too_large` / `agent_assets_quota`, 415
  `binary_assets_unsupported`, 422 `unsupported_config_key`, 422 `tooling_not_permitted`. Give each exception a
  `code` attribute carrying the X14 code so handlers map uniformly.
- Text-only rule: `content_type` must start with `text/` (else 415); the DB ceiling (1 MiB) is never the first guard.
- `build_studio_services` imports the per-service modules inside the function body: they land in TASK-3934..17
  and the function is first exercised end-to-end in TASK-3944.

### Common constraints (all FEAT-621 tasks)
- Contract verified against `dev` @ `32b1a45d4` (2026-09-30). Earlier FEAT-621 tasks shift line numbers:
  re-run every `grep -c` before editing and fix this file first if an anchor moved.
- Async throughout; the pool is the host's `app["database"]` (asyncdb `pg` pool); no sync driver, no second pool.
- Raw parametrised SQL (`$1…$n`), never value interpolation; schema literal `navigator`.
- Transactions only through `studio_transaction`; statements only through `_exec` (spec §2.5a).
- Pydantic for payloads, frozen dataclasses for records; `self.logger` in views,
  `logging.getLogger("Parrot.AgentStudio.Storage")` in storage/services/runtime.
- ARCHITECTURE Rule 4: functions ≤ 60 lines, cyclomatic complexity ≤ 10, modules ≤ 500 lines.
- **Database rule** (spec §4): integration tests read `TEST_STUDIO_PG_DSN` and `pytest.skip` with a reason when it is
  unset. Point it at a PostgreSQL ≥ 14 database dedicated to this worktree — the fixtures truncate `navigator.ai_*`.
- **Request/session rule** (spec §4, ARCHITECTURE R6): handler tests use `aiohttp_client` with the real session
  middleware or `make_mocked_request(..., app=app)` + `request["NAV_SESSION"] = SessionData(...)`; never a `Mock`
  with a hand-set `.session`. Each new assertion is mutation-checked (revert the guarded line ⇒ RED).
- Worktree tests: prefix with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src` as needed;
  never `uv sync` inside a worktree.

---

## Implementation Blueprint

> Write each block to its declared path nearly verbatim, then complete every `# FILL IN:` marker. Never change a
> signature, class name or file path the blueprint fixes (they come from spec §2.4/§2.5/§3 skeletons).

### Steps (in order)
1. `_common.py` (block below), 2. `__init__.py` lazy table, 3. tests (policy patched at the
   `parrot.tools.tooling_policy` boundary — a third-party-to-storage module we call, not request plumbing).

### `packages/ai-parrot-server/src/parrot/handlers/studio/storage/services/__init__.py` (CREATE)
```python
"""Agent Studio services (spec §2.5). Lazy exports: each service lives in its own submodule."""
from importlib import import_module
from typing import Any

_EXPORTS = {
    "StudioLimits": "_common", "StudioClassAllowlist": "_common", "StudioToolingGate": "_common",
    "StudioServices": "_common", "build_studio_services": "_common",
    "StudioToolingService": "tooling", "StudioAgentService": "agents", "StudioAssetService": "assets",
    "StudioDraftService": "drafts", "StudioSkillCatalogService": "catalog",
}
__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> Any:
    if name not in _EXPORTS:
        raise AttributeError(name)
    return getattr(import_module(f".{_EXPORTS[name]}", __name__), name)
```

### `packages/ai-parrot-server/src/parrot/handlers/studio/storage/services/_common.py` (CREATE) — gate and limits
```python
@dataclass(frozen=True)
class StudioLimits:
    identity_max: int = 64 * 1024
    kb_max: int = 256 * 1024
    skills_max: int = 128 * 1024
    agent_total_max: int = 4 * 1024 * 1024

    @classmethod
    def from_config(cls) -> "StudioLimits":
        # FILL IN: STUDIO_ASSET_MAX_BYTES_IDENTITY/_KB/_SKILLS, STUDIO_AGENT_MAX_ASSET_BYTES via config.getint.
        raise NotImplementedError


class StudioToolingGate:
    def __init__(self, app: web.Application) -> None:
        self._app = app

    def enforce(self, part: StudioPartition, tooling: NormalizedTooling, *, agent_id: UUID | None,
                actor: str | None, phase: Literal["write", "activate", "build"]) -> None:
        """enforce_tenant_tooling on the FINAL normalised tooling; TenantToolingRefused → StudioToolingRefused."""
        from parrot.tools.tooling_policy import TenantToolingRefused, ToolingSubject, enforce_tenant_tooling
        try:
            enforce_tenant_tooling(self._app, tooling,
                                   subject=ToolingSubject(tenant=part.tenant, agent_id=agent_id, actor=actor, phase=phase))
        except TenantToolingRefused as exc:
            raise StudioToolingRefused(str(exc)) from exc
# FILL IN: StudioClassAllowlist, validate_definition_for, validate_asset_input, normalized_tooling_for,
#   studio_runtime_dir(), StudioServices (repos, agents, assets, tooling, drafts, skills),
#   build_studio_services(app, repos).
```

### `packages/ai-parrot-server/tests/studio/storage/test_service_common.py` (CREATE)
```python
"""FEAT-621 M5 foundation — limits, allowlists, gate (DB-free)."""
# FILL IN: test_limits_per_kind (64 KiB identity OK, +1 → StudioAssetTooLarge); test_binary_content_type_refused
#   (application/pdf → code binary_assets_unsupported); test_class_allowlist_tenant_vs_global ("Foo" refused on a
#   tenant partition, allowed on GLOBAL); test_tenant_config_keys_allowlist (tenant + any config key →
#   unsupported_config_key; GLOBAL passes); test_gate_maps_refusal (patched enforce_tenant_tooling raising
#   TenantToolingRefused → StudioToolingRefused); test_lazy_exports.
```

### FILL IN checklist
- [ ] `from_config`, allowlist, four validators, container + factory.
- [ ] six tests.

---

## Acceptance Criteria

- [ ] Per-kind size limits and the total quota constant per §2.5 (`test_limits_per_kind`).
- [ ] Non-text content → 415 code (`test_binary_content_type_refused`).
- [ ] Tenant `bot_class` limited to `parrot.bots.__all__` + host additions; GLOBAL unchanged (`test_class_allowlist_tenant_vs_global`).
- [ ] Tenant `config` keys outside `STUDIO_TENANT_CONFIG_KEYS` → 422 `unsupported_config_key` (`test_tenant_config_keys_allowlist`).
- [ ] `StudioToolingGate.enforce` re-raises policy refusals as `StudioToolingRefused` (AC13 groundwork).
- [ ] `ruff check` clean on every touched Python file; new functions within Rule-4 budgets (`flake8` complexity).

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/studio/storage/test_service_common.py -q`

---

## Test Specification

| Test | Covers |
|---|---|
| `test_limits_per_kind` | §2.5 limits |
| `test_binary_content_type_refused` | §2.9 415 |
| `test_class_allowlist_tenant_vs_global` | §2.5 allowlist |
| `test_tenant_config_keys_allowlist` | §2.4 |
| `test_gate_maps_refusal` | §2.5b |
| `test_lazy_exports` | package layout |

---

## Agent Instructions

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug agentstudio-db-storage --feature-id FEAT-621`).
2. Read the spec sections cited in Context; check every `Depends-on` task is `"done"` in
   `sdd/tasks/index/agentstudio-db-storage.json`.
3. Verify the Codebase Contract anchors (`grep -c`) before editing; fix stale entries in this file first.
4. Set this task `"in-progress"` in the index (with `started_at`) and commit only the index.
5. Implement exactly the files listed, starting from the Blueprint; no refactors outside scope.
6. `ruff check --fix` the touched Python files; run the Validation Commands.
7. Commit code only (never `git add .`/`-A`):
   `feat(agentstudio-db-storage): TASK-3933 — Services foundation: StudioLimits, class allowlist, StudioToolingGate, StudioServices factory`.
8. Close with `scripts/sdd/close_task.sh TASK-3933 agentstudio-db-storage verified` and fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (sonnet)
**Date**: 2026-10-01
**Notes**: services/ package: lazy __init__, _common.py (limits, allowlist, gate, validators incl. safe asset names [no traversal/absolute/backslash/NUL] and per-kind 413, factory). 21 DB-free tests; 7 guards mutation-checked RED (text/ check, NUL/backslash, traversal, size cap, tenant config keys, tenant allowlist, GLOBAL-private visibility). Extra exceptions with X14 'code' defined in _common (StudioValidationError, StudioBinaryAssetRefused, StudioAssetFileTooLarge, StudioAgentAssetsQuota) because models.py is outside this task's file list; the gate sets code/reason/item on StudioToolingRefused instances. TOOLKITS tooling_policy verified present on this branch.

**Deviations from spec**: added validate_visibility() helper and optional allowlist/visibility kwargs on validate_definition_for
