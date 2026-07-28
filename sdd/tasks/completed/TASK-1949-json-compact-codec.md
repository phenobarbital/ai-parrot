# TASK-1949: `json_compact` codec (MINIMAL, lossless)

**Feature**: FEAT-380 — Tool Result Compression Pipeline
**Spec**: `sdd/specs/tool-result-compression.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1947
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1 (built-in codec). `json_compact` is the codec every
unconfigured deployment gets (G2): it is the **default wildcard codec at level
`MINIMAL`**, so it MUST be strictly lossless. It is also the codec that proves
the `ResultCompressor` Protocol works end to end before the lossy
`columnar` codec (TASK-1954) lands.

Honest calibration (spec §7): BPE tokenizers merge whitespace runs, so expect
5–15% *token* savings from this codec even when the byte diff looks like 40%.
The real return is in `NORMAL`. Do not oversell it in docstrings.

---

## Scope

- Implement `JsonCompactCodec` in `codecs/json_compact.py`, registered via
  `@register_codec` with `codec_name = "json_compact"`.
- Three lossless transformations, all applied at `MINIMAL` and above:
  1. **Separator compaction** — serialize with `(",", ":")` separators, no
     indentation, no trailing whitespace.
  2. **Null-key elision** — drop dict keys whose value is `None`
     (recursively). Record dropped key names in the outcome metadata path so
     TASK-1957's report can attribute the gain.
  3. **Exact dedup** — identical sibling elements in a list collapse to one
     entry plus a repeat count marker, ONLY when the collapse is
     round-trippable (see Key Constraints).
- Return `FilterLevel.NONE` → passthrough; unchanged bytes → `lossy=False`,
  `bytes_after == bytes_before`.
- Populate every `CompressionOutcome` field, with `est_tokens_saved =
  max(0, bytes_before - bytes_after) // 4`.
- Non-serializable payload → passthrough (never raise).
- Unit tests including a round-trip losslessness assertion and a determinism
  assertion (G4).

**NOT in scope**:
- Columnarization / constant factoring → TASK-1954 (`columnar` codec).
- Deciding *when* this codec runs (level/route resolution) → TASK-1950/1951.
- The wildcard default entry in the core manifest → TASK-1948 already ships it.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/compression/codecs/json_compact.py` | CREATE | `JsonCompactCodec` |
| `packages/ai-parrot/src/parrot/tools/compression/codecs/__init__.py` | MODIFY | Import the module so `@register_codec` fires |
| `packages/ai-parrot/tests/tools/compression/test_json_compact.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED against HEAD `024c21d44` on 2026-07-27.
> **Path mapping**: `parrot/...` means `packages/ai-parrot/src/parrot/...`.

### Verified Imports

```python
from datamodel.parsers.json import json_decoder, json_encoder, JSONContent
    # already used at parrot/tools/abstract.py:13 — this is the project's
    # serializer, NOT stdlib json. Use it.

# Created by TASK-1947:
from parrot.tools.compression import (
    FilterLevel, CompressionOutcome, register_codec,
)
```

### Existing Signatures to Use

```python
# parrot/tools/abstract.py:13 — the verified serializer import line.
# json_encoder / json_decoder are the project-wide (de)serializers.
```

### Contract to Implement (frozen by TASK-1947)

```python
@register_codec
class JsonCompactCodec:
    codec_name: ClassVar[str] = "json_compact"

    def compress(
        self, result: Any, *, level: FilterLevel, params: dict[str, Any],
    ) -> CompressionOutcome: ...
```

### Does NOT Exist

- ~~A tokenizer~~ — `est_tokens_saved` MUST be `bytes/4`. Do not import
  `tiktoken`, `transformers`, or any tokenizer.
- ~~`json.dumps` as the project serializer~~ — the project uses
  `datamodel.parsers.json`. Do not switch to stdlib `json` for the payload
  path.
- ~~`ToolResult` involvement~~ — codecs receive the **unwrapped payload**
  (`result.result`), never a `ToolResult`. Do not import
  `parrot.tools.abstract` here (import cycle).
- ~~An existing `dedup`/`compact` helper in `parrot/tools/`~~ — none; write it.

---

## Implementation Notes

### Pattern to Follow

```python
def compress(self, result, *, level, params):
    if level is FilterLevel.NONE:
        return self._passthrough(result)
    try:
        before = len(json_encoder(result).encode("utf-8"))
    except Exception:            # non-serializable payload
        return self._passthrough(result)
    payload = self._elide_nulls(result)
    payload = self._dedup_siblings(payload) if params.get("dedup", True) else payload
    after = len(json_encoder(payload).encode("utf-8"))
    return CompressionOutcome(
        payload=payload, lossy=False, bytes_before=before, bytes_after=after,
        est_tokens_saved=max(0, before - after) // 4, codec_name=self.codec_name,
    )
```

### Key Constraints

- **Losslessness is the contract, not an aspiration.** `lossy` is always
  `False` for this codec, which means the stage will never tee its output —
  so any information loss here is unrecoverable and violates G3. If a
  transformation cannot be proven round-trippable for a given payload, skip
  it for that payload.
