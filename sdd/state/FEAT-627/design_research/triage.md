# Design research triage — wikitoolkit-standup

Model: `gpt-5.6-luna` (codex-cli 0.157.0, reasoning high) · Status: completed
Brief: `brief.md` (accepted brainstorm sections + 27 verified code anchors; no spec text, no author reasoning)
Path checks: all 29 distinct `affected_paths` resolved inside the repository and exist (`test -e`).

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Make page attributes part of the page write lifecycle (architecture) | CONFIRM | `upsert_pages`/`replace_source_slice`/`delete_page` each own a transaction (store.py:543-560, 878+); attrs now travel on `WikiPageRecord.attrs` and are written/deleted in the same `_write()` block. | §2 Overview, M1, AC2 |
| S2 | Handle missing `page_attrs` tables despite keeping schema v3 (risk) | CONFIRM | `_migrate` checks only `_MIGRATION_COLUMNS` (store.py:229,1357); read-only planes skip replay. Table-presence check + `supports_attrs=False` path + two tests added. | M1, AC1, §4 |
| S3 | Extract attributes before source-specific body transformations (architecture) | CONFIRM | `_note_body` (vault_scan.py:103) drops frontmatter; `build_file_slice` wraps content. Extraction moved to the source boundary; body parsing only in `entity reindex`. | §2 Overview, M2, §7 |
| S4 | Define an explicit task entity mapping (api) | CONFIRM | Task pages carry status as body text only (sdd_ingest.py:255-292). `task` added to `EntityType`; tasks read from the index JSON. | §2 Data Models, M5 |
| S5 | Specify canonical status + identity normalisation before collectors (api) | CONFIRM | Per-type enums, `status_raw`, precedence, `ticket_status_map`, identity model, SDD author limitation made explicit. | §2 Data Models, M3, §7, AC7 |
| S6 | Choose and document a backend contract for attributes (architecture) | CONFIRM + ESCALATE | Contract on `BaseWikiStore` with unsupported defaults; SQLite + InMemory implement; federation forwards. Arango/Postgres parity → §8 Q11. | M1; §8 Q11 |
| S7 | Audit the hook import graph instead of only lazily registering standup (risk) | CONFIRM (scoped) + ESCALATE | cli.py:108-110 imports the ledger at module load; project.py:28 imports decisions.models. Feature adds nothing to that path (LazyGroup, import-light modules, sys.modules test); pre-existing cost → §8 Q12. | M6, AC13, §7; §8 Q12 |
| S8 | Add standup configuration to both base and overlay schemas (api) | CONFIRM | Both models are `extra="forbid"` (project.py:382, :816). `StandupConfig` on both. | §2 Data Models, M5, AC15 |
| S9 | Make period boundaries and brief writes deterministic and recoverable (architecture) | CONFIRM | Timezone/week-start config, injectable clock, `wiki_write_lock` (project.py:74), tmp+`os.replace`, `items` attr as delta source of truth. | M5, §7, AC9/AC10 |
| S10 | Treat `wiki_standup` as an explicit mutating MCP operation (api) | CONFIRM | Read-only by default; writes local-only and reported; assets + checked-in command in one task. | M7, AC14 |
| S11 | Bound and sanitize the optional LLM summary input (risk) | CONFIRM | `BriefProjection` (≤40 items, ≤120-char titles, no bodies/urls), prompt forbids new facts, timeout, fail-safe write. | §2 Data Models, M5, AC8 |
| S12 | Build a cross-source and migration test matrix before collector implementation (testing) | CONFIRM | §4 covers attrs lifecycle, v3-without-table (both modes), aliases, federated read-only, periods, delta, dual-output failure, hook import set, model-absent fallback. | §4 |

Summary: **12** confirmed · **0** rejected · **2** escalated (S6, S7 carry §8 questions in addition to their confirmed part).
