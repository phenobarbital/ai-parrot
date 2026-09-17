---
id: FEAT-569
title: Verified outcome-driven memory dynamics
slug: memory-dynamics
type: feature
mode: enrichment
status: accepted
source:
  kind: file
  file_path: sdd/proposals/memory-dynamics.brainstorm.md
  jira_key: null
  jira_url: null
  fetched_at: 2026-09-17
  summary_oneline: Unify episodic, brain and coder-feedback retention through verified outcome-driven FSRS dynamics
overall_confidence: medium
base_branch: dev
research_state: sdd/state/FEAT-569/
created: 2026-09-17
updated: 2026-09-18
---

# FEAT-569 — Verified outcome-driven memory dynamics

> **Mode:** enrichment · **Confidence:** medium · **Status:** accepted (2026-09-18, after diagnostic review — see §7)
> **Source:** [preserved brainstorm](../state/FEAT-569/source.md)
> **Audit:** [research state](../state/FEAT-569/state.json)
> FEAT-569 identifies proposal research only; `/sdd-spec` reserves the formal FEAT-ID through `reserve_ids.py` (the ledger counter, not this number, is authoritative).

## 0. Origin

Invocation: `$sdd-proposal memory-dynamics -- @sdd/proposals/agent-memory-dynamics.brainstorm.md`.
The complete source, including frontmatter, is preserved byte-for-byte in [source.md](../state/FEAT-569/source.md) as fetched on 2026-09-17. On 2026-09-18 the brainstorm was renamed to [`memory-dynamics.brainstorm.md`](memory-dynamics.brainstorm.md) so `/sdd-spec memory-dynamics` loads it as the authoritative input; it remains authoritative for everything this proposal does not explicitly correct.

> **Recall does not reinforce.** Reading a memory updates `last_accessed`; only a review (recalled + intervened + verified outcome) changes stability.

The source chooses Option B: full FSRS-6, autonomous verified outcomes, one memory policy across episodes, brain pages and coder feedback, recoverable forgetting, and out-of-process access. It defers profiles and rehearsal probes and requires four spikes before specification. Those choices are preserved; its implementation sketches are hypotheses to verify. **Evidence: F001.**

## 1. Synthesis Summary

Extend the existing memory stores with a shared, deterministic dynamics policy, retaining the current feedback tools as adapters. `EpisodicMemoryStore`, `BrainStore`, `CoderFeedbackStore`, and `UnifiedMemoryManager` are appropriate integration points, but their current contracts do not provide atomic reviews or per-memory attribution. **F002–F009.** Proceed with validation and contract design before implementation: source-only review found concurrency, identity, context-packing, and FSRS parity gaps. Overall confidence is medium in the proposed scope; effectiveness for autonomous agents remains unvalidated. **F001, F003, F006–F011.**

## 2. Codebase Findings

### 2.1 Localization

Paths below are relative to `packages/ai-parrot/src/parrot/`, except where explicitly marked. Full paths and excerpts are in the linked findings.

