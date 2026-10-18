# TASK-4370: GoogleGenAIClient routing gates — whitelist Argon, drop gemini-3.7-pro, widen the generation predicate

**Feature**: FEAT-688 — Raise the google-genai floor and refresh GoogleModel for Gemini 4.x (Argon)
**Spec**: `sdd/specs/gemini-upgrade.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 2** plus its gate tests (§4). The enum does not drive routing: the
client decides combined tools+schema, thinking-only behaviour and Vertex `location="global"` with
`startswith()` tests on the model string. Without this task, `gemini-4-argon` is accepted but
silently routed down the two-phase reformat path. Evidence (live REST probes, 2026-10-15,
`sdd/state/FEAT-688/findings/F011-live-catalogue-verification.md`): Argon accepts `tools` +
`responseSchema` in one call, and accepts `thinkingBudget: 0` (so it is **not** thinking-only).

## Scope

1. `_default_combined_call_prefixes`: add `"gemini-4-argon"` (first entry), remove `"gemini-3.7-pro"`.
2. `_requires_thinking`: remove the `gemini-3.7-pro` clause. Do **not** add Argon.
3. Rename `_is_gemini3_model` → `_is_modern_gemini_model`, matching `gemini-3` **or** `gemini-4`;
   update both call sites and both docstring mentions in `client.py`.
4. `_model_class_key`: return a generation-specific key (`gemini3_*` / `gemini4_*`).
5. Gate tests in `packages/ai-parrot/tests/test_google_client.py`.

**NOT in scope**:
- `models.py` / the enum — TASK-4369. This task uses string ids only, so it does not depend on it.
- `_is_computer_use_model` — its `gemini-3-flash-preview` prefix is still a live model.
- `_rejects_zero_thinking_budget`, `_thinking_off`, `_invoke_thinking_config`, the eight inline
  `ThinkingConfig(...)` literals — Argon needs none of them changed.
- Client defaults (`_default_model`, `_fallback_model`, `_lightweight_model`, `_default_reformat_model`) — U4.
- Any `deprecated_models` attribute — U2.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-client-google/src/parrot/clients/google/client.py` | MODIFY | prefixes, `_requires_thinking`, predicate rename, `_model_class_key` |
| `packages/ai-parrot/tests/test_google_client.py` | MODIFY | parametrize updates + three new tests + one docstring |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.clients.google import GoogleGenAIClient                     # test_google_client.py:6
from parrot.clients.google.models import GoogleModel                    # test_google_client.py:342
```

### Existing Signatures to Use
```python
# packages/ai-parrot-client-google/src/parrot/clients/google/client.py
class GoogleGenAIClient(AbstractClient, GoogleGeneration, GoogleAnalysis):   # line 103
    _default_combined_call_prefixes: tuple[str, ...] = (                      # line 148
        "gemini-3.8-flash",       # 149
        "gemini-3.7-flash",       # 150
        "gemini-3.7-pro",         # 151  ← remove
        "gemini-3.6-flash", "gemini-3.5-flash", "gemini-3.5-flash-lite",
        "gemini-3.1-pro", "gemini-3.1-flash-lite",
    )
    @staticmethod
    def _is_gemini3_model(model: str) -> bool                                 # line 229-238 (def at 230)
    @staticmethod
    def _is_preview_model(model: str) -> bool                                 # line 242
    @staticmethod
    def _requires_thinking(model: str) -> bool                                # line 270; clause at 281
    @staticmethod
    def _rejects_zero_thinking_budget(model: str) -> bool                     # line 288 (= _requires_thinking or 3.5-flash-lite)
    @staticmethod
    def _supports_combined_tools_and_schema(model, prefixes) -> bool          # line 394; docstring mention at 401
    @staticmethod
    def _as_model_str(model) -> str                                           # line 420
    def _model_class_key(self, model: str) -> str                             # line 433-443
    async def get_client(self, model: str = None, **kwargs) -> genai.Client   # line 639; comment 661, call 671
