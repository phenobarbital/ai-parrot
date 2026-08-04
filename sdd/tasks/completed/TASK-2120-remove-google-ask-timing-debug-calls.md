# TASK-2120: Remove all "Google ask timing" debug/info log calls from GoogleGenAIClient

**Feature**: remove-google-ask-timing-debug
**Feature ID**: FEAT-411
**Spec**: sdd/specs/remove-google-ask-timing-debug.spec.md
**Jira**: NAV-9384
**Status**: [x] done
**Priority**: medium
**Effort**: S
**Depends-on**: none
**Assigned-to**: sdd-worker

## Context

`GoogleGenAIClient` in `packages/ai-parrot/src/parrot/clients/google/client.py`
has nine `self.logger.debug` / `self.logger.info` calls whose message starts with
`"Google ask timing:"`. These were ad-hoc metering probes added before OTEL
instrumentation landed. They are now dead weight: redundant with OTEL spans,
noisy in production CloudWatch, and each carries a `phase_started = time.perf_counter()`
assignment with no other consumer.

## Scope

1. Remove all nine `"Google ask timing"` log calls from `client.py`.
2. Remove the associated `phase_started = time.perf_counter()` assignment for
   each removed log, wherever that assignment has no other consumer.
3. Verify `ask_started` (a different variable) is **not** removed — it feeds the
   OTEL `AfterClientCallEvent` at the bottom of `ask()`.
4. If `time` is no longer used anywhere in the file after the deletions, remove
   the `import time` line too.

## Files to Modify

- `packages/ai-parrot/src/parrot/clients/google/client.py`

## Implementation Notes

Locate all occurrences with:
```bash
grep -n "Google ask timing" packages/ai-parrot/src/parrot/clients/google/client.py
```

Expected output (9 lines):
- ~2986: `"Google ask timing: prepare_conversation_context_ms=..."`
- ~3059: `"Google ask timing: build_tools_ms=..."`
- ~3143: `"Google ask timing: ensure_client_ms=..."`
- ~3277: `"Google ask timing: chat.send_message start model=..."` (INFO)
- ~3288: `"Google ask timing: chat.send_message_ms=..."` (INFO)
- ~3413: `"Google ask timing: function_loop_ms=..."`
- ~3435: `"Google ask timing: response_text_extract_ms=..."`
- ~3641: `"Google ask timing: update_conversation_memory_ms=..."`
- ~3680: `"Google ask timing: ai_message_factory_ms=..."`

For each, also remove the immediately-preceding `phase_started = time.perf_counter()`
**if and only if** `phase_started` is not used between its assignment and this log call
for anything else.

Special cases:
- The `phase_started` around the `send_message` block (~line 3275) feeds both the
  `send_message start` log AND the `function_loop_ms` log — safe to remove once both
  logs are removed.
- `ask_started` (~line 2941) is used at lines ~3682 and ~3711 — do NOT remove it.

After edits, verify with:
```bash
grep -c "Google ask timing" packages/ai-parrot/src/parrot/clients/google/client.py
# must be 0
grep -c "ask_started" packages/ai-parrot/src/parrot/clients/google/client.py
# must be >= 2 (assigned + used by OTEL)
```

Then check whether `time` is still needed:
```bash
grep -n "^import time\|time\." packages/ai-parrot/src/parrot/clients/google/client.py | grep -v "Google ask timing"
```

## Acceptance Criteria

- [x] `grep -c "Google ask timing" packages/ai-parrot/src/parrot/clients/google/client.py` outputs `0`
- [x] All `phase_started = time.perf_counter()` assignments exclusively used for removed logs are deleted
- [x] `ask_started` variable is still present and untouched (2 occurrences: assignment + OTEL use)
- [x] `ruff check .` — no new issues introduced (pre-existing I001 import-sort issue unrelated to this task)
- [x] `pytest -q` — 59 passed, 2 pre-existing failures unrelated to this change

## Output

When complete, the agent must:
1. Move this file to `sdd/tasks/completed/`
2. Update `sdd/tasks/index/remove-google-ask-timing-debug.json` — set `"status": "done"`
3. Commit: `sdd: complete TASK-2120 remove-google-ask-timing-debug-calls`

### Completion Note

Removed all 9 "Google ask timing" debug/info log calls from
`packages/ai-parrot/src/parrot/clients/google/client.py`, along with their
associated `phase_started = time.perf_counter()` assignments (8 assignments
removed; one shared assignment for the `send_message` retry loop removed once
both the `send_message start` and `send_message_ms` logs were removed).

`ask_started` (line ~2941) was preserved — it remains consumed by the OTEL
`AfterClientCallEvent` at the end of `ask()`. The `import time` line was
preserved — `time` is still used in ~20 other places in the file
(`_lc_round1_t0`, `time.time()`, `time.sleep()`, `time.monotonic()`, etc.).

Post-edit verification: `grep -c "Google ask timing"` → 0; `grep -c "ask_started"` → 2.
Tests: 59 passed, 2 pre-existing failures (redaction tests, unrelated to this change).
Ruff: no new issues; pre-existing I001 import-sort issue present before this task.
