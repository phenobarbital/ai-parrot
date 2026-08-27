# TASK-2502: Executable WorkKind → (flow type, base branch) mapping

**Feature**: FEAT-466 — Dev-Loop Run Fidelity
**Spec**: `sdd/specs/dev-loop-run-fidelity.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements **spec Module 1**.

The whole FEAT-466 base-branch bug exists because the rule *"a bugfix is a
hotfix and flows from `main`"* is written down in **prose, inside an agent
markdown file** (`.claude/agents/sdd-research.md:61-69`) and nowhere else. No
code has ever evaluated it. Every consumer that needed the answer either
defaulted to `feature`/`dev` or guessed from `brief.kind`.

This task creates the one function that answers the question, so the six other
tasks in this feature can all call it instead of re-deriving it. It is pure,
has no I/O beyond reading an optional file, and is the dependency root of the
feature — start here.

There is also a latent crash to fix on the way. `.claude/commands/sdd-spec.md:131`
documents:

> "Read the brainstorm/proposal frontmatter (**or default to `feature`/`dev`
> when no exploration doc exists**)"

but the code it tells you to call does not do that:

```python
>>> parse(Path('sdd/proposals/does-not-exist.brainstorm.md'))
FileNotFoundError: [Errno 2] No such file or directory
```

`parse()` defaults gracefully when a file exists *without* frontmatter, but
raises when the file is absent — which is precisely the dev-loop bug path's
situation. The documented default has never had an implementation.

---

## Scope

- Add `resolve_flow()` to `scripts/sdd/sdd_meta.py`, implementing this
  precedence (highest first):
  1. **Explicit overrides** — `type_override` / `base_branch_override`
  2. **Document frontmatter** — `doc_path`, when it is not `None` *and* the
     file exists
  3. **Work-kind mapping** — `bug` → `("hotfix", "main")`;
     `enhancement` / `new_feature` → `("feature", "dev")`
  4. **Default** — `("feature", "dev")`
- Return a `FlowMeta`, so the existing `_hotfix_implies_main` validator
  (`sdd_meta.py:36`) enforces the cross-field rule. **Do not re-implement
  that check.**
- Treat a missing `doc_path` as "no document" (fall through to the next
  precedence level), never as an error.
- Add a `WORK_KIND_FLOW` mapping constant next to `KNOWN_BRANCHES` so the
  mapping is inspectable and testable in isolation.
- Emit a soft warning (`warnings.warn` or a module logger) when a resolved
  `base_branch` falls outside `KNOWN_BRANCHES` — matching the "soft warning"
  behaviour `KNOWN_BRANCHES`' own docstring already promises
  (`sdd_meta.py:23-26`).
- Unit tests per the Test Specification below.

**NOT in scope**:
- Any change to `parse()` or `emit()` — they are load-bearing for existing
  callers. Add a new function; do not alter existing behaviour.
- Any change to `scripts/sdd/reserve_ids.py`. FEAT-466 explicitly leaves the
  allocator untouched (spec §1 Non-Goals, and there is an acceptance criterion
  asserting it).
- Wiring `resolve_flow()` into `/sdd-spec` or `sdd-research` — that is
  TASK-2507.
- Adding `flow_type` / `base_branch` to `WorkBrief` — that is TASK-2508.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `scripts/sdd/sdd_meta.py` | MODIFY | Add `WORK_KIND_FLOW` + `resolve_flow()` |
| `tests/sdd/test_sdd_meta_resolve_flow.py` | CREATE | Unit tests for the new function |

> Check whether `tests/sdd/` already exists; if the repo's SDD script tests
> live elsewhere (`grep -rl "sdd_meta" --include=test_*.py .`), co-locate with
> them instead of creating a new directory.

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from pathlib import Path
from typing import Literal
import yaml
from pydantic import BaseModel, model_validator
# all four already imported at scripts/sdd/sdd_meta.py:15-19

from scripts.sdd.sdd_meta import FlowMeta, parse, emit, KNOWN_BRANCHES
# verified: scripts/sdd/sdd_meta.py:29, 45, 78, 26
```

### Existing Signatures to Use