```
`_is_gemini3_model` occurrences in `client.py`: **5** (230 def, 401 docstring, 440 call, 661 comment,
671 call). In tests: 1 (`test_google_client.py:351`, docstring). No other module references it, and
no test asserts the literal `"gemini3_stable"`/`"gemini3_preview"` (verified by repo-wide grep).

### Does NOT Exist
- ~~`GoogleGenAIClient._build_thinking_config`~~ — does not exist; do not create it.
- ~~`GoogleGenAIClient._cache_key_for_model`~~ — the helper is `_model_class_key`.
- ~~`GoogleGenAIClient.deprecated_models`~~ — not being added (U2).
- ~~`packages/ai-parrot/tests/clients/test_google_client.py`~~ — the file is `packages/ai-parrot/tests/test_google_client.py`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-client-google/src/parrot/clients/google/client.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/test_google_client.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-client-google/src/parrot/clients/google/client.py#GoogleGenAIClient._is_gemini3_model",
    "sym:packages/ai-parrot-client-google/src/parrot/clients/google/client.py#GoogleGenAIClient._requires_thinking",
    "sym:packages/ai-parrot-client-google/src/parrot/clients/google/client.py#GoogleGenAIClient._model_class_key",
    "sym:packages/ai-parrot-client-google/src/parrot/clients/google/client.py#GoogleGenAIClient.get_client",
    "sym:packages/ai-parrot-client-google/src/parrot/clients/google/client.py#GoogleGenAIClient._supports_combined_tools_and_schema"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `client.py` is ~5800 lines; touch only the anchors below. Do not reformat the file (black would
  reflow unrelated code — restore anything outside these hunks).
- The class docstring (lines 104-115) lists example prefixes; it is illustrative and may stay as is.
- `_rejects_zero_thinking_budget` is derived from `_requires_thinking`, so removing the 3.7-pro
  clause updates both.

---

## Implementation Blueprint

### Steps (in order)
1. Edit the prefix tuple — because this is what gives Argon the single-call path (AC-1).
2. Remove the `gemini-3.7-pro` clause from `_requires_thinking` — because the id is no longer served and a dead prefix keeps matching it.
3. Rename and widen the predicate, then update calls at 440 and 671 and text at 401 and 661 — because Vertex needs `location="global"` for the 4.x family too.
4. Change the `_model_class_key` return — because 3.x and 4.x must not share a cached client key.
5. Update tests; run the Validation Commands.

### `packages/ai-parrot-client-google/src/parrot/clients/google/client.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c -F '        "gemini-3.8-flash",' client.py → line 149)
# BEFORE — insert above `        "gemini-3.8-flash",`
        "gemini-4-argon",
# DELETE — occurrences: 1 (line 151)
        "gemini-3.7-pro",
```
```python
# DELETE — occurrences: 1 (verified: client.py:281)
            or model.startswith("gemini-3.7-pro")
```
```python
# REPLACE lines 229-238 (`def _is_gemini3_model` occurs once, line 230)
    @staticmethod
    def _is_modern_gemini_model(model: str) -> bool:
        """Check if a model belongs to a modern Gemini generation (3.x or 4.x).

        Modern generations on Vertex AI require location='global' and preview
        variants need api_version='v1beta1'. Renamed from ``_is_gemini3_model``
        when the 4.x family landed (FEAT-688).
        """
        model = GoogleGenAIClient._as_model_str(model)
        if not model:
            return False
        return model.startswith("gemini-3") or model.startswith("gemini-4")
```
```python
# REPLACE the body of _model_class_key (lines 440-443; `return f"gemini3_{suffix}"` occurs once, line 442)
        if self._is_modern_gemini_model(model):
            generation = "gemini4" if GoogleGenAIClient._as_model_str(model).startswith("gemini-4") else "gemini3"
            suffix = "preview" if self._is_preview_model(model) else "stable"
            return f"{generation}_{suffix}"
        return "default"
```
```python
# line 671 — occurrences: 1
            if self._is_modern_gemini_model(resolved_model):
# line 670 comment `# Gemini 3.x family requires location='global' on Vertex AI`
#   → `# Gemini 3.x/4.x families require location='global' on Vertex AI`
# lines 401 and 661: replace the text `_is_gemini3_model` with `_is_modern_gemini_model`
```
**Why**: spec M2. After the edit `grep -c _is_gemini3_model client.py` must be `0`.

### `packages/ai-parrot/tests/test_google_client.py` (MODIFY)
```python
# occurrences: 1 (line 351) — docstring text only:
        """Helper is a @staticmethod (matches the _is_modern_gemini_model pattern)."""

# occurrences: 1 (line 362) — AFTER `            "gemini-3.5-flash-001",` add:
            "gemini-4-argon",

# occurrences: 1 (line 374) — AFTER `            "gemini-3-flash-preview",  # NOT in the prefix list — 3-flash without the .5` add:
            "gemini-3.7-pro",  # retired upstream (FEAT-688) — no longer whitelisted
