# TASK-2660: Subsystem scaffolding, config, and agent façade

**Feature**: FEAT-481 — Fireflies → Obsidian LLM-Wiki Knowledge-Base Agent
**Spec**: `sdd/specs/fireflies-wiki-knowledgebase-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Foundation for the whole feature (spec Module 1). Creates the `parrot/flows/wiki_ingest/`
package (modeled on `parrot/flows/dev_loop/`), the registered agent façade, and the
subsystem's **own** config module. **Additive-only (G11): edit no existing file.**

## Scope

- Create `parrot/flows/wiki_ingest/{__init__,agent,definition,factories,runner,conf}.py` (empty/stub node package `nodes/`).
- `@register_agent(name="fireflies_wiki_kb", at_startup=True)` `Agent` subclass exposing the six intents (`ingest`, `query`, `health`, `lint`, `archive`, `build_graph_report`) as method stubs + tool surface.
- `conf.py` with: `WIKI_KB_VAULT_PATH`, `WIKI_KB_PARTICIPANTS`, `WIKI_KB_LLM_STRONG` (default `google:gemini-2.5-pro`), `WIKI_KB_LLM_CHEAP` (default `google:gemini-2.5-flash`), `WIKI_KB_INGEST_CRON` (default `"0 * * * *"`), `WIKI_KB_INGEST_LIMIT`, `WIKI_KB_MAX_CATCHUP_DAYS`, `FIREFLIES_SYNC_OVERLAP_DAYS` (reuse FEAT-472), `WIKI_KB_ACTIVE_WINDOW_DAYS=14`, `WIKI_KB_RAW_ROOT`, `FIREFLIES_WIKI_EMAIL_ENABLED=false`.
- Build the strong/cheap tier clients from the config strings via `LLMFactory` in `configure()`.

**NOT in scope**: fetch, compilation, rendering, workflows (later tasks).

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/wiki_ingest/__init__.py` | CREATE | package |
| `.../wiki_ingest/conf.py` | CREATE | self-contained config |
| `.../wiki_ingest/agent.py` | CREATE | `FirefliesWikiKBAgent` façade + tier clients |
| `.../wiki_ingest/{definition,factories,runner}.py` | CREATE | flow scaffolding (stubs) |
| `packages/ai-parrot/tests/unit/test_wiki_kb_agent_scaffold.py` | CREATE | init + config tests |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.registry import register_agent
from parrot.scheduler import ScheduleType, schedule   # 5-field cron via add_cron — scheduler/inprocess.py:83
from parrot.clients.factory import LLMFactory         # clients/factory.py: SUPPORTED_CLIENTS google:127, claude/anthropic:108-109, openai-codex:146-147
from parrot.bots.agent import Agent                    # bots/agent.py:1236 (BasicAgent:29 mixes MCPEnabledMixin)
```
### Existing Signatures to Use
```python
# clients/factory.py
LLMFactory.create(spec: str)            # build a client from "provider:model"
LLMFactory.parse_llm_string(spec: str)  # -> (provider, model_id)
```
### Does NOT Exist
- ~~`parrot/agents/conf.py::WIKI_KB_*`~~ — do NOT add keys there; use the subsystem's own `conf.py`.

## Implementation Notes
- Mirror `parrot/flows/dev_loop/` structure. Do not import from `agents/obsidian.py` or edit it.
- `self.logger`, async, Pydantic; Google-style docstrings.

## Acceptance Criteria
- [ ] `from parrot.flows.wiki_ingest.agent import FirefliesWikiKBAgent` works; agent registers.
- [ ] `configure()` builds strong + cheap clients from `provider:model` config (Google default).
- [ ] No existing file modified; `pytest` for existing agents stays green.
- [ ] `ruff`/`mypy` clean.

## Test Specification
```python
async def test_agent_registers_and_builds_tier_clients(monkeypatch):
    agent = FirefliesWikiKBAgent(...)
    await agent.configure()
    assert agent.strong_client and agent.cheap_client
```
