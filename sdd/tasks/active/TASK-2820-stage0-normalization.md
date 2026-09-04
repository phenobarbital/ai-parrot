# TASK-2820: Stage 0 normalization (`normalize_turn`)

**Feature**: FEAT-525 — Per-Turn Conversation Compaction
**Spec**: `sdd/specs/per-turn-conversation-compaction.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2819
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 and constraint C1/C4. Stage 0 makes stored bytes canonical
so that (a) token counts are stable, (b) content ids are stable across
writers, and (c) tracebacks do not dominate a turn. It runs once at write
time inside `ConversationMemory.add_turn` (wired in TASK-2826); this task
delivers only the pure functions.

---

## Scope

- Create `parrot/memory/compaction/normalize.py` with `NORM_VERSION = "1"`
  and the five rules from spec §3 Module 2:
  1. `unicodedata.normalize("NFC", text)`;
  2. strip ANSI escape sequences (CSI/OSC/SS3) and C0 control characters
     except `\n` and `\t` (`\r\n` → `\n`);
  3. strip trailing whitespace per line; collapse runs of ≥3 blank lines to 2;
  4. `canonical_json_text(text)`: if `text.strip()` parses with `orjson.loads`
     to a `dict` or `list`, return `orjson.dumps(obj, option=orjson.OPT_SORT_KEYS).decode()`,
     else return the input unchanged; `ToolInvocation.input` dicts are
     round-tripped through the same canonical dump so key order is stable;
  5. `condense_traceback(text, *, keep_frames=3)`: when `text` contains
     `"Traceback (most recent call last):"`, keep the header line, the last
     `keep_frames` `File "…"` frame pairs, and the final exception line;
     otherwise return the input unchanged.
- `normalize_text(text)` applies rules 1–3 (in that order).
- `normalize_invocation(inv)` returns a **new** `ToolInvocation` with
  `input` canonicalized (rule 4), `output` through `normalize_text` then
  `canonical_json_text`, `error` through `normalize_text` then
  `condense_traceback`. `omitted`, `wm_key`, `output_chars`, `status`,
  `elapsed_ms` copied unchanged.
- `normalize_turn(turn)` returns a **new** `ConversationTurn` with
  `user_message`, `assistant_response`, `context_used` through
  `normalize_text`; `error` through `normalize_text` + `condense_traceback`;
  every invocation through `normalize_invocation`; `norm_version =
  NORM_VERSION`. Never mutates its argument. Idempotent.
- Unit + `hypothesis` property tests.

**NOT in scope**: wiring into `add_turn` (TASK-2826), the `normalize=False`
memory option (TASK-2826), token counting (TASK-2821).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/memory/compaction/normalize.py` | CREATE | rules 1–5, `normalize_text`, `canonical_json_text`, `condense_traceback`, `normalize_invocation`, `normalize_turn`, `NORM_VERSION` |
| `packages/ai-parrot/tests/unit/memory/compaction/test_normalize.py` | CREATE | per-rule fixtures + idempotence property |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: Use only what is listed here. Verify anything else before using it.

### Verified Imports
```python
from parrot.memory.abstract import ConversationTurn                       # verified: memory/abstract.py:16 (dev 198e6fecd)
from parrot.memory.compaction.models import ToolInvocation, ToolStatus   # created by TASK-2819 (verify it landed)
import orjson                                                             # verified: 3.12.0 installed
import re, unicodedata                                                    # stdlib
from dataclasses import replace                                           # stdlib — use for "new turn" copies
from hypothesis import given, strategies as st                            # verified: hypothesis 6.165.10 (dev dep, pyproject.toml:702)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/memory/abstract.py — ConversationTurn (after TASK-2819)
#   user_message: str; assistant_response: str; context_used: Optional[str]; error: Optional[str]
#   tool_invocations: List[ToolInvocation]; norm_version: Optional[str]

# packages/ai-parrot/src/parrot/memory/compaction/models.py — ToolInvocation (after TASK-2819)
#   tool_name: str; input: Dict[str, Any]; output: Optional[str]; status: ToolStatus; error: Optional[str]
#   elapsed_ms: Optional[int]; output_chars: Optional[int]; omitted: Dict[str, str]; wm_key: Optional[str]

# Style precedent (verified): packages/ai-parrot/src/parrot/security/groundedness/normalize.py:1-14
#   module docstring "All functions are pure, synchronous, and stdlib-only"; compiled regexes at module level.
```

