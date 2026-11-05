---
id: FG-002
query_id: Q031
type: git_log
intent: "Recent history of the Google client routing gates."
executed_at: 2026-11-04T01:37:14Z
duration_ms: 400
parent_id: null
depth: 0
---

# FG-002 — client.py is hot: 15 commits in 90 days across FEAT-688, FEAT-719, FEAT-781 and unified-usage

## Summary

`client.py` changed in four feature lanes since mid-October: the FEAT-688 routing gates
(`c76b846670`, TASK-4370, +27/-14 with 35 test lines in `packages/ai-parrot/tests/test_google_client.py`),
the FEAT-719 computer-use vocabulary (`e875799d5d`, TASK-4586, +94 lines + new
`tests/unit/test_computer_use_vocabulary.py`), the FEAT-781 cache/stream fixes
(`4f9d6383c3`, `235ba562a4`, `d889c66d9e`, 2026-10-30, PR #1890) and the unified-usage
counters (`aaee16b4b5`, 2026-11-01, TASK-5079). Any 2.5-prefix gate edit lands on top of
these; the last gate edit is three weeks old, so anchors from the FEAT-688 task files are stale.

## Citations

- path: `packages/ai-parrot-client-google/src/parrot/clients/google/client.py`
  lines: n/a
  symbol: `GoogleGenAIClient`
  excerpt: |
    aaee16b4b5 2026-11-01 fix(unified-usage): TASK-5079 — client cache/reasoning counters, drop dead hasattr
    5a7628e82e 2026-10-30 style(google-client-fixes): FEAT-781 — lint fixes
    d889c66d9e 2026-10-30 fix(google-client-fixes): TASK-4913 — FEAT-719 leftovers: Literal vocabulary type (client.py +7/-2)
    235ba562a4 2026-10-30 fix(google-client-fixes): TASK-4912 — return Gemini stream chunks verbatim
    4f9d6383c3 2026-10-30 fix(google-client-fixes): TASK-4911 — attach Gemini CachedContent without system_instruction
    e875799d5d 2026-10-22 feat(model-deprecation-followups): TASK-4586 (client.py +94/-6; tests/unit/test_computer_use_vocabulary.py +70)
    c76b846670 2026-10-16 feat(gemini-upgrade): TASK-4370 — GoogleGenAIClient routing gates (client.py +27/-14; tests/test_google_client.py +35)
    979b52468f 2026-10-12 fix(google): preserve broader anyOf union values
    5b6befc708 2026-10-11 fix(google): carry only string enums out of anyOf

- path: `packages/ai-parrot/tests/test_google_client.py`
  lines: n/a
  symbol: n/a
  excerpt: |
    gate tests added by c76b846670 (TASK-4370) — the file to extend when the 2.5 thinking prefix is dropped

- path: `packages/ai-parrot-client-google/tests/unit/test_computer_use_vocabulary.py`
  lines: n/a
  symbol: n/a
  excerpt: |
    added by e875799d5d (TASK-4586) — computer-use tests live in the satellite, not in packages/ai-parrot/tests

## Notes

- Two test trees cover client.py: `packages/ai-parrot/tests/test_google_client.py` (FEAT-688) and `packages/ai-parrot-client-google/tests/unit/` (FEAT-719/781).
- [cross-lane: type=grep, intent=re-grep the prefix gates in client.py at HEAD — FEAT-688 anchors predate four later commits]
