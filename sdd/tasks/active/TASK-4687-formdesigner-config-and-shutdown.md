# TASK-4687: Config fields and shutdown aclose (M7 part 1)

**Feature**: FEAT-734 — Serve FormDesigner forms from a Teams agent
**Spec**: `sdd/specs/formdesigner-serve-forms.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 7**, the two non-wrapper parts: the new `formdesigner_*`
read/render fields on `MSTeamsAgentConfig` (with `{NAME}_FORMDESIGNER_*` env
fallbacks), and closing the mixin's client on `IntegrationManager.shutdown()`.

The FEAT-551 session leak is **already fixed** (ledger `a9514c9232ad` closed by
TASK-4059): `shutdown()` already closes the wrapper's FormDesigner client and
voice transcriber in a per-bot loop. This task only adds the agent's own
`aclose()` beside them. Do not re-fix the old leak.

Independent of the mixin (`aclose` is called through `getattr`), so wave 1.

**Cross-feature note**: FEAT-733 TASK-4655 also edits `models.py` (adds
`formdesigner_tenant_map`). It has not merged. Whoever lands second rebases;
fields here are additive and do not touch FEAT-733's names.

---

## Scope

- Add five dataclass fields after `prefer_id_token` (all defaulted — no breaking change):
  `formdesigner_mode: str = "remote"`, `formdesigner_base_url: Optional[str] = None`,
  `formdesigner_tenant: Optional[str] = None`, `formdesigner_public_url: Optional[str] = None`,
  `formdesigner_render_timeout: float = 15.0`.
- `__post_init__` env fallbacks: `{NAME}_FORMDESIGNER_BASE_URL`, `_TENANT`,
  `_PUBLIC_URL`, and `_MODE` (only when the field is still `"remote"`); then
  validate `formdesigner_mode in {"remote", "local"}` → `ValueError` otherwise.
- `from_dict` reads the five keys.
- `manager.py::shutdown`: inside the existing per-bot `msteams_bots` loop, after
  the voice-transcriber `try`, add an isolated `try` that awaits
  `wrapper.agent.aclose()` only when it exists and returns an awaitable.
- Tests: `test_config_env_fallbacks` (+ default/validation) in
  `test_msteams_models.py`; `test_shutdown_closes_client_sessions` in
  `test_msteams_manager_shutdown.py`.

**NOT in scope**: `formdesigner_tenant_map` / `require_signature` (FEAT-733);
any wrapper change (TASK-4693); the mixin's `aclose` body (TASK-4691).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/models.py` | MODIFY | formdesigner_* read/render fields + env fallbacks + from_dict |
| `packages/ai-parrot-integrations/src/parrot/integrations/manager.py` | MODIFY | await agent.aclose() in the per-bot close loop |
| `packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_models.py` | MODIFY | config env-fallback tests |
| `packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_manager_shutdown.py` | MODIFY | shutdown closes agent client |


---

## Codebase Contract (Anti-Hallucination)

### Verified Imports (already in models.py)
```python
from dataclasses import dataclass, field      # models.py:5
from typing import TYPE_CHECKING, Dict, List, Optional, Any   # models.py:6
from navconfig import config                  # models.py:7 — config.get(<ENV NAME>)
```

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/integrations/msteams/models.py
@dataclass
class MSTeamsAgentConfig:                                                    # line 16
    name: str                                                                # line 32
    formdesigner_api_base_path: str = "/api/v1"  # must match …              # line 66
    prefer_id_token: bool = True  # send id_token for strong JWKS verification   # line 71 <- field anchor (occurrences: 1)
    def __post_init__(self): ...                                             # line 73
                self.formdesigner_api_base_path = str(env_base_path)         # line 104 <- env anchor (occurrences: 1)
    @classmethod
    def from_dict(cls, name: str, data: Dict[str, Any]) -> "MSTeamsAgentConfig":  # line 138
            prefer_id_token=bool(data.get("prefer_id_token", True)),         # line 181 <- from_dict anchor (occurrences: 1)

