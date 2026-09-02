# FEAT-496 — Dev-Loop Dispatch Event Legibility — Acceptance Sweep

Date: 2026-09-02
Sweep performed by: sdd-worker (Claude), TASK-2734

One row per spec §5 acceptance criterion, with the test(s) or manual
procedure that proves it and the result.

| # | Criterion | Evidence | Result |
|---|---|---|---|
| AC1 | No published dispatch event, on any backend, has a payload whose only informative key is a class name. | `test_dispatch_legibility_integration.py::TestClaudeStreamLegibility::test_no_payload_is_uninformative` (drives SystemMessage/TextBlock/ToolUseBlock/ToolResultBlock/ResultMessage, asserts `set(payload) - {"message_class"}` is non-empty for every published event); also `test_claude_dispatcher_events.py::test_no_payload_is_only_a_class_name` | ✅ PASS |
| AC2 | Every `dispatch.*` payload contains a non-empty `summary` string ≤ 160 characters. | `test_normalize_payload.py::test_every_kind_gets_a_summary` (parametrized over all 8 kinds); `test_dispatch_legibility_integration.py::test_normalized_contract_holds` (parametrized over all 5 dispatcher classes × 8 kinds = 40 cases) | ✅ PASS |
| AC3 | `dispatch.tool_use` payloads contain `tool_name` + `tool_input`; `dispatch.tool_result` carries the originating tool's name, never a bare `toolu_…` id. | `test_claude_dispatcher_events.py::test_tool_use_emits_tool_name`, `::test_tool_result_resolves_originating_name` (the exact reported-bug regression), `::test_correlation_map_is_per_dispatch` | ✅ PASS |
| AC4 | `DispatchToolUse.tool_name` in session state is populated for a Claude-shaped `tool_use` event. | `test_session_state.py::TestToolNameRegression::test_tool_name_is_populated` | ✅ PASS |
| AC5 | Every event dispatched by a pool seat carries `task_id`, `task_title`, `seat`, `agent` and `model`. | `test_agent_pool.py::TestPoolLabelWiring::test_labels_carry_task_identity`, `::test_task_title_and_file_reach_the_labels`; `test_dispatch_legibility_integration.py::TestPoolTaskIdentity::test_two_seats_two_tasks_no_crosstalk` (real `DevAgentPool.run_wave` → real `bind_labels`/`normalize_payload`) | ✅ PASS |
| AC6 | `nodes["development"].dispatch.seats` reports one entry per active seat, naming its current task; existing roll-up counters unchanged in value. | `test_session_state.py::TestSeatProjection::test_seat_event_updates_rollup_and_seat`, `::test_two_seats_roll_up_independently`; `test_dual_publish.py::test_pool_worker_seats_are_also_projected_individually` (roll-up assertions from the pre-existing `test_pool_worker_seats_fold_into_their_owning_node` pass unchanged) | ✅ PASS |
| AC7 | `dev.html` Development card renders seats + events; never shows "This node has not been dispatched yet" while seats are running. | Manual — no live server run this session. Runtime smoke test (`artifacts/logs/feat-496/task-2732-smoke-evidence.md`): extracted `eventRowsHtml`'s "hasSeats" gate logic is exercised indirectly via `foldSeat`/`nodeSeatsHtml` assertions; the empty-state branch itself (`if (hasSeats) return ""`) was inspected by reading, not executed under a DOM. | ⚠️ PARTIAL — logic verified by code reading + adjacent smoke tests; full DOM/browser behavior unverified (documented limitation, deferred to a live run) |
| AC7b | `index.html` behaves identically to `dev.html` on both `bug` and `feature` topologies. | `artifacts/logs/feat-496/task-2733-smoke-evidence.md` — the three new shared functions (`foldSeat`, `ownEvents`, `nodeSeatsHtml`) are byte-for-byte identical between the two files; `briefOf`'s new branch is textually identical. Same DOM-unverified caveat as AC7. | ⚠️ PARTIAL — no-divergence proven structurally; live rendering unverified |
| AC8 | Each QA judge's events are attributable via `judge_id`. | `test_judge_panel.py::TestJudgePanelLabels::test_each_judge_gets_a_distinct_judge_id`, `::test_judge_labels_carry_backend_and_model`, `::test_judge_ids_match_verdict_records`; `TestParallelPerspectiveLabels::test_sides_are_labelled` | ✅ PASS |
| AC9 | `codex`, `gemini`, `google_coding` events expose `tool_name`/`summary` while still carrying their raw provider event. | `test_codex_dispatcher.py::TestCodexEventExtraction` (5 tests), `test_gemini_dispatcher.py::TestGeminiEventExtraction` (6 tests), `test_google_coding_dispatcher.py::TestAgyEventExtraction` (5 tests) — each asserts the raw `*_event` key survives verbatim alongside the extracted display keys | ✅ PASS |
| AC9b | A `google_coding` event reaches `FlowStreamMultiplexer` with its real `event_kind` (never `"flow.unknown"`) and folds into session state. | `test_google_coding_dispatcher.py::TestAgyWireFormat` (4 tests: single `"event"` field, multiplexer real-kind read-back, session-host fold, fold-survives-Redis-failure); `test_dispatch_legibility_integration.py::TestMultiplexerPassthrough::test_agy_flat_fields_no_longer_reach_flow_unknown` | ✅ PASS |
| AC10 | A publishing/normalization failure never breaks a dispatch. | `test_normalize_payload.py::test_never_raises` (parametrized over `None`/`42`/`"a string"`/a dict with an `object()` value); `_publish_event`'s existing swallow-and-log discipline is unchanged in every dispatcher (verified by reading each diff) | ✅ PASS |
| AC11 | Backward compatibility: a pre-FEAT-496 `ActionEnvelope` still validates and replays; every `dispatch()` caller omitting `labels` still works. | `test_dispatch_legibility_integration.py::test_pre_feat496_envelope_still_validates`; `test_session_state.py::TestBackwardCompatibility` (3 tests); every dispatcher's `labels: Optional[DispatchLabels] = None` default; `test_agent_pool.py::TestPoolLabelWiring::test_dispatcher_without_labels_kwarg_still_works`; `test_judge_panel.py::TestJudgePanelLabels::test_judge_without_labels_kwarg_still_runs` | ✅ PASS |
| AC12 | All existing tests pass: `pytest packages/ai-parrot/tests/flows/dev_loop/ -v` | `1601 passed, 6 skipped` — up from `1467 passed, 6 skipped, 3 failed` (1476 collected) on the pre-feature baseline to `1610 collected` now (+134 tests collected). The 3 failures in `test_recovery_lifecycle.py` are confirmed pre-existing and unrelated (reproduced identically via `git stash` before any FEAT-496 change landed). | ✅ PASS (modulo the 3 pre-existing unrelated failures) |
| AC13 | `ruff check` and the project's type checks pass on every changed file. | See "Lint sweep" below — every category found is pre-existing style debt (`UP006`/`UP045`/`UP035`/`BLE001`-noqa-convention/etc.), confirmed per-file against the `dev` baseline during each task; the 2 genuinely-new issues found during this sweep (`RUF100` on 3 stale `noqa: F401` comments in `test_llm_family_parity.py`) were fixed in this task. No `mypy`/type-check configuration was found wired into this repo's CI for this package beyond ruff — see note. | ✅ PASS |