### Does NOT Exist
- ~~`parrot.memory.compaction.normalize`~~ — this task creates it.
- ~~A shared ANSI-stripping helper in `parrot/`~~ — none; write the regex here (`\x1b\[[0-?]*[ -/]*[@-~]` for CSI, `\x1b\][^\x07]*\x07` for OSC, `\x1bO.` for SS3).
- ~~`ConversationTurn.normalized` / `.normalize()`~~ — no such method; use the module function.
- ~~`json` module for canonical output~~ — use `orjson` with `OPT_SORT_KEYS` (spec §7 "Canonical JSON").

---

## Implementation Notes

### Pattern to Follow
```python
"""Stage 0 normalization for conversation turns (FEAT-525).

All functions are pure, synchronous, and depend on stdlib + orjson only.
normalize_turn(normalize_turn(t)) == normalize_turn(t) is a tested property.
"""
_ANSI_CSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_C0_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_BLANK_RUN_RE = re.compile(r"\n{4,}")   # ≥3 blank lines → 2 blank lines ("\n\n\n")
```

### Key Constraints
- Pure: no logging, no I/O, no global state besides compiled regexes.
- `normalize_turn` must return the argument's fields unchanged when they are already normalized (idempotence) — test with `hypothesis` text strategies that include combining marks, ANSI sequences, `\r\n`, and JSON-looking strings.
- Rule 4 must not touch strings that parse to scalars (`"42"`, `"true"`) — only objects/arrays.
- `condense_traceback` must keep the last exception line verbatim so errors stay searchable (C7).

### References in Codebase
- `packages/ai-parrot/src/parrot/security/groundedness/normalize.py` — purity/style precedent.

---

## Acceptance Criteria

- [ ] Five per-rule tests pass with fixed fixtures (NFC, ANSI/C0, whitespace, canonical JSON, traceback).
- [ ] Property: `normalize_turn(normalize_turn(t)) == normalize_turn(t)` for generated turns (≥200 examples).
- [ ] `normalize_turn` never mutates its argument (assert on a deep copy).
- [ ] `norm_version == "1"` on the result.
- [ ] All tests pass: `timeout -s KILL 300 pytest packages/ai-parrot/tests/unit/memory/compaction/test_normalize.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/memory/compaction/normalize.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/memory/compaction/test_normalize.py
import copy
from hypothesis import given, settings, strategies as st
from parrot.memory.abstract import ConversationTurn
from parrot.memory.compaction.models import ToolInvocation
from parrot.memory.compaction.normalize import (
    NORM_VERSION, canonical_json_text, condense_traceback, normalize_text, normalize_turn,
)


def test_rule_nfc_and_ansi_and_whitespace():
    raw = "é\x1b[31mred\x1b[0m  \r\nline\n\n\n\n\nend  "
    assert normalize_text(raw) == "éred\nline\n\n\nend"


def test_rule_canonical_json():
    assert canonical_json_text('{"b": 1, "a": [2, 1]}') == '{"a":[2,1],"b":1}'
    assert canonical_json_text("42") == "42"
    assert canonical_json_text("not json") == "not json"


def test_rule_traceback_condensed_keeps_exception_line():
    tb = "Traceback (most recent call last):\n" + "".join(
        f'  File "f{i}.py", line {i}, in fn\n    call()\n' for i in range(10)) + "ValueError: bad\n"
    out = condense_traceback(tb, keep_frames=3)
    assert out.count('File "') == 3 and out.rstrip().endswith("ValueError: bad")


text_st = st.text(alphabet=st.characters(blacklist_categories=("Cs",)), max_size=200)

@st.composite
def turns(draw):
    inv = ToolInvocation(tool_name=draw(st.text(min_size=1, max_size=10)),
                         input={draw(st.text(max_size=5)): draw(st.integers())},
                         output=draw(st.one_of(st.none(), text_st)), error=draw(st.one_of(st.none(), text_st)))
    return ConversationTurn(turn_id="t", user_id="u", user_message=draw(text_st),
                            assistant_response=draw(text_st), tool_invocations=[inv])

@settings(max_examples=200)
@given(turns())
def test_normalize_idempotent_and_pure(turn):
    before = copy.deepcopy(turn)
    once = normalize_turn(turn)
    assert turn == before
    assert normalize_turn(once) == once
    assert once.norm_version == NORM_VERSION
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2819 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing any code; update it first if anything changed
4. **Update status** in `sdd/tasks/index/per-turn-conversation-compaction.json` → `"in-progress"`
5. **Implement** following the scope, contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2820-stage0-normalization.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