# packages/ai-parrot-integrations/src/parrot/integrations/manager.py
async def shutdown(self) -> None: ...                                        # line 988
        for name, wrapper in self.msteams_bots.items():                      # line 1064
                await wrapper.close_formdesigner_client()                    # line 1067
                await wrapper.close_voice_transcriber()                      # line 1072
                self.logger.error("Error closing voice transcriber for MS Teams bot '%s': %s", name, e)  # line 1074 <- anchor (occurrences: 1)
        self.msteams_bots.clear()                                            # line ~1139

# packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_manager_shutdown.py
def _manager() -> IntegrationBotManager: ...                                 # line 12
def _fake_msteams_wrapper() -> MagicMock: ...                                # line 18 (wrapper.agent is an auto MagicMock!)
```

### Does NOT Exist
- ~~`MSTeamsAgentConfig.formdesigner_tenant_map`~~ — FEAT-733, unmerged. Do not add it here.
- ~~`MSTeamsAgentConfig.tenant`~~ — never existed; `app_tenantid` is an AAD GUID.
- ~~`AbstractBot.aclose` / `Agent.aclose`~~ — no bot base defines `aclose`; only the FEAT-734 mixin will.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-integrations/src/parrot/integrations/msteams/models.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-integrations/src/parrot/integrations/manager.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_models.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_manager_shutdown.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/msteams/models.py#MSTeamsAgentConfig",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/msteams/models.py#MSTeamsAgentConfig.from_dict",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/manager.py#IntegrationBotManager.shutdown"
  ]
}
```

---

## Implementation Notes

- **MagicMock trap**: in the existing shutdown tests `wrapper.agent.aclose` is an
  auto-created `MagicMock`; calling it returns a non-awaitable `MagicMock`. Use
  `result = closer(); if inspect.isawaitable(result): await result` so those
  tests keep passing without edits. Add `import inspect` to manager.py if absent
  (it is absent today — add it).

---

## Implementation Blueprint

### Steps (in order)
1. Add the fields, env fallbacks and `from_dict` keys — *why*: YAML-configured bots go through `from_dict`; env through `__post_init__`.
2. Add the `aclose` try-block in the shutdown loop — *why*: one failing close must not skip siblings (existing isolation test).
3. Add the tests.

### `packages/ai-parrot-integrations/src/parrot/integrations/msteams/models.py` (MODIFY) — fields
```python
# occurrences: 1 (verified: grep -c '    prefer_id_token: bool = True  # send id_token for strong JWKS verification' models.py)
# AFTER — insert below `    prefer_id_token: bool = True  # send id_token for strong JWKS verification` (verified: models.py:71)
    # FormDesigner form serving (FEAT-734) — read/render side used by TeamsFormDesignerMixin
    formdesigner_mode: str = "remote"  # "remote" (HTTP) | "local" (in-process FormRegistry)
    formdesigner_base_url: Optional[str] = None  # read/render origin (remote mode)
    formdesigner_tenant: Optional[str] = None  # last-resort FormDesigner tenant slug
    formdesigner_public_url: Optional[str] = None  # public origin for envelope URLs (local mode)
    formdesigner_render_timeout: float = 15.0
```

### `models.py` (MODIFY) — env fallbacks
```python
# occurrences: 1 (verified: grep -c '                self.formdesigner_api_base_path = str(env_base_path)' models.py)
# AFTER — insert below `                self.formdesigner_api_base_path = str(env_base_path)` (verified: models.py:104)
        # FormDesigner form-serving env fallbacks (FEAT-734)
        name_upper_fd = self.name.upper()
        if not self.formdesigner_base_url:
            self.formdesigner_base_url = config.get(f"{name_upper_fd}_FORMDESIGNER_BASE_URL")
        if not self.formdesigner_tenant:
            self.formdesigner_tenant = config.get(f"{name_upper_fd}_FORMDESIGNER_TENANT")
        if not self.formdesigner_public_url:
            self.formdesigner_public_url = config.get(f"{name_upper_fd}_FORMDESIGNER_PUBLIC_URL")
        if self.formdesigner_mode == "remote":
            env_mode = config.get(f"{name_upper_fd}_FORMDESIGNER_MODE")
            if env_mode:
                self.formdesigner_mode = str(env_mode).strip().lower()
        if self.formdesigner_mode not in ("remote", "local"):
            raise ValueError(
                f"MSTeams[{self.name}]: formdesigner_mode must be 'remote' or 'local', got {self.formdesigner_mode!r}"
            )
