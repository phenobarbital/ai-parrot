---
kind: inline
jira_key: null
fetched_at: 2026-05-12T16:56:09Z
summary_oneline: "Instrumentalize two Node.js scripts (ECR scan collection + HTML report) inside the existing CloudSploit toolkit"
---

# User request (literal)

> Tengo un script Javascript para Cloudsploit ECR, se puede instrumentalizar
> algo así en nuestro CloudSploit toolkit?

Two Node.js scripts were attached:

## Script 1 — `collect_ecr_findings.js`

Purpose: Collects ECR image scan findings for a hard-coded list of ECR repos.

Key behaviors:
- Reads AWS credentials from `$AWS_CREDENTIAL_FILE` or `~/.cloudsploit/aws/credentials.json`
  (JSON file with `accessKeyId`, `secretAccessKey`, optional `region`). Falls back
  to env vars `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`.
- Defaults region to `us-east-2` (env `AWS_DEFAULT_REGION` overrides).
- For each repo in a hard-coded list `REPOS = [{ name, tags: [...] }, ...]`,
  tries tags in priority order (e.g. `staging > production > dev > latest`)
  and stops at the first tag whose image has scan findings.
- Calls `aws ecr describe-image-scan-findings --repository-name <repo>
  --image-id imageTag=<tag> --region <region>` via `execSync`.
- Compatible with both **Basic Scanning** and **Enhanced Scanning** (Inspector).
- Output JSON shape:
  ```json
  {
    "generated_at": "<ISO-8601>",
    "region": "<region>",
    "repos": [
      {
        "repo": "<name>",
        "tag": "<tag>",
        "scan_time": "<ISO-8601 | null>",
        "counts": { "CRITICAL": N, "HIGH": N, "MEDIUM": N, "LOW": N, "INFORMATIONAL": N },
        "findings": [ <ECR finding object>, ... ]
      }
    ]
  }
  ```
- Console output is human-readable per-repo progress, totals at the end.

Hard-coded repos (23 entries) include:
`navigator-api-tf`, `navigator-next-tf`, `navigator-front-tf`,
`navigator-frontend-next-tf`, `navigator-svelte-tf`, `navigator-apps-tf`,
`navigator-front-middleware-tf`, `navigator-eventhooks-tf`,
`navigator-chatbots-tf`, `navigator-voice-tf`, `navigator-partner-portal-tf`,
`navigator-agents-server-tf`, `navigator-api-ai-tf`, `navigator-mcp-tf`,
`navigator-copilot-svelte-tf`, `dataintegrator-tf`,
`dataintegrator-worker-tf`, `dataintegrator-worker-ai-tf`,
`dataintegrator-worker-scraping-tf`, `dataintegrator-sftp-tf`,
`logstash-tf`, `zammad-tf`, `zammad-teams-middleware-tf`.

## Script 2 — `generate_ecr_report.js`

Purpose: Generates an HTML vulnerability report from the JSON produced by
script 1.

Key behaviors:
- Loads findings JSON via `fs.readFileSync`.
- Computes global severity totals across repos.
- Sorts repos with `navigator-api-tf` pinned first, other `navigator-*` next,
  then everything else; secondary sort by CRITICAL/HIGH/MEDIUM/LOW counts.
- Groups CVEs by package (`package_name@package_version`) using the ECR
  `attributes` array (`package_name`, `package_version`, `fixed_in_versions`,
  `CVSS3_SCORE` / `CVSS4_SCORE`).
- Renders a self-contained HTML file with:
  - Hero header with global severity counts.
  - Per-repo collapsible cards (CRITICAL/HIGH auto-expand).
  - Per-package collapsible blocks inside each repo, with CVE table
    (severity badge, CVE id linked to URI, description, fix version, CVSS).
  - Client-side search input + severity filter (`CRITICAL/HIGH/MEDIUM`) +
    per-repo package severity filter.
  - Inline CSS + inline JS (no external assets).
- Output filename defaults to `<input>_report.html` when not specified.

## Implicit functional requirements

- **Auth**: support both credential-file and env-var auth, same way CloudSploit
  toolkit does for its CSPM scans.
- **Multi-repo, multi-tag with priority fallback**.
- **Severity bucketing**: CRITICAL/HIGH/MEDIUM/LOW/INFORMATIONAL.
- **Package grouping** in the rendered report.
- **HTML report** with interactive filters and search.
- **JSON intermediate** for diffing/comparing across runs (parallel to the
  existing `compare_scans()` capability in `CloudSploitToolkit`).
