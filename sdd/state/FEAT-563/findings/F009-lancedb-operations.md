---
id: F009
query_id: Q004
type: read
intent: Index and reader lifecycle need explicit policy
executed_at: 2026-09-09T23:24:11.921Z
parent_id: null
depth: 1
---

# F009 — Index and reader lifecycle need explicit policy

## Summary

Official reindexing documentation says queries combine indexed data with scans of unindexed additions; maintenance affects performance. The async API documents read_consistency_interval=None as no cross-process refresh checking, with zero enabling a check on every read. Vector indexes are manually managed in OSS. The local quickstart documents CPU wheel compatibility caveats.

## Citations

External documentation; URLs and supported claims below.

## Notes

External sources, accessed 2026-09-10:
- https://docs.lancedb.com/indexing/reindexing — index freshness and scan fallback.
- https://docs.lancedb.com/indexing/vector-index — manual OSS index management.
- https://lancedb.github.io/lancedb/python/python/ — cross-process read refresh policy.
- https://docs.lancedb.com/quickstart — CPU/wheel compatibility.
- https://docs.lancedb.com/faq/faq-oss — embedded OSS background.
Proposal recommendation: one application process owns mutations initially; explicitly test another reader's visibility if supported. No throughput, multi-writer safety or network-filesystem guarantees are asserted.