```
**Why**: fail loudly on a typo'd mode — a silent fallback to remote would send reads to the wrong place.

### `models.py` (MODIFY) — from_dict
```python
# occurrences: 1 (verified: grep -c '            prefer_id_token=bool(data.get("prefer_id_token", True)),' models.py)
# AFTER — insert below `            prefer_id_token=bool(data.get("prefer_id_token", True)),` (verified: models.py:181)
            # FormDesigner form serving (FEAT-734)
            formdesigner_mode=data.get("formdesigner_mode", "remote"),
            formdesigner_base_url=data.get("formdesigner_base_url"),
            formdesigner_tenant=data.get("formdesigner_tenant"),
            formdesigner_public_url=data.get("formdesigner_public_url"),
            formdesigner_render_timeout=float(data.get("formdesigner_render_timeout", 15.0)),
```

### `packages/ai-parrot-integrations/src/parrot/integrations/manager.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c "Error closing voice transcriber for MS Teams bot" manager.py)
# AFTER — insert below `                self.logger.error("Error closing voice transcriber for MS Teams bot '%s': %s", name, e)` (verified: manager.py:1074)
            # FEAT-734: the agent's own FormDesigner client (TeamsFormDesignerMixin.aclose)
            try:
                closer = getattr(getattr(wrapper, "agent", None), "aclose", None)
                if closer is not None:
                    result = closer()
                    if inspect.isawaitable(result):
                        self.logger.debug("Closing agent FormDesigner client for MS Teams bot '%s'", name)
                        await result
            except Exception as e:
                self.logger.error("Error closing agent resources for MS Teams bot '%s': %s", name, e)
# ALSO add `import inspect` to the stdlib imports at the top of manager.py — it is NOT imported today (verified: grep "^import inspect" manager.py -> 0 hits)
```

### Tests (MODIFY — append)
```python
# tests/integrations/msteams/test_msteams_models.py — append
class TestMSTeamsAgentConfigFormDesignerServe:
    def test_defaults_are_backward_compatible(self): ...     # FILL IN: mode "remote", others None / 15.0
    def test_config_env_fallbacks(self, monkeypatch): ...    # FILL IN: patch models.config.get (navconfig) to return
                                                             #   TESTBOT_FORMDESIGNER_BASE_URL/_TENANT/_MODE/_PUBLIC_URL
    def test_invalid_mode_raises(self): ...                  # FILL IN
    def test_from_dict_reads_fields(self): ...               # FILL IN

# tests/integrations/msteams/test_msteams_manager_shutdown.py — append
@pytest.mark.asyncio
async def test_shutdown_closes_client_sessions(): ...        # FILL IN: wrapper.agent.aclose = AsyncMock(); awaited once;
                                                             #   plus a wrapper whose agent.aclose raises -> siblings still closed
```

### FILL IN checklist
- [ ] `import inspect` added to manager.py (absent today)
- [ ] four model tests (monkeypatch `parrot.integrations.msteams.models.config.get`)
- [ ] shutdown test

---

## Acceptance Criteria

- [ ] Every new field defaulted; existing config tests pass unchanged.
- [ ] `{NAME}_FORMDESIGNER_BASE_URL` / `_TENANT` / `_MODE` / `_PUBLIC_URL` resolve in `__post_init__`.
- [ ] Invalid mode → `ValueError`.
- [ ] `shutdown()` awaits `agent.aclose()` once per bot, isolated; existing shutdown tests unchanged and passing.
- [ ] `ruff check` clean.

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_models.py -q`
- `pytest packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_manager_shutdown.py -q`


---

## Test Specification

See the appended test stubs in the blueprint (`test_config_env_fallbacks`, `test_shutdown_closes_client_sessions` are spec §4 rows).

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug formdesigner-serve-forms --feature-id FEAT-734`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/formdesigner-serve-forms.json`
4. **Verify the Codebase Contract** — confirm every import/signature before writing code; never use anything under "Does NOT Exist"
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:` marker, never change a fixed signature or path
7. **Verify** — run the Validation Commands with
   `PYTHONPATH=packages/ai-parrot-integrations/src:packages/ai-parrot/src:packages/parrot-formdesigner/src`
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4687 formdesigner-serve-forms verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
