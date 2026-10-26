# TASK-4734: G4 — mid-conversation mount/unmount vs prompt caching spike

**Feature**: FEAT-746 — Squawk: typed binary inter-agent protocol
**Spec**: `sdd/specs/inter-agent-protocol.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4737
**Assigned-to**: unassigned

---

## Context

Spec §3 gate **G4 — S4 mount/unmount + prompt cache** (Q11). M7 lets the planner pre-mount categories and the model mount/unmount mid-conversation. Adding tool definitions mid-conversation can invalidate a provider's cached prompt prefix. G4 measures, on at least two providers, whether a mount breaks the cached prefix (cache-read tokens observed through usage) and decides whether mounted definitions must live in a separate cache segment via `AbstractClient._apply_cache_hints`. Its amendment fixes M7's premount policy.

---

## Scope

- `spike.py`: a 3-turn conversation per provider (turn 1 with N baseline tools; turn 2 identical prompt → expect cache read; turn 3 after registering 3 more tools → observe cache read tokens vs turn 2). Uses only existing `AbstractClient` subclasses and `ToolManager.register_tool`; records `usage` from the returned `AIMessage` (cache read/creation tokens where the provider reports them).
- Run under `PARROT_TEST_REAL_LLM=1` only (two providers minimum: whichever of Anthropic/OpenAI/Google are configured); offline mode prints the request shapes without calling.
- `report.md` with per-provider cache behaviour and the amendment (premount-only vs free mid-conversation mount, and whether `_apply_cache_hints` needs a mounted-tools segment).
- `packages/ai-parrot-squawk/tests/spikes/test_g4_mount_prompt_cache.py`: opt-in (`PARROT_SPIKE=1` **and** `PARROT_TEST_REAL_LLM=1`), one provider, asserts the measurement completes and records numbers (no threshold — the verdict is human).

**NOT in scope**: changing `clients/base.py` (never without discussion; the amendment only *proposes* a segment), `SquawkRemoteToolkit` (M7).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `sdd/state/FEAT-746/spikes/G4-mount-prompt-cache/spike.py` | CREATE | 3-turn cache measurement per provider |
| `sdd/state/FEAT-746/spikes/G4-mount-prompt-cache/report.md` | CREATE | Gate report + amendment |
| `packages/ai-parrot-squawk/tests/spikes/test_g4_mount_prompt_cache.py` | CREATE | Opt-in smoke |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.tools.manager import ToolManager, ToolDefinition, ToolFormat   # verified: packages/ai-parrot/src/parrot/tools/manager.py:289, :31, :75
from parrot.clients.base import AbstractClient   # verified: packages/ai-parrot/src/parrot/clients/base.py; _apply_cache_hints at :565 (read-only reference for the report)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/clients/base.py:565
def _apply_cache_hints(self, payload, segments, trace_context=None) -> Dict[str, Any]   # where a "mounted tools" segment WOULD land — do not modify in this task
# packages/ai-parrot/src/parrot/tools/manager.py
def register_tool(...)   # :853     def get_tool_schemas(provider_format) # :1313
```
Provider clients: discover the configured ones at runtime via the existing client registry/imports used by `packages/ai-parrot/tests/clients/` (read one of those tests for the instantiation idiom; record the exact class names you used in the report).

