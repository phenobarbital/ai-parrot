# TASK-5161: Record the AC-12 live gate, tighten the computer-use tests, refresh uv.lock for google-genai 2.34

**Feature**: FEAT-798 — Retire gemini-2.5-{pro,flash}: move the Google defaults to Gemini 4 Argon / 3.8-flash and bump google-genai
**Spec**: `sdd/specs/google-migration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (<1h)
**Depends-on**: TASK-5148, TASK-5152, TASK-5155
**Assigned-to**: unassigned
**Discovered-from**: `issue:c95dd1c22324`

---

## Context

The FEAT-798 sdd-worker's review left four gaps (ledger `issue:c95dd1c22324`):

1. Spec AC-12 needs `models.get` evidence in `artifacts/logs/` for `gemini-4-argon`, `gemini-3.8-flash`,
   `gemini-3.8-flash-tts` and `gemini-3.8-live`. The worker sandbox had no network/API key, so none exists,
   although TASK-5155 already deleted the 2.5 predecessors.
2. Weak computer-use tests after TASK-5148 dropped `gemini-2.5-computer-use*` from `_is_computer_use_model`:
   `test_computer_use_requires_thinking` asserts `is False` (name contradicts the assertion), and
   `test_retired_legacy_model_no_longer_computer_use` only restates the vocabulary fallthrough. Two client
   docstrings still talk about "legacy computer-use model identifiers" without naming the one that remains.
3. `test_voicebot_provider_switch.py` failed two source-inspection tests in a merge-tier run; never checked
   against a baseline.
4. `uv.lock` still resolves `google-genai` 2.31.0 while both pyprojects require `>=2.34.0` (`uv lock --check` fails).

## Scope

- Run the AC-12 gate from the host and commit its JSON output as
  `artifacts/logs/FEAT-798-ac12-models-get.json` (`git add -f`; `artifacts/` is gitignored).
- `packages/ai-parrot/tests/clients/test_google_computer_use.py`: rename the contradictory test to state the
  retirement, and add a positive test that the remaining computer-use model (`gemini-3-flash-preview`) is
  thinking-only.
- `packages/ai-parrot-client-google/tests/unit/test_computer_use_vocabulary.py`: make the retired-model test
  pin the behavioural flip (not computer-use, not enabled without opt-in) and contrast it with
  `gemini-3-flash-preview` (enabled, `"legacy"` vocabulary).
- `client.py`: the `ComputerUseVocabulary` comment and the `_computer_use_enabled` docstring name
  `gemini-3-flash-preview` as the only legacy id.
- `uv.lock`: `uv lock --upgrade-package google-genai` (lock only — never `uv sync` inside a worktree).
- Voicebot: verify against `origin/dev`; if the failures predate FEAT-798, record that and leave them.

**NOT in scope**: the `_requires_thinking` comment near `client.py:1261` ("False for flash-preview") —
pre-existing, unrelated to the 2.5 retirement. Class defaults at `client.py:130-133,171` (AC-13).
Fixing the voicebot tests (separate, pre-existing).

## Files to Modify

- `artifacts/logs/FEAT-798-ac12-models-get.json` (new, force-added)
- `packages/ai-parrot/tests/clients/test_google_computer_use.py`
- `packages/ai-parrot-client-google/tests/unit/test_computer_use_vocabulary.py`
- `packages/ai-parrot-client-google/src/parrot/clients/google/client.py` (comments/docstrings only)
- `uv.lock`

## Codebase Contract

### Existing Signatures
- `GoogleGenAIClient._is_computer_use_model(model) -> bool` — `model.startswith(("gemini-3-flash-preview",))`
- `GoogleGenAIClient._requires_thinking(model) -> bool` — Pro prefixes or `_is_computer_use_model`
- `GoogleGenAIClient._computer_use_enabled(self, model) -> bool`, `_computer_use_vocabulary(self, model) -> Literal["legacy", "v3_8"]`
- `GoogleModel.GEMINI_3_FLASH_COMPUTER_USE = "gemini-3-flash-preview"`

### Does NOT Exist
- Any `gemini-2.5-computer-use*` prefix in `_is_computer_use_model` (removed by TASK-5148).

## Acceptance Criteria

- [ ] `artifacts/logs/FEAT-798-ac12-models-get.json` shows `models.get` succeeding for all four ids (`"passed": true`).
- [ ] No test name contradicts its assertion; `gemini-3-flash-preview` is covered as thinking-only and `"legacy"`.
- [ ] `uv lock --check` passes and `uv.lock` resolves `google-genai` >= 2.34.0.
- [ ] The voicebot failures are shown to reproduce on `origin/dev`.
- [ ] `ruff check` clean on touched Python files; the validation command passes.

## Validation Commands

```bash
PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-client-google/src pytest packages/ai-parrot/tests/clients/test_google_computer_use.py packages/ai-parrot-client-google/tests/unit/test_computer_use_vocabulary.py -q
```

## Completion Note

(filled on close)
