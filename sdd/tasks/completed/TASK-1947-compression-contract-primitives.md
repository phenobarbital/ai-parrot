# TASK-1947: Compression contract primitives (FilterLevel, Protocol, codec registry)

**Feature**: FEAT-380 — Tool Result Compression Pipeline
**Spec**: `sdd/specs/tool-result-compression.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1 (first half). This task creates the `parrot.tools.compression`
package and **freezes the contract every other task codes against**:
`FilterLevel`, `CompressionOutcome`, the `ResultCompressor` Protocol, and the
codec-class registry (`register_codec` / `get_codec`).

It is deliberately small and blocking: TASK-1948 (TOML registry), TASK-1949
(`json_compact` codec), TASK-1950 (budget) and TASK-1954 (columnar codec) all
run in parallel once this merges. Getting three parallel worktrees to redefine
the same Protocol is exactly the merge pain this task exists to prevent.

---

## Scope

- Create the package `packages/ai-parrot/src/parrot/tools/compression/` and the
  sub-package `.../compression/codecs/`.
- Implement `FilterLevel(str, Enum)` in `levels.py` with the four members and
  an ordering helper so callers can compare/cap levels (`MINIMAL` is the
  documented default; capping to `MINIMAL` is required by TASK-1953).
- Implement `CompressionOutcome(BaseModel)` and the `ResultCompressor`
  Protocol in `protocol.py`, exactly as specified in §2 "Data Models".
- Implement the codec-class registry in `protocol.py`:
  `register_codec` (class decorator keyed by `codec_name`), `get_codec(name)`,
  and `known_codecs()` (used by TASK-1948 for load-time validation of TOML
  `codec` values). Duplicate registration of the same `codec_name` raises
  `ValueError`.
- Export the public surface from `compression/__init__.py`.
- Write unit tests for the above.

**NOT in scope**:
- TOML schema / `CompressorRegistry` / multi-source loading → TASK-1948
  (that task extends `__init__.py`'s exports; do not stub it here).
- Any actual codec implementation (`json_compact` → TASK-1949,
  `columnar` → TASK-1954).
- Latency budget / circuit breaker → TASK-1950.
- Any change to `manager.py`, `abstract.py` or the events package.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/compression/__init__.py` | CREATE | Public surface (see below) |
| `packages/ai-parrot/src/parrot/tools/compression/levels.py` | CREATE | `FilterLevel` + ordering/cap helper |
| `packages/ai-parrot/src/parrot/tools/compression/protocol.py` | CREATE | `CompressionOutcome`, `ResultCompressor`, `register_codec`, `get_codec`, `known_codecs` |
| `packages/ai-parrot/src/parrot/tools/compression/codecs/__init__.py` | CREATE | Empty package marker for codec implementations |
| `packages/ai-parrot/tests/tools/compression/__init__.py` | CREATE | Test package marker |
| `packages/ai-parrot/tests/tools/compression/test_contract.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED against HEAD `024c21d44` on 2026-07-27.
> **Path mapping**: every `parrot/...` path means
> `packages/ai-parrot/src/parrot/...`. The package does NOT live at the repo
> root. A stale build copy exists at
> `packages/ai-parrot/build/lib.linux-x86_64-cpython-311/parrot/` — restrict
> every `grep` to `packages/ai-parrot/src/`.

### Verified Imports

```python
# stdlib / third-party only — this task adds no parrot-internal dependency.
from enum import Enum
from typing import Any, ClassVar, Protocol, runtime_checkable
from pydantic import BaseModel, Field
```

### Existing Signatures to Use

```python
# NONE. This task creates a new leaf package with no inbound dependency on
# existing parrot code. Do not import from parrot.tools.manager,
# parrot.tools.abstract, or parrot.tools.working_memory here — those
# integrations belong to TASK-1951/1952/1953 and importing them now would
# create an import cycle (parrot.tools.__init__ imports manager).
```

### Contract to Create (frozen — other tasks depend on these exact names)

```python
# parrot/tools/compression/levels.py
class FilterLevel(str, Enum):
    NONE = "none"
    MINIMAL = "minimal"       # lossless only  ← DEFAULT
    NORMAL = "normal"         # bounded lossy; activates tee
    AGGRESSIVE = "aggressive" # structural summary only

# parrot/tools/compression/protocol.py
class CompressionOutcome(BaseModel):
    payload: Any
    lossy: bool
    bytes_before: int
    bytes_after: int
    est_tokens_saved: int      # bytes/4 heuristic — approximate by design
    codec_name: str

@runtime_checkable
class ResultCompressor(Protocol):
    codec_name: ClassVar[str]
    def compress(
        self, result: Any, *, level: FilterLevel, params: dict[str, Any],
    ) -> CompressionOutcome: ...

def register_codec(cls: type) -> type: ...       # class decorator
def get_codec(name: str) -> type | None: ...
def known_codecs() -> frozenset[str]: ...
```

### Does NOT Exist

- ~~`parrot.tools.compression`~~ — neither package nor import today; you are
  creating it from scratch.
- ~~`FilterLevel` anywhere in the codebase~~ — zero occurrences. The name
  comes from RTK; it does not exist here.
- ~~`ToolResult.compress()` / `ToolResult.compressed`~~ — zero occurrences.
- ~~`AbstractTool.compress_result()`~~ — zero occurrences (rejected design
  Option C).
- ~~A tokenizer available to the pipeline~~ — none exists. `est_tokens_saved`
  MUST be the `bytes/4` heuristic. Do not add a tokenizer dependency.
- ~~`CompressorRegistry`~~ — does not exist yet; it is TASK-1948's deliverable.
  Do NOT create a stub for it here.

---

## Implementation Notes

### Pattern to Follow

`compress()` is intentionally **synchronous** (spec §7): the inline path has a
sub-millisecond budget and must never `await`. Off-loop execution is the
caller's decision (TASK-1950's budget router), not the codec's.

```python
# levels.py — ordering helper so TASK-1953 can cap a level to MINIMAL
_ORDER = {FilterLevel.NONE: 0, FilterLevel.MINIMAL: 1,
          FilterLevel.NORMAL: 2, FilterLevel.AGGRESSIVE: 3}