```python
# scripts/sdd/sdd_meta.py
KNOWN_BRANCHES: frozenset[str] = frozenset({"main", "staging", "dev"})   # line 26

class FlowMeta(BaseModel):                                               # line 29
    type: Literal["feature", "hotfix"]                                   # line 32
    base_branch: str                                                     # line 33

    @model_validator(mode="after")
    def _hotfix_implies_main(self) -> "FlowMeta":                        # line 36
        # raises ValueError when type == "hotfix" and base_branch != "main"

def parse(doc_path: Path) -> FlowMeta:                                   # line 45
    # returns FlowMeta(type="feature", base_branch="dev") when the file
    # exists but has no/invalid frontmatter (lines 67, 70, 73)
    # RAISES FileNotFoundError when the file does not exist (line 66)

def emit(meta: FlowMeta) -> str:                                         # line 78
```

```python
# packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py
WorkKind = Literal["bug", "enhancement", "new_feature"]                  # line 116
```

> Note: `sdd_meta.py` is a **standalone script module** — it must NOT import
> from `parrot.*` (it runs without the package installed). Accept `kind` as a
> plain `str` and validate against a local tuple of the three literals rather
> than importing `WorkKind`.

### Does NOT Exist

- ~~`sdd_meta.resolve_flow()`~~ / ~~`sdd_meta.resolve()`~~ — the module
  exposes only `KNOWN_BRANCHES`, `FlowMeta`, `parse`, `emit`.
- ~~`sdd_meta.WORK_KIND_FLOW`~~ — you are creating it.
- ~~`FlowMeta.kind`~~ — `FlowMeta` has exactly two fields, `type` and
  `base_branch`.
- ~~`from parrot.flows.dev_loop.models.base import WorkKind`~~ inside
  `sdd_meta.py` — do not add this import (see note above).
- ~~a `hotfix` code path anywhere in `packages/`~~ —
  `grep -rni "hotfix" --include=*.py packages/` matches only a test string at
  `packages/ai-parrot/tests/bots/test_github_reviewer.py:103`.

---

## Implementation Notes

### Pattern to Follow

Mirror `parse()`'s shape: small, total, no side effects, Google-style
docstring with an explicit `Raises:` section.

```python
#: WorkKind -> (flow type, base branch). A bugfix is a hotfix and lands on
#: main; everything else is a feature and lands on dev. This mapping used to
#: live only as prose in .claude/agents/sdd-research.md (FEAT-466).
WORK_KIND_FLOW: dict[str, tuple[str, str]] = {
    "bug": ("hotfix", "main"),
    "enhancement": ("feature", "dev"),
    "new_feature": ("feature", "dev"),
}


def resolve_flow(
    *,
    kind: str | None = None,
    doc_path: Path | None = None,
    type_override: str | None = None,
    base_branch_override: str | None = None,
) -> FlowMeta:
    """Resolve the SDD flow type and base branch for a run.

    Precedence, highest first:
      1. ``type_override`` / ``base_branch_override`` (explicit caller intent)
      2. ``doc_path`` frontmatter, when the path is given AND exists
      3. ``WORK_KIND_FLOW[kind]``
      4. ``("feature", "dev")``

    Levels 1 and 2/3 compose: an explicit ``base_branch_override`` with no
    ``type_override`` keeps the type resolved from the lower level, and vice
    versa. This is what lets the console override only the base branch.

    Args:
        kind: A ``WorkKind`` value (``"bug"``/``"enhancement"``/
            ``"new_feature"``). Unknown or ``None`` falls through to the
            default.
        doc_path: Optional brainstorm/proposal/spec whose frontmatter should
            be consulted. A path that does not exist is treated as "no
            document", NOT as an error.
        type_override: Explicit ``"feature"``/``"hotfix"``.
        base_branch_override: Explicit branch name.

    Returns:
        A validated ``FlowMeta``.

    Raises:
        ValueError: When the resolved combination is invalid — e.g.
            ``type="hotfix"`` with a base branch other than ``"main"``. Raised
            by ``FlowMeta``'s own validator, not re-implemented here.
    """
    resolved_type: str | None = None
    resolved_base: str | None = None

    if doc_path is not None and doc_path.exists():
        from_doc = parse(doc_path)
        resolved_type, resolved_base = from_doc.type, from_doc.base_branch
    elif kind in WORK_KIND_FLOW:
        resolved_type, resolved_base = WORK_KIND_FLOW[kind]

    final_type = type_override or resolved_type or "feature"
    final_base = base_branch_override or resolved_base or "dev"

    if final_base not in KNOWN_BRANCHES:
        logger.warning(
            "base_branch %r is not one of the canonical branches %s; "
            "assuming a sub-feature branch.",
            final_base, sorted(KNOWN_BRANCHES),
        )
    return FlowMeta(type=final_type, base_branch=final_base)
```

