---
kind: inline
jira_key: null
fetched_at: 2026-05-18
summary_oneline: S3 report reader toolkit — agnostic LLM-facing tools for retrieving, filtering, comparing, and summarizing S3-stored reports
---

A Security Agent using CloudSploitToolkit and other tools is using
`PostgresS3SecurityReportStore` for saving all those findings in an S3 bucket.
Current JSON files follow the scan report format (e.g.,
`security-reports/cloudsploit/scan_20260518_232916.json`).

The idea is creating a tool for interacting with the S3 bucket — the agent can
retrieve the last report, filter by report, extract reports by category, compare
two reports to each other (example: comparing current last report with previous
one to find changes), summarize reports.

The toolkit (inheriting from `AbstractToolkit` and extending
`FileS3Manager` + `PostgresS3SecurityReportStore`) should be more agnostic,
allowing LLMs to extract HTML or JSON documents from S3 bucket — not limited
to security reports only.