def cap(level: FilterLevel, ceiling: FilterLevel) -> FilterLevel:
    """Return ``level`` clamped so it never exceeds ``ceiling``."""
    return level if _ORDER[level] <= _ORDER[ceiling] else ceiling
```

### Key Constraints

- Google-style docstrings + strict type hints on everything (project rule).
- Pydantic for `CompressionOutcome`; plain `Protocol` (not ABC) for
  `ResultCompressor` so third-party codecs need no parrot base class (G6).
- `FilterLevel` subclasses `str` so TOML values deserialize directly and
  Pydantic validates them without a custom validator.
- No logging side effects at import time; module-level `logger =
  logging.getLogger(__name__)` is fine.
- The codec registry is a module-level dict; it is populated by import side
  effect of the codec modules (TASK-1949/1954 register themselves).

### References in Codebase

- `parrot/tools/toolkit.py:390` — `_post_execute()`, the transformer-contract
  precedent (return value replaces the result).
- `parrot/tools/registry.py:42` — `ToolkitRegistry`, an existing registry
  shape in this package for naming/style reference.

---

## Acceptance Criteria

- [ ] `from parrot.tools.compression import FilterLevel, CompressionOutcome, ResultCompressor, register_codec, get_codec` works.
- [ ] Importing `parrot.tools.compression` does NOT import `parrot.tools.manager` (no cycle) — assert with a fresh-interpreter import test or `sys.modules` check.
- [ ] `FilterLevel.MINIMAL` is documented as the default; `cap()` clamps correctly for all 16 pairs.
- [ ] `register_codec` rejects a duplicate `codec_name` with `ValueError`.
- [ ] `known_codecs()` reflects registered codecs and is used by nothing yet.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/tools/compression/ -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/tools/compression/`

---

## Test Specification

```python
# packages/ai-parrot/tests/tools/compression/test_contract.py
import pytest
from parrot.tools.compression import (
    FilterLevel, CompressionOutcome, ResultCompressor,
    register_codec, get_codec, known_codecs,
)
from parrot.tools.compression.levels import cap


class TestFilterLevel:
    def test_default_is_minimal(self):
        assert FilterLevel("minimal") is FilterLevel.MINIMAL

    def test_str_enum_serializes_to_toml_value(self):
        assert FilterLevel.AGGRESSIVE == "aggressive"

    @pytest.mark.parametrize("level,ceiling,expected", [
        (FilterLevel.AGGRESSIVE, FilterLevel.MINIMAL, FilterLevel.MINIMAL),
        (FilterLevel.NONE, FilterLevel.AGGRESSIVE, FilterLevel.NONE),
        (FilterLevel.NORMAL, FilterLevel.NORMAL, FilterLevel.NORMAL),
    ])
    def test_cap(self, level, ceiling, expected):
        assert cap(level, ceiling) is expected


class TestCodecRegistry:
    def test_register_and_get(self):
        @register_codec
        class _Dummy:
            codec_name = "dummy_test"
            def compress(self, result, *, level, params):
                return CompressionOutcome(
                    payload=result, lossy=False, bytes_before=1,
                    bytes_after=1, est_tokens_saved=0, codec_name="dummy_test",
                )
        assert get_codec("dummy_test") is _Dummy
        assert "dummy_test" in known_codecs()
        assert isinstance(_Dummy(), ResultCompressor)

    def test_duplicate_name_raises(self):
        with pytest.raises(ValueError, match="dummy_test"):
            @register_codec
            class _Clash:
                codec_name = "dummy_test"
                def compress(self, result, *, level, params): ...

    def test_unknown_codec_returns_none(self):
        assert get_codec("nope") is None


def test_no_import_cycle_with_manager():
    """compression must be importable without pulling in ToolManager."""
    import subprocess, sys
    code = (
        "import parrot.tools.compression, sys;"
        "assert 'parrot.tools.manager' not in sys.modules"
    )
    assert subprocess.run([sys.executable, "-c", code]).returncode == 0
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above (§2 Data Models, §3 Module 1).
2. **Check dependencies** — none.
3. **Verify the Codebase Contract** — confirm `parrot/tools/compression/` does
   NOT already exist before creating it.
4. **Update status** in `sdd/tasks/index/tool-result-compression.json` →
   `"in-progress"`.
5. **Implement** following the scope and contract above.
6. **Verify** all acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/TASK-1947-compression-contract-primitives.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 4.5)
**Date**: 2026-07-27
**Notes**: Implemented `parrot.tools.compression` package exactly per contract:
`FilterLevel` + `cap()` in `levels.py`; `CompressionOutcome`, `ResultCompressor`
Protocol, and the codec registry (`register_codec`/`get_codec`/`known_codecs`)
in `protocol.py`; public surface re-exported from `__init__.py`; empty
`codecs/` package marker. All 10 unit tests pass (including the
no-import-cycle-with-manager subprocess check and all 16 `cap()` pairs).
`ruff check` clean.

**Deviations from spec**: none
