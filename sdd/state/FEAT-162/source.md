---
kind: file
jira_key: null
file_path: sdd/proposals/security-report-catalog-brainstorm.md
fetched_at: 2026-05-12T00:13:00Z
summary_oneline: Cross-session security report catalog (Postgres metadata + S3 content) populated by producer toolkits and consumed via a new SecurityReportToolkit, with weekly/monthly fractal summaries.
---

# Source: security-report-catalog-brainstorm.md (file)

The source is an internal SDD brainstorm document at
`sdd/proposals/security-report-catalog-brainstorm.md` describing a new
cross-session, cross-user catalog of security reports backed by Postgres
(metadata) and S3 (content), populated by the existing producer toolkits
(CloudSploit, Prowler, Trivy, Checkov) via a `ReportPersistenceMixin`,
and consumed by the `SecurityAgent` through a new `SecurityReportToolkit`.

The brainstorm declares its own codebase contract (§3), a three-layer
architecture (§4), a per-module breakdown (§5), key design decisions
(§6), user flow examples (§7), env vars (§8), open questions (§9),
non-goals (§10), and acceptance criteria (§11).

See the full source at `sdd/proposals/security-report-catalog-brainstorm.md`
(committed verbatim — not duplicated here).
