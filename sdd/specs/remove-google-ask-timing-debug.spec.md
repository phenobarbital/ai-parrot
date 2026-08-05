---
feature: remove-google-ask-timing-debug
feature_id: FEAT-411
type: feature
base_branch: dev
jira: NAV-9384
status: approved
---

# FEAT-411 — Remove deprecated "Google ask timing" debug logs from GoogleGenAIClient

**Jira**: [NAV-9384](https://trocglobal.atlassian.net/browse/NAV-9384)
**Status**: approved

## 1. Motivation & Business Requirements

`GoogleGenAIClient` (`packages/ai-parrot/src/parrot/clients/google/client.py`) contains
nine `self.logger.debug` / `self.logger.info` calls whose message starts with
`"Google ask timing:"`. These were added as ad-hoc metering probes during early
development of the Google client.

OpenTelemetry (OTEL) instrumentation was subsequently added (`AfterClientCallEvent`,
`ClientRoundEvent`) and now covers all the same phases with structured spans. The
string-based timing logs are therefore redundant, and:

- They add noise to production CloudWatch log streams.
- They are emitted at `DEBUG` and `INFO` level, which means they appear in staging
  and production under common log configurations.
- Each log call is preceded by a `phase_started = time.perf_counter()` assignment
  that has no other consumer — pure dead weight.

The `ask_started` variable must **not** be removed; it is still consumed by the
OTEL `AfterClientCallEvent` emission at the end of `ask()` and by `ask_stream()`.

## 2. Architectural Overview

Single-file change: `packages/ai-parrot/src/parrot/clients/google/client.py`.

No interface changes, no dependency updates, no new abstractions. This is a
pure deletion of dead instrumentation code.

## 3. Affected Files

| File | Change |
|------|--------|
| `packages/ai-parrot/src/parrot/clients/google/client.py` | Remove 9 timing log blocks + their associated `phase_started` assignments |

## 4. Implementation Notes

### Log occurrences to remove (line numbers approximate, verify before edit)

| # | Approx line | Log message |
|---|-------------|-------------|
| 1 | ~2985 | `"Google ask timing: prepare_conversation_context_ms=..."` |
| 2 | ~3059 | `"Google ask timing: build_tools_ms=..."` |
| 3 | ~3143 | `"Google ask timing: ensure_client_ms=..."` |
| 4 | ~3277 | `"Google ask timing: chat.send_message start model=..."` (INFO) |
| 5 | ~3288 | `"Google ask timing: chat.send_message_ms=..."` (INFO) |
| 6 | ~3413 | `"Google ask timing: function_loop_ms=..."` |
| 7 | ~3435 | `"Google ask timing: response_text_extract_ms=..."` |
| 8 | ~3641 | `"Google ask timing: update_conversation_memory_ms=..."` |
| 9 | ~3680 | `"Google ask timing: ai_message_factory_ms=..."` |

### `phase_started` removal rules

For each `phase_started = time.perf_counter()` assignment:
- Remove it **only** when the assignment's sole consumer is a "Google ask timing" log
  that is also being removed.
- The `phase_started` at ~line 3275 feeds both the `send_message start` log (#4)
  **and** the `function_loop_ms` log (#6) — remove it only when both logs are removed.
- `ask_started` at ~line 2941 feeds the OTEL `AfterClientCallEvent` at ~line 3711 —
  **do not remove**.

### `time` import

After the deletions, verify whether `time` is still imported and used elsewhere in
the file. If the module has no remaining `time.*` calls, remove the `import time`
line as well (run `ruff` to confirm).

## 5. Acceptance Criteria

- [ ] Zero occurrences of `"Google ask timing"` remain in `client.py`
  (`grep -c "Google ask timing" packages/ai-parrot/src/parrot/clients/google/client.py` → `0`)
- [ ] All `phase_started = time.perf_counter()` assignments that were exclusively
  used for the removed logs are also removed.
- [ ] `ask_started` variable is preserved and untouched.
- [ ] `ruff check .` exits 0 (run from repo root with venv active).
- [ ] `pytest -q` exits 0.

## 6. Out of Scope

- No changes to `ask_stream()`, `generation.py`, or any other file.
- No changes to OTEL instrumentation.
- No new tests required (no logic change).
