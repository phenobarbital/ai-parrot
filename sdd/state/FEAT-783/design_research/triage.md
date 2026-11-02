# Design-research triage — FEAT-783

Model: gpt-5.6-luna · codex-cli 0.164.0 · 9 suggestions · all 22 cited paths verified
(containment + existence). Every claim below was spot-checked against the source
before disposition, per CLAUDE.md "Verify the reviewer's evidence".

| # | Suggestion | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Carry one explicit attribution object through dispatch and lifecycle events | **CONFIRM** | Attribution is genuinely split across `DispatchLabels`, `usage_attribution()`, `AttemptUsageRow` and engine-local ids; one immutable model is cheaper than four partial ones. | §2 Overview, §3 M1 |
| S2 | Put attribution on the event, not only in the subscriber ContextVar | **CONFIRM** | Verified: `AfterClientCallEvent` already snapshots `agent_name`/`user_id`/`session_id` from ContextVars at construction (`events/client.py:58-65`), so this follows the file's own established pattern; subscriber-side reads are unsafe for forwarded/cross-registry delivery. | §3 M1, §6 |
| S3 | Aggregate failure markers by `attempt_uid` instead of treating them as cycles | **CONFIRM** | Verified: `run_ledger.py:134-165` `by_seat()` sets `rounds=len(cycles)` over every record and counts `status=="failed"` separately, and `dispatchers/claude.py:1051-1060` emits a harvested usage event *then* a `ClientCallFailedEvent` — one failed attempt really does become two cycles. | §3 M6, §7 |
| S4 | Make the authoritative store durable or narrow the CLI guarantee | **CONFIRM (scope noted)** | Verified: `RunLedgerRecorder` is in-memory with a no-op `aclose()`, so a separate `wikitoolkit usage report` process cannot read it. Durability is mandatory. Scope note: the reviewer's option "extend `CoderTelemetrySink` as canonical" is excluded by a user decision — `UsageRecord` stays the per-call source of truth and `AttemptUsageRow` becomes a derived roll-up. | §3 M5, §8 |
| S5 | Normalize cache counters and provider cost before fan-out | **CONFIRM** | Verified: `AfterClientCallEvent` carries only flat `input_tokens`/`output_tokens`/`cost_usd` (`events/client.py:70-75`), while `dispatchers/claude.py:965-967` already extracts `cache_creation_input_tokens`, `cache_read_input_tokens` and `total_cost_usd` and then drops them for lack of event slots. Cache data is discarded at a boundary that already has it. | §3 M2, §6 |
| S6 | Keep attempt and execution IDs out of metric labels | **CONFIRM** | `attempt_uid`/`execution_id` are unbounded; `subscribers/metrics.py:8-10` already forbids unbounded labels by contract. Bounded `feat_id`/`task_id` may be labels; attempt/execution identity belongs to the durable store and spans. | §3 M1/M7, §5 AC-9, §7 |
| S7 | Use a dedicated Codex usage codec, not the generic shared dispatcher module | **CONFIRM (overrides the proposal)** | The accepted proposal proposed `dispatchers/_shared.py`. The reviewer is right that `_shared.py` is imported by twelve sibling dispatchers and that reaching into `ai-parrot-client-openai` from `dev_loop` to parse CLI output inverts the dependency direction. A dedicated codec with fixture coverage is the better seam. | §3 M4 |
| S8 | Treat Claude Code OTLP ingestion as an opt-in reconciliation source | **CONFIRM (corrects the proposal)** | Verified and material: `dispatchers/claude.py` drives the **Claude Agent SDK** out of process, and FEAT-479 Module 6 already harvests terminal usage into `AfterClientCallEvent` (`_emit_usage_event`, claude.py:977). The proposal's claim that "both CLI seats are outside AbstractClient entirely" is wrong for the dispatched Claude coder seat. Spike S1 therefore gates only the *interactive* Claude Code session, not the dispatched coder. | §2 Overview, §3 M7, §8 |
| S9 | Version the price source on every computed cost | **CONFIRM** | Verified: `valid_from` appears nowhere in `cost/calculator.py` — `cost_usd` ignores it and uses whatever price is loaded, so a pricing refresh silently changes historical answers. Given U3 mandates a refresh, this must land with it. | §3 M3, §5 AC-7 |

**Confirmed: 9 · Rejected: 0 · Escalated: 0**

No suggestion was rejected. Two (S7, S8) contradict the accepted proposal and were
adopted over it; S8 materially reduces the risk the user accepted in U2, because the
dispatched Claude coder seat turns out to be already wired. The brief carried only
the accepted exploration document and verified code anchors — no spec draft, no
reasoning — so these are not ratifications of a conclusion already drawn.
