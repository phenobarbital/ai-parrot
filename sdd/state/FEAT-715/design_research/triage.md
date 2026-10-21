# Design-research triage — FEAT-715

All 19 cited paths passed containment + existence. Five load-bearing factual
claims were independently re-verified before any disposition was assigned.

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Define one asyncio owner for InboxWatcher (architecture) | CONFIRM | watchdog callbacks run on observer threads while `InboxProcessor.run()` is async and owns the lock; the ownership contract was under-specified. | §3 M2, §7 Patterns |
| S2 | Expose a structured Fireflies meeting payload (api) | CONFIRM | Verified: `sync_fireflies_transcripts` returns a report dict (`synced`/`errors`/`from_date`), not the raw transcript+summary — so C5 could not be met by calling it. | §2 Data Models, §3 M4/M5 |
| S3 | Specify the atomic-write and startup-scan contract (risk) | CONFIRM | Verified: `discover()` skips dot-prefixed names (processor.py:167), so a dot-prefixed temp is safe — but the startup scan and final-path revalidation were genuinely missing. | §3 M2/M5, AC5a, AC22 |
| S4 | Make quiescence an injectable timing policy (api) | CONFIRM | A hard-coded sleep makes the two-sample rule untestable; injecting clock/stat keeps AC5 deterministic without real delays. | §3 M1/M2, §4 |
| S5 | Resolve watchdog's optional-dependency packaging gap (risk) | ESCALATE | **Verified and it refutes the brainstorm's C10**: `watchdog>=4.0` is NOT in `[project.dependencies]`; it is only in the `filesystem-transport-full` extra. "No new dependency" was false. Which way to resolve it is a packaging-policy call for the owner. | §8 Q1, §7 External Dependencies |
| S6 | Add a genuine file-only mode to SkillRegistryMixin (architecture) | CONFIRM (adapted) | Verified: with `enable_skill_registry=True` (default) `_configure_skill_registry` builds a DB registry at `AGENTS_DIR/{agent_id}/skills` (mixin.py:327-329) — the same path chosen for file skills. Adopted in-scope (set the flag False, wire `SkillFileToolkit` directly); **rejected** the part that would modify the shared mixin, as that expands blast radius to every agent. | §3 M5, §7 Known Risks |
| S7 | Explicit ingestion-to-meeting correlation contract (architecture) | CONFIRM | Verified: `mark_wiki_ingested(...) -> int` returns a stamped-row count, not a path, so the backlink needs resolution by external id. | §3 M7 |
| S8 | Telegram confirmation as an idempotent authorization protocol (api) | CONFIRM | AC13 asserted idempotence without defining a mechanism; `telegram_command` only attaches metadata and carries no approval state. | §3 M7, AC13/AC23/AC24 |
| S9 | Per-meeting working-memory scope (api) | CONFIRM | Without stable keys and inter-meeting isolation one meeting's artifacts can leak into the next. | §3 M6 |
| S10 | Failure-isolation and long-running CLI acceptance tests (testing) | CONFIRM | Directly strengthens the G6 independence guarantee and the watcher contract. | §4, §5 |

Summary: **8** confirmed · **1** confirmed-adapted (S6) · **1** escalated (S5) · 0 rejected.