### Key Constraints

- **Keep it importable standalone.** `scripts/sdd/sdd_meta.py` is imported by
  slash commands via `python -c "from scripts.sdd.sdd_meta import parse"` with
  no venv guarantees beyond `pyyaml` + `pydantic`. No `parrot.*` imports, no
  new third-party dependencies.
- **Do not swallow the validator error.** A caller asking for
  `type="hotfix", base_branch="dev"` is a bug in the caller; let `ValueError`
  propagate so `/sdd-spec`'s documented abort message can surface it.
- The precedence is deliberately *field-wise*, not *level-wise* — a caller
  passing only `base_branch_override` must keep the kind-derived type. There
  is a test for this.
- `logger` — add a module-level `logging.getLogger(__name__)` if none exists;
  do not use `print`.

### References in Codebase

- `scripts/sdd/sdd_meta.py:45-76` — `parse()`, the shape to mirror.
- `scripts/sdd/sdd_meta.py:36-42` — the validator you are reusing.
- `.claude/agents/sdd-research.md:61-69` — the prose rule being made
  executable. Read it; it is the requirement.
- `.claude/commands/sdd-spec.md:141-155` — the two abort messages that consume
  this function's `ValueError` in TASK-2507.

---

## Acceptance Criteria

- [ ] `resolve_flow(kind="bug")` returns `FlowMeta(type="hotfix", base_branch="main")`
- [ ] `resolve_flow(kind="enhancement")` and `resolve_flow(kind="new_feature")`
      both return `FlowMeta(type="feature", base_branch="dev")`
- [ ] `resolve_flow()` with no arguments returns `("feature", "dev")`
- [ ] `resolve_flow(kind="bug", doc_path=<missing path>)` returns
      `("hotfix", "main")` and does **not** raise `FileNotFoundError`
- [ ] A `doc_path` that exists and declares frontmatter beats the kind mapping
- [ ] `type_override` / `base_branch_override` beat both, and compose
      field-wise
- [ ] `resolve_flow(type_override="hotfix", base_branch_override="dev")`
      raises `ValueError`
- [ ] `parse()` and `emit()` behaviour is unchanged (their existing tests, if
      any, still pass)
- [ ] All tests pass: `pytest tests/sdd/test_sdd_meta_resolve_flow.py -v`
- [ ] `ruff check scripts/sdd/sdd_meta.py` clean
- [ ] `python -c "from scripts.sdd.sdd_meta import resolve_flow; print(resolve_flow(kind='bug'))"`
      works from the repo root

---

## Test Specification

