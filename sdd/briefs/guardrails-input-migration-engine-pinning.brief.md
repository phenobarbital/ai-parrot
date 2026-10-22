---
kind: brief
slug: guardrails-input-migration-engine-pinning
key: d6027c24b96d
base_branch: dev
source:
  type: ledger
  ref: "issue:d6027c24b96d"
  url: null
jira_issue_key: null
ledger_issue: "issue:d6027c24b96d"
created: "2026-10-22"
---

# Brief: Pin the injection engine in the INPUT-migration test harness

<!-- FEAT-698. One brief = one fix. Task files live in sdd/briefs/<slug>/tasks/. -->

## Problem

All 8 of these tests in `packages/ai-parrot/tests/unit/test_guardrails_input_migration.py`
fail on any machine where an ONNX graph is cached, and pass where one is not:

```
TestRunInputPipelineGolden::test_blocked_input_sets_reason_and_report
TestRunInputPipelineGolden::test_trusted_source_bypasses
TestPromptForLlmInvariant::test_question_object_never_rebound
TestInvokeEndToEnd::test_blocked_input_canned_response_no_llm_call
TestAskEndToEnd::test_blocked_input_canned_response_with_threats_detected
TestAskStreamEndToEnd::test_blocked_input_yields_canned_string
TestAskStreamEndToEnd::test_method_context_is_ask_stream_not_ask
TestSanitizeQuestionDeprecatedDelegate::test_delegate_raises_on_block
```

Every one dies the same way:

```
AttributeError: 'NoneType' object has no attribute 'detect_injection'
```

Quoting the source (`issue:d6027c24b96d`, kind `tech_debt`, severity `minor`,
discovered-from `spec:FEAT-714`):

> So this suite's pass/fail depends on whatever the dev machine has cached, and
> it is GREEN in an environment with no ONNX graph.

Observed on `dev@b35379119` (2026-10-22) while running a neighbouring-suite
regression sweep for FEAT-714 / TASK-4563 — **pre-existing**, reproduced
identically on the unfixed tree, so not caused by that feature. The practical
cost is a suite nobody can trust: 8 reds that look like a real regression on
one laptop and a clean run on another, and CI coverage that silently depends on
cache state.

## Root cause

The harness does patch a detector — just not one that is on the path the
guardrail actually takes.

`_patched_bot` (`packages/ai-parrot/tests/unit/test_guardrails_input_migration.py:34`)
builds the bot under a patch of
`parrot.bots.guardrails.builtin.prompt_injection._get_shared_injection_detector`
(`:37`). That function (`prompt_injection.py:123`) is consulted **only** by the
*pytector* engine-construction branch (`prompt_injection.py:548`).

But `PromptInjectionGuardrail.__init__` does not call it. It resolves its engine
through `_resolve_injection_engine()` (`prompt_injection.py:617`), whose
precedence chain prefers the **ONNX** backend. When ONNX wins, the ctor sets

```python
self._pytector_detector = (          # prompt_injection.py:730
    self._injection_engine._detector
    if isinstance(self._injection_engine, _PytectorInjectionEngine)
    else None
)
```

— i.e. `None`, exactly as its own NOTE at `prompt_injection.py:724` documents:
`_pytector_detector` is a back-compat alias for the *pytector* detector
specifically, never "whichever ML engine is in use".

So the harness's patch is **inert**: engine resolution runs for real, picks
ONNX, and the 8 tests then dereference `None` at their
`pi_guardrail._pytector_detector.detect_injection.return_value = (True, 0.99)`
line (`:99` and 7 siblings). Nothing in this file ever patches
`_resolve_injection_engine`, which is the only lever that decides the backend.

This suite was already known to be fragile for a *related* reason:
`packages/ai-parrot/tests/conftest.py:51`'s autouse
`_reset_injection_engine_singleton` fixture names
`test_guardrails_input_migration.py` by name as a victim of cross-suite engine
leakage. FEAT-439 fixed the leakage; it never made this suite pin its own
engine, so the file still inherits whatever resolution finds on the box.

## Research findings

- **Symbols** (`wikitoolkit symbols lookup` / `blast`):
  `_resolve_injection_engine` (`prompt_injection.py:617`, memoized,
  `force_reresolve` arg) is called by `PromptInjectionGuardrail.__init__`
  (`:685-740`) and `warmup_injection_model` (`:913-961`). Its blast radius
  includes ~14 `TestEngineResolution`/`TestWarmup` tests in
  `test_guardrails_prompt_injection.py` — all of which patch it, which is
  precisely the pattern this file is missing.
- **Prior art in the repo**: `_mock_pytector_engine`
  (`test_guardrails_prompt_injection.py:45`) is a 3-line helper that wraps a
  `MagicMock` detector as a resolved pytector engine, written for exactly this
  purpose — "for `_resolve_injection_engine` patches". Its sibling fixture
  (`:51-61`) is the canonical usage: patch the resolver, return the wrapped
  mock, and `_pytector_detector` is then the same mock object the test holds,
  so assertions that set `detect_injection.return_value` keep working unchanged.
- **Ledger context**: `wikitoolkit ledger context` on the target file reports
  only this issue — no other open work touches it.
- **Why the ONNX branch wins here**: the autouse singleton reset means each test
  re-resolves, and resolution prefers a cached ONNX snapshot over pytector; the
  dev box has one. Nothing is wrong with resolution — the test harness is simply
  not pinning it.

## Decisions

From the Q&A round:

1. **Helper home — promote to `tests/conftest.py`.** Move/add a shared
   `_mock_pytector_engine` helper to `packages/ai-parrot/tests/conftest.py`,
   beside the existing `_reset_injection_engine_singleton` autouse fixture, and
   have both suites use it. One definition instead of a second copy that can
   drift, and the next suite needing a pinned engine finds it where the reset
   fixture already lives. (Rejected: duplicating the helper locally; building
   `_PytectorInjectionEngine(...)` inline, which hard-codes a private ctor
   signature into the test.)
2. **Add a regression guard.** `_patched_bot` asserts the patch took effect
   (`_pytector_detector is mock_detector`) before returning the bot, so a future
   change to engine resolution fails with a clear message instead of 8 opaque
   `AttributeError: 'NoneType'` reds. (Rejected: fix-only, which leaves the same
   trap armed; parametrizing the seam tests over all three engines, which turns
   a single-file tech-debt fix into a test-suite redesign.)

## Fix plan

- **HOTFIX-d6027c24b96d-1** — pin the engine in `_patched_bot` and share the
  helper: add `_mock_pytector_engine` to `tests/conftest.py`, patch
  `_resolve_injection_engine` (alongside or in place of the inert
  `_get_shared_injection_detector` patch) so the guardrail resolves to the
  wrapped mock, assert the wiring took effect, and point
  `test_guardrails_prompt_injection.py` at the shared helper. The 8 tests'
  `_pytector_detector.detect_injection` lines are left untouched — they start
  working again because the alias is populated.

## Validation commands

- `pytest packages/ai-parrot/tests/unit/test_guardrails_input_migration.py -q`
- `pytest packages/ai-parrot/tests/unit/test_guardrails_prompt_injection.py -q`
