# TASK-4984: CompletionUsage cache and reasoning counters

**Feature**: FEAT-783 — Unified usage & cost metrics per SDD spec
**Spec**: `sdd/specs/unified-usage.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 (model half), goal G3. `CompletionUsage` today keeps cache data only in
`extra_usage`, so it is lost the moment usage is summed or forwarded. This task adds
first-class `cache_read_tokens`, `cache_creation_tokens` and `reasoning_output_tokens`,
so the codex codec (TASK-4993) and the event carriage (TASK-4986) have a typed shape to fill.

---

## Scope

- Add the three counters to `CompletionUsage`, with the `AliasChoices` validation aliases from the spec skeleton.
- Make `__add__` sum the three counters field-wise.
- Make `from_claude` and `from_bedrock` populate the new counters from the keys they already read. Keep `extra_usage` unchanged for backward compatibility.
- Write unit tests.

**NOT in scope**: event fields (TASK-4986), pricing (TASK-4987), any client other than the two `from_*` constructors named above.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/models/basic.py` | MODIFY | Three counters + `__add__` + two constructors |
| `packages/ai-parrot/tests/unit/models/test_completion_usage_cache_counters.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.models.basic import CompletionUsage   # basic.py:48
# basic.py already imports AliasChoices, ConfigDict, Field from pydantic (import block basic.py:3-12; used at :78-83)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/models/basic.py
class CompletionUsage(BaseModel):                 # :48, model_config = ConfigDict(populate_by_name=True)
    prompt_tokens: int = Field(0, validation_alias=AliasChoices("prompt_tokens", "input_tokens"))
    extra_usage: Dict[str, Any] = Field(default_factory=dict)   # :94
    @classmethod
    def from_claude(cls, usage: Dict[str, Any]) -> "CompletionUsage":   # :137 — extra_usage=usage
    @classmethod
    def from_bedrock(cls, usage: Dict[str, Any]) -> "CompletionUsage":  # :146 — reads cacheReadInputTokens / cacheWriteInputTokens
    def __add__(self, other: Any) -> "CompletionUsage":                 # :273 — returns CompletionUsage(...) at :301-311
```

### Does NOT Exist
- ~~`CompletionUsage.cache_creation`~~ / ~~`CompletionUsage.cache_read_tokens`~~ — not fields today; cache data lives only in `extra_usage`
- ~~`CompletionUsage.reasoning_output_tokens`~~ — no slot exists
- ~~`CompletionUsage.from_codex`~~ — do not add; the codec lives in TASK-4993

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/models/basic.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/unit/models/test_completion_usage_cache_counters.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/models/basic.py#CompletionUsage"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Counters are `int = 0`, not Optional: a sum of "unknown" is handled by `usage_reported` upstream, not here.
- `total_tokens` semantics do NOT change. Cache tokens are a breakdown of input, not an addition (Anthropic reports `input_tokens` exclusive of cache; that reconciliation is the calculator's job in TASK-4987).

---

## Implementation Blueprint

### Steps (in order)
1. Add the three fields directly below `extra_usage`, so they sit with the provider-specific data.
2. Extend `__add__`. Without this, multi-round tool use would silently drop the counters (FEAT-397 accumulation).
3. Populate them in `from_claude`/`from_bedrock`, so the two providers that already report cache data stop losing it.
4. Write tests.

### `packages/ai-parrot/src/parrot/models/basic.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    extra_usage: Dict\[str, Any\] = Field(default_factory=dict)' basic.py)
# AFTER — insert below `    extra_usage: Dict[str, Any] = Field(default_factory=dict)` (verified: basic.py:94)

    # FEAT-783: first-class cache / reasoning counters (previously only in extra_usage).
    cache_read_tokens: int = Field(
        0, validation_alias=AliasChoices("cache_read_tokens", "cache_read_input_tokens", "cached_input_tokens")
    )
    cache_creation_tokens: int = Field(
        0,
        validation_alias=AliasChoices(
            "cache_creation_tokens", "cache_creation_input_tokens", "cache_write_input_tokens"
        ),
    )
    reasoning_output_tokens: int = 0
```
```python
# occurrences: 1 — inside __add__'s return (basic.py:301-311), add after `total_tokens=...,`:
            cache_read_tokens=self.cache_read_tokens + other.cache_read_tokens,
            cache_creation_tokens=self.cache_creation_tokens + other.cache_creation_tokens,
            reasoning_output_tokens=self.reasoning_output_tokens + other.reasoning_output_tokens,
```
```python
# from_claude (basic.py:137) — add kwargs:
            cache_read_tokens=usage.get("cache_read_input_tokens", 0) or 0,
            cache_creation_tokens=usage.get("cache_creation_input_tokens", 0) or 0,
# from_bedrock (basic.py:146) — add kwargs:
            cache_read_tokens=usage.get("cacheReadInputTokens", 0) or 0,
            cache_creation_tokens=usage.get("cacheWriteInputTokens", 0) or 0,
```
**Why**: `or 0` guards against providers that send an explicit `null`. Add a line about the three counters to the `__add__` docstring's Semantics list.

### `packages/ai-parrot/tests/unit/models/test_completion_usage_cache_counters.py` (CREATE)
```python
"""FEAT-783 TASK-4984 — CompletionUsage cache/reasoning counters."""
from parrot.models.basic import CompletionUsage


def test_aliases_populate_counters() -> None:
    # FILL IN: cache_read_input_tokens / cached_input_tokens / cache_creation_input_tokens / cache_write_input_tokens all map
    ...


def test_add_sums_new_counters_fieldwise() -> None:
    # FILL IN: (a + b).cache_read_tokens == a.cache_read_tokens + b.cache_read_tokens, same for the other two
    ...


def test_from_claude_and_bedrock_populate_counters() -> None:
    # FILL IN: both constructors fill the counters; extra_usage still holds the raw payload
    ...


def test_total_tokens_unchanged_by_cache_counters() -> None:
    # FILL IN: total_tokens is not increased by the cache counters
    ...
```

### FILL IN checklist
- [ ] Four test bodies; bounded by AC-3 (model half)

---

## Acceptance Criteria

- [ ] `CompletionUsage` carries `cache_read_tokens`, `cache_creation_tokens`, `reasoning_output_tokens` (AC-3).
- [ ] `__add__` sums all three.
- [ ] Existing CompletionUsage tests still pass.

## Validation Commands
- `pytest packages/ai-parrot/tests/unit/models/test_completion_usage_cache_counters.py -q`
- `pytest packages/ai-parrot/tests/unit/models/test_completion_usage_add.py -q`
- `pytest packages/ai-parrot/tests/test_completion_usage.py -q`

## Test Specification
See blueprint.

## Agent Instructions
Touch only `basic.py` and the new test. `PYTHONPATH=packages/ai-parrot/src`.

## Completion Note

- Task: TASK-4984
- Feature: unified-usage
- Implementation SHA: 0ea7fd310aa515f2e5c9bb3400d1b904008dbe57
- Closed at (UTC): 2026-10-31T00:30:50+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: gpt-5.6-sol · Backend: codex · Model: gpt-5.6-sol · Attempts: 1 · Duration: 65.0s · Tokens: n/a |
