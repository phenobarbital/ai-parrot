# TASK-4933: Runtime wiring — `load_experts()` in the REPL loader and `BotManager.load_bots`

**Feature**: FEAT-778 — Domain Experts
**Spec**: `sdd/specs/domain-experts.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4926
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 14, G12, §8 Q9, AC29. Neither host sees experts today: `StandaloneAgentLoader._ensure_discovered`
(REPL, `parrot agent <name>`) and `BotManager.load_bots` (server, `/api/v1/chat/<name>`) each run their own
discovery pipeline. One fail-open helper, called by both right after `load_agent_definitions`, makes every expert
reachable through the existing name resolution (`BotManager.get_bot` already falls back to
`AgentRegistry.has/get_instance`, `manager.py:905-913`; `register_instance` creates singleton metadata whose
cached instance `get_instance` returns, `registry.py:110-129`).

Default wiki for the helper (task-time decision, needed because seeding requires a writable store and no default
wiki exists): when no `wiki_toolkit` is passed, build a lightweight `LLMWikiToolkit(None, None, None, WikiConfig(…),
store=create_wiki_store(…))` over `AGENTS_DIR/.experts_wiki` (sqlite) — the same construction
`bots/github_reviewer.py:1210-1222` uses. A leading dot keeps it out of bundle discovery.

---

## Scope

- Create `experts/bootstrap.py` with `load_experts(...)`.
- REPL: call it in `StandaloneAgentLoader._ensure_discovered` after the YAML-definitions step.
- Server: add `enable_experts: bool = True` to `BotManager.__init__` and call `load_experts` in `load_bots`
  between the YAML-definitions step and "Step 3: Instantiate startup agents".
- Tests for both hosts and for fail-open.

**NOT in scope**: a `parrot experts` CLI (not added — §6 Does NOT Exist), routes (none needed), docs (TASK-4935).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/experts/bootstrap.py` | CREATE | `load_experts` |
| `packages/ai-parrot/src/parrot/cli/loaders.py` | MODIFY | REPL discovery calls `load_experts` |
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | `enable_experts` flag + call in `load_bots` |
| `packages/ai-parrot/tests/experts/test_bootstrap.py` | CREATE | Helper + REPL loader tests |
| `packages/ai-parrot-server/tests/manager/test_load_bots_experts.py` | CREATE | Server wiring tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.registry import agent_registry                         # verified: parrot/registry/__init__.py:7 (used by cli/loaders.py:21)
from parrot.cli.loaders import StandaloneAgentLoader               # verified: parrot/cli/loaders.py:90
from parrot.knowledge.wiki.models import WikiConfig                # verified: parrot/knowledge/wiki/models.py:54
from parrot.knowledge.wiki.store import create_wiki_store          # verified: parrot/knowledge/wiki/store.py:2809
from parrot.conf import AGENTS_DIR                                 # verified: parrot/conf.py:181
from parrot.experts.registry import ExpertRegistry                 # TASK-4926
# lazy, inside the helper only: from parrot_tools.wiki.toolkit import LLMWikiToolkit   # toolkit.py:48
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/cli/loaders.py
class StandaloneAgentLoader:                       # line 90
    async def _ensure_discovered(self) -> None     # line 109 — load_modules (128) → discover_config_agents (132)
        #   → if definitions_dir.is_dir(): load_agent_definitions (138) + debug log (139)
    async def load(self, name: str) -> AbstractBot # line 141 — agent_registry.get_instance(name) (158)
# packages/ai-parrot-server/src/parrot/manager/manager.py
class BotManager:                                                    # line 214
    def __init__(..., enable_registry_bots: bool = ENABLE_REGISTRY_BOTS, ...)   # param line 228; attr line 261
    async def load_bots(self, app: web.Application) -> None          # line 430; `if self.enable_registry_bots:` line 438
        #   load_agent_definitions (454) → "# Step 3: Instantiate startup agents" (457) → instantiate_startup_agents (458)
    async def get_bot(self, name, new=False, session_id="", request=None, **kwargs)   # line 790 — registry fallback 905-913
