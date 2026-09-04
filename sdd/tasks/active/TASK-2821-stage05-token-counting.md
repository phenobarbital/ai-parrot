# TASK-2821: Stage 0.5 token counting (`TokenCounter`, `count_turn`)

**Feature**: FEAT-525 — Per-Turn Conversation Compaction
**Spec**: `sdd/specs/per-turn-conversation-compaction.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2819
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3, constraints C4 and C15, resolved "Tokenizer" decision:
`o200k_base` via `tiktoken`, name recorded per turn, heuristic fallback
(`bytes // 4`, named `"heuristic"`) when `tiktoken` is unavailable or the
encoding cannot be loaded offline. Every memory instance counts every
written turn (always-on), so this must be cheap and never block on the
network at import time.

---

## Scope

- Create `parrot/memory/compaction/tokens.py` with:
  - `class TokenCounter(Protocol)`: `name: str`; `def count(self, text: str) -> int`.
  - `class TiktokenCounter`: `__init__(self, encoding: str = "o200k_base")`;
    `name == encoding`; the `tiktoken.Encoding` is loaded lazily on first
    `count()` and cached in a module-level dict keyed by encoding name
    (precedent `knowledge/wiki/store.py:187-202`); `count("") == 0`.
  - `class HeuristicCounter`: `name = "heuristic"`;
    `count(text) = max(1, len(text.encode("utf-8")) // 4)` for non-empty text, `0` for empty.
  - `get_default_counter() -> TokenCounter`: returns a `TiktokenCounter`
    when `import tiktoken` succeeds **and** `get_encoding("o200k_base")`
    loads; otherwise a `HeuristicCounter`, logging one warning per process
    (module-level flag). Result cached per process.
  - `count_turn(turn, counter) -> TokenCount`: `user = count(user_message)`,
    `assistant = count(assistant_response)`, `tools = Σ over invocations of
    count(canonical input JSON) + count(output or "") + count(error or "")`,
    `total = user + assistant + tools`, `tokenizer = counter.name`.
    `context_used` is **excluded** (resolved decision).
  - `needs_recount(turn, counter) -> bool`: `turn.token_count is None or
    turn.token_count.tokenizer != counter.name`.
- Unit tests. Tests must not download encodings: monkeypatch
  `tiktoken.get_encoding` where a real encoding is not needed, and skip
  the real-`o200k_base` test when the encoding cannot be loaded.

**NOT in scope**: wiring into `add_turn` (TASK-2826), `calibration`
(TASK-2823), prompt estimation in the bot (TASK-2830).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/memory/compaction/tokens.py` | CREATE | protocol, two counters, default resolver, `count_turn`, `needs_recount` |
| `packages/ai-parrot/tests/unit/memory/compaction/test_tokens.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import tiktoken                                                            # verified: 0.9.0 installed; pyproject.toml:61; get_encoding("o200k_base") loads locally (2026-09-04)
import orjson                                                              # verified: 3.12.0
from parrot.memory.abstract import ConversationTurn                        # verified: memory/abstract.py:16 (dev 198e6fecd)
from parrot.memory.compaction.models import TokenCount, ToolInvocation     # created by TASK-2819
import logging                                                             # module logger: logging.getLogger(__name__)
```

### Existing Signatures to Use
```python
# tiktoken (0.9.0): tiktoken.get_encoding(name: str) -> tiktoken.Encoding ; Encoding.encode(text: str) -> list[int]
#   NOTE: get_encoding may hit the network the first time an encoding is used (documented at knowledge/wiki/store.py:193)

# Lazy-cache precedent (verified) — packages/ai-parrot/src/parrot/knowledge/wiki/store.py:187-202
#   module-level _TOKEN_ENCODER = None; first use: _TOKEN_ENCODER = tiktoken.get_encoding("cl100k_base")

# Existing cl100k_base sites — DO NOT change them (non-goal): skills/parsers.py:29, knowledge/wiki/store.py:202,
#   knowledge/pageindex/utils.py:53

# models.py (TASK-2819): TokenCount(user, assistant, tools, total, tokenizer) frozen dataclass
```

### Does NOT Exist
- ~~`parrot.memory.compaction.tokens`~~ — this task creates it.
- ~~A shared token-counting utility in `parrot/memory`~~ — none; `ContextAssembler` (`memory/unified/context.py`) uses `len(text)//4` inline and is out of scope.
- ~~`tiktoken.encoding_for_model` for the memory counter~~ — do not use; the counter is fixed to an encoding name, not a model.
- ~~`TokenCount.context_used`~~ — not a field; `context_used` is excluded from counting by decision.

---