```python
# tests/sdd/test_sdd_meta_resolve_flow.py
import pytest

from scripts.sdd.sdd_meta import FlowMeta, WORK_KIND_FLOW, resolve_flow


class TestResolveFlowKindMapping:
    def test_bug_is_a_hotfix_on_main(self):
        meta = resolve_flow(kind="bug")
        assert (meta.type, meta.base_branch) == ("hotfix", "main")

    @pytest.mark.parametrize("kind", ["enhancement", "new_feature"])
    def test_non_bug_kinds_are_features_on_dev(self, kind):
        meta = resolve_flow(kind=kind)
        assert (meta.type, meta.base_branch) == ("feature", "dev")

    def test_no_arguments_returns_default(self):
        meta = resolve_flow()
        assert (meta.type, meta.base_branch) == ("feature", "dev")

    def test_unknown_kind_falls_through_to_default(self):
        meta = resolve_flow(kind="not-a-kind")
        assert (meta.type, meta.base_branch) == ("feature", "dev")

    def test_mapping_constant_is_exhaustive(self):
        assert set(WORK_KIND_FLOW) == {"bug", "enhancement", "new_feature"}


class TestResolveFlowMissingDocument:
    def test_missing_doc_path_is_not_an_error(self, tmp_path):
        """THE regression this task exists for: parse() raises
        FileNotFoundError on a missing path, which is exactly the dev-loop
        bug path's situation."""
        meta = resolve_flow(kind="bug", doc_path=tmp_path / "nope.brainstorm.md")
        assert (meta.type, meta.base_branch) == ("hotfix", "main")

    def test_none_doc_path_is_not_an_error(self):
        assert resolve_flow(kind="bug", doc_path=None).type == "hotfix"


class TestResolveFlowPrecedence:
    def test_existing_doc_frontmatter_beats_kind(self, tmp_path):
        doc = tmp_path / "x.brainstorm.md"
        doc.write_text("---\ntype: feature\nbase_branch: dev\n---\n# body\n")
        meta = resolve_flow(kind="bug", doc_path=doc)
        assert (meta.type, meta.base_branch) == ("feature", "dev")

    def test_overrides_beat_document(self, tmp_path):
        doc = tmp_path / "x.brainstorm.md"
        doc.write_text("---\ntype: feature\nbase_branch: dev\n---\n")
        meta = resolve_flow(
            doc_path=doc, type_override="hotfix", base_branch_override="main"
        )
        assert (meta.type, meta.base_branch) == ("hotfix", "main")

    def test_overrides_compose_field_wise(self):
        """Only base_branch overridden -> the kind-derived type survives.
        This is what lets the console override just the base branch."""
        meta = resolve_flow(kind="enhancement", base_branch_override="staging")
        assert (meta.type, meta.base_branch) == ("feature", "staging")


class TestResolveFlowValidation:
    def test_hotfix_off_main_is_rejected(self):
        with pytest.raises(ValueError, match="hotfix"):
            resolve_flow(type_override="hotfix", base_branch_override="dev")

    def test_unknown_branch_warns_but_succeeds(self, caplog):
        meta = resolve_flow(base_branch_override="feat/parent-branch")
        assert meta.base_branch == "feat/parent-branch"
```

---

## Agent Instructions

1. **Read the spec** — `sdd/specs/dev-loop-run-fidelity.spec.md`, §1 (why),
   §3 Module 1 (what), §6 (verified anchors).
2. **Verify the Codebase Contract** — `sed -n '20,80p' scripts/sdd/sdd_meta.py`
   and confirm the line numbers above still match before writing code.
3. **Reproduce the latent crash first** so you know the default is genuinely
   missing:
   ```bash
   python -c "from pathlib import Path; from scripts.sdd.sdd_meta import parse; parse(Path('nope.md'))"
   ```
4. **Write the failing tests, then the implementation** (TDD).
5. **Verify** every acceptance criterion, then run the full SDD script test
   sweep to confirm nothing regressed.
6. Move this file to `sdd/tasks/completed/` and set the index entry to `done`.

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-27
**Notes**: Added `WORK_KIND_FLOW` + `resolve_flow()` to `scripts/sdd/sdd_meta.py`
exactly per the provided implementation notes, plus a co-located test file
`tests/sdd_scripts/test_sdd_meta_resolve_flow.py` (an existing
`tests/sdd_scripts/test_sdd_meta.py` was found via the documented grep, so no
new `tests/sdd/` directory was created). All 21 tests pass (13 new + 8
existing regression), `python -c "from scripts.sdd.sdd_meta import
resolve_flow; print(resolve_flow(kind='bug'))"` works from repo root. `ruff
check scripts/sdd/sdd_meta.py` reports one pre-existing UP037 finding at
`_hotfix_implies_main` (line 48, unrelated to this task's diff — verified via
`git diff` that the changed lines are only the new `resolve_flow`/
`WORK_KIND_FLOW` additions); left untouched per "do not alter existing
behaviour".

**Deviations from spec**: none
