# Design Research Triage — FEAT-603 sharepoint-filemanager

Model: gpt-5.6-luna (codex-cli 0.156.1, reasoning high) · Run: 2026-09-25T15:35:23Z → 15:39:39Z · Status: completed
Path checks: all 31 `affected_paths` entries passed repository containment and `test -e`.
Source verification: S2 (`sharepoint.py:120-172`), S4 (`sharepoint.py:107-121`, msgraph `odata_next_link` + `with_url`), S7 (`web.py:229-232, 257-259`) re-read before disposition.
Note: S2 `rationale` is truncated in `suggestions.json` (reviewer output cut mid-sentence); the claim was verified from source.

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Define an authenticated-client injection boundary (architecture) | CONFIRM | `O365Tool._get_client` returns a plain `O365Client` (base.py:148); drive helpers live on subclasses. `adopt_client(client)` with copy-over contract; close() never closes adopted client. | §3 M1, M7/M8, §7, AC3 |
| S2 | Remove SharePoint site resolution's hidden mutable input (architecture) | CONFIRM | Verified `_detect_and_resolve_subsite` reads/mutates `_srcfiles`. Manager never populates it; sub-sites via explicit `site="parent/sub"`. | §2, §3 M3, §7, AC23 |
| S3 | Keep sharing-link options off the exact interface method (api) | CONFIRM | Signature parity (AC1). `create_sharing_link` extension; `get_file_url` wrapper. | §2, §3 M1, AC7 |
| S4 | Implement pagination for every list and search operation (risk) | CONFIRM | Tools call `.children.get()` once. `_iter_children`/`_iter_search`; `max_results` after filtering. | §3 M1, §7, AC20 |
| S5 | Use one bounded retry policy for SDK and raw HTTP paths (risk) | CONFIRM | One `_retrying(idempotent=)`; copy POST / session creation never retried. | §3 M1, §7, AC21 |
| S6 | Validate copy-monitor URLs before sending credentials (risk) | CONFIRM | `_validate_graph_url` (delta.py:387 pattern); no auth header, no redirects, never logged. | §2, §3 M1, §7, AC21 |
| S7 | Do not claim streaming while using the existing serving extension unchanged (risk) | CONFIRM (guard) + ESCALATE (streaming) | Verified BytesIO buffering. `serving_max_bytes` guard (413) in v1; streaming subclass is owner's call. | §3 M1, §7, AC22, §8 Q4 |
| S8 | Specify path and folder semantics separately from legacy tool paths (api) | CONFIRM | `list_files` files only; `list_entries` → `DriveEntry(is_folder)`; library-relative == drive-relative with `prefix=""`. | §2, §3 M1/M7, §7 |
| S9 | Make OneDrive user targeting cache-safe (risk) | CONFIRM | Single-slot caches on `OneDriveClient`; per-user `_user_drives` dict. | §3 M2, §7, AC24 |
| S10 | Test batch result and cancellation semantics explicitly (testing) | CONFIRM | `index`/`state`/`error_code`; skipped attempts=0; shared BinaryIO rejected; cancellation tests. | §2, §3 M1, §4, AC8 |
| S11 | Preserve lazy-import and optional-dependency guarantees (testing) | CONFIRM | Already decided (`msgraph` extra) + lazy-import tests listed. | §3 M5/M9, AC10, AC14 |

Summary: 11 confirmed (S7 additionally escalated) · 0 rejected · 1 escalated (S7 → §8 Q4).