### Does NOT Exist
- ~~`ToolManager.mount_category`~~ — M7; use `register_tool` for the "mount" step in this spike.
- ~~A provider-neutral `usage.cache_read_tokens` field~~ — read the provider-specific usage keys the clients already surface (Anthropic `cache_read_input_tokens`, OpenAI `prompt_tokens_details.cached_tokens`, Google `cached_content_token_count`) and normalize in the spike only.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "sdd/state/FEAT-746/spikes/G4-mount-prompt-cache/spike.py", "action": "CREATE"},
    {"path": "sdd/state/FEAT-746/spikes/G4-mount-prompt-cache/report.md", "action": "CREATE"},
    {"path": "packages/ai-parrot-squawk/tests/spikes/test_g4_mount_prompt_cache.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/manager.py#ToolManager",
    "sym:packages/ai-parrot/src/parrot/clients/base.py#AbstractClient._apply_cache_hints"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Exclusive task: consumes real provider quota; never run in CI.
- Prompt must exceed each provider's minimum cacheable prefix (Anthropic ≥ 1024 tokens for most models): pad the system prompt deterministically.
- Measure, do not judge, in code: the verdict and the amendment are written in the report by the agent.

### References in Codebase
- `packages/ai-parrot/src/parrot/core/events/lifecycle/events/client.py:142` — `PromptCacheAppliedEvent` (FEAT-181) shows which cache fields the clients already observe.

---

## Implementation Blueprint

### Steps (in order)
1. Write `spike.py` with `baseline_tools(n)`, `extra_tools(k)`, `run_provider(client) -> dict` (3 turns, usage per turn) and `main()` — *why*: one function per provider keeps the table honest.
2. Pad the system prompt above the cache minimum — *why*: otherwise no provider caches and the spike measures nothing.
3. Run on ≥ 2 providers; fill the report; write the amendment — *why*: M7's premount policy depends on it.

### `sdd/state/FEAT-746/spikes/G4-mount-prompt-cache/spike.py` (CREATE)
```python
"""G4 — does mounting tools mid-conversation break the cached prefix? (FEAT-746)"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any

from parrot.tools.manager import ToolDefinition, ToolManager

PAD = ("You are a careful HR analytics assistant. " * 400)  # > 1024 tokens on every tokenizer


async def _noop(**kwargs):
    return {"ok": True}


def _tool(name: str) -> ToolDefinition:
    return ToolDefinition(name=name, description=f"Tool {name} returns a struct.", input_schema={"type": "object", "properties": {"q": {"type": "string"}}}, function=_noop)


def baseline_tools(n: int) -> list[ToolDefinition]:
    return [_tool(f"base_{i}") for i in range(n)]


def extra_tools(k: int) -> list[ToolDefinition]:
    return [_tool(f"hr__reports__cap_{i}") for i in range(k)]


def cache_fields(usage: dict[str, Any]) -> dict[str, int]:
    """Normalize provider-specific cache counters for the report."""
    # FILL IN: map Anthropic/OpenAI/Google usage keys to {"cache_read": int, "cache_write": int, "input": int} — bounded by the keys the clients already surface
    raise NotImplementedError


async def run_provider(client, label: str) -> dict[str, Any]:
    """Three turns: baseline, repeat (expect cache read), after mount (observe)."""
    tm = ToolManager()
    for t in baseline_tools(6):
        tm.register_tool(tool=t)
    turns: list[dict[str, Any]] = []
    # FILL IN: turn 1 and 2 call client.ask(system=PAD, prompt="List the tools you can use.", tools=tm.get_tool_schemas(<fmt>)); turn 3 after registering extra_tools(3)
    # record cache_fields(message.usage) per turn — bounded by: identical prompt on turns 1-2; only tools change on turn 3
    return {"provider": label, "turns": turns}


async def main_async() -> list[dict[str, Any]]:
    results = []
    # FILL IN: instantiate the configured clients (read packages/ai-parrot/tests/clients/ for the idiom); skip unconfigured ones and say so
    return results


def main() -> int:
    if os.environ.get("PARROT_TEST_REAL_LLM") != "1":
        print("offline: set PARROT_TEST_REAL_LLM=1 to measure; printing request shape only")
        print(json.dumps({"baseline": len(baseline_tools(6)), "extra": len(extra_tools(3)), "pad_chars": len(PAD)}))
        return 0
    print(json.dumps(asyncio.run(main_async()), indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```
**Why this shape**: the question is purely empirical and provider-specific (Q11/S4); the code only produces the three-turn usage table, the agent writes the verdict.

### `packages/ai-parrot-squawk/tests/spikes/test_g4_mount_prompt_cache.py` (CREATE)
```python
"""G4 smoke — one provider, three turns complete (opt-in, real LLM)."""
from __future__ import annotations

import asyncio
import importlib.util
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("PARROT_SPIKE") != "1" or os.environ.get("PARROT_TEST_REAL_LLM") != "1",
    reason="spike: set PARROT_SPIKE=1 and PARROT_TEST_REAL_LLM=1",
)
SPIKE = Path(__file__).resolve().parents[4] / "sdd/state/FEAT-746/spikes/G4-mount-prompt-cache/spike.py"


def test_three_turns_complete():
    spec = importlib.util.spec_from_file_location("g4_spike", SPIKE)
    g4 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(g4)
    results = asyncio.run(g4.main_async())
    assert results and all(len(r["turns"]) == 3 for r in results)
```

### FILL IN checklist
- [ ] `spike.py::cache_fields` — provider key mapping; bounded by the keys the clients surface
- [ ] `spike.py::run_provider` / `main_async` — client instantiation and the three calls; bounded by one conversation per provider
- [ ] `report.md` — per-provider table + amendment (premount policy; `_apply_cache_hints` segment yes/no)

---

## Acceptance Criteria

- [ ] On ≥ 2 providers turn 2 shows cache reads and turn 3's cache behaviour is recorded
- [ ] `report.md` states, per provider, whether the mount broke the prefix, and proposes M7's premount policy (spec G4 pass criterion: mount adds definitions without breaking the cached prefix on ≥ 2 providers — or the amendment says it does not and prescribes premount-only)
- [ ] Offline run prints the request shape and exits 0
- [ ] Opt-in test completes on one provider

---

## Validation Commands

- `pytest packages/ai-parrot-squawk/tests/spikes/test_g4_mount_prompt_cache.py -q`

---

## Test Specification

See blueprint test; skipped unless both env flags are set.

---

## Agent Instructions

1. **Work in the feature worktree** (`python -m scripts.sdd.ensure_worktree --slug inter-agent-protocol --feature-id FEAT-746`)
2. **Read the spec** §3 G4/M7, §1 Non-Goals (`clients/base.py` untouched)
3. **Check dependencies** — TASK-4737 `"done"` (tests package exists)
4. **Verify the Codebase Contract**
5. **Update status** → `"in-progress"`, commit only the index
6. **Implement**; ask the operator for provider credentials — never read or copy keys into files
7. **Verify** — Validation Commands
8. **Commit** — only the listed files
9. **Close** with `scripts/sdd/close_task.sh TASK-4734 inter-agent-protocol verified`
10. **Completion Note** — quote the amendment verbatim

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
