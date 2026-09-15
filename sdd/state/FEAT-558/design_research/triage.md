## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted proposal** (never over this spec).
> Model: `gpt-5.6-luna` (codex-cli 0.154.0, reasoning effort high) · Status: completed
> · Transcript: `sdd/state/FEAT-558/design_research/`
> All 12 suggestions' `affected_paths` passed repository containment and `test -e`; each claim was re-read in the code before disposition.

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Use a per-call QueryModel repository (architecture) | CONFIRM | matches `get_query_slug`'s explicit `_connection` pattern; avoids shared `Meta.connection` state | §3 M4 `SlugCatalog`, §7 Patterns |
| S2 | Do not use stale positive tenant-cache entries for authorization (risk) | CONFIRM | `program_slug` is mutable; the proposal's TTL cache was dropped — every authorising call re-reads the row | §2 Overview, §3 M4, §5 AC, §7 Risks |
| S3 | Make unrestricted and raw execution explicit capabilities (risk) | CONFIRM (partial) | added `allow_raw_sql=False` gate for unrestricted instances and no raw-SQL tool argument; the "no unrestricted default" part is REJECTED because proposal U4 (`None` = unrestricted) is a resolved user decision | §2 Overview, §2 Interfaces, §5 AC |
| S4 | Isolate MultiQS blocking joins from the event loop (architecture) | ESCALATE | verified `t.join(timeout)` at `multi/__init__.py:315`; the fix trades loop responsiveness against connection-pool semantics — human decision | §8 Q3, §7 Risks |
| S5 | Make save target selection and collision behavior explicit (api) | CONFIRM | `manager.post` upserts by `query_slug` alone; added `program`/`overwrite` args and cross-program refusal | §3 M4 `upsert`, M6 `save_multiquery`, §5 AC |
| S6 | Traverse and normalize pipelines before tenant validation (architecture) | CONFIRM | `validate_pipeline` skips `queries/files/sources` contents; `normalize_pipeline()` added | §3 M4, M6 |
| S7 | Reject invalid condition expressions instead of relying on parser filtering (api) | CONFIRM | parser silently drops unsafe keys/operators (`sql.pyx:130-155`); `validate_filter()` + `rejected_inputs` | §2 Overview, §3 M3, §4 tests |
| S8 | Enforce max_rows before execution and define count semantics (risk) | CONFIRM | `querylimit=min(limit,max_rows)` pushed into QS; fields renamed `returned_rows` / `total_rows` / `truncated` | §2 Data Models, §3 M3/M5 |
| S9 | Test result normalization against real querysource shapes (testing) | CONFIRM | fakes cannot cover DataFrame/dict/empty→`DataNotFound` shapes | §4 Integration Tests |
| S10 | Separate metadata disclosure from raw query disclosure (risk) | CONFIRM (partial) | `SlugDetail` redacts `source/params/attributes/dwh_*/cache_options`; `include_sql` stays default `True` because explaining the query is requirement G2 | §2 Data Models, §3 M5, §7 Risks |
| S11 | Align the dialect artifact with the supported dependency range (risk) | CONFIRM | extra floor was `>=4.1.11` vs installed 4.5.11; floor raised, version guard + `.pxd` surface test added | §3 M3, M7, §5 AC, §7 Deps |
| S12 | Fix registry generation before removing QSourceTool (architecture) | CONFIRM | generator preserves unmatched entries (`generate_tool_registry.py:296-298`); explicit key removal + integrity test | §3 M7, §5 AC, §7 Risks |

Summary: **11** confirmed (2 partial) · **0** rejected · **1** escalated.

