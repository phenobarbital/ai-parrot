---
finding_id: F003
query_id: Q008,Q009,Q010,Q011
type: prior-art
confidence: high
citations:
  - packages/ai-parrot-tools/src/parrot_tools/aws/ecr.py:188-240
  - packages/ai-parrot-tools/src/parrot_tools/aws/ecr.py:66-87
  - packages/ai-parrot/src/parrot/interfaces/aws.py:22-122
  - packages/ai-parrot-tools/src/parrot_tools/aws/__init__.py:13
---

# `ECRToolkit.aws_ecr_get_image_scan_findings` already exists

`packages/ai-parrot-tools/src/parrot_tools/aws/ecr.py:188-240` (`ECRToolkit`)
already wraps `ecr.describe_image_scan_findings` via the async `aioboto3`
session managed by `AWSInterface` (`parrot/interfaces/aws.py`). Returned shape:

```python
{
  "repository_name": str,
  "image_tag": str,
  "scan_status": str,           # ECR ImageScanStatus.status
  "severity_counts": {           # CRITICAL/HIGH/MEDIUM/LOW/INFORMATIONAL
      "CRITICAL": int, ...
  },
  "findings": [
      {"name": str, "severity": str, "description": str, "uri": str},
      ...
  ],
  "findings_count": int,
  "total_vulnerabilities": int,
}
```

Critical caveats vs. the user's JS script:

1. **Severity counts ARE returned** by ECR's API — the JS script gets them
   from `imageScanFindings.findingSeverityCounts` and we do the same. ✓
2. **Attributes (package_name, package_version, fixed_in_versions, CVSS) are
   NOT propagated**. The JS script reads them from `f.attributes[]` array on
   each ECR finding; our current Python wrapper drops them at ecr.py:206-214.
   So either:
   - Extend `aws_ecr_get_image_scan_findings` to keep `attributes`, OR
   - Add a new method (e.g. `aws_ecr_get_image_scan_findings_detailed`) that
     returns full attribute payload for downstream report rendering.
3. **`ScanNotFoundException`** is already handled gracefully (returns dict
   with `scan_status: "NOT_FOUND"`) — the JS script silently treats absence
   as `null`. Our wrapper is strictly better here.
4. **Multi-repo / tag-priority iteration is NOT present.** The JS script
   iterates `REPOS = [{name, tags: [...]}, ...]` and falls back to the next
   tag when a scan is missing. This loop is the **distinguishing logic** the
   user wants automated.
5. **Auth model**: `ECRToolkit` uses `AWSInterface(aws_id="default", ...)`
   which resolves credentials from navconfig's `AWS_CREDENTIALS` dict
   keyed by `aws_id`. The JS script reads
   `~/.cloudsploit/aws/credentials.json` directly. These are different
   sources; aligning ECR collection with the rest of the AI-Parrot AWS
   toolkits means using `AWSInterface` (not custom file loading).

**Auxiliary**: `inspector.py` also has `aws_inspector_get_ecr_image_findings`
(inspector.py:560) — same data but via Inspector v2 (Enhanced Scanning) with
much richer normalization, including `vulnerable_packages` with
`fixed_in_version`, `package_manager`, `file_path` (inspector.py:370-378).
The JS script's "package grouping" output is essentially what Inspector v2
returns natively. The ECR Basic Scanning API only exposes packages via the
`attributes` array.

**SDK**: canonical is `aioboto3` for async toolkits (`pyproject.toml` lists
`boto3>=1.28` under the `aws` extra; AWSInterface wraps `aioboto3.Session`).
Inside CloudSploit's *executor* `boto3` is never imported — that module only
shells out to the Node CLI.
