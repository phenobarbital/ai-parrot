# TASK-1845: File-based identity loader + public cached reader

**Feature**: FEAT-321 — PromptBuilder Identity Capability
**Spec**: `sdd/specs/promptbuilder-identity-capability.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 2. Nothing today loads the five identity fields
(`role`, `goal`, `capabilities`, `backstory`, `rationale`) from per-field
Markdown files. This task creates the `IdentityFields` model and
`load_identity(directory)`, and promotes the private mtime-keyed cached reader
`agent_context._read_cached` to a public `read_text_cached(path)` so the loader
(and the hot-reload path in TASK-1846) get near-free repeated reads.

---

## Scope

- MODIFY `packages/ai-parrot/src/parrot/bots/prompts/agent_context.py`:
  add public `read_text_cached(path: Union[str, Path]) -> str` — stats the
  file (`st_mtime`) and delegates to the existing lru-cached `_read_cached`;
  returns `""` when the file does not exist or cannot be read (debug log).
  Refactor `load_agent_context` to use it internally (behavior unchanged).
- CREATE `packages/ai-parrot/src/parrot/bots/prompts/identity.py`:
  - `IDENTITY_FILES: tuple[str, ...] = ("role", "goal", "capabilities", "backstory", "rationale")`
  - `class IdentityFields(BaseModel)` — five `Optional[str]` fields (default
    `None`) + `as_kwargs() -> dict[str, str]` returning non-empty fields only
    (exact model shape in spec §2 Data Models).
  - `def load_identity(directory: Union[str, Path], *, escape_placeholders: bool = False) -> IdentityFields`
    — for each name in `IDENTITY_FILES` read `<directory>/<name>.md` via
    `read_text_cached`, strip; empty/whitespace/missing/unreadable → `None`
    (SILENT — debug log only, mirror `load_agent_context`). Content is
    injected **verbatim — NO `$`-escaping by default** (dynamic-variable
    parity, spec §7). When `escape_placeholders=True`, replace `$` with `$$`.
    Missing directory → all fields `None`, no error.
- Write unit tests (see Test Specification).

**NOT in scope**: the prompt layer/preset (TASK-1844), the mixin/hot-reload
(TASK-1846), Porygon (TASK-1847), any change to `load_agent_context`'s public
behavior or to `AGENT_CONTEXT_LAYER`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/prompts/identity.py` | CREATE | `IdentityFields` + `load_identity` |
| `packages/ai-parrot/src/parrot/bots/prompts/agent_context.py` | MODIFY | Add public `read_text_cached` |
| `packages/ai-parrot/tests/bots/prompts/test_identity_loader.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-07-21 on `dev`. Use these VERBATIM; verify anything not listed.

### Verified Imports
```python
from parrot.bots.prompts.agent_context import load_agent_context  # existing
from pydantic import BaseModel, Field                             # house standard
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/prompts/agent_context.py
@functools.lru_cache(maxsize=256)
def _read_cached(path: str, mtime: float) -> str    # line 38-54 — cache key is
    ...                                             # (path, mtime); changed st_mtime ⇒ fresh read
def load_agent_context(agent_id: str) -> str        # line 57 — reads
    ...   # <AGENT_CONTEXT_DIR>/<agent_id>.md; MISSING FILE → "" SILENTLY (lines 88-89);
          # lazily creates the dir swallowing OSError to debug log (85-86)
AGENT_CONTEXT_LAYER   # line 96-107 — do not modify
```

### Does NOT Exist
- ~~`parrot/bots/prompts/identity.py`~~ / ~~`IdentityFields`~~ / ~~`load_identity`~~ /
  ~~`IDENTITY_FILES`~~ — created by THIS task.
- ~~`read_text_cached`~~ — created by THIS task; today only private `_read_cached` exists.
- ~~an `identity/` directory convention anywhere in the framework~~ — introduced by
  this feature; do not look for prior art.
- ~~async file reading here~~ — `_read_cached`/`load_agent_context` are synchronous by
  design (lru_cache); `load_identity` is synchronous too (it runs inside `__init__`
  and per-build hooks).

---

## Implementation Notes

### Pattern to Follow
```python
# read_text_cached: thin public wrapper keeping ONE shared lru cache
def read_text_cached(path: Union[str, Path]) -> str:
    p = Path(path)
    try:
        mtime = p.stat().st_mtime
    except OSError:
        return ""
    return _read_cached(str(p), mtime)
