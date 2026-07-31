---
type: Wiki Overview
title: 'TASK-1338: Add wheel-content verification test (lock pure PEP 420 into CI)'
id: doc:sdd-tasks-completed-task-1338-wheel-content-verification-test-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 6** of the spec — the CI guard that locks the U3
---

# TASK-1338: Add wheel-content verification test (lock pure PEP 420 into CI)

**Feature**: FEAT-201 — ai-parrot-embeddings
**Spec**: `sdd/specs/ai-parrot-embeddings.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1333, TASK-1334, TASK-1335, TASK-1336
**Assigned-to**: unassigned

---

## Context

Implements **Module 6** of the spec — the CI guard that locks the U3
decision (pure PEP 420; no `__init__.py` in the satellite at four
namespace levels). This test builds the satellite wheel and inspects
its zip contents to assert absence of forbidden `__init__.py` files
**and** presence of the expected backend `.py` files. Without this
test, a future setuptools change or accidental commit could
silently break the namespace contract.

Reference: spec §3 Module 6, §5 acceptance criteria 2 and 23.

---

## Scope

- Add `packages/ai-parrot-embeddings/tests/test_wheel_layout.py` with
  two test classes:
  - `TestWheelHasNoInitAtNamespaceLevels` — asserts the satellite
    wheel zip contains NO entry matching any of:
    `parrot/__init__.py`, `parrot/embeddings/__init__.py`,
    `parrot/stores/__init__.py`, `parrot/rerankers/__init__.py`.
  - `TestWheelContainsExpectedBackends` — asserts the wheel DOES
    contain the moved backend files at their expected dotted paths.
- Provide the `satellite_wheel_path` and `satellite_wheel_namelist`
  fixtures in `packages/ai-parrot-embeddings/tests/conftest.py` (use
  the implementation from spec §4 Test Specification).
- Verify the build command works locally:
  `uv build --wheel --out-dir /tmp/wheel-test packages/ai-parrot-embeddings`

**NOT in scope**:
- Cross-distribution namespace-resolution test — that's TASK-1339
  (Module 7).
- Matryoshka / contextual regression — that's TASK-1340 (Module 8).
- Modifying `tool.setuptools.packages.find` config in either pyproject.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-embeddings/tests/conftest.py` | CREATE | `satellite_wheel_path` + `satellite_wheel_namelist` fixtures |
| `packages/ai-parrot-embeddings/tests/test_wheel_layout.py` | CREATE | Wheel-content assertions |

---

## Codebase Contract (Anti-Hallucination)

### Verified Build Tooling

```bash
# uv build is the canonical wheel builder in this repo
uv build --wheel --out-dir <dir> <package-dir>
# Produces: ai_parrot_embeddings-<version>-py3-none-any.whl
```

### Verified Expected Wheel Entries (post-Modules 2-4)

Inside the satellite wheel (a normal Python wheel = zip):

- `parrot/embeddings/google.py` — present
- `parrot/embeddings/huggingface.py` — present
- `parrot/embeddings/openai.py` — present
- `parrot/stores/postgres.py` — present
- `parrot/stores/pgvector.py` — present (3-line shim)
- `parrot/stores/faiss_store.py` — present
- `parrot/stores/milvus.py` — present
- `parrot/stores/arango.py` — present
- `parrot/stores/bigquery.py` — present
- `parrot/rerankers/local.py` — present
- `parrot/rerankers/llm.py` — present

NONE of these:
- `parrot/__init__.py`
- `parrot/embeddings/__init__.py`
- `parrot/stores/__init__.py`
- `parrot/rerankers/__init__.py`

### Verified zipfile API

```python
import zipfile
with zipfile.ZipFile(wheel_path) as zf:
    names = zf.namelist()  # list of slash-separated strings
```

### Does NOT Exist (Anti-Hallucination)

- ~~`tox` integration~~ — this repo uses `uv` + `pytest`, not tox.
  Build via `uv build`, not `python setup.py bdist_wheel`.
- ~~`build` module fallback~~ — `uv build` is the canonical path.
  If `uv` is unavailable in the test environment (unlikely), fall back
  to `python -m build --wheel` (requires `pip install build`); declare
  the fallback as a `dev` extra if needed.
- ~~`wheel.cli`~~ — not used here.
- ~~`packaging.metadata`~~ — not needed for the layout check.

---

## Implementation Notes

### Conftest fixtures

