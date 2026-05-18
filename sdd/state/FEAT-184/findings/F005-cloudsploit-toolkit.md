# F005 — CloudSploitToolkit (composition pattern)

**Path**: `packages/ai-parrot-tools/src/parrot_tools/cloudsploit/toolkit.py`
**Lines**: 159-801

`class CloudSploitToolkit(ReportPersistenceMixin, AbstractToolkit)`

Constructor pops `file_manager` and `report_store` from kwargs before
calling super().__init__(**kwargs).

Relevant pattern for new toolkit: how it composes domain services
(executor, parser, comparator, report_generator) and exposes them
as tools.

Has `compare_scans(baseline_path, current_path)` → ComparisonReport
using ScanComparator. This is CloudSploit-specific (ScanResult models).

Has `generate_report(format, output_path)` → str (HTML generation).
