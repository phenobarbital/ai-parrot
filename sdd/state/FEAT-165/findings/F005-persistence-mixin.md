---
finding_id: F005
query_id: Q013
type: pattern
confidence: high
citations:
  - packages/ai-parrot-tools/src/parrot_tools/security/persistence.py:37-55
  - packages/ai-parrot-tools/src/parrot_tools/security/persistence.py:58-150
  - packages/ai-parrot-tools/src/parrot_tools/cloudsploit/toolkit.py:27-44
  - packages/ai-parrot-tools/src/parrot_tools/cloudsploit/toolkit.py:49-73
---

# ReportPersistenceMixin already supports the ECR shape

`ReportPersistenceMixin._persist_report` (persistence.py:77) accepts a
`scanner: str` arg (e.g. `"cloudsploit"`, `"trivy"`), arbitrary `scope` dict,
and content (bytes or `Path`). It's a no-op when `file_manager` /
`report_store` are not injected (persistence.py:120-121).

`CloudSploitToolkit._persist_after_scan` (toolkit.py:49-73) calls it with
`scanner="cloudsploit"`, `framework=...`, `provider="aws"`,
`scope={"account_id": ..., "region": ...}`. The pattern to mirror for ECR is
identical — just register a new scanner key like `"ecr-image-scan"`.

If we want auto-parsed severity summaries, `get_report_parser(scanner)`
(referenced at persistence.py:124) implies there's a parser registry under
`security/parsers/`. That's a follow-up — initial implementation can pass
explicit `severity_summary=...` to bypass the parser lookup.
