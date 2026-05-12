---
id: F023
query_id: Q023
type: grep
intent: Check whether the /tmp/security-reports/ default path is literally hard-coded somewhere we'll need to coordinate with.
executed_at: 2026-05-12T00:00:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F023 — `/tmp/security-reports` is hardcoded in two places: `agents/security.py` (REPORTS_DIR) and `ComplianceReportToolkit.__init__` default

## Summary

The literal `"/tmp/security-reports"` appears in exactly two files in the
source tree:

1. `agents/security.py:81` — module-level constant `REPORTS_DIR = "/tmp/security-reports"`,
   passed to `CloudSploitConfig.results_dir` (line 146:
   `f"{REPORTS_DIR}/cloudsploit"`) and `ComplianceReportToolkit.report_output_dir` (line 172).
2. `packages/ai-parrot-tools/src/parrot_tools/security/compliance_report_toolkit.py:84` —
   default value of `report_output_dir` kwarg.

CloudSploit's executor writes `scan_*.json` into `CloudSploitConfig.results_dir`
when set (see F011). For the mixin, the cleanest contract is: **the mixin reads
from whatever path the underlying toolkit just wrote**, then uploads to S3 via
the `FileManager`, then stores the metadata. The local file remains on disk
(no implicit cleanup — that is out of scope per the brainstorm's "v1 starts
fresh, do not migrate" acceptance criterion).

## Citations

- path: `agents/security.py`
  lines: 81
  symbol: REPORTS_DIR constant
  excerpt: |
    REPORTS_DIR = "/tmp/security-reports"

- path: `agents/security.py`
  lines: 145-173
  symbol: REPORTS_DIR consumers
  excerpt: |
    self._cloudsploit_toolkit = CloudSploitToolkit(
        config=CloudSploitConfig(
            ...
            results_dir=f"{REPORTS_DIR}/cloudsploit",
        ),
    )
    self._compliance_toolkit = ComplianceReportToolkit(
        ...
        report_output_dir=REPORTS_DIR,
    )

- path: `packages/ai-parrot-tools/src/parrot_tools/security/compliance_report_toolkit.py`
  lines: 78-94
  symbol: default report_output_dir
  excerpt: |
    def __init__(
        self,
        prowler_config: Optional[ProwlerConfig] = None,
        trivy_config: Optional[TrivyConfig] = None,
        checkov_config: Optional[CheckovConfig] = None,
        scoutsuite_config: Optional[ScoutSuiteConfig] = None,
        report_output_dir: str = "/tmp/security-reports",
        **kwargs,
    ):
        ...
        self.report_generator = ReportGenerator(output_dir=report_output_dir)

## Notes

- `ContainerSecurityToolkit` does NOT take `report_output_dir` — Trivy's output
  is captured from stdout (see `trivy_scan_image` / `trivy_scan_filesystem`
  implementations in F012). The mixin must encode the scan stdout as bytes
  itself for that toolkit, NOT read from disk.
- Acceptance criterion #7 in the brainstorm (don't migrate existing
  `/tmp/security-reports/` content) is well-aligned with this finding —
  pre-existing files can stay where they are; only new scans get auto-persisted.
- Note the brainstorm's plan to remove `output_format="json"` from the
  scan tools' return shape is wrong — `run_scan` already only returns
  `ScanResult` (no JSON-on-disk parameter); the `results_dir` write is a
  side effect controlled by `CloudSploitConfig.results_dir`.
