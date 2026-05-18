# F006 — ScanComparator

**Path**: `packages/ai-parrot-tools/src/parrot_tools/cloudsploit/comparator.py`
**Lines**: 1-71

`compare(baseline: ScanResult, current: ScanResult) → ComparisonReport`

Identity key: `(plugin, region, resource)`.
Tracks: new findings, resolved findings, unchanged, severity-changed.

This is CloudSploit-specific. A generic comparator for JSON documents
would need a different approach — either generic JSON diff or parser-
dispatch-based comparison.
