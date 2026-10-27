---
type: feature
base_branch: dev
projects: [ai-parrot-client-google]
tags: [tests, reel, veo, pytest-timeout, ledger-fix]
---

# Feature Specification: Repair the stale Veo fixtures in the reel unit tests and bound each reel test's runtime

**Feature ID**: FEAT-744
**Date**: 2026-10-25
**Author**: agent:sdd-fix
**Status**: approved
**Target version**: 1.2.x

> Ledger-driven fix (`/sdd-fix`). Group `fixgroup:951bdbae2ae2`,
> issue `issue:990069166e04` (tech_debt, major, discovered-from spec:FEAT-593).

---

## 1. Motivation & Business Requirements

### Problem Statement

`issue:990069166e04` reports that the merge-tier validation sweep timed out
inside `packages/ai-parrot-client-google/tests/unit/reel/` (2026-09-23: ~one test
outcome per 30–60 s, a 600 s budget exhausted, still unfinished after 1800 s).

Re-measured on 2026-10-25 against `dev` (`d7856cd3d`), with markers
`not e2e and not real_llm and not integration`:

- With network: 211 tests in 29.5 s. Without network (`bwrap --unshare-net`,
  the merge-tier sandbox condition): 211 tests in 29.2 s. Slowest test 5.2 s
  (ffmpeg assembly). **The slowness does not reproduce** and no commit since
  2026-09-20 explicitly addresses it, so it was most likely host load during the
  full-workspace sweep. Nothing caps a single reel test's runtime, so if it
  happens again one hung test can still burn the whole budget.
- **The suite is red instead**: 1 failure + 14 setup errors, all
  `ReelValidationError: Unknown video model 'veo-3.1-generate-preview'`.
  FEAT-719 / TASK-4581 (`d40738b959`) removed the dead Veo preview profiles from
  `VideoProfileRegistry.default()` (the `gemini_developer` surface now has only
  `gemini-omni-1.1-flash`; the Vertex `veo-3.1-*-001` entries are
  `enabled=False`). It updated `test_reel_profiles.py` (which now builds a
  test-only `veo_registry`) but missed `test_reel_veo.py` (its `profile`
  fixture resolves the removed id from the default registry) and
  `test_reel_orchestration.py::TestMixedVeoOmniDispatch` (requests the removed id
  as the reel's `video_model`). FEAT-719 is closed; nothing tracks this.

### Goals

- G1. `tests/unit/reel/` is green again: the 14 `test_reel_veo.py` errors and the
  `TestMixedVeoOmniDispatch` failure pass, without re-adding dead models to the
  production registry.
- G2. Every test under `tests/unit/reel/` runs with a per-test `pytest-timeout`
  limit (120 s), so one hung test fails fast instead of exhausting a merge-tier
  budget, which is the issue's suggested fix.
- G3. No production source changes.

### Non-Goals (explicitly out of scope)

- Re-enabling Vertex Veo or adding any profile to `VideoProfileRegistry.default()`.
- Changing marker-selection logic in `scripts/sdd/select_tests` or `coder_run_validation`.
- Speeding up the ffmpeg assembly tests.
- Test files outside `tests/unit/reel/`.

---

## 2. Architectural Design

### Overview

Test-only change, following the pattern TASK-4581 already set in
`test_reel_profiles.py`: tests that need a Veo profile build an **enabled,
test-local** `VideoModelProfile` (backend `veo`, surface `gemini_developer`)
instead of resolving one from the production registry.

- `test_reel_veo.py`: the `profile` fixture constructs that profile directly.
- `test_reel_orchestration.py::TestMixedVeoOmniDispatch`: patch
  `VideoProfileRegistry.default` (the classmethod `generate_video_reel` and
  `generate_video_clip` call through the local import
  `from .reel.profiles import VideoProfileRegistry`) to return a registry holding
  the test Veo profile + the real default Omni profile.
- New `tests/unit/reel/conftest.py`: a `pytest_collection_modifyitems` hook adds
  `pytest.mark.timeout(120)` to each collected item under this directory that
  has no explicit `timeout` marker.

### Integration Points

`pytest-timeout>=2.3` is already a root dev dependency (`pyproject.toml:75`,
2.4.0 installed); `pytest.ini` sets `asyncio_mode = auto`.

---

## 3. Module Breakdown

### Module 1: Reel test fixtures + per-test timeout
**Files**: `packages/ai-parrot-client-google/tests/unit/reel/test_reel_veo.py`,
`packages/ai-parrot-client-google/tests/unit/reel/test_reel_orchestration.py`,
`packages/ai-parrot-client-google/tests/unit/reel/conftest.py` (new).
One task: TASK-4700.

---

## 4. Test Specification

### Validation Contract

```bash
pytest packages/ai-parrot-client-google/tests/unit/reel -m "not e2e and not real_llm and not integration" -q
```
must report 0 failed / 0 errors, and each reel item must carry a `timeout` marker.

---

## 5. Acceptance Criteria

- AC1. The reel directory selection above passes in full (was: 1 failed, 14 errors).
- AC2. `VideoProfileRegistry.default()` is unchanged (`git diff` touches no `src/` file).
- AC3. Every item collected under `tests/unit/reel/` has a `timeout` marker of 120 s
  unless it declares its own.

---

## 6. Codebase Contract

### Verified Imports
```python
from parrot.clients.google.reel.profiles import VideoModelProfile, VideoProfileRegistry  # test_reel_profiles.py:16-21
```

### Existing Class Signatures
```python
# packages/ai-parrot-client-google/src/parrot/clients/google/reel/profiles.py
class VideoProfileRegistry:
    def __init__(self, profiles: Iterable[VideoModelProfile]) -> None: ...   # :116
    @classmethod
    def default(cls) -> "VideoProfileRegistry": ...                          # gemini_developer: omni only
    def resolve(self, model_id: str, surface: ApiSurface) -> VideoModelProfile: ...
```

### Does NOT Exist (Anti-Hallucination)
- No Veo profile on `gemini_developer` in `VideoProfileRegistry.default()`.
- No enabled Veo profile anywhere in `VideoProfileRegistry.default()`.
- No `conftest.py` in `tests/unit/reel/` today.

### Edit Sites (Blueprint Anchors)
- `test_reel_veo.py:28-30`: `def profile():` fixture.
- `test_reel_orchestration.py:171`: `class TestMixedVeoOmniDispatch:`.

---

## 7. Implementation Notes & Constraints

- Keep the test-local model id `veo-3.1-generate-preview` so the existing wire
  assertions stay valid; the profile's `source="test"` marks it test-only.
- `pytest-timeout` default method on Linux is `signal`; leave it.

## 8. Open Questions

None.

## Revision History

- 2026-10-25: initial (agent:sdd-fix).
