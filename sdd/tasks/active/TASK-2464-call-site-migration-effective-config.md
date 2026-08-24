# TASK-2464: Migrate MCP server, Claude hook, installer, and federation to the effective config

**Feature**: FEAT-461 — wikitoolkit Environment Support (env-aware config + memory sync)
**Spec**: `sdd/specs/wikitoolkit-env-support.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2462
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3. A missed call site silently uses the base config — the
spec's top risk (§7). This task migrates every non-CLI consumer of
`load_project_config()` to `load_effective_config()` so the Claude hook,
the wiki MCP server, the installer, and federation all see the env-merged
view. Env comes from the process environment ONLY in these paths — no
prompts, no file generation ever.

---

## Scope

- Migrate consumer call sites to `load_effective_config(root).config`:
  - `wiki/federation.py:228` (foreign project config for a `path`/`store`
    namespace — use the TARGET repo's effective config).
  - `wiki/claude_code/cli.py:95`
  - `wiki/claude_code/hook.py:186`
  - `wiki/claude_code/installer.py:494` and `:670`
  - `wiki/mcp_server.py:108` and `:214`
- LEAVE on raw `load_project_config` the base-config WRITE paths:
  `cli.py:1784` (`ns add` writes base config) and `cli.py:290/337` are
  TASK-2463's surface — do not touch `cli.py` in this task.
- Verify the offline-local degradation path end-to-end: local mode (sqlite
  primary) + unreachable Arango namespace → the existing `NamespaceSkip`
  machinery skips it under `DEFAULT_ARANGO_TIMEOUT`, local results still
  returned. Add a regression test if not already covered by
  `test_namespaces_e2e.py`.
- Add a guard test that greps the wiki package for remaining CONSUMER
  `load_project_config(` calls and asserts only the allowed (write-path)
  sites remain — this enforces spec acceptance criterion "all 11 call sites".
- Write/extend tests per the Test Specification.

**NOT in scope**: `cli.py` changes (TASK-2463); sync (TASK-2466/2467);
any behavior change beyond swapping the config source.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/federation.py` | MODIFY | effective config for foreign roots |
| `packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py` | MODIFY | swap both call sites |
| `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/hook.py` | MODIFY | swap call site (hook-safe import path) |
| `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py` | MODIFY | swap both call sites |
| `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/cli.py` | MODIFY | swap call site |
| `tests/knowledge/wiki/test_env_call_sites.py` | CREATE | migration + guard + offline degradation tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.project import load_project_config  # project.py:578
# From TASK-2462 (verify it landed before starting):
from parrot.knowledge.wiki.project import load_effective_config, WikiEffectiveConfig
```

### Existing Signatures to Use
```python
# Call sites to migrate (verified 2026-08-25):
# federation.py:228        foreign = load_project_config(project_root)
# claude_code/cli.py:95    config = load_project_config(root)
# claude_code/hook.py:186  config = config or load_project_config(root)
# claude_code/installer.py:494  config = config or load_project_config(root)
# claude_code/installer.py:670  config = load_project_config(root)
# mcp_server.py:108        config = load_project_config(root)
# mcp_server.py:214        config = load_project_config(root)

# packages/ai-parrot/src/parrot/knowledge/wiki/federation.py
class NamespaceSkip(BaseModel)                       # line 67
async def open_namespace_store(..., arango_timeout: float = DEFAULT_ARANGO_TIMEOUT)  # line 340
# bounded Arango probe: asyncio.wait_for(store.initialize(), timeout=timeout)  # line 335
# open-all returns (handles, skipped: list[NamespaceSkip])                     # lines 440-482
# namespace store opening passes arango_credentials_env=cfg.credentials_env    # line 194
```

### Does NOT Exist
- ~~`load_effective_config` in any of these files today~~ — this task adds
  the import; TASK-2462 created the function.
- ~~an `env` parameter on hook/MCP entry points~~ — do NOT add one; env is
  read from the process environment inside `load_effective_config`.
- ~~interactive prompts or overlay generation in hook/MCP/installer paths~~ —
  forbidden by spec (§2: "no prompts, no file generation in these paths").

---

## Implementation Notes

### Pattern to Follow
```python
# Drop-in swap, keeping the local variable a WikiProjectConfig:
config = config or load_effective_config(root).config
```

### Key Constraints
- `hook.py` runs in the PreToolUse hot path: `load_effective_config` must not
  drag new heavy imports into `project.py` (TASK-2462 guarantees this;
  verify with the hook's import test if one exists).
- Federation foreign-root resolution (federation.py:228): the FOREIGN repo's
  overlays apply to the foreign root — pass that root, not the local one.
- No behavior change other than the config source: same defaults, same
  errors (`WikiConfigError` may now also name an overlay file).

### References in Codebase
- `tests/knowledge/wiki/test_namespaces_e2e.py` — end-to-end namespace
  scenarios (FEAT-450) to extend for offline-local coverage.
- `tests/knowledge/wiki/test_federation.py` — federation test conventions.

---

## Acceptance Criteria

- [ ] All 7 listed call sites use `load_effective_config`.
- [ ] Guard test passes: no consumer `load_project_config(` calls remain in
  the wiki package outside the allowed write paths (`cli.py` surfaces owned
  by TASK-2463 and base-config save/`ns add`).
- [ ] Hook and MCP server honor `WIKI_ENV`/`ENV` from the process
  environment (test with monkeypatch).
- [ ] Offline-local degradation: unreachable Arango namespace under local
  sqlite primary → skipped with `NamespaceSkip`, bounded timeout, local
  results returned (regression test).
- [ ] All tests pass: `pytest tests/knowledge/wiki/test_env_call_sites.py tests/knowledge/wiki/test_federation.py -v`
- [ ] No linting errors on the touched files.

---

## Test Specification

```python
# tests/knowledge/wiki/test_env_call_sites.py

class TestCallSiteMigration:
    def test_mcp_server_uses_effective_config(self, repo_with_overlays, monkeypatch): ...
    def test_hook_uses_effective_config(self, repo_with_overlays, monkeypatch): ...
    def test_installer_uses_effective_config(self, repo_with_overlays, monkeypatch): ...
    def test_federation_foreign_root_uses_foreign_overlays(self, tmp_path): ...

class TestGuard:
    def test_no_stray_consumer_load_project_config_calls(self):
        """Grep the wiki package; assert only allowed write-path sites remain."""

class TestOfflineDegradation:
    async def test_unreachable_namespace_skipped_bounded(self, tmp_path): ...
```

---

## Agent Instructions

1. **Read the spec** at `sdd/specs/wikitoolkit-env-support.spec.md` (§3 Module 3, §6, §7).
2. **Check dependencies** — TASK-2462 must be in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** before writing ANY code.
4. **Update status** in `sdd/tasks/index/wikitoolkit-env-support.json` → `"in-progress"`.
5. **Implement**, then verify all acceptance criteria.
6. **Move this file** to `sdd/tasks/completed/`.
7. **Update index** → `"done"` and fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