```python
# packages/ai-parrot-embeddings/tests/conftest.py
import subprocess
import zipfile
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def satellite_pkg_root() -> Path:
    """Return the root of the satellite package directory."""
    # This file lives at packages/ai-parrot-embeddings/tests/conftest.py
    return Path(__file__).parent.parent.resolve()


@pytest.fixture(scope="session")
def satellite_wheel_path(satellite_pkg_root, tmp_path_factory) -> Path:
    """Build the satellite wheel once per session and return its path."""
    out_dir = tmp_path_factory.mktemp("wheel")
    subprocess.check_call(
        ["uv", "build", "--wheel", "--out-dir", str(out_dir), str(satellite_pkg_root)],
    )
    wheels = list(out_dir.glob("ai_parrot_embeddings-*.whl"))
    assert len(wheels) == 1, f"expected exactly one wheel, found {wheels}"
    return wheels[0]


@pytest.fixture(scope="session")
def satellite_wheel_namelist(satellite_wheel_path) -> list[str]:
    """All filenames inside the satellite wheel (slash-separated)."""
    with zipfile.ZipFile(satellite_wheel_path) as zf:
        return zf.namelist()
```

### Test body

```python
# packages/ai-parrot-embeddings/tests/test_wheel_layout.py
import pytest


FORBIDDEN_INIT_PATHS = [
    "parrot/__init__.py",
    "parrot/embeddings/__init__.py",
    "parrot/stores/__init__.py",
    "parrot/rerankers/__init__.py",
]

EXPECTED_BACKENDS = [
    "parrot/embeddings/google.py",
    "parrot/embeddings/huggingface.py",
    "parrot/embeddings/openai.py",
    "parrot/stores/postgres.py",
    "parrot/stores/pgvector.py",
    "parrot/stores/faiss_store.py",
    "parrot/stores/milvus.py",
    "parrot/stores/arango.py",
    "parrot/stores/bigquery.py",
    "parrot/rerankers/local.py",
    "parrot/rerankers/llm.py",
]


class TestWheelHasNoInitAtNamespaceLevels:
    """U3: pure PEP 420 — no __init__.py at the four namespace levels."""

    @pytest.mark.parametrize("forbidden", FORBIDDEN_INIT_PATHS)
    def test_no_init_at(self, satellite_wheel_namelist, forbidden):
        assert forbidden not in satellite_wheel_namelist, (
            f"satellite wheel must not contain {forbidden!r} "
            f"(violates U3 / pure PEP 420 namespace package). "
            f"Found names: {[n for n in satellite_wheel_namelist if forbidden in n]}"
        )


class TestWheelContainsExpectedBackends:
    """The moved backends must actually ship in the wheel."""

    @pytest.mark.parametrize("expected", EXPECTED_BACKENDS)
    def test_present(self, satellite_wheel_namelist, expected):
        assert expected in satellite_wheel_namelist, (
            f"satellite wheel missing {expected!r}. "
            f"Available parrot/ entries: "
            f"{[n for n in satellite_wheel_namelist if n.startswith('parrot/')]}"
        )
```

### Performance

The fixture is `scope="session"` so the wheel is built **once** per
test run. Parametrized tests share the same wheel.

### References in Codebase

- `packages/ai-parrot/pyproject.toml:529-532` — proof that
  `namespaces = true` is the host-side enabler (TASK-1338 verifies the
  satellite-side outcome).
- `packages/ai-parrot-tools/pyproject.toml:84-86` — sibling-pattern
  `include = ["parrot_tools*"]` to compare against.

---

## Acceptance Criteria

- [ ] `packages/ai-parrot-embeddings/tests/conftest.py` exists with
      `satellite_pkg_root`, `satellite_wheel_path`, and
      `satellite_wheel_namelist` fixtures.
- [ ] `packages/ai-parrot-embeddings/tests/test_wheel_layout.py`
      exists with the two test classes above.
- [ ] `pytest packages/ai-parrot-embeddings/tests/test_wheel_layout.py
      -v` passes locally (assuming Modules 1-4 are complete).
- [ ] If a hand-crafted regression `__init__.py` is dropped into the
      satellite at any of the four levels, the test FAILS with a clear
      message (manually verify by temporarily creating such a file,
      confirming failure, then removing it).
- [ ] Test runs in under 60 seconds on a clean checkout.
- [ ] No flakiness — the wheel build is deterministic given the same
      source tree.

---

## Test Specification

The test file itself is the deliverable. The acceptance criteria are
the test contract.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** §3 Module 6 and §4 Test Specification.
2. **Check dependencies** — TASK-1333 through TASK-1336 must all be
   in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — confirm `uv build` is available
   in the dev environment; confirm the satellite pyproject builds a
   wheel locally.
4. **Update status** in
   `sdd/tasks/index/ai-parrot-embeddings.json` → `"in-progress"`.
5. **Implement** the conftest fixtures and the test classes. Run
   them. Verify the manual failure-injection step.
6. **Verify** all acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note**.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker agent)
**Date**: 2026-05-28
**Notes**: All 15 wheel layout tests pass. The conftest.py fixtures build
the wheel via `uv build` and make it available session-scoped. Both
`TestWheelHasNoInitAtNamespaceLevels` and `TestWheelContainsExpectedBackends`
are fully implemented and passing.

**Deviations from spec**: none | describe if any