```
```python
# BEFORE — insert above `class TestCombinedCallPrefixesResolution:` (occurrences: 1, line 398)
class TestModernGeminiGates:
    """FEAT-688: generation predicate, cache key and thinking gates for Gemini 4.x."""

    @pytest.mark.parametrize("model", ["gemini-3.5-flash", "gemini-3.1-pro-preview", "gemini-4-argon"])
    def test_is_modern_gemini_model_true(self, model):
        assert GoogleGenAIClient._is_modern_gemini_model(model) is True

    @pytest.mark.parametrize("model", ["gemini-2.5-pro", "gemini-flash-latest", "", None])
    def test_is_modern_gemini_model_false(self, model):
        assert GoogleGenAIClient._is_modern_gemini_model(model) is False

    def test_is_modern_gemini_model_accepts_enum(self):
        # FILL IN: GoogleModel.GEMINI_3_5_FLASH → True — bounded by AC-4 (use an existing member; not GEMINI_4_ARGON, which TASK-4369 adds)

    def test_old_predicate_removed(self):
        assert not hasattr(GoogleGenAIClient, "_is_gemini3_model")

    def test_model_class_key_separates_generations(self):
        client = GoogleGenAIClient(api_key="fake")
        # FILL IN: key(gemini-4-argon) != key(gemini-3.5-flash); key(gemini-2.5-pro) == "default" — bounded by AC-5

    def test_argon_is_not_thinking_only(self):
        assert GoogleGenAIClient._requires_thinking("gemini-4-argon") is False
        assert GoogleGenAIClient._rejects_zero_thinking_budget("gemini-4-argon") is False

    def test_gemini_3_7_pro_no_longer_thinking_gated(self):
        assert GoogleGenAIClient._requires_thinking("gemini-3.7-pro") is False
```
**Why**: string ids keep this task independent of TASK-4369; `GoogleGenAIClient(api_key="fake")`
is the established constructor pattern in this file (line 406).

### FILL IN checklist
- [ ] `test_is_modern_gemini_model_accepts_enum` body
- [ ] `test_model_class_key_separates_generations` assertions
- [ ] `grep -c _is_gemini3_model client.py` → 0; in the test file the name survives only inside `test_old_predicate_removed`

---

## Acceptance Criteria

- [ ] AC-1: `_supports_combined_tools_and_schema("gemini-4-argon", GoogleGenAIClient._default_combined_call_prefixes)` is `True`.
- [ ] AC-2: the same call with `"gemini-3.7-pro"` is `False`; `_requires_thinking("gemini-3.7-pro")` is `False`.
- [ ] AC-3: `_requires_thinking("gemini-4-argon")` and `_rejects_zero_thinking_budget("gemini-4-argon")` are `False`.
- [ ] AC-4: `_is_gemini3_model` no longer exists; `_is_modern_gemini_model` is True for `gemini-3*`/`gemini-4*`, False for 2.x/empty/None, accepts enum members.
- [ ] AC-5: `_model_class_key` differs between a 3.x and a 4.x model; returns `"default"` for 2.x.
- [ ] AC-6: `ruff check` clean on both files; no unrelated hunks in `client.py`.

## Validation Commands
- `pytest packages/ai-parrot/tests/test_google_client.py -q`
- `pytest packages/ai-parrot/tests/clients/test_google_computer_use.py -q`

Run with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-client-google/src` inside the worktree.

## Test Specification

See the blueprint block for `test_google_client.py`. `test_google_computer_use.py` is a regression
guard: the computer-use predicate must be unaffected.

---

## Agent Instructions

1. **Work in the feature worktree** — `python -m scripts.sdd.ensure_worktree --slug gemini-upgrade --feature-id FEAT-688`
2. **Read the spec** `sdd/specs/gemini-upgrade.spec.md` (§3 M2, §4, §6)
3. **Check dependencies** — none
4. **Verify the Codebase Contract** — re-run `grep -c` on every anchor before editing
5. **Update status** in `sdd/tasks/index/gemini-upgrade.json` → `"in-progress"` and commit only that file
6. **Implement** from the blueprint; complete every `# FILL IN:`
7. **Verify** — run the Validation Commands
8. **Commit the code** — stage only the two listed files
9. **Close** with `scripts/sdd/close_task.sh TASK-4370 gemini-upgrade verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker (TASK-4370 via coder seat / native sonnet)
**Date**: 2026-10-15
**Notes**: Implemented per blueprint; merge-tier validation: remaining failures (bedrock factory, lyria, live_envelope, deep_research mock, folder_convention[google]) are pre-existing on origin/dev (verified); this task's tests pass in isolation (33 passed models/factory, 129 incl. google_client).
**Deviations from spec**: none material (TASK-4370: predicate written as startswith(tuple) per ruff PIE810).
