---
id: F024
query_id: Q039
type: read
intent: "Read the /pr-review command head: what review already exists so escrow does not duplicate it."
executed_at: 2026-11-07T01:26:34Z
duration_ms: 800
parent_id: null
depth: 0
merged_from: [FC-024]
---

# F024 — /pr-review reviews a GitHub PR against a Jira ticket's acceptance criteria (post-PR, Jira-keyed, optional auto-draft)

## Summary

`.claude/commands/pr-review.md` lines 1-80: `/pr-review <PR_URL> <JIRA_KEY> [--auto-draft]` fetches the PR via `gh` and the Jira ticket via navconfig-loaded `JIRA_*` credentials, then judges whether the diff satisfies the ticket's description and acceptance criteria, optionally converting the PR to draft. It runs **after** the PR exists (i.e. after /sdd-done §9.2) and is keyed by a Jira issue, not by a FEAT spec. Together with the worker's own `code-reviewer` (FC-003) this is the "review" layer the user explicitly says escrow must *not* duplicate: escrow's value is the held state + external release, not another read of the diff.

## Citations

- path: `.claude/commands/pr-review.md`
  lines: 1-5
  symbol: null
  excerpt: |
    # /pr-review — Review a PR Against Jira Acceptance Criteria
    Fetches a GitHub Pull Request and its associated Jira ticket, then reviews
    whether the code changes satisfy the ticket's description and acceptance criteria.
    Optionally converts the PR to draft if criteria are not met.

- path: `.claude/commands/pr-review.md`
  lines: 10-10
  symbol: null
  excerpt: |
    /pr-review <PR_URL> <JIRA_KEY> [--auto-draft]

- path: `.claude/commands/pr-review.md`
  lines: 22-26
  symbol: null
  excerpt: |
    | `<PR_URL>`     | yes      | Full GitHub PR URL (e.g., `https://github.com/org/repo/pull/123`) |
    | `<JIRA_KEY>`   | yes      | Jira issue key (e.g., `NAV-8036`) |
    | `--auto-draft` | no       | If present AND criteria fail, convert PR to draft automatically |

## Notes

- Ordering today: worker code-reviewer → /sdd-done (gates) → PR → /pr-review. Escrow sits between worker completion and /sdd-done.
