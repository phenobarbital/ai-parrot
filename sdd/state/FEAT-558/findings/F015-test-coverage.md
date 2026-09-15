---
id: F015
query_id: Q018
type: glob
intent: Existing test coverage for qsource / querytoolkit / query_slug.
executed_at: 2026-09-15T02:55:00Z
duration_ms: 900
parent_id: null
depth: 0
---
# F015 — Zero tests for QSourceTool/QueryToolkit; QuerySlugSource is covered under packages/ai-parrot/tests
## Summary
No file under `packages/*/tests` matches `*qsource*`, `*querytoolkit*` or `*querysource*`. `QuerySlugSource` is exercised by `packages/ai-parrot/tests/test_dataset_manager.py` and the auth suite (`tests/auth/test_datasetmanager_authz_integration.py`, `test_authorizing_data_source.py`, `test_rls_injection.py`). `ai-parrot-tools` tests live per-module under `packages/ai-parrot-tools/tests/<module>/` (276 test files); a new toolkit should add `packages/ai-parrot-tools/tests/querysource/`.
## Citations
- path: `packages/ai-parrot/tests/test_dataset_manager.py`
- path: `packages/ai-parrot/tests/auth/test_datasetmanager_authz_integration.py`
- path: `packages/ai-parrot/tests/auth/test_rls_injection.py`
- path: `packages/ai-parrot-tools/tests/`
  excerpt: aws business_automation cloudsploit company_info computer contracts dataset_manager docker google graphindex ... (276 test_*.py)
