---
id: FG-004
query_id: Q033
type: git_log
intent: "Commits mentioning gemini / google-genai in the last 90 days across the repo — merged PRs #1685 (FEAT-688), #1773 (FEAT-719), #1890 (FEAT-781)."
executed_at: 2026-11-04T01:37:14Z
duration_ms: 500
parent_id: null
depth: 0
---

# FG-004 — Three merged Gemini lanes in 90 days; FEAT-688 went proposal → merge in 24 h

## Summary

25 matching commits. FEAT-688 (gemini-upgrade) ran 2026-10-15 → 2026-10-16: research proposal
as provisional FEAT-672 (`ca140336eb`), spec (`374cdf7461`), three tasks, merge `acd1dcc924`
(PR #1685). Its TASK-4371 commit `bf7d588bff` is literally "align google-genai floor at 2.31.0".
FEAT-781 (google-client-fixes, PR #1890, `7412fa1ccd`, 2026-10-30) fixed CachedContent and
stream chunks. FEAT-719's Gemini work is referenced via TASK-4913 "FEAT-719 leftovers".
Nothing in the window mentions gemini-2.5 retirement or a deprecation date.

## Citations

- path: `packages/ai-parrot-client-google/pyproject.toml`
  lines: n/a
  symbol: n/a
  excerpt: |
    bf7d588bff 2026-10-16 Jesus feat(gemini-upgrade): TASK-4371 — align google-genai floor at 2.31.0
    acd1dcc924 2026-10-16 phenobarbital Merge pull request #1685 from phenobarbital/feat-FEAT-688-gemini-upgrade

- path: `sdd/specs/gemini-upgrade.spec.md`
  lines: n/a
  symbol: n/a
  excerpt: |
    374cdf7461 2026-10-15 sdd: approved spec + coherent proposal for FEAT-688 — gemini-upgrade
    ca140336eb 2026-10-15 sdd: research-grounded proposal for FEAT-672 — google-genai bump + GoogleModel refresh (provisional id)

- path: `packages/ai-parrot-client-google/src/parrot/clients/google/client.py`
  lines: n/a
  symbol: n/a
  excerpt: |
    7412fa1ccd 2026-10-30 Merge pull request #1890 from phenobarbital/feat-FEAT-781-google-client-fixes
    4f9d6383c3 2026-10-30 fix(google-client-fixes): TASK-4911 — attach Gemini CachedContent without system_instruction
    235ba562a4 2026-10-30 fix(google-client-fixes): TASK-4912 — return Gemini stream chunks verbatim

- path: `packages/ai-parrot/src/parrot/bots/`
  lines: n/a
  symbol: n/a
  excerpt: |
    c6541d544d 2026-10-16 fix(bots): honour use_tools=False in ask/ask_stream/conversation and its prompt
    eaf9f1fbde 2026-10-22 fix(bots-agent-tech-debt): TASK-4619 — speech_report rejects empty speakers
    (no commit in 90 days changes a Gemini default inside parrot.bots)

## Notes

- Unrelated matches: be6e31d092 (Gemini CLI config writer), 5c9d12dd1e, 911b157fd4.
- [cross-lane: type=wiki_page, intent=read sdd/specs/gemini-upgrade.spec.md §non-goals to confirm 2.5 retirement was explicitly deferred]