| Path | Symbol / seam | Lines | Evidence |
|---|---|---|---|
| `memory/episodic/store.py` | `EpisodicMemoryStore.recall_similar`, `get_failure_warnings` | 377–508 | [F002](../state/FEAT-569/findings/F002-recall.md) |
| `memory/episodic/models.py` | `MemoryNamespace` | 214–271 | F002 |
| `memory/episodic/backends/abstract.py` | `AbstractEpisodeBackend.update_metadata` | 106–125 | [F003](../state/FEAT-569/findings/F003-atomicity.md) |
| `memory/episodic/backends/pgvector.py` | `PgVectorBackend.update_metadata`; UUID key | 118–149, 492–525 | F003, F006 |
| `memory/episodic/backends/redis_vector.py` | `RedisVectorBackend.update_metadata` | 544–596 | F003 |
| `memory/episodic/backends/faiss.py` | `FAISSBackend.update_metadata`, `save` | 257–315 | F003 |
| `memory/episodic/mixin.py` | `EpisodicMemoryMixin._safe_record_ask` | 423–487 | [F004](../state/FEAT-569/findings/F004-outcomes.md) |
| `memory/dream/brain.py` | `BrainStore.remember`, `search` | 50–149 | [F005](../state/FEAT-569/findings/F005-brain.md) |
| `memory/dream/runner.py` | `DreamCycleRunner.run_cycle`, `_collect` | 180–269 | F005 |
| `knowledge/wiki/store.py` | `WikiPageRecord` | 409–455 | F005 |
| `knowledge/wiki/ledger/coder_feedback.py` | `CoderFeedback.feedback_id`; `CoderFeedbackStore.record`, `_read`, `context` | 67–71, 96–185 | [F006](../state/FEAT-569/findings/F006-feedback.md) |
| `knowledge/wiki/ledger/coder_reviews.py` | `CoderReview`, `CoderReviewStore.record` | 21–107 | [F007](../state/FEAT-569/findings/F007-reviews.md) |
| `flows/dev_loop/sdd_coder/engine.py` | `SddCoderEngine._feedback_for`, `record_review` | 1433–1500 | F007 |
| `flows/dev_loop/sdd_coder/models.py` | `FeedbackConfig` | 165–170 | F007 |
| `memory/unified/models.py` | `MemoryContext` | 13–43 | [F008](../state/FEAT-569/findings/F008-context.md) |
| `memory/unified/manager.py` | `UnifiedMemoryManager.get_context_for_query`, `_record_episodic` | 158–175, 368–400 | F004, F008 |
| `memory/unified/context.py` | `ContextAssembler.assemble` | 49–129 | F008 |
| `knowledge/wiki/project.py` | `find_shared_root` | 1184–1222 | [F009](../state/FEAT-569/findings/F009-storage.md) |
| `knowledge/wiki/ledger/log.py` | `LedgerLog.append` | 20–81 | F009 |
| Repository: `.claude/agents/sdd-coder.md`; `flows/dev_loop/_subagent_data/sdd-coder.md` | checked-pattern prose in both copies | 115–124 | F008 |

### 2.2 Constraints Discovered

