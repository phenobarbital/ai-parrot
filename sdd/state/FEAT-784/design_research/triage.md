# Design Research Triage — FEAT-784 sdd-decision-audit

Model: gpt-5.6-luna (codex-cli 0.166.0, reasoning high) · Status: completed · 11 suggestions, all `affected_paths` inside the repository and present on disk (checked with `spec_tools check-path` + `test -e`, 2026-10-31).

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Define a real consistent decision inventory snapshot (architecture) | CONFIRM | `inventory()` skips deleted pages and downgrades decode errors to diagnostics (repository.py:63-95, verified); gate must fail closed | §3 M5 `InventorySnapshot` (two-phase read, `SNAPSHOT_UNSTABLE`, decode ⇒ incomplete) |
| S2 | Do not expose partially published approval batches (risk) | CONFIRM | only per-page CAS exists (store.py:824/1865, verified); readers need a batch marker | §3 M8 batch marker + `is_eligible` consults it; AC12 |
| S3 | Version the envelope and relation vocabulary explicitly (api) | CONFIRM | `schema_version: Literal[1]`, `parrot-adr:v1` marker, closed `DecisionLink.relation` (models.py:144/175, codec.py:34, verified) | §3 M1 (`ENVELOPE_MARKER_V2`, `Literal[1, 2]`, `ADR_UNSUPPORTED_SCHEMA`); §7 rollout order |
| S4 | Separate effective-governing inventory from ordinary retrieval (architecture) | CONFIRM | `_visible()` shows unknown/proposed statuses (service.py:161-170, verified); supersession never evaluated there | §3 M5 eligibility predicate + `effective_head`; §7 "budgeted outputs are not gate inputs" |
| S5 | Add a typed target resolver instead of interpreting empty structural results (api) | CONFIRM | `outline()` returns empty on missing/unindexed; `lookup()` is a suggestion API (structural/service.py:182/264, verified) | §3 M4 `ResolvedTarget.state ∈ {resolved, missing, unsupported, stale, incomplete}` |
| S6 | Treat blast-radius truncation and read-repair as audit incompleteness (risk) | CONFIRM | `_BLAST_RADIUS_NODE_CAP = 500` (:42), `truncated = True` (:458), `_ensure_fresh` read-repair with `read_repair=False` rootless mode (:138, :433) — all verified | §3 M6 (gate uses `read_repair=False`; cap/truncation/dangling ⇒ `incomplete`); §7 risk |
| S7 | Make the `about` taxonomy independent from free-form SDD tags (alternative) | CONFIRM | `DocTaxonomy` permits arbitrary tags and only warns on unknown projects (sdd_meta.py:201/220, verified) | §3 M3 `Taxonomy.map_projects` with unmapped diagnostics; projections rebuildable |
| S8 | Keep the spec-entry parser separate from legacy ADR refresh and define revision transitions (architecture) | CONFIRM | `parse_adr()` is one path-identified record (parser.py:252, codec.py:104, verified) | §3 M2 `spec_entries.py`; `previous_revision` pin; M8 never resets history |
| S9 | Make approval an executable SDD transition (architecture) | CONFIRM + ESCALATE | the gate refusing `approved` is in M9/M10 (AC15); extending the refusal to `/sdd-task` decomposition is cheap but the owner deferred `/sdd-task` work to a later phase | §3 M10 / AC15; §8 Q3 (owner: run check mode in `/sdd-task`?) |
| S10 | Freeze the approval-evidence trust adapter before implementing ingestion (risk) | CONFIRM | already resolved by the owner (brainstorm §8): git-commit-bound manifest; `DecisionService.review()` is never a publication path | §3 M3 `GitCommitApprovalAdapter`; §7 note; §8 resolved item |
| S11 | Require backend and transport parity for the new evaluation API (testing) | CONFIRM | parity tests already make SQLite and memory mandatory (`test_backend_parity.py`, verified present) | §4 Integration Tests (`test_backend_parity_schema2`, `test_cli_mcp_json_equivalence`) |

Summary: **11** confirmed · **0** rejected · **1** escalated (S9, partial).
