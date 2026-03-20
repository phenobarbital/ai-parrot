# TASK-284: BotManager.load_bots — Gate registry and database steps

**Feature**: BotManager Initialization Flags Decoupling (FEAT-042)
**Spec**: `sdd/specs/decoupling-db-bots-botmanager.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 1h)
**Depends-on**: TASK-283
**Assigned-to**: claude-session

---

## Context

> Wraps the AgentRegistry block and the `_load_database_bots` call in
> `load_bots()` behind `self.enable_registry_bots` and
> `self.enable_database_bots` respectively.
> Implements spec Section 3 Module 3 and Section 4 "load_bots gated execution".

---

## Scope

Modify the `load_bots` method in `parrot/manager/manager.py` (currently
around lines 194–223).

**NOT in scope**: Any other methods or files.

---

## Files to Modify

| File | Action |
|---|---|
| `parrot/manager/manager.py` | MODIFY |

---

## Change Specification

The current `load_bots` method performs these steps unconditionally:
1. `registry.load_modules()`
2. `registry.discover_config_agents()`
3. `registry.load_agent_definitions()` (if definitions_dir exists)
4. `registry.instantiate_startup_agents(app)`
5. `_load_database_bots(app)`
6. `_log_final_state()`

Wrap steps 1–4 in `if self.enable_registry_bots:` and step 5 in
`if self.enable_database_bots:`:

```python
async def load_bots(self, app: web.Application) -> None:
    """Load and register all bots using the registry and optional database.

    Args:
        app: The aiohttp Application instance passed during startup.
    """
    self.logger.info("Starting bot loading with global registry")

    if self.enable_registry_bots:
        # Step 1: Import modules to trigger decorator registration
        await self.registry.load_modules()

        # Step 2: Register config-based agents
        config_count = self.registry.discover_config_agents()
        self.logger.info(f"Registered {config_count} agents from config")

        # Step 2b: Load YAML agent definitions from agents/agents/
        definitions_dir = self.registry.agents_dir / "agents"
        if definitions_dir.is_dir():
            def_count = self.registry.load_agent_definitions(definitions_dir)
            self.logger.info(f"Loaded {def_count} agents from YAML definitions")

        # Step 3: Instantiate startup agents
        startup_results = await self.registry.instantiate_startup_agents(app)
        await self._process_startup_results(startup_results)
    else:
        self.logger.info(
            "AgentRegistry loading skipped (enable_registry_bots=False)"
        )

    # Step 4: Load database bots
    if self.enable_database_bots:
        await self._load_database_bots(app)
    else:
        self.logger.debug(
            "Database bot loading skipped (enable_database_bots=False)"
        )

    # Step 5: Report final state
    self._log_final_state()
```

---

## Acceptance Criteria

- [ ] `load_bots()` skips all `AgentRegistry` steps when `enable_registry_bots=False`
- [ ] `load_bots()` logs `INFO` "AgentRegistry loading skipped ..." when skipped
- [ ] `load_bots()` skips `_load_database_bots()` when `enable_database_bots=False`
- [ ] `load_bots()` logs `DEBUG` "Database bot loading skipped ..." when skipped
- [ ] All registry steps execute when `enable_registry_bots=True`
- [ ] `_load_database_bots` is called when `enable_database_bots=True`
- [ ] `_log_final_state()` is always called regardless of flags
- [ ] `ruff check parrot/manager/manager.py` passes

---

## Agent Instructions

1. Read `parrot/manager/manager.py` around lines 194–230 to understand current `load_bots`
2. Replace the method body per the change spec above
3. Run `ruff check parrot/manager/manager.py` and fix issues
4. Update `sdd/tasks/.index.json` → `"done"`
5. Move this file to `sdd/tasks/completed/TASK-284-load-bots-gating.md`
6. Fill in the Completion Note below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-03-10
**Notes**: Wrapped AgentRegistry steps 1–3 in `if self.enable_registry_bots:` block with INFO-level skip log. Wrapped `_load_database_bots(app)` call in `if self.enable_database_bots:` block with DEBUG-level skip log. `_log_final_state()` is always called. Updated docstring to Google-style. No new ruff issues introduced.