## Implementation Notes

### Pattern to Follow
```python
_ENCODINGS: dict[str, "tiktoken.Encoding"] = {}
_DEFAULT: Optional[TokenCounter] = None
_WARNED = False

class TiktokenCounter:
    def __init__(self, encoding: str = "o200k_base") -> None:
        self.name = encoding
    def count(self, text: str) -> int:
        if not text:
            return 0
        enc = _ENCODINGS.get(self.name)
        if enc is None:
            import tiktoken
            enc = _ENCODINGS[self.name] = tiktoken.get_encoding(self.name)
        return len(enc.encode(text, disallowed_special=()))
```

### Key Constraints
- `disallowed_special=()` so text containing `<|endoftext|>`-like markers never raises.
- No network at import time; no `get_encoding` call outside `count()` / `get_default_counter()`.
- Canonical input JSON for `tools` = `orjson.dumps(inv.input, option=orjson.OPT_SORT_KEYS).decode()`.
- Pure aside from the encoding cache and the one-time warning.

### References in Codebase
- `packages/ai-parrot/src/parrot/knowledge/wiki/store.py:187-202` — lazy encoding cache.

---

## Acceptance Criteria

- [ ] `TiktokenCounter().name == "o200k_base"`; counting is deterministic and the encoding is loaded once (monkeypatched `get_encoding` called exactly once across two counters of the same name).
- [ ] With `tiktoken` import failing (monkeypatched `builtins.__import__` or `sys.modules["tiktoken"] = None`), `get_default_counter().name == "heuristic"` and exactly one warning is logged.
- [ ] `count_turn` ignores `context_used`; `total == user + assistant + tools`; `tokenizer == counter.name`.
- [ ] `needs_recount` is `True` for `None` and for a tokenizer-name mismatch, `False` otherwise.
- [ ] All tests pass: `timeout -s KILL 300 pytest packages/ai-parrot/tests/unit/memory/compaction/test_tokens.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/memory/compaction/tokens.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/memory/compaction/test_tokens.py
import sys
import pytest
from parrot.memory.abstract import ConversationTurn
from parrot.memory.compaction.models import TokenCount, ToolInvocation
from parrot.memory.compaction import tokens as tk


class _FakeEnc:
    def encode(self, text, disallowed_special=()):
        return text.split()


def test_counter_tiktoken_lazy_cache(monkeypatch):
    calls = []
    monkeypatch.setattr(tk, "_ENCODINGS", {})
    import tiktoken
    monkeypatch.setattr(tiktoken, "get_encoding", lambda name: (calls.append(name), _FakeEnc())[1])
    a, b = tk.TiktokenCounter("o200k_base"), tk.TiktokenCounter("o200k_base")
    assert a.count("x y z") == 3 and b.count("q") == 1 and calls == ["o200k_base"]
    assert a.name == "o200k_base"


def test_counter_heuristic_fallback(monkeypatch, caplog):
    monkeypatch.setattr(tk, "_DEFAULT", None); monkeypatch.setattr(tk, "_WARNED", False)
    monkeypatch.setitem(sys.modules, "tiktoken", None)
    c = tk.get_default_counter()
    assert c.name == "heuristic" and c.count("abcdefgh") == 2 and c.count("") == 0
    assert sum("heuristic" in r.message for r in caplog.records) == 1


def test_count_turn_excludes_context_used():
    c = tk.HeuristicCounter()
    inv = ToolInvocation(tool_name="q", input={"a": 1}, output="o" * 40, error=None)
    t = ConversationTurn(turn_id="t", user_id="u", user_message="u" * 40, assistant_response="a" * 40,
                         context_used="c" * 4000, tool_invocations=[inv])
    tc = tk.count_turn(t, c)
    assert tc == TokenCount(user=10, assistant=10, tools=c.count('{"a":1}') + 10, total=tc.total, tokenizer="heuristic")
    assert tc.total == tc.user + tc.assistant + tc.tools


def test_needs_recount_on_mismatch():
    c = tk.HeuristicCounter()
    t = ConversationTurn(turn_id="t", user_id="u", user_message="a", assistant_response="b")
    assert tk.needs_recount(t, c)
    t.token_count = TokenCount(1, 1, 0, 2, "o200k_base")
    assert tk.needs_recount(t, c)
    t.token_count = TokenCount(1, 1, 0, 2, "heuristic")
    assert not tk.needs_recount(t, c)
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2819 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing any code; update it first if anything changed
4. **Update status** in `sdd/tasks/index/per-turn-conversation-compaction.json` → `"in-progress"`
5. **Implement** following the scope, contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2821-stage05-token-counting.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
