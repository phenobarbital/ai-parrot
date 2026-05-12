---
id: F012
query_id: Q012
type: grep
intent: Locate ComplianceReportToolkit and ContainerSecurityToolkit and identify their scan methods + config classes.
executed_at: 2026-05-12T00:00:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F012 — ComplianceReportToolkit has 11 public methods; ContainerSecurityToolkit has 10 `trivy_*` methods. Neither accepts `file_manager`/`report_store` yet.

## Summary

`ComplianceReportToolkit` (`packages/ai-parrot-tools/src/parrot_tools/security/compliance_report_toolkit.py:54`)
is constructed with four optional scanner configs + `report_output_dir`. Public
methods include `compliance_full_scan`, `compliance_soc2_report`,
`compliance_hipaa_report`, `compliance_pci_report`, `compliance_custom_report`,
`compliance_executive_summary`, `compliance_get_gaps`,
`compliance_get_remediation_plan`, `compliance_compare_reports`,
`compliance_export_findings`. Returns `ConsolidatedReport` (Pydantic) for
`*_full_scan` and report-file paths (`str`) for the per-framework reports.
`ContainerSecurityToolkit` exposes 10 `trivy_*` methods including
`trivy_scan_image`, `trivy_scan_filesystem`, `trivy_scan_repo`, `trivy_scan_k8s`,
`trivy_scan_iac`, `trivy_generate_sbom`, `trivy_get_summary`, `trivy_get_findings`,
`trivy_generate_report`, `trivy_compare_scans`. **Neither toolkit currently
accepts `file_manager` or `report_store` kwargs** — they must be added.

## Citations

- path: `packages/ai-parrot-tools/src/parrot_tools/security/compliance_report_toolkit.py`
  lines: 54-115
  symbol: ComplianceReportToolkit.__init__
  excerpt: |
    class ComplianceReportToolkit(AbstractToolkit):
        name: str = "compliance_report"
        def __init__(self,
            prowler_config: Optional[ProwlerConfig] = None,
            trivy_config: Optional[TrivyConfig] = None,
            checkov_config: Optional[CheckovConfig] = None,
            scoutsuite_config: Optional[ScoutSuiteConfig] = None,
            report_output_dir: str = "/tmp/security-reports",
            **kwargs,
        ):
            super().__init__(**kwargs)
            self.report_generator = ReportGenerator(output_dir=report_output_dir)

- path: `packages/ai-parrot-tools/src/parrot_tools/security/compliance_report_toolkit.py`
  lines: 246-330
  symbol: compliance_full_scan (returns ConsolidatedReport)
  excerpt: |
    async def compliance_full_scan(
        self, provider="aws", target_image=None, iac_path=None,
        k8s_context=None, framework=None, regions=None,
        progress_callback=None,
    ) -> ConsolidatedReport:
        ...
        consolidated = self._consolidate_results(scan_results)
        self._last_consolidated = consolidated
        return consolidated

- path: `packages/ai-parrot-tools/src/parrot_tools/security/compliance_report_toolkit.py`
  lines: 332-470 (header lines)
  symbol: per-framework methods return str (file path)
  excerpt: |
    async def compliance_soc2_report(self, provider="aws", output_path=None, include_evidence=True) -> str: ...
    async def compliance_hipaa_report(self, provider="aws", output_path=None) -> str: ...
    async def compliance_pci_report(self, provider="aws", output_path=None) -> str: ...
    async def compliance_custom_report(self, framework, provider="aws", output_path=None) -> str: ...

- path: `packages/ai-parrot-tools/src/parrot_tools/security/container_security_toolkit.py`
  lines: 22-49
  symbol: ContainerSecurityToolkit
  excerpt: |
    class ContainerSecurityToolkit(AbstractToolkit):
        name: str = "container_security"
        def __init__(self, config: Optional[TrivyConfig] = None, **kwargs):
            super().__init__(**kwargs)
            self.config = config or TrivyConfig()
            self.executor = TrivyExecutor(self.config)
            self.parser = TrivyParser()
            self._last_result: Optional[ScanResult] = None

- path: `packages/ai-parrot-tools/src/parrot_tools/security/container_security_toolkit.py`
  lines: 52-427
  symbol: 10 trivy_* methods
  excerpt: |
    async def trivy_scan_image(self, image, severity=None, ignore_unfixed=False, scanners=None) -> ScanResult: ...
    async def trivy_scan_filesystem(self, path, severity=None, scanners=None) -> ScanResult: ...
    async def trivy_scan_repo(self, repo_url, branch=None, severity=None) -> ScanResult: ...
    async def trivy_scan_k8s(self, context, ...) -> ScanResult: ...
    async def trivy_scan_iac(self, ...) -> ScanResult: ...
    async def trivy_generate_sbom(...) -> ...
    async def trivy_get_summary(self) -> dict: ...
    async def trivy_get_findings(self, severity=None, ...) -> ...
    async def trivy_generate_report(...) -> ...
    async def trivy_compare_scans(...) -> ...

## Notes

- `ContainerSecurityToolkit.scan_filesystem` (brainstorm name) does not exist;
  the real name is `trivy_scan_filesystem`.
- Brainstorm's claim that ComplianceReportToolkit "orchestrates Prowler + Trivy
  + Checkov" is correct; the actual code also includes ScoutSuite (see line 38).
- All scanners return `ScanResult` Pydantic models; the mixin's `content` arg
  needs to serialize them.
- The brainstorm assumes adding `file_manager` + `report_store` kwargs via
  mixin `super().__init__(...)`; mixin must NOT swallow these kwargs before
  passing the rest down to `AbstractToolkit.__init__`.