# packages/ai-parrot/src/parrot/knowledge/wiki/store.py:2809
def create_wiki_store(storage_dir: str | Path, wiki_name: str = "", backend: str = "sqlite", **kwargs) -> BaseWikiStore
# parrot_tools/wiki/toolkit.py:82 — LLMWikiToolkit(pageindex, graphindex, okf, config, agent_id="agent", store=None, confine_sources=False)
```

### Does NOT Exist
- ~~`parrot.experts.bootstrap`~~, ~~`BotManager.enable_experts`~~, ~~`agent_registry.experts`~~ — created here.
- ~~a `parrot experts` subcommand~~ — not added.
- ~~`instantiate_startup_agents` handling instances~~ — it only handles `register()`-ed factories (spec M14).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/experts/bootstrap.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/cli/loaders.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/src/parrot/manager/manager.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/experts/test_bootstrap.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/tests/manager/test_load_bots_experts.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/cli/loaders.py#StandaloneAgentLoader._ensure_discovered",
    "sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager.load_bots",
    "sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager.get_bot",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#create_wiki_store"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Fail-open: any exception inside `load_experts` is logged at ERROR with `registry.report()` so far and swallowed;
  the function returns `None`. Hosts keep starting (AC29).
- `manager.py` is a 2 400-line file under FEAT-746/747 churn: the edit is one constructor parameter, one attribute
  line and one call. Re-anchor on the quoted lines if numbers moved; never re-indent surrounding code.
- Import `load_experts` lazily inside `load_bots` / `_ensure_discovered` (keeps host import time unchanged).

---

## Implementation Blueprint

### Steps (in order)
1. `bootstrap.py`, then the two host edits, then tests.

### `packages/ai-parrot/src/parrot/experts/bootstrap.py` (CREATE)
```python
"""Load domain experts into an AgentRegistry from any host — REPL or server (FEAT-778 M14)."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from parrot.conf import AGENTS_DIR
from parrot.experts.registry import ExpertRegistry

_LOGGER = logging.getLogger(__name__)
EXPERTS_WIKI_DIRNAME = ".experts_wiki"


def _default_wiki_toolkit(agents_dir: Path) -> Any:
    """Lightweight sqlite-backed LLMWikiToolkit over AGENTS_DIR/.experts_wiki (pattern: bots/github_reviewer.py:1210)."""
    from parrot.knowledge.wiki.models import WikiConfig  # noqa: PLC0415
    from parrot.knowledge.wiki.store import create_wiki_store  # noqa: PLC0415
    from parrot_tools.wiki.toolkit import LLMWikiToolkit  # noqa: PLC0415 — tools distribution, optional

    storage = agents_dir / EXPERTS_WIKI_DIRNAME
    storage.mkdir(parents=True, exist_ok=True)
    config = WikiConfig(wiki_name="experts", storage_dir=storage, storage_backend="sqlite", sync_graph=False)
    store = create_wiki_store(storage, wiki_name="experts", backend="sqlite")
    return LLMWikiToolkit(None, None, None, config, agent_id="experts", store=store)


async def load_experts(agent_registry: Any, *, agents_dir: Path | None = None, workspace: Path | None = None,
                       wiki_toolkit: Any = None, bookstore: Any = None, enabled: bool = True) -> ExpertRegistry | None:
    """Discover, seed and register every expert; fail-open (never raises). Sets agent_registry.experts."""
    if not enabled:
        return None
    root = Path(agents_dir or AGENTS_DIR)
    registry: ExpertRegistry | None = None
    try:
        registry = ExpertRegistry(agent_registry=agent_registry, agents_dir=root, workspace=workspace,
                                  wiki_toolkit=wiki_toolkit or _default_wiki_toolkit(root), bookstore=bookstore)
        count = await registry.load()
        report = registry.report()
        _LOGGER.info("experts: %d loaded, %d skipped, %d seeded, shadowing=%s", count, len(report["skipped"]),
                     len(report["seeded"]), report["shadowing"])
        agent_registry.experts = registry
        return registry
    except Exception:  # pylint: disable=broad-except — fail-open by contract (AC29)
        _LOGGER.exception("experts: loading failed; report so far=%s", registry.report() if registry else None)
        return None
```

### `packages/ai-parrot/src/parrot/cli/loaders.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '            self.logger.debug("Discovery: %d agent(s) from YAML definitions", def_count)' packages/ai-parrot/src/parrot/cli/loaders.py)
# AFTER — insert below that line, dedented to the method body level (outside the `if definitions_dir.is_dir():`)
#         (verified: loaders.py:139)

        # Step 4: domain experts (FEAT-778) — fail-open, never blocks the REPL
        from parrot.experts.bootstrap import load_experts  # noqa: PLC0415

        await load_experts(agent_registry)
```

### `packages/ai-parrot-server/src/parrot/manager/manager.py` (MODIFY)
```python
# (a) occurrences: 1 (verified: grep -c '        enable_registry_bots: bool = ENABLE_REGISTRY_BOTS,' …/manager.py) — AFTER line 228:
        enable_experts: bool = True,
# (b) occurrences: 1 (verified: grep -c '        self.enable_registry_bots: bool = enable_registry_bots' …/manager.py) — AFTER line 261:
        self.enable_experts: bool = enable_experts
# (c) occurrences: 1 (verified: grep -c '            # Step 3: Instantiate startup agents' …/manager.py) — BEFORE line 457:
            # Step 2c: domain experts (FEAT-778) — fail-open
            from parrot.experts.bootstrap import load_experts  # noqa: PLC0415

            await load_experts(self.registry, enabled=self.enable_experts)

# FILL IN: add `enable_experts` to the __init__ docstring Args next to enable_registry_bots (line 239).
```

### FILL IN checklist
- [ ] Docstring line for `enable_experts`.
- [ ] Tests: stub `ExpertRegistry.load` to raise → fail-open; order of calls in `load_bots` via a stub registry.

---

## Acceptance Criteria

- [ ] AC29 — after `StandaloneAgentLoader._ensure_discovered()` with a bundled-only setup, `agent_registry.has("cve-analyst")`;
      `BotManager.get_bot("cve-analyst")` returns the `ExpertAgent` through the registry fallback; `load_experts` runs
      after `load_agent_definitions` and before `instantiate_startup_agents`; `enable_experts=False` skips it;
      an exception inside loading is logged and swallowed.
- [ ] `ruff check` passes on all three source files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/experts/test_bootstrap.py -q`
- `pytest packages/ai-parrot-server/tests/manager/test_load_bots_experts.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/experts/test_bootstrap.py
async def test_load_experts_disabled_returns_none(): ...            # FILL IN
async def test_load_experts_is_fail_open(monkeypatch, caplog): ...  # FILL IN
async def test_standalone_loader_discovers_experts(monkeypatch, tmp_path): ...   # FILL IN: fake wiki toolkit
# packages/ai-parrot-server/tests/manager/test_load_bots_experts.py
async def test_bot_manager_load_bots_wires_experts(monkeypatch): ...  # FILL IN: call order
async def test_enable_experts_false_skips(monkeypatch): ...          # FILL IN
async def test_expert_reachable_through_get_bot(monkeypatch): ...    # FILL IN
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug domain-experts --feature-id FEAT-778`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/domain-experts.json`
4. **Verify the Codebase Contract** — before writing ANY code, confirm every import and signature still exists;
   if anything changed, update the contract FIRST. Never reference a name not in the contract without verifying it.
5. **Update status** in `sdd/tasks/index/domain-experts.json` → `"in-progress"` (set `started_at`) and commit only that file
6. **Implement** — start from the Implementation Blueprint, complete every `# FILL IN:` marker, never change a
   signature or path the blueprint fixes
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src`
   (add `packages/ai-parrot-server/src` when the task touches the server) and `ruff check` the files you changed
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4933 domain-experts verified` — never move the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker; Seat: gpt-5.6-terra (codex) · Attempts: 1
**Date**: 2026-10-30
**Notes**: Merged; task-tier and chunk merge-tier validation green.

**Deviations from spec**: none
