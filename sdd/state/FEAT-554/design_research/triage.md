# Design research triage — FEAT-554 (model gpt-5.6-luna, 2026-09-11)

Path verification: 10/10 suggestions had every `affected_paths` entry inside the
repository and present on disk. Every structural claim was additionally
re-checked against the cited source before adoption.

| # | Disposition | Reason | Landed in |
|---|---|---|---|
| S1 | CONFIRM | `_report_locked` (budget.py:327-359) reports settled provider usage only; estimates stay inside reservations | §2, M1, AC-5 |
| S2 | CONFIRM (narrowing branch only) | `GeminiOpenAICompatClient` (openai_compat.py:17) defines neither budget hook; building a Google adapter is FEAT-550 scope and is rejected here | §1 Non-Goals, AC-15 |
| S3 | CONFIRM | `action_from_dispatch_event` whitelists 7 usage scalars; `_apply_to_session_host` swallows validation errors → the brainstorm mechanism would fail silently | §2, M2 |
| S4 | CONFIRM | `dispatch.failed` payloads carry error fields only (llm.py:184-215) | §2, M2, AC-6 |
| S5 | CONFIRM | `collector.error` holds the full exception string (engine.py:583) | M4, AC-7 |
| S6 | CONFIRM | engine holds only `_base_path` (engine.py:162); no repo root to infer | M3/M4, AC-9 |
| S7 | CONFIRM | per-feature files leave the two-sessions-one-feature case; adopted single pre-serialized O_APPEND write + 4096B line budget | §7, M4, AC-10 |
| S8 | CONFIRM | `parse_task_files` reads inside the worktree that `/sdd-done` removes | M4, AC-8 |
| S9 | CONFIRM | `_resolve_model` (llm.py:879) can diverge from `RosterSeat.model` | M4, AC-14 |
| S10 | CONFIRM | existing dispatcher fakes expose no budget hooks | §4 |

Summary: 10 confirmed, 0 rejected, 0 escalated.