```
Silence discipline mirrors `load_agent_context` (agent_context.py:88-89):
missing → `""`, no warnings; decode/permission errors → debug log + `""`.

### Key Constraints
- Pydantic model with strict type hints + Google-style docstrings.
- `as_kwargs()` filters empty values so injection never short-circuits the
  `kwarg → class attr → DEFAULT` fallthrough with `""`.
- Whitespace-only file content must normalize to `None` (spec §7 gotcha).
- NO `$`-escaping by default — spec resolved question; escaping would break
  `$current_date`-style dynamic variables inside personas (abstract.py:1200-1214).
- Module-level `logging.getLogger(__name__)` (no `self` here — plain functions).

### References in Codebase
- `packages/ai-parrot/src/parrot/bots/prompts/agent_context.py:38-89` — caching +
  silence pattern to mirror
- `sdd/specs/promptbuilder-identity-capability.spec.md` §2 Data Models — exact
  `IdentityFields` shape

---

## Acceptance Criteria

- [ ] `load_identity(dir)` loads all five fields, stripped, from a full
      `identity/` fixture directory.
- [ ] Missing file / empty file / whitespace-only file → that field is `None`;
      no exception, no warning.
- [ ] Missing directory → `IdentityFields()` with all fields `None`.
- [ ] File containing `$current_date` loads verbatim (no `$$`) by default;
      `escape_placeholders=True` doubles `$`.
- [ ] `read_text_cached` returns cached content for unchanged mtime and fresh
      content after the file is modified (mtime bumped).
- [ ] `load_agent_context` behavior unchanged (existing tests still pass).
- [ ] All tests pass: `pytest packages/ai-parrot/tests/bots/prompts/test_identity_loader.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/bots/prompts/`
- [ ] Imports work: `from parrot.bots.prompts.identity import IdentityFields, load_identity`

---

## Test Specification

```python
# packages/ai-parrot/tests/bots/prompts/test_identity_loader.py
import os
import pytest
from parrot.bots.prompts.identity import IdentityFields, load_identity
from parrot.bots.prompts.agent_context import read_text_cached


@pytest.fixture
def identity_dir(tmp_path):
    for f, text in {
        "role": "a test analyst",
        "goal": "answer questions",
        "capabilities": "- do X\n- do Y",
        "backstory": "context here",
        "rationale": "be concise",
    }.items():
        (tmp_path / f"{f}.md").write_text(text, encoding="utf-8")
    return tmp_path


class TestLoadIdentity:
    def test_reads_all_fields(self, identity_dir):
        fields = load_identity(identity_dir)
        assert fields.role == "a test analyst"
        assert fields.capabilities == "- do X\n- do Y"
        assert len(fields.as_kwargs()) == 5

    def test_missing_file_is_none(self, identity_dir):
        (identity_dir / "goal.md").unlink()
        assert load_identity(identity_dir).goal is None

    def test_empty_file_is_none(self, identity_dir):
        (identity_dir / "role.md").write_text("   \n", encoding="utf-8")
        fields = load_identity(identity_dir)
        assert fields.role is None
        assert "role" not in fields.as_kwargs()

    def test_missing_directory(self, tmp_path):
        assert load_identity(tmp_path / "nope").as_kwargs() == {}

    def test_no_dollar_escaping_by_default(self, identity_dir):
        (identity_dir / "backstory.md").write_text("Today is $current_date", encoding="utf-8")
        assert load_identity(identity_dir).backstory == "Today is $current_date"

    def test_escape_placeholders_flag(self, identity_dir):
        (identity_dir / "backstory.md").write_text("costs $10", encoding="utf-8")
        assert "$$" in load_identity(identity_dir, escape_placeholders=True).backstory


class TestReadTextCached:
    def test_mtime_invalidation(self, tmp_path):
        f = tmp_path / "x.md"
        f.write_text("v1", encoding="utf-8")
        assert read_text_cached(f) == "v1"
        f.write_text("v2", encoding="utf-8")
        os.utime(f, (f.stat().st_atime, f.stat().st_mtime + 2))
        assert read_text_cached(f) == "v2"

    def test_missing_file_empty(self, tmp_path):
        assert read_text_cached(tmp_path / "nope.md") == ""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none for this task
3. **Verify the Codebase Contract** — before writing ANY code, confirm every
   listed import/signature still exists; update the contract first if drifted
4. **Update status** in `sdd/tasks/index/promptbuilder-identity-capability.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1845-identity-loader-cached-reader.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-21
**Notes**: Promoted `read_text_cached(path)` in `agent_context.py` as a thin
public wrapper over the existing `_read_cached` lru cache (single shared
cache preserved); `load_agent_context` refactored to call it internally,
behavior unchanged (17 pre-existing tests in
`tests/test_agent_context_loader.py` still pass). Created
`prompts/identity.py` with `IdentityFields` (Pydantic model, 5 optional
fields + `as_kwargs()`), `IDENTITY_FILES` tuple, and `load_identity()` —
missing/empty/whitespace-only/unreadable file all silently resolve to
`None` (debug log only), content injected verbatim by default with an
opt-in `escape_placeholders` flag. 10 new unit tests pass; `ruff check`
clean on all touched files.

**Deviations from spec**: none
