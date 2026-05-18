# F008 — Parser registry

**Path**: `packages/ai-parrot-tools/src/parrot_tools/security/parsers/__init__.py`
**Lines**: 21-50

Registry: trivy, cloudsploit, prowler, checkov, aggregator.

`get_report_parser(scanner: str) → ReportParser`

Each parser implements:
- `parse(content: bytes) → ParsedReport` (severity_summary + top_findings)
- `extract_section(content: bytes, section: str) → dict`

The new toolkit can leverage parsers for content-type-specific
extraction when dealing with security reports, but needs a generic
fallback for non-security S3 documents.
