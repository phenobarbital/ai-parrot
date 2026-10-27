# TASK-4700: Repair stale Veo fixtures in reel unit tests + per-test timeout

**Feature**: FEAT-744 — Repair the stale Veo fixtures in the reel unit tests and bound each reel test's runtime
**Spec**: `sdd/specs/unit-reel-tech-debt.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

**Discovered-from**: `issue:990069166e04`

---

## Context

FEAT-719 / TASK-4581 removed the dead Veo preview profiles from
`VideoProfileRegistry.default()`, but `test_reel_veo.py` and
`test_reel_orchestration.py::TestMixedVeoOmniDispatch` still resolve
`veo-3.1-generate-preview` from it → 14 setup errors + 1 failure. The ledger
issue's original slowness no longer reproduces (211 tests in ~30 s, with and
without network), but nothing bounds a single reel test's runtime. This task
implements spec §3 Module 1 in full.

## Scope

- `test_reel_veo.py`: the `profile` fixture builds an enabled, test-local
  `VideoModelProfile` (`veo-3.1-generate-preview`, `gemini_developer`, backend
  `veo`, same shape as `test_reel_profiles.py::veo_registry`) instead of
  resolving it from `VideoProfileRegistry.default()`.
- `test_reel_orchestration.py::TestMixedVeoOmniDispatch`: patch
  `VideoProfileRegistry.default` to return a registry with that Veo profile plus
  the real default `gemini-omni-1.1-flash` profile.
- New `tests/unit/reel/conftest.py`: add `pytest.mark.timeout(120)` to every item
  collected under this directory that has no explicit `timeout` marker.

**NOT in scope**: any `src/` change; test files outside `tests/unit/reel/`;
marker-selection logic in SDD scripts.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-client-google/tests/unit/reel/test_reel_veo.py` | MODIFY | test-local Veo profile fixture |
| `packages/ai-parrot-client-google/tests/unit/reel/test_reel_orchestration.py` | MODIFY | patch registry in `TestMixedVeoOmniDispatch` |
| `packages/ai-parrot-client-google/tests/unit/reel/conftest.py` | CREATE | per-test 120 s timeout |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.clients.google.reel.profiles import VideoModelProfile, VideoProfileRegistry  # test_reel_profiles.py:16-21
```

### Existing Signatures to Use
```python
# packages/ai-parrot-client-google/src/parrot/clients/google/reel/profiles.py
class VideoProfileRegistry:
    def __init__(self, profiles: Iterable[VideoModelProfile]) -> None: ...   # :116
    @classmethod
    def default(cls) -> "VideoProfileRegistry": ...                          # :123-124
    def resolve(self, model_id: str, surface: ApiSurface) -> VideoModelProfile: ...
```
`generation.py:1938-1942` and `:2023-2032` import `VideoProfileRegistry` locally
and call `VideoProfileRegistry.default()`, so patching the classmethod on the
class object takes effect.

### Does NOT Exist
- No Veo profile on `gemini_developer`, and no enabled Veo profile, in `VideoProfileRegistry.default()`.
- No `conftest.py` in `tests/unit/reel/` before this task.

---

## Acceptance Criteria

- [ ] `pytest packages/ai-parrot-client-google/tests/unit/reel -m "not e2e and not real_llm and not integration"` → 0 failed, 0 errors.
- [ ] No file under `packages/*/src/` changes.
- [ ] Every collected reel item carries a `timeout` marker (120 s unless its own).

## Validation Commands

- `pytest packages/ai-parrot-client-google/tests/unit/reel/test_reel_veo.py packages/ai-parrot-client-google/tests/unit/reel/test_reel_orchestration.py -q`

The full-directory run in the Acceptance Criteria is checked by hand before close.

## Completion Note

**Completed**: 2026-10-25 — agent:claude (via /sdd-fix), commit `2fa8691e0`.

- `tests/unit/reel/` (`not e2e and not real_llm and not integration`): 211 passed in 34 s
  (before: 1 failed, 14 errors). Validation command (veo + orchestration files) passes.
- The ledger issue's slowness did not reproduce, with or without network
  (`bwrap --unshare-net`): ~30 s for the whole directory. The timeout guard is the
  issue's suggested prevention, not a fix for an observed hang.
- Deviation from Scope: the test-only Veo profile lives in the new `conftest.py`
  as the shared fixture `veo_test_profile` (used by both test files) instead of
  being built inside `test_reel_veo.py`. Its shape is the pre-FEAT-719 Developer-API
  Veo profile (`person_generation_values=["allow_adult", "allow_all", "dont_allow"]`),
  which the wire-config assertions require.
- AC3 checked: all 211 collected items carry `timeout(120)`; a probe test sleeping
  5 s under a 2 s limit failed with `Timeout (>2.0s) from pytest-timeout` (probe removed).
- No `src/` file changed.
