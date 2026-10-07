---
id: F012
query_id: Q012
type: git_log
intent: Recent commits on jiratoolkit.py — conventions in flight.
executed_at: 2026-10-07T22:57:00Z
duration_ms: 400
parent_id: null
depth: 0
---

# F012 — 14 commits in 120 days, all by the repo owner; last substantive: FEAT-593 config surface

## Summary

Recent activity is config/auth hardening, not description handling: FEAT-593 (2026-09-23) added `JiraToolkitConfig` + `config_options`; FEAT-454 (2026-08-24) delegated reads to JiraInterface; 2026-09-29 forwarded `is_internal` in `jira_add_comment`. No commit touches description composition — no regression risk, and no concurrent work in that region. All commits are by Jesus / Jesus Lara.

## Citations

- path: `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py`
  excerpt: |
    5bafcf8a9 2026-09-29 fix(jiratoolkit): forward is_internal in jira_add_comment
    7f9c3e708 2026-09-23 feat(tool-configuration-agentstudio): TASK-3650 — JiraToolkitConfig + JiraToolkit.config_options(default_project)
    1e94ac244 2026-08-24 feat(jira-extractor-llmwiki): TASK-2402 — JiraToolkit delegation refactor + adversarial review fixes
    cded602e1 2026-07-26 fix(jiratoolkit): treat raised JIRAError 401/403 as definitive rejection
    9c972f8f9 2026-07-06 fix(jiratoolkit): remove silent default auth fallback