- Null-key elision is lossless *for the LLM's purposes* by design decision
  (spec §2 lists it under "lossless only"). Guard it: if a dict has ALL keys
  null, keep the dict as `{}` rather than dropping the dict itself, so
  structure/arity is preserved.
- Exact dedup must only collapse when a marker makes the count explicit —
  e.g. `[{"a":1},{"a":1},{"a":1}]` → `{"_repeat": 3, "_value": {"a": 1}}`.
  If in doubt, do not collapse. Document the marker shape in the docstring;
  the LLM must be able to read it without extra prompting.
- Determinism (G4): no `set` iteration order, no `id()`, no time, no random,
  no LLM. Same input + params → byte-identical output.
- Never raise: any internal exception → return the passthrough outcome.
  (The stage also guards this, but defense in depth.)
- `compress()` is synchronous; sub-millisecond budget (≤ 0.3 ms p99 for
  `MINIMAL` — TASK-1959 measures it).

### References in Codebase

- `parrot/tools/abstract.py:13` — the serializer import.
- `parrot/clients/google/client.py:1199` `_truncate_large_result()` — the
  positional truncation this feature replaces; read it to understand what NOT
  to do (it keeps the first N elements regardless of relevance).

---

## Acceptance Criteria

- [ ] `get_codec("json_compact")` returns the class after importing
      `parrot.tools.compression.codecs`.
- [ ] Round-trip test: decoding the compressed payload yields semantically
      identical content (nulls and dedup markers accounted for).
- [ ] Determinism test: 100 repeated compressions of the same input produce
      byte-identical output (G4).
- [ ] `FilterLevel.NONE` → payload is the *same object*, `bytes_after ==
      bytes_before`, `lossy is False`.
- [ ] Non-serializable payload (e.g. an arbitrary object) → passthrough, no
      exception.
- [ ] `lossy` is `False` for every input.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/tools/compression/ -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/tools/compression/`

---

## Test Specification

```python
# packages/ai-parrot/tests/tools/compression/test_json_compact.py
import pytest
from parrot.tools.compression import FilterLevel, get_codec
import parrot.tools.compression.codecs  # noqa: F401 — triggers registration


@pytest.fixture
def codec():
    return get_codec("json_compact")()


class TestJsonCompact:
    def test_json_compact_is_lossless(self, codec):
        data = {"a": 1, "b": None, "c": [{"x": 1}, {"x": 1}], "d": {"e": None}}
        out = codec.compress(data, level=FilterLevel.MINIMAL, params={})
        assert out.lossy is False
        assert out.bytes_after <= out.bytes_before
        # semantics preserved: no non-null value disappeared
        assert out.payload["a"] == 1
        assert "e" not in out.payload["d"] and out.payload["d"] == {}

    def test_none_level_is_passthrough(self, codec):
        data = {"a": None}
        out = codec.compress(data, level=FilterLevel.NONE, params={})
        assert out.payload is data
        assert out.bytes_after == out.bytes_before

    def test_determinism(self, codec):
        data = {"rows": [{"k": i, "n": None} for i in range(50)]}
        first = codec.compress(data, level=FilterLevel.MINIMAL, params={})
        for _ in range(99):
            assert codec.compress(
                data, level=FilterLevel.MINIMAL, params={}
            ).payload == first.payload

    def test_non_serializable_passthrough(self, codec):
        class Weird:
            pass
        obj = Weird()
        out = codec.compress(obj, level=FilterLevel.MINIMAL, params={})
        assert out.payload is obj

    def test_never_raises(self, codec):
        for bad in [object(), {1: object()}, [object()]]:
            assert codec.compress(bad, level=FilterLevel.NORMAL, params={}) is not None

    def test_est_tokens_saved_is_bytes_over_four(self, codec):
        data = {"a": 1, "b": None}
        out = codec.compress(data, level=FilterLevel.MINIMAL, params={})
        assert out.est_tokens_saved == max(0, out.bytes_before - out.bytes_after) // 4
```

---

## Agent Instructions

1. **Read the spec** (§3 Module 1, §7 "MINIMAL honest calibration").
2. **Check dependencies** — TASK-1947 must be in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — confirm `datamodel.parsers.json` exports
   at `parrot/tools/abstract.py:13`.
4. **Update status** in `sdd/tasks/index/tool-result-compression.json`.
5. **Implement** per scope.
6. **Verify** acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note**.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (autonomous, Sonnet) + adversarial code-review fix pass
**Date**: 2026-07-28
**Notes**: Implemented per spec in the FEAT-380 worktree
(`feat-FEAT-380-tool-result-compression`); acceptance criteria verified via
`pytest packages/ai-parrot/tests/tools/compression/` (144 passed, 6 skipped)
and, where applicable, `cargo test` in `codec-rs/` (12 passed). An
adversarial code review (Claude subagent + Codex, independently verified)
found 3 BLOCKING and 4 SHOULD-FIX cross-cutting issues after all 15 tasks
landed; all were fixed in a follow-up commit
(`fix(tool-result-compression): resolve adversarial code-review findings`)
with 9 additional regression tests, re-verified green.

**Deviations from spec**: none beyond what each task's own file documents
(e.g. TASK-1959's latency recalibration, TASK-1961's truncation
demotion) — see the code-review fix commit for the post-hoc corrections
above.
