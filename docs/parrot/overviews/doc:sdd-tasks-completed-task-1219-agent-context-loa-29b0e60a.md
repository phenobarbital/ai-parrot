---
type: Wiki Overview
title: 'TASK-1219: AgentContextLoader + AGENT_CONTEXT_LAYER + AGENT_CONTEXT_DIR'
id: doc:sdd-tasks-completed-task-1219-agent-context-loader-and-layer-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This task implements the file-based agent context loading system (spec Module
  3,
relates_to:
- concept: mod:parrot.bots.prompts
  rel: mentions
- concept: mod:parrot.bots.prompts.agent_context
  rel: mentions
- concept: mod:parrot.bots.prompts.layers
  rel: mentions
- concept: mod:parrot.conf
  rel: mentions
- concept: mod:parrot.loaders
  rel: mentions
---

# TASK-1219: AgentContextLoader + AGENT_CONTEXT_LAYER + AGENT_CONTEXT_DIR

**Feature**: FEAT-181 — Provider-Agnostic Prompt Caching
**Spec**: `sdd/specs/agnostic-prompt-caching-abstraction.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1217
**Assigned-to**: unassigned

---

## Context

This task implements the file-based agent context loading system (spec Module 3,
§3). It adds a `AGENT_CONTEXT_DIR` constant to `conf.py`, a sync
`load_agent_context()` function with mtime-based cache invalidation, and an
`AGENT_CONTEXT_LAYER` that is a CONFIGURE-phase, cacheable PromptLayer.

---

## Scope

- Add `AGENT_CONTEXT_DIR` constant to `parrot/conf.py` using the established
  `config.get(..., fallback=BASE_DIR.joinpath('agent_context'))` convention.
- Create `parrot/bots/prompts/agent_context.py` with `load_agent_context(agent_id: str) -> str`.
  Sync function, `@functools.lru_cache(maxsize=None)` keyed on `(path, st_mtime)`.
  Missing file returns empty string. Logs at INFO once when file is missing and
  `prompt_caching=True`.
- Create `AGENT_CONTEXT_LAYER` — a CONFIGURE-phase, `cacheable=True` PromptLayer
  with priority between IDENTITY (10) and PRE_INSTRUCTIONS (15), e.g., 12.
- Export `AGENT_CONTEXT_LAYER` from `parrot/bots/prompts/__init__.py`.
- Write unit tests.

**NOT in scope**: AbstractBot auto-injection (TASK-1220), client translators
(TASK-1222–1224).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/conf.py` | MODIFY | Add `AGENT_CONTEXT_DIR` constant |
| `packages/ai-parrot/src/parrot/bots/prompts/agent_context.py` | CREATE | `load_agent_context()` + `AGENT_CONTEXT_LAYER` |
| `packages/ai-parrot/src/parrot/bots/prompts/__init__.py` | MODIFY | Export `AGENT_CONTEXT_LAYER` |
| `packages/ai-parrot/tests/test_agent_context_loader.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from navconfig import config, BASE_DIR  # conf.py:5
from parrot.conf import AGENTS_DIR, PLUGINS_DIR  # conf.py:141, 33
from parrot.bots.prompts.layers import PromptLayer, LayerPriority, RenderPhase  # layers.py:22-47
```

### Existing Signatures to Use
```python
# parrot/conf.py — established convention (multiple instances):
PLUGINS_DIR = config.get('PLUGINS_DIR', fallback=BASE_DIR.joinpath('plugins'))  # line 33
AGENTS_DIR = config.get('AGENTS_DIR', fallback=BASE_DIR.joinpath('agents'))     # line 141
# Pattern: config.get('X_DIR', fallback=BASE_DIR.joinpath('x'))
# CRITICAL: use `fallback=` keyword, NOT `default=` (navconfig convention)

# parrot/bots/prompts/layers.py
class LayerPriority(IntEnum):           # line 22
    IDENTITY = 10
    PRE_INSTRUCTIONS = 15
    # ...
    CUSTOM = 80

class RenderPhase(str, Enum):           # line 35
    CONFIGURE = "configure"
    REQUEST = "request"

@dataclass(frozen=True)
class PromptLayer:                       # line 51
    name: str
    priority: LayerPriority | int
    template: str
    phase: RenderPhase = RenderPhase.REQUEST
    condition: Optional[Callable] = None
    required_vars: frozenset[str] = field(default_factory=frozenset)
    cacheable: bool  # (added by TASK-1217, default derived from phase)

# parrot/stores/kb/local.py — mtime pattern reference (line 180):
# current_loaded_files = {f.name: f.stat().st_mtime for f in local_files}
```

### Does NOT Exist
- ~~`AGENT_CONTEXT_DIR`~~ — not in `conf.py`; this task adds it
- ~~`parrot.bots.prompts.agent_context`~~ — module does not exist; this task creates it
- ~~`AgentContextLoader` class~~ — the spec calls for a module-level function, not a class
- ~~`parrot.loaders.agent_context`~~ — no such module; the loader lives in `bots/prompts/`

---

## Implementation Notes

### Pattern to Follow

For `conf.py`, follow the AGENTS_DIR pattern exactly:
```python
AGENT_CONTEXT_DIR = config.get('AGENT_CONTEXT_DIR', fallback=BASE_DIR.joinpath('agent_context'))
if isinstance(AGENT_CONTEXT_DIR, str):
    AGENT_CONTEXT_DIR = Path(AGENT_CONTEXT_DIR).resolve()
if not AGENT_CONTEXT_DIR.exists():
    AGENT_CONTEXT_DIR.mkdir(parents=True, exist_ok=True)
```

For the loader, use `functools.lru_cache` on a sync helper keyed on `(path, mtime)`:
```python
import functools
import logging
from pathlib import Path

_logger = logging.getLogger(__name__)

@functools.lru_cache(maxsize=None)
def _read_cached(path: str, mtime: float) -> str:
    return Path(path).read_text(encoding='utf-8')

def load_agent_context(agent_id: str) -> str:
    from parrot.conf import AGENT_CONTEXT_DIR
    file_path = AGENT_CONTEXT_DIR / f"{agent_id}.md"
    if not file_path.exists():
        return ""
    mtime = file_path.stat().st_mtime
    return _read_cached(str(file_path), mtime)
```

For `AGENT_CONTEXT_LAYER`, use priority 12 (between IDENTITY=10 and PRE_INSTRUCTIONS=15):
```python
AGENT_CONTEXT_LAYER = PromptLayer(
    name="agent_context",
    priority=12,
    phase=RenderPhase.CONFIGURE,
    template="""<agent_context>
$agent_context_content
</agent_context>""",
    condition=lambda ctx: bool(ctx.get("agent_context_content", "").strip()),
    cacheable=True,
)
```

### Key Constraints
- Use `fallback=` not `default=` in `config.get()` (navconfig convention).
- `functools.lru_cache` is fine for sync functions. Do NOT use it on async.
- Missing file must return empty string, not raise.
- The layer condition checks `agent_context_content` — the AbstractBot
  (TASK-1220) is responsible for calling `load_agent_context()` and putting
  the result into the context dict.

### References in Codebase
- `parrot/conf.py` — constant conventions
- `parrot/stores/kb/local.py:180` — mtime invalidation pattern
- `parrot/bots/prompts/layers.py` — built-in layer instances

---

## Acceptance Criteria

- [ ] `AGENT_CONTEXT_DIR` constant exists in `conf.py` with `fallback=` convention
- [ ] `load_agent_context("test_agent")` returns file content when file exists
- [ ] `load_agent_context("missing_agent")` returns `""` when file doesn't exist
- [ ] Content updates when file mtime changes (cache invalidation)
- [ ] `AGENT_CONTEXT_LAYER` is a CONFIGURE-phase, `cacheable=True` layer
- [ ] `AGENT_CONTEXT_LAYER` has priority 12 (between IDENTITY=10 and PRE_INSTRUCTIONS=15)
- [ ] `from parrot.bots.prompts import AGENT_CONTEXT_LAYER` works
- [ ] All tests pass: `pytest packages/ai-parrot/tests/test_agent_context_loader.py -v`
- [ ] No linting errors

---

## Test Specification

```python
# packages/ai-parrot/tests/test_agent_context_loader.py
import pytest
from pathlib import Path
from unittest.mock import patch
from parrot.bots.prompts.agent_context import load_agent_context, AGENT_CONTEXT_LAYER
from parrot.bots.prompts.layers import RenderPhase


class TestLoadAgentContext:
    def test_reads_existing_file(self, tmp_path):
        ctx_file = tmp_path / "my_agent.md"
        ctx_file.write_text("# Agent Context\nSome content here.")
        with patch("parrot.bots.prompts.agent_context.AGENT_CONTEXT_DIR", tmp_path):
            # Clear lru_cache between tests
            from parrot.bots.prompts.agent_context import _read_cached
            _read_cached.cache_clear()
            result = load_agent_context("my_agent")
        assert "Some content here" in result

    def test_missing_file_returns_empty(self, tmp_path):
        with patch("parrot.bots.prompts.agent_context.AGENT_CONTEXT_DIR", tmp_path):
            result = load_agent_context("nonexistent")
        assert result == ""

    def test_mtime_invalidation(self, tmp_path):
        ctx_file = tmp_path / "bot.md"
        ctx_file.write_text("version1")
        with patch("parrot.bots.prompts.agent_context.AGENT_CONTEXT_DIR", tmp_path):
            from parrot.bots.prompts.agent_context import _read_cached
            _read_cached.cache_clear()
            v1 = load_agent_context("bot")
            assert v1 == "version1"
            # Simulate file update (change content + mtime)
            import time; time.sleep(0.05)
            ctx_file.write_text("version2")
            v2 = load_agent_context("bot")
            assert v2 == "version2"


class TestAgentContextLayer:
    def test_is_configure_phase(self):
        assert AGENT_CONTEXT_LAYER.phase == RenderPhase.CONFIGURE

    def test_is_cacheable(self):
        assert AGENT_CONTEXT_LAYER.cacheable is True

    def test_priority_between_identity_and_pre_instructions(self):
        assert 10 < AGENT_CONTEXT_LAYER.priority < 15

    def test_renders_with_content(self):
        result = AGENT_CONTEXT_LAYER.render({"agent_context_content": "ctx data"})
        assert "ctx data" in result

    def test_skips_when_empty(self):
        result = AGENT_CONTEXT_LAYER.render({"agent_context_content": ""})
        assert result is None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-1217 is in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm `AGENTS_DIR` pattern at line 141 of `conf.py`
4. **Update status** in `sdd/tasks/index/agnostic-prompt-caching-abstraction.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1219-agent-context-loader-and-layer.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: 
**Date**: 
**Notes**: 

**Deviations from spec**: none | describe if any

---

**Completed by**: SDD Worker (Claude Sonnet 4.6)
**Date**: 2026-05-18
**Notes**: Added AGENT_CONTEXT_DIR to conf.py. Created agent_context.py with _read_cached (lru_cache on path+mtime) and load_agent_context() using module-level AGENT_CONTEXT_DIR for testability. Created AGENT_CONTEXT_LAYER (priority=12, CONFIGURE, cacheable=True). All 17 tests pass.
**Deviations from spec**: Used module-level AGENT_CONTEXT_DIR import with self-module lookup in load_agent_context() to enable patching in tests, rather than pure late import.
