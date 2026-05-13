---
finding_id: F002
query_id: Q003
type: schema-comparison
confidence: high
citations:
  - packages/ai-parrot-tools/src/parrot_tools/cloudsploit/models.py:15-20
  - packages/ai-parrot-tools/src/parrot_tools/cloudsploit/models.py:38-47
  - packages/ai-parrot-tools/src/parrot_tools/cloudsploit/models.py:69-78
---

# Model schemas don't match ECR scan output

`SeverityLevel` (models.py:15-20) is the CloudSploit set: `OK | WARN | FAIL | UNKNOWN`.
ECR / Inspector severities are different: `CRITICAL | HIGH | MEDIUM | LOW | INFORMATIONAL | UNTRIAGED`.

`ScanFinding` (models.py:38-47) carries:
- `plugin, category, title, description, resource, region, status: SeverityLevel, message`

ECR findings carry (per `aws_ecr_get_image_scan_findings` in `aws/ecr.py:206-214`):
- `name, severity, description, uri` (the user's report adds `package_name`,
  `package_version`, `fixed_in_versions`, `CVSS3_SCORE`/`CVSS4_SCORE` from
  `attributes[]`)

`ScanSummary` (models.py:50-66) buckets by OK/WARN/FAIL/UNKNOWN — no concept of
CRITICAL/HIGH/MEDIUM/LOW counts.

**Implication:** Reusing `ScanResult` / `ScanFinding` for ECR collection is a
type mismatch. The new feature needs its own Pydantic models:
- `EcrScanFinding` (with name, severity, description, uri, package_name,
  package_version, fixed_in_versions, cvss).
- `EcrRepoFindings` (repo, tag, scan_time, counts dict, list of findings).
- `EcrCollectionResult` (generated_at, region, repos: list[EcrRepoFindings]).
- A bridging severity enum (`EcrSeverity`) distinct from `SeverityLevel`.

This matches the JS output JSON shape 1:1 so existing JS-produced reports
remain readable by the new Python collector.
