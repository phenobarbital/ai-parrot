---
id: F011
query_id: Q011
type: grep
intent: Read CloudSploitToolkit to capture run_cloudsploit_scan signature, results_dir path, and CloudSploitConfig fields.
executed_at: 2026-05-12T00:00:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F011 — CloudSploitToolkit method is `run_scan` / `run_compliance_scan` — NOT `run_cloudsploit_scan`

## Summary

The brainstorm calls the scan method `run_cloudsploit_scan` — that name does
not exist. The actual public tools are `run_scan` (full plugin set) and
`run_compliance_scan(framework=...)`. Both return `ScanResult` (a Pydantic
model, not a `dict`). The toolkit only takes `config: Optional[CloudSploitConfig]`
in its constructor; there are no `file_manager` / `report_store` kwargs (yet).
`CloudSploitConfig.results_dir` is `Optional[str]`. JSON output is written to
`{results_dir}/scan_{YYYYMMDD_HHMMSS}.json` after parsing.

## Citations

- path: `packages/ai-parrot-tools/src/parrot_tools/cloudsploit/toolkit.py`
  lines: 23-37
  symbol: CloudSploitToolkit.__init__
  excerpt: |
    class CloudSploitToolkit(AbstractToolkit):
        def __init__(self, config: Optional[CloudSploitConfig] = None, **kwargs):
            super().__init__(**kwargs)
            self.config = config or CloudSploitConfig()
            self.executor = CloudSploitExecutor(self.config)
            self.parser = ScanResultParser()
            self.report_generator = ReportGenerator()
            self.comparator = ScanComparator()
            self._last_result: Optional[ScanResult] = None

- path: `packages/ai-parrot-tools/src/parrot_tools/cloudsploit/toolkit.py`
  lines: 71-119
  symbol: run_scan (full scan, returns ScanResult; writes JSON to results_dir if set)
  excerpt: |
    async def run_scan(
        self, plugins=None, ignore_ok=False, suppress=None, config=None,
    ) -> ScanResult:
        ...
        if self.config.results_dir:
            results_dir = Path(self.config.results_dir)
            ts = result.summary.scan_timestamp.strftime("%Y%m%d_%H%M%S")
            path = str(results_dir / f"scan_{ts}.json")
            self.parser.save_result(result, path)

- path: `packages/ai-parrot-tools/src/parrot_tools/cloudsploit/toolkit.py`
  lines: 121-163
  symbol: run_compliance_scan(framework, ignore_ok=True, config=None) -> ScanResult
  excerpt: |
    async def run_compliance_scan(self, framework: str, ignore_ok: bool = True, config=None) -> ScanResult:
        try:
            fw = ComplianceFramework(framework.lower())
        ...
        result = self.parser.parse(results_json)
        result.summary.compliance_framework = fw.value
        self._last_result = result
        return result

- path: `packages/ai-parrot-tools/src/parrot_tools/cloudsploit/models.py`
  lines: 81-173 (selected)
  symbol: CloudSploitConfig fields
  excerpt: |
    class CloudSploitConfig(BaseModel):
        compliance_framework: Optional[str] = ...   # line 61 (different model?)
        use_docker: bool = ...                       # line 94
        cloud_provider: CloudProvider = ...          # line 103
        results_dir: Optional[str] = ...             # line 173

## Notes

- **Brainstorm correction needed**: signature should be `run_compliance_scan(framework, ...)` (not `run_cloudsploit_scan(compliance, output_format)`).
- The output is always JSON (no `output_format="json"` parameter on this method);
  HTML/PDF are produced by a separate `generate_report(format="html"|"pdf")` method.
- `run_scan` returns a Pydantic `ScanResult`, not a raw dict. The mixin's
  `content` arg should serialize it (e.g. `result.model_dump_json().encode()` or
  read the on-disk JSON via `self.config.results_dir / scan_*.json`).