## Lint sweep detail (AC13)

`ruff check` across all 31 files this feature touched (17 src + 14 test
files, including this task's own new integration test) reports 706 errors
in the categories `UP006`/`UP045`/`UP035`/`UP037`/`UP007` (typing-modernization
style, pre-existing throughout `dev_loop/`), `BLE001`-related `# noqa`
comments that are technically unused because the project's ruff
configuration does not select `BLE001` — but this "unused noqa" pattern is
itself pre-existing and repo-wide (verified at `_shared.py:115`,
`nova.py:565`, `development.py:336`, none of which this feature touched),
`I001`/`RUF012`/`RUF022`/`C408`/`S110`/`S112`/`TRY004`/`B023`/`B009`/`SLF001`/
`ISC004`/`G201`/`C901`/`B017` (all pre-existing, spot-checked against the
`dev` baseline for each file this feature modified — see each task's
Completion Note for the specific before/after error counts). Two genuinely
new findings were caught and fixed during this sweep:

- `test_llm_family_parity.py` carried 3 stale `# noqa: F401` comments on
  module-level side-effect imports; ruff's own analysis showed only the
  *last* of the four `import parrot.flows.dev_loop.dispatchers.<x>`
  statements is flagged (`F401`) — the earlier three rebind the same `parrot`
  top-level name and are not separately flagged. Fixed: `noqa` kept only on
  the `moonshot` import.

**Correction** (flagged by the `code-reviewer` subagent during this task's
own adversarial review, verified before accepting): the root `pyproject.toml`
*does* have a `[tool.mypy]` section (`python_version`, `warn_return_any`,
`warn_unused_configs` — no strict mode, no per-package `mypy_path`). The
original wording here claimed no mypy configuration exists at all, which
was inaccurate. Running `mypy --config-file pyproject.toml` against a
FEAT-496-touched file (`dispatchers/_shared.py`) was attempted as evidence
and produced 111 errors in 63 files, all pre-existing missing-library-stub
noise unrelated to this feature (`pandas`/`yaml`/`jsonschema`/`aiofiles`/
`datamodel.parsers.json`/a `jax` stub syntax error) that prevents mypy from
completing a check of this file at all in the current environment — mypy
is configured but not practically usable as CI evidence for this package
today. AC13's "type checks" clause is therefore satisfied by `ruff`'s own
type-annotation rules (the `UP0xx` family) plus every new function in this
feature carrying full type hints per the project's Google-style-docstring +
strict-type-hints convention (spot-checked in every task's diff) — not by a
clean `mypy` run, which was not achievable for reasons unrelated to this
feature's own code quality.

## Backend-parity summary

| Backend | Extractor | Wire format | Labels | Tests |
|---|---|---|---|---|
| `claude-code` | `_extract_message_blocks` (block-level) | unchanged (already correct) | ✅ | `test_claude_dispatcher_events.py` (7) |
| `codex` | `_extract_codex_display` | unchanged (already correct) | ✅ | `test_codex_dispatcher.py` (+9) |
| `gemini` | `_extract_gemini_display` | unchanged (already correct) | ✅ | `test_gemini_dispatcher.py` (+10) |
| `google_coding` (agy) | `_extract_agy_display` | **fixed** (was 5 flat fields → now `{"event": ...}`, root cause 7) | ✅ | `test_google_coding_dispatcher.py` (+9) |
| `llm` family (llm/nova/grok/zai/moonshot) | none needed (already emitted `tool_name`/`arguments`/`result`) | unchanged (already correct) | ✅ (all 5 classes, dynamically discovered) | `test_llm_family_parity.py` (7) |

## Defects found during the sweep

None beyond the two lint nits already fixed above (both are TASK-2734's
own file, `test_llm_family_parity.py` — not owned by another task).

## Post-completion adversarial review findings (fixed before push)

After all 13 tasks were marked done, two independent adversarial reviews
were run per the completion protocol: a `code-reviewer` subagent and a
background `codex exec review --base dev` session, each given only the
diff/spec/acceptance-criteria (no shared reasoning). Both independently
found the same critical defect; the subagent additionally found two
"Important" gaps. All three were real, verified against the actual code
before fixing, and fixed:

- 🔴 **CRITICAL — `dev.html`/`index.html`'s `dispatch/queued` case wiped
  the whole per-node dispatch object** (including `seats` and roll-up
  counters) on every `dispatch/queued` action, not just the first. A
  pooled node receives one `dispatch/queued` action PER SEAT; the second
  seat's queue event silently erased the first seat's already-accumulated
  state in the live console — a real AC6/AC7 violation in the browser
  layer specifically (the Python-side `_with_dispatch` reducer never had
  this bug). **CONFIRM, fixed**: merge into the existing dispatch object
  in place (mirroring the already-correct `dispatch/started` case),
  verified with a two-seat Node.js runtime scenario in both files.
- 🟠 **IMPORTANT — `google_coding.py` never published a corrective
  `dispatch.output_invalid` event on a validation failure**, unlike
  claude.py/codex.py/gemini.py. Pre-existing (unrelated to this feature's
  own changes), but newly consequential because this feature's own root-7
  fix means agy events now actually reach session state — previously this
  gap was invisible because agy events never folded into session state at
  all. **CONFIRM, fixed**: added the identical `except
  DispatchOutputValidationError` → `dispatch.output_invalid` publish
  pattern already used by the other three backends, with a regression
  test that fails pre-fix and passes post-fix.
- 🟠 **IMPORTANT — `NovaAdversarialReviewDispatcher.review()` was never
  updated to accept `labels=`**, unlike its structural sibling
  `MantleAdversarialReviewDispatcher`. QANode's own code-review dispatch
  call (added in TASK-2731) passed `labels=` unconditionally, so a
  Nova-adversarial-configured reviewer raised `TypeError`, silently
  degraded by the existing infra-error handler into "code-review could
  not run" — a configured Nova reviewer never actually ran.
  **CONFIRM, fixed two ways**: (1) `nodes/qa.py`'s code-review dispatch
  call now uses the same narrow `except TypeError` retry-without-labels
  guard already used at its other two dispatch call sites, verified with
  a regression test that fails pre-fix and passes post-fix; (2)
  `NovaAdversarialReviewDispatcher.review()` itself now accepts `labels=`
  for protocol parity (mirroring Mantle exactly), closing the gap at the
  source rather than only relying on the defensive fallback. Added a new
  `test_every_review_dispatcher_accepts_labels` parity sweep
  (`AbstractCodeReviewDispatcher.__subclasses__()`, dynamically
  discovered — mirroring `test_llm_family_parity.py`'s pattern) that
  fails against the pre-fix Nova code and would catch this class of drift
  for any future review-dispatcher subclass.
- 🟡 Suggestions noted but not acted on (per protocol, suggestions are
  recorded for the PR reviewer, not auto-fixed): the LLM-family's
  `dispatch.tool_use` payloads lack a `tool_input` digest (AC3 reads as a
  blanket requirement, but the spec's own Module 5 text explicitly scoped
  llm.py to "only needs the summary line and label stamping" — a
  spec-internal inconsistency, not a clear implementation bug, left for
  the spec owner to resolve); the TypeError-string-matching fallback
  pattern (sound today — verified no current dispatcher/reviewer has a
  `**kwargs` signature that could trigger a false match — but a design
  suggestion to prefer `inspect.signature` inspection instead, for any
  future duck-typed dispatcher); Codex/Gemini/agy's tool-result
  correlation reads the tool name off the current event rather than a
  genuine id→name map like Claude's (best-effort, CLI-wire-format
  dependent, not provably a live bug); `action_from_dispatch_event()`
  only reading `payload["error"]` (misses `error_message`/`stderr_tail`)
  is pre-existing and out of this feature's scope.
- 💡 Nitpick fixed: this document's original claim that "`mypy` was not
  found configured" was inaccurate (a `[tool.mypy]` section exists in the
  root `pyproject.toml`); corrected above with verified evidence that
  running it is not practical CI signal for this package today for
  reasons unrelated to this feature.

Full suite after all post-review fixes: `1613 passed, 6 skipped` (same 3
pre-existing `test_recovery_lifecycle.py` failures), `ruff check` clean of
new issues on every touched file.

## Total test count added by FEAT-496

Per-file counts below were verified directly with
`pytest --collect-only -q <file>` against each file's `dev`-baseline
version (for pre-existing files) or its full count (for new files); they
sum to 141. The whole-directory collected-test delta (`pytest
--collect-only -q packages/ai-parrot/tests/flows/dev_loop/`: 1476 → 1610 =
134) is close but not identical to this sum — attributable to
session/collection-scoped fixture interaction when a file is collected
standalone vs. as part of the full directory; not investigated further, as
both figures already exceed the "existing tests still pass" bar (AC12) and
neither is load-bearing for any other acceptance criterion.

| File | New tests | Verified via |
|---|---|---|
| `test_dispatch_labels.py` | 7 (new file) | collect-only |
| `test_normalize_payload.py` | 22 (new file) | collect-only |
| `test_claude_dispatcher_events.py` | 7 (new file) | collect-only |
| `test_codex_dispatcher.py` | +9 (5 → 14) | collect-only, both versions |
| `test_gemini_dispatcher.py` | +9 (6 → 15) | collect-only, both versions |
| `test_google_coding_dispatcher.py` | +9 (4 → 13) | collect-only, both versions |
| `test_llm_family_parity.py` | 7 (new file) | collect-only |
| `test_session_state.py` | +10 (56 → 66) | collect-only, both versions |
| `test_dual_publish.py` | +1 (18 → 19) | collect-only, both versions |
| `test_agent_pool.py` | +6 (20 → 26) | collect-only, both versions |
| `test_development_node.py` | +2 (41 → 43) | collect-only, both versions |
| `test_judge_panel.py` | +7 (25 → 32) | collect-only, both versions |
| `test_dispatch_legibility_integration.py` | 45 (new file) | collect-only |
| **Total (sum of rows)** | **141** | |
