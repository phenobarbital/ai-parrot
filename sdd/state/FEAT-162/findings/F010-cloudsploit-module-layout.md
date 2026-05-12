---
id: F010
query_id: Q010
type: glob
intent: Locate the CloudSploitToolkit module (FEAT-160 just merged; brainstorm says it lives under parrot_tools.cloudsploit).
executed_at: 2026-05-12T00:00:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F010 — CloudSploitToolkit lives at `packages/ai-parrot-tools/src/parrot_tools/cloudsploit/`

## Summary

The CloudSploit module is at
`packages/ai-parrot-tools/src/parrot_tools/cloudsploit/` (8 Python files plus
templates). FEAT-160 ("cloudsploit-config-support", merged 2026-05-12 — same
day as this research) added a `config_file` field and a `config` per-call
override; the brainstorm pre-dates that merge. Module is importable as
`parrot_tools.cloudsploit` (re-exported via `__init__.py`).

## Citations

- path: `packages/ai-parrot-tools/src/parrot_tools/cloudsploit/`
  lines: directory
  symbol: layout
  excerpt: |
    __init__.py
    comparator.py
    executor.py
    models.py     -- CloudSploitConfig, ScanResult, ComplianceFramework, ComparisonReport, SeverityLevel
    parser.py     -- ScanResultParser
    reports.py    -- ReportGenerator
    templates/    -- HTML/PDF templates
    toolkit.py    -- CloudSploitToolkit

## Notes

- See F011 for `CloudSploitToolkit` and `CloudSploitConfig` signatures.
- See F019 for the FEAT-160 commits (`config_file` field added 2026-05-12).