- **Metadata storage is not a review transaction.** PostgreSQL top-level JSON merging can overwrite a concurrent update to the same nested dynamics object; Redis does read/merge/write; FAISS persists replacement snapshots. A review needs deduplication plus serialized or compare-and-swap state updates, with recovery across log/state failures. **F003, F009.**
- **Recall must cover every retrieval path.** Semantic recall requires an embedding provider. Warnings separately fetch recent failures and reorder by importance/recency. That branch scopes only by tenant/agent, so new model-scoped feedback must not leak through it. An SDD adapter needs an explicit local retrieval strategy or configured embedding provider, and ranking must run before final packing. **F002, F006.**
- **Record only delivered memories as exposure.** The current pipeline passes strings and trims section budgets. A manifest captured before final packing would credit unseen memories. Preserve IDs and versions through packing and bind attribution to tenant, agent, model, execution, attempt and turn as applicable. A citation establishes claimed use, not successful application. **F005, F007, F008.**
- **Preserve identifier compatibility.** Existing feedback IDs are `coder-feedback:` strings; PostgreSQL episode keys are UUIDs. Use deterministic UUID mapping plus a legacy alias rather than asserting equality. The engine currently detects exposure from the `[coder-feedback:` text marker; replace that dependence with structured exposure or preserve it during transition. **F006, F007.**
- **Keep calibration separate from verified behavior.** The [official algorithm](https://github.com/open-spaced-repetition/awesome-fsrs/wiki/The-Algorithm) requires a same-day successful-review clamp omitted in the source sketch. The [reference scheduler](https://raw.githubusercontent.com/open-spaced-repetition/py-fsrs/main/fsrs/scheduler.py) uses whole elapsed days and parameter bounds. Pin the implementation and test numerical parity before vendoring; any fractional-time variant must be explicitly identified. **F011.**
- **No automatic historical grading.** Review records contain correction counts and exposure, not causal memory receipts. Historical feedback can migrate as lessons; reconstructing per-memory grades from it is unsupported. **F006, F007.**
- **Outcome collection must cover both entry paths.** The hardcoded conversational success is in the wrapper `_safe_record_ask`, not directly in `_record_post_ask`. Unified recording has a separate delegation path that must also obey the verified-outcome policy. **F004.**
- **The unified write path is currently dead (prerequisite).** `UnifiedMemoryManager._record_episodic` (`memory/unified/manager.py:395`) calls `record_tool_episode(namespace=, query=, response=, tool_calls=)`; the real signature (`memory/episodic/store.py:235`) is `(namespace, tool_name, tool_args, tool_result, user_query=None)`. The call raises `TypeError`, `record_interaction` swallows it as a WARNING (`manager.py:203`), and `tests/memory/unified/test_manager.py` hides it behind an `AsyncMock`. `LongTermMemoryMixin` agents therefore record **no** episodes through this path today, so there is nothing for dynamics to grade there. Repair it (or retire the path) as a prerequisite task, with a test against the real store signature. **F004 (amended 2026-09-18).**

### 2.3 Recent History

Research used `dev` at `9ab95566e5982dbc3fe1cee8b03789ddcf6f161c`; the brainstorm's earlier checks were described as against `main`. Commit `5a5474461` (2026-09-16) added execution attribution to review history. Preserve that attribution during migration. The scoped log also includes working-memory turn persistence commit `f8c549728` (2026-09-08). No regression causality is inferred. **F012.**

## 3. Probable Scope

### What's New

These are proposed capabilities, not existing APIs:

1. **A shared FSRS dynamics policy:** versioned parameters and deterministic transitions, explicit initialization, legacy neutral behavior, relevance/importance/retrievability ranking, recoverable forgetting and relearning. Access bookkeeping must never change stability. Source choices remain subject to S1 calibration. **F001, F011.**
2. **A durable review service:** scoped immutable outcome IDs, memory version and attribution receipts, deterministic grade precedence, ordered state application, retries and replay. Access updates must never overwrite review state. Review commands must not accept model-asserted success as verified evidence. **F003, F007–F009.**
3. **A concurrent local backend for SDD:** prefer evaluating SQLite using the existing dependency and shared-root convention; do not ship multi-writer FAISS snapshots as the default. Benchmark retrieval including the selected embedding or lexical path. **F002, F003, F009.**
4. **Shared operations surfaces:** the source's proposed citation, review, status, import, recovery, export and offline fitting operations, reachable from in-process agents and external workers. Treat these names as proposed surface design, with signatures resolved in the spec. No dependencies are added by this proposal. **F001, F009, F011.**

### What Changes

- **Episodic store and adapters:** initialize dynamics, rescore every retrieval route consistently, enforce full namespace filters, and expose structured results without breaking text consumers. Missing legacy state remains neutral until reviewed. Verify kill-switch behavior against baseline rankings, including the new importance multiplier. **F001–F004, F010.**
- **Brain consolidation:** replace cycle-count promotion with outcome-grounded policy after S4. Carry explicit lineage, distinguish inherited priors from reviewed evidence, and avoid counting episode/page aliases twice for one outcome. Re-distillation must version pages even when title/category is unchanged and revisit relevant episodes below the current collection watermark. **F001, F005.**
- **Coder feedback:** retain its public adapter and audit event, migrate idempotently by legacy occurrence identity, preserve first timestamps and recurrence grouping, and keep complete verification text. Define transition behavior for `max_age_days`; silently ignoring a configured limit is a behavioral change. Preserve the meaningful lesson text rather than reducing it to the pattern slug. **F006, F007, F010.**
- **Context and worker reporting:** carry post-packing memory IDs/versions, structured checked-pattern references, and independently verified outcomes. Extend the validated result path in the spec and update both prompt copies together; prose claims alone must not grant positive grades. **F007, F008.**

### Design Corrections Required Before Specification

| Source sketch | Required clarification / correction | Evidence |
|---|---|---|
| Metadata-first means no schema work | Dynamics JSON may be additive, but model-scope filtering, atomic reviews and brain state still need storage design. | F002, F003, F005 |
| Feedback ID equals episode ID | Preserve a legacy alias with UUID-compatible canonical identity. | F006 |
| A review tool call implies successful completion | Verify outcome and attempt identity separately; zero fix commits is not proof of success. | F007 |
| EASY follows generic successful conditions | Specify mutually exclusive grade precedence and a deterministic verified recovery predicate; textual overlap is insufficient. | F001, F007 |
| `record_lesson` initializes EASY | Treat initial parameters as a prior, not an earned review or eligibility for promotion. | F001, F011 |
| Maximum inherited stability and summed reviews prove a distilled page | New synthesized content requires lineage and its own evidence; inherited counters are not independent verification. | F001, F005 |
| Every forgotten item follows a lapse update | Retrievability exclusion is not an observed failure; select the transition from the verified grade. | F001, F011 |
| One-hop forwarding survives repeated re-distillation | Define canonical resolution, cycle prevention, bounded traversal/path compression and duplicate suppression across aliases. | F001, F005 |
| JSONL plus metadata retry gives idempotency | Define a required outcome ID, apply revision and replay cursor; an optional episode ID cannot identify every review. Append application receipts rather than editing prior log records. | F001, F003, F009 |
| CSV is immediately consumable by the optimizer | Define and test conversion to the reference review-log objects, including stable numeric card IDs. | F011 |

### Patterns and Non-Goals

Reuse shared-root resolution, durable bounded receipts, token-bounded whole lessons and existing injected strategy tests. **F002, F006, F009, F010.** Preserve provider-client history ownership and conversation compaction. Defer per-principal profiles, active rehearsal probes and skill usefulness scoring; none is necessary to validate this proposal. These boundaries follow the source direction. **F001.**

### Spec Carry-Forward Requirements

Source structure this proposal compressed and the spec must restore. None of it is contradicted by the findings. **F001.**

- **Store is the contract.** `EpisodicMemoryStore` and `BrainStore` own the dynamics; `LongTermMemoryMixin`, `parrot mcp-local episodic`, the `wikitoolkit memory …` group and the SDD coder engine are four clients of that one store. The "durable review service" in *What's New* §2 is `EpisodicMemoryStore.review()` plus the `ReviewLog` protocol hardened as described — **not** a new subsystem or a fourth implementation of the concern ("menos es más").
- **Parallelism lanes (source §Parallelism Assessment), amended by the gate decision in §6:**
  - **Lane 0a — spikes S1–S4** as gate tasks (below). Every other lane `depends_on` the spike whose output it consumes.
  - **Lane 0b — `memory/dynamics/`**: FSRS formulas, `MemoryState`, `Grade`, grade function, review log. Pure, no I/O. Depends on S1 (time unit, parity).
  - **Lane 0c — prerequisite repair** of `UnifiedMemoryManager._record_episodic` (§2.2). Independent; may run first.
  - **Lane 1 — episodic store**: initial state, rescoring recall, `review`/`cite`, `model_id` scope, mixin attribution, toolkit. Depends on 0b, S3.
  - **Lane 2 — dream cycle**: collect rule, lineage, forwarding, re-distill, anti-pattern. Depends on 0b, S4. Independent of Lane 1 once `MemoryState` is frozen.
  - **Lane 3 — SDD**: `CoderFeedback` → episodes, `_feedback_for` / `coder_record_review` adapters, `checked_patterns`, both agent-prose copies, `import-feedback`. Depends on Lane 1 and S2. Last.
  - **Lane 4 — CLI/MCP surface**, `export-reviews` / `fit`, ops `status`. Depends on Lane 1–2 interfaces only.
  - Isolation: `mixed` — one worktree for Lane 0, then per-lane worktrees.
- **Source specifics that stay in scope** unless a Design Correction above overrides them: conversational `ask()` with no verified signal records `PARTIAL` and produces no review; re-distill trigger on rising difficulty and anti-patterns rendered first in warnings (thresholds from S1); `DreamCycleReport.pages_redistilled` / `memories_forgotten`; `PostgresReviewLog` sink for pgvector deployments; optional extra `memory-fit = ["fsrs[optimizer]"]`; partial supersession of the FEAT-390 spec's `reinforcement_count` decision; ACT-R base-level activation only as a tie-breaker if FSRS proves outcome-sparse.

### Required Validation Gates

No gate has been executed by this proposal research. **F001, F011.** Per the owner decision recorded in §6, the gates run **inside the spec as Lane 0a gate tasks**, not before it: each is a task whose acceptance criteria are the evidence below, and no implementation lane may start until the spikes it depends on have passed and their outputs (time unit, backend, attribution default, page-state placement, thresholds) are written back into the spec.

| Gate | Required evidence (acceptance criteria of the gate task) |
|---|---|
| **S1 — FSRS parity and cold start** | Pin reference code; verify all grades, same-day/long-gap cases, clamps and parameter rejection. Replay 30-day synthetic traces and available real signals without inventing historical attribution. Measure premature forgetting, useful retention, ranking change and stale-memory persistence. The source's one-sided retention check alone does not demonstrate useful forgetting. Keep time-unit and threshold decisions open until measured. |
| **S2 — Local storage and review consistency** | Eight reader/writer processes; 5k baseline episodes and up to 10k scale; zero lost writes and source target p95 recall below 50 ms with hardware and embedding costs stated. Include same-memory concurrent reviews, duplicate outcomes, crashes between log/state writes, restart replay, and migration retries. Compare against FAISS snapshots. |
| **S3 — Attribution** | Inspect a 50-outcome sample with independent relevance judgments; measure false reinforcement, missed attribution and shared-tool collisions. Validate explicit citations against actual packed context and outcome receipts. Source overlap cap of three remains provisional; choose default and precision target explicitly. |
| **S4 — Brain state and lineage** | Compare frontmatter, dedicated state sidecar and metadata-column designs. Verify search/packing is not polluted, edits/copies preserve state, repeated re-distillation has stable versioned lineage, reviews are not double-counted, and promotion never treats inherited priors as verified reviews. |

Implementation acceptance should additionally cover legacy imports, unavailable embeddings, disabled dynamics, namespace isolation, verified failure versus missing signal, cancelled turns, clock skew, parameter changes, forgotten-item recovery and replay convergence. Existing tests are regression anchors, not evidence these new behaviors already work. **F002–F011.**

## 4. Confidence Map

| ID | Claim | Evidence | Confidence |
|---|---|---|---|
| C1 | Semantic recall requires embeddings; warnings independently reorder results. | F002 | high |
| C2 | Metadata patches do not provide atomic review application. | F003, F009 | high |
| C3 | The conversational wrapper writes unverified SUCCESS/3. | F004 | high |
| C4 | Brain state and injected-memory provenance need structured contracts. | F005, F008 | high |
| C5 | Feedback identity and exposure detection need explicit migration. | F006, F007 | high |
| C6 | Current reviews cannot reconstruct per-memory historical grades. | F007 | high |
| C7 | Shared-root resolution and aiosqlite are available foundations. | F009 | high |
| C8 | FSRS parity clamps and optimizer conversion need specification. | F011 | high |
| C9 | One dynamics policy can unify the flows while retaining adapters. | F002, F005, F006, F008 | medium |
| C10 | The proposed defaults improve autonomous-agent outcomes. | F001, F011 | low; hypothesis only |
| C11 | The unified manager's episodic write path raises `TypeError` and records nothing today. | F004 (amended) | high; signature bind reproduced 2026-09-18 |

Distribution: **9 high, 1 medium, 1 low** (C11 added by the 2026-09-18 diagnostic review; `synthesis.json` keeps the original ten). High claims are directly read contracts; C9 is architectural synthesis. C10 is not an accepted conclusion and blocks claims of efficacy or production readiness. Overall scope confidence is **medium**.

## 5. Open Questions

Source decisions retained: Option B, full FSRS, verified outcomes, recall-only access tracking, unified feedback, recoverable forgetting, deferred profiles/probes. These are source decisions, not new answers from this session. **F001.**

Six material policy questions remain for Jesus (U1–U4 from the proposal research; U5–U6 restored by the 2026-09-18 diagnostic review):

1. **U1 — Attribution default:** citations first, with generic overlap disabled until S3; or enable both once S3 meets an agreed precision target? Recommended: citations first. Blocks C9/C10.
2. **U2 — Adapter lifetime:** permanent compatibility adapter, or announced deprecation after a release? Recommended: permanent adapter for v1, with legacy IDs/config preserved. Blocks C5/C9.
3. **U3 — Calibration target:** retain the source's 30-day horizon or use another operating horizon, and what false-reinforcement/precision threshold should S3 meet? Required before spike acceptance. Blocks C10.
4. **U4 — Log retention:** retain the complete review corpus in v1, or archive after fitting with replayable manifests? Recommended: complete corpus in v1. Blocks C9.
5. **U5 — `max_age_days` fate:** the source decides to drop it ("retrievability replaces it" — one ageing rule), while `FeedbackConfig.max_age_days` (default 90, 1..365) is live roster configuration and §3 flags silently ignoring it as a behavioural change. Options: (a) drop as the source says, with a deprecation warning when a non-default value is set; (b) keep it as a hard upper bound applied on top of retrievability during the adapter's lifetime. Recommended: (a), preserving the source's single ageing rule. Blocks C5/C9.
6. **U6 — Profile deferral check (source open question):** confirm that `EpisodeCategory.USER_PREFERENCE` + `get_user_preferences` is sufficient for the conversational agents in production today, so deferring the per-principal profile plane costs nothing in v1. Does not block the spec; a "no" reopens scope.

Time units, backend choice, page-state placement and calibrated thresholds are technical spike outputs, not questions to settle by guesswork. Anti-pattern representation can remain metadata-first for the candidate v1; enum/schema changes require justification in the spec. **F001, F002, F005.**

## 6. Recommended Next Step

**`/sdd-spec memory-dynamics`** — with S1–S4 as Lane 0a gate tasks inside the spec.

Owner decision (Jesus, 2026-09-18): the source's "spike gates before `/sdd-spec`" becomes "spike gates before any implementation lane". The validation-first intent is kept — nothing in Lanes 0b–4 may start before the spikes it depends on pass — but the gates are tracked as SDD tasks instead of as an untracked pre-spec activity. The spec must therefore leave time unit, backend choice, attribution default, page-state placement and thresholds as explicit *spike outputs* and must not freeze untested defaults.

Inputs for the spec, in precedence order: (1) the *Design Corrections* and §2.2 constraints of this proposal; (2) [`memory-dynamics.brainstorm.md`](memory-dynamics.brainstorm.md) — authoritative for everything not corrected here, including Code Context, the capability list and the lanes; (3) *Spec Carry-Forward Requirements* above. Do **not** run a second `/sdd-brainstorm`: the exploration document already exists, and spike results and U1–U6 answers are folded into it (or into the spec's open questions) rather than into a new document.

### Alternatives

- **Spikes first, spec after** (the source's original ordering): execute S1–S4 ad hoc, write the results into the brainstorm, then `/sdd-spec`. Rejected by the owner on 2026-09-18 in favour of tracked gate tasks.
- **Hotfix the dead unified write path separately** (§2.2, C11): valid regardless of this feature's schedule; if done first, Lane 0c disappears.

History: at the 2026-09-17 proposal review gate the user answered **proceed**, which finalised a *discussion* proposal with U1–U4 and S1–S4 unresolved. The 2026-09-18 acceptance does not resolve them either and does not accept untested defaults; it authorises the specification described above.

## 7. Research Audit

| Artifact | Location |
|---|---|
| Checkpoint and budget | [state.json](../state/FEAT-569/state.json) |
| Exact source | [source.md](../state/FEAT-569/source.md) |
| Queries | [research_plan.json](../state/FEAT-569/research_plan.json) |
| Evidence | [findings/](../state/FEAT-569/findings/) — F001–F012 |
| Structured synthesis | [synthesis.json](../state/FEAT-569/synthesis.json) |
| Citation map | [evidence-map.json](../state/FEAT-569/evidence-map.json) |

Default limits: 40 repository files, 25 searches, 10 Git queries, depth 2, 300 seconds of research. Consumed counters are recorded in state; workflow/template reads and synthesis time are excluded. Research was not budget-truncated. Wiki status/query/page were used before source inspection; direct reads corrected stale-index risk. No runtime tests or spike experiments were run; document/schema validation is recorded separately. No implementation or dependency changes.

**Diagnostic review, 2026-09-18** (independent re-verification of §2 against `dev`; cited files unchanged since `9ab95566e`): all ten claims held; 19 of 20 localization rows were correct. Amendments: the `coder_feedback.py` range (was `77–215` on a 185-line file) fixed here and in F006, `evidence-map.json`, `synthesis.json`; the dead unified write path added (§2.2, C11, F004); U5–U6 restored; *Spec Carry-Forward Requirements* added; §6 rewritten; source brainstorm renamed to the `memory-dynamics` slug and committed. F011's FSRS claims were re-checked against the `py-fsrs` `main` scheduler (whole-day `.days` elapsed time; same-day `max(increase, 1.0)` clamp for Hard/Good/Easy; parameter-bound `ValueError`). `validation.json` still describes the 2026-09-17 run; its "four unknowns" and source-path checks predate these amendments.

## 8. Provenance

Generated using `sdd-proposal`, the repository research-plan, finding, synthesis and proposal templates, plus `parrot-wiki` orientation. State and plan use schema version 1.0. The plan schema does not allow the prompt's priority-zero wiki queries, so those are recorded in its permitted `meta` field. Full structured citations take precedence over the source brainstorm's unverified implementation sketches. External primary sources are recorded in [F011](../state/FEAT-569/findings/F011-fsrs-reference.md).
