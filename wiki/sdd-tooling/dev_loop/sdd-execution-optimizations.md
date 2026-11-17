# Proposals to Reduce SDD Execution Time

Date: 2026-09-21. Status: analysis and proposals, no implementation changes.

> **Update 2026-09-21 (second profiler pass):** §8 answers the open questions of §2 with measurements, corrects the baseline and adds proposals. Where §8 contradicts an earlier figure, §8 prevails.

## 1. Diagnosis

The priority is to reduce the repetitive decisions of the `sdd-worker`, the duplicated work between implementation and review, and the attempts that require recovery. Before attributing savings to polling or widening parallelism, we need to measure what actually blocks delivery.

The evaluation identifies reasonable candidates, but **its percentages do not equal recoverable time**. It mixes call durations, agent intervals and a residual attributed to the model; in addition, the numeric summary contains a discrepancy. It is better to instrument and apply small changes before redesigning the executor.

This document uses three levels of evidence:

- **Verified locally:** current instructions, the `wait` implementation and the aggregates of the MCP JSONL files.
- **Provided:** figures from the four native runs and the description of the profiler. Their transcripts have not been audited and the profiler has not been run.
- **Proposed:** improvements, experimental targets and conditional estimates; they are not demonstrated savings.

## 2. Review of the evaluation

### 2.1 Aggregates and representativeness

The tables repeated in the original message are counted only once.

| Quantity | Recomputed from the four rows |
|---|---:|
| Wall-clock time | 19 h 19 min 02 s |
| Time classified as active | 11 h 01 min 49 s |
| Time classified as idle | 8 h 17 min 11 s |
| Time attributed to the model | 4 h 18 min 22 s |
| Model / active | **39.0%**, versus 36.2% in the provided aggregate |
| Weight of FEAT-564 in active time | 45.1% |
| Model / active excluding FEAT-564 | 27.6% |

There are also differences of a few seconds between column sums, consistent with rounding or truncation. The difference between 39.0% and 36.2% requires reconciling denominators or attribution rules: it is not explained by that rounding.

FEAT-564 strongly influences the result. Four features do not allow us to conclude that time scales "with the number of turns, not with the feature": difficulty, size, failures and dependencies can simultaneously explain more turns and longer duration. Comparisons should be made per accepted task, complexity and number of correction cycles, in addition to per feature.

### 2.2 What the profiler actually measures

The union of intervals avoids double-counting concurrent work, but it does not demonstrate causality nor identify the critical path by itself. If two categories coincide, the result depends on how the shared interval is assigned to them. That rule must be published.

A gap longer than 120 seconds without tools does not prove that the user was absent. It may include long generation, provider queues, compaction, transport or uninstrumented processes. Label it as an **unattributed interval** until there is explicit evidence of human waiting. Recomputing with thresholds of 60, 120 and 300 seconds helps detect sensitivity without turning any of them into a reference truth.

Likewise, "orchestrator model" computed by difference is a **residual**, not a direct measurement of inference. To separate it, we need request-start, first-token and response-end events, when the runtime exposes them. Assistant messages are also not necessarily equivalent to provider requests; we must specify what `turn` means.

The correction of the background agents' span is necessary. It must also be documented how incomplete children, resumptions, clocks and MCP work that does not appear as a child span of the transcript are handled.

### 2.3 `coder_wait`: waiting is not overhead

The current implementation uses `asyncio.wait_for(asyncio.shield(task), timeout=timeout_s)`: it **returns when the job finishes or the deadline expires**, keeping the work alive when the wait expires. It does not necessarily sleep until the next tick.

Therefore:

- `33 × 120 s = 66 min`, not 40 min. About 40 minutes may be the sum of observed partial waits; the ceiling does not allow deducing that sum.
- 6% of 11 h 01 min 49 s is about 39.7 minutes, but part of it may overlap entirely with useful implementation.
- The 33 additional turns, using the provided estimate of 3.5 s, amount to about **116 s** of model time, before measuring other costs. They do not justify promising 40 minutes of savings.
- The current prompt prescribes 90 s; the toolkit has a default of 120 s. The version and effective arguments of the runs must be recorded.

The real risk is blocking attention on a native hand-back, serializing MCP requests or waiting for the whole chunk before taking advantage of an already finished task. Measure `task end → observation → merge → next task enabled`. Do not increase the timeout indiscriminately: the current documentation warns about server serialization and client limits.

### 2.4 MCP telemetry and recovery

The local files FEAT-559, FEAT-560 and FEAT-563 reproduce the **22 attempts**, with **8,597.886 s accumulated**. They are a different cohort: they must not be added to the active time of FEAT-578/565/572/564 nor that sum interpreted as wall-clock time.

| Seat | Attempts | Accumulated seconds | Median, s | completed / salvaged / failed |
|---|---|---|---|---|
| mistral | 6 | 2,205.085 | 355.432 | 4 / 2 / 0 |
| codex-spark | 1 | 1,801.191 | 1,801.191 | 0 / 0 / 1 |
| qwen | 5 | 1,716.222 | 329.162 | 4 / 1 / 0 |
| glm5 | 2 | 1,077.251 | 538.626 | 2 / 0 / 0 |
| minimax | 3 | 941.315 | 308.580 | 3 / 0 / 0 |
| glm | 5 | 856.822 | 175.004 | 1 / 2 / 2 |

`salvaged` must not be automatically counted as time without delivery, nor `completed` as acceptance without defects. Each attempt must be linked to merge, review and corrections. The failed codex-spark attempt represents 20.9% of the accumulated time of this cohort, but a single observation does not demonstrate model inferiority: infrastructure errors, contract errors and capability errors must be distinguished.

The claim that 70–80% of native coders' time is generation remains to be verified. Even if it were correct, tests may have a larger impact on integration and closeout than inside the seat.

## 3. Prioritized optimizations

| Order | Change | Intended benefit | Effort / risk |
|---|---|---|---|
| P0 | Persistent, reconciled telemetry | Avoid optimizing misattributed intervals | Medium / low |
| P1 | Automate the worker's mechanical transitions | Fewer turns and re-reads | Medium / medium |
| P1 | Complete briefs and compact responses | Less repeated exploration and fewer corrections | Low–medium / low |
| P1 | Incremental review and bounded closeout | Reduce the final serial block | Medium / medium |
| P1 | Recovery guided by progress and quality | Avoid long unproductive attempts | Medium / medium |
| P2 | Tests based on reusable evidence | Reduce redundant validation | Medium / medium |
| P2 | Events and planning by ready tasks | Reduce barrier waits and reaction delays | High / high |

### 3.1 Automate the orchestrator's mechanical work

The cost of control calls may be small and, even so, the conversation needed to decide each call may be expensive. Move to the kernel only deterministic transitions:

1. Normalize the delivery and validate identity, scope, commits and state.
2. Run the prescribed checks and return structured evidence.
3. Prepare the completion note and the index update from that evidence.
4. Apply idempotent transitions; return concrete exceptions to the worker.

The worker keeps the semantic decisions: reviewing defects, resolving conflicts, assessing insufficient evidence and handling blockers. The result may include `state`, `evidence_refs`, `pending_actions` and `requires_decision`, without asking the model to reconstruct the state from multiple outputs.

Keep the review and feedback records per delivery. Reducing calls or batching persistence does not authorize declaring a review that did not take place. Design recovery for failures between commit, index and ledger; the worker remains the owner of SDD state.

**Experiment:** automate one frequent transition and compare control turns per accepted task, state errors and critical time. Do not redesign the whole engine to save the small execution time of its tools.

### 3.2 Improve the input and output contracts

Prepare each brief with verified paths and symbols, permitted scope, acceptance criteria, validation commands, already resolved dependencies and relevant feedback. Code-linked information must include a base revision or hash to detect staleness.

Hand the worker a structured summary with commits, tests run, result, limitations and links to logs. Consult full logs only when a result requires it. Keep the mandatory conventions and allow access to the original evidence; compacting does not mean removing necessary context.

Do not split every task into more agents by default: the cost of startup, exploration and review may exceed the parallelism. Split by independent contracts; group small, closely related steps only if it preserves verifiable acceptance and clear file ownership.

**Experiment:** measure repeated reads, input/output tokens when available, time to first edit and corrections per delivery. Do not use fewer tokens as a substitute for less time or better quality.

### 3.3 Incremental review with base-revision evidence

The 950–1150 seconds per review provided are equivalent to about 16–19 minutes; reducing them deserves an experiment. Reviewing contracts and changes that have stabilized during implementation can bring discoveries forward and reduce the serial closeout.

- Each early review is tied to the reviewed diff and SHA, covered criteria and findings.
- Later changes invalidate the affected part and its dependencies.
- The final review covers the pending delta and the global integration: interfaces, invariants and risks that only appear when tasks are joined.
- Separate semantic review from mechanical checks already backed by valid evidence.

Start with one bounded incremental review; add reviewers only if there are independent scopes and available capacity. More agents can increase queues, tokens and duplicated results. Maintain adversarial independence and prevent an approval on an earlier SHA from enabling the closeout of a different diff.

**Experiment:** compare final duration and total review cost, confirmed defects, later corrections and criteria coverage. A shorter final review is not enough if prior work was duplicated.

### 3.4 Reduce unproductive attempts

Routing by complexity, effective model identity and suspensions are already part of the flow. Extend those guarantees instead of creating a global ranking from 1–6 samples per seat.

Define progress signals: a valid change within scope, reduction of failures and fulfillment of criteria. An isolated turn counter can penalize complex tasks or reward useless edits. Detect repeated loops without progress and prepare a diagnosis before triggering the existing recovery.

Calibrate budgets per task class, including time, turns and corrections. Distinguish legitimate slowness, a blocked tool and a repeated error. Preserve branches and evidence before recovering; do not start another writer on a task whose previous agent might still be active. Suspending a model does not prove its process has ended.

Optimize **time to accepted task**, including failed attempts, recovery, review and fixes. For resource consumption, additionally measure accumulated agent-seconds per accepted task; do not confuse the two indicators.

### 3.5 Reduce redundant tests without reducing necessary coverage

The current flow already selects tests by `task`, `merge` and `feature` levels, limits suites inside the coder and reuses certain green escalations by content. Do not propose it as a novelty.

Investigate the 226 runs: reason, selection, code revision, startup/collection duration and whether there were relevant changes since the previous one. Distinguish true duplicates from regressions that are necessary after combining branches.

To widen reuse, the identity of the evidence must cover relevant content, tests, configuration, environment and dependencies. The hash of a single file is not enough for every class of validation. Keep post-merge checks when the integrated composition changes.

The documentation points to potentially very broad core escalations and an empty xdist allowlist. Measure those suites before changing thresholds. Enable parallelism only for distributions whose equivalence and isolation are demonstrated; do not reduce coverage to improve the stopwatch.

### 3.6 Events and continuous planning

First measure how much time passes between a delivery and its consumption. If it is significant, explore MCP notifications with event recovery and a bounded-wait fallback, always according to what the host allows. Do not assume its support exists.

Then, evaluate releasing capacity per finished task instead of waiting for the whole chunk: dispatch ready tasks when their dependencies are **accepted**, an eligible model is available and the scope does not conflict. Prioritize tasks that unblock the critical path, without bypassing exclusivity, concurrency limits or complex/unknown classification.

It requires up-to-date planning, serialized merges onto the integration branch, idempotent events and evidence of termination before cleaning up worktrees. It is an architecture change; it only pays off if the barrier between chunks represents a material delay.

## 4. Required measurement

Persist a compact record outside the ephemeral worktrees. Keep export before cleanup and events during execution to survive failures prior to closeout. The concrete destination must follow existing ledger and telemetry conventions.

| Group | Proposed fields or events |
|---|---|
| Identity | feature, execution_id, job_id, task_id, attempt_uid, backend, requested and resolved model |
| Versions | repository commit, prompt/policy hash, experiment configuration |
| Timing | task ready, dispatch, start/end, observed delivery, merge, acceptance, review, feature end |
| Correlation | span_id, parent_span_id, toolUseId/agent ID when they exist |
| Quality | terminal, gate results, confirmed defects, recovery and corrective commits |
| Tests | selection, reason, revision/content, environment, duration, result and reuse |
| Model | requests, tokens and observed latencies; explicit unknown value if missing |

For native seats, combine dispatch/delivery records with transcript import when available. Do not invent tokens nor infer success from the absence of errors. Record work still active at the end of the window as incomplete.

Publish separately:

- End-to-end wall-clock time, with explicit human waiting broken down.
- Automatic time, keeping a section for unattributed intervals.
- Accumulated seconds per resource, which can exceed wall-clock time.
- Critical path derived from dependencies and observed transitions.
- Reaction delay and queue delay; correction cost per accepted task.

## 5. Potential savings: scenarios, not predictions

On the provided base of 11 h 01 min 49 s of active time:

| Hypothetical scenario | Reduction of active time | Aggregate equivalent |
|---|---:|---:|
| Reduce 25% of the orchestrator component, if its real weight is 36.2–39.0% | 9.1–9.8% | 60–65 min |
| Reduce 50% of the final review, if it takes 11% exclusive | 5.5% | 36 min |
| Reduce 50% of pytest, if it takes 8.3% exclusive | 4.15% | 27 min |

These calculations assume correct attribution, effective reduction of the component and presence on the critical path. They cannot be added together without correcting for overlaps and substitution effects. Eliminating all the observed `coder_wait` waiting is not a valid savings scenario: the awaited work is still necessary.

As an initial pilot target, aim for **15% less median automatic time on comparable tasks/features**, with no observable increase in defects, recoveries or missing evidence. It is an experimental threshold, not a forecast derived from four runs.

## 6. Validation sequence

1. **Reconcile the baseline.** Audit the profiler's rules, resolve 36.2% versus 39.0%, verify shared intervals and separate versions/cohorts.
2. **Close observability.** Persist MCP and native events; verify recovery after restart and cleanup without losing attribution.
3. **Low-risk pilot.** Bounded briefs and one automated mechanical transition. Compare with the previous policy on work of similar complexity.
4. **Separate pilots.** Incremental review, progress-based recovery and test reuse. Change one factor at a time so the effect can be attributed.
5. **Evaluate architecture.** Only with evidence of costly barriers, introduce events and continuous planning.

Alternate control and variant between comparable runs, recording external load, size, complexity and versions. Do not compare a new small feature with FEAT-564 as the only reference. Use repetitions over isolated snapshots when it is of interest to compare the same task without contamination from earlier artifacts.

Report sample size, median, dispersion and individual cases; estimate p90/p95 when there is enough sample. Include failures and abandonments to avoid survivorship bias. The absence of defects in a few tasks does not demonstrate quality equivalence.

Every change must be able to be disabled through policy/configuration. Roll back the pilot upon loss of evidence, omitted validations, a double writer, a sustained increase in recoveries or correctness regressions. Task approval keeps the same functional criteria.

## 7. Local sources and scope

- [Worker: orchestration and closeout cycle](https://github.com/phenobarbital/ai-parrot/blob/main/.claude/agents/sdd-worker.md): waiting, consolidation, feedback, adversarial review and SDD state.
- [Coder contract](https://github.com/phenobarbital/ai-parrot/blob/main/.claude/agents/sdd-coder.md): scope, validation and delivery.
- [Orchestrator documentation](sdd-coder-orchestrator.md): routing, suspensions, telemetry and test selection. Some general examples may differ from the updated prompt; verify the effective contract before implementing.
- [Job wait](https://github.com/phenobarbital/ai-parrot/blob/main/packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/jobs.py): return on completion or timeout.
- [Toolkit](https://github.com/phenobarbital/ai-parrot/blob/main/packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py): `coder_wait` interface and per-seat summary.
- [Seat summary](https://github.com/phenobarbital/ai-parrot/blob/main/packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/summary.py) and [telemetry](https://github.com/phenobarbital/ai-parrot/blob/main/packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/telemetry.py): aggregation and projection of attempts.
- Local telemetry: [FEAT-559](../../artifacts/logs/sdd-coder-usage/FEAT-559.jsonl), [FEAT-560](../../artifacts/logs/sdd-coder-usage/FEAT-560.jsonl), [FEAT-563](../../artifacts/logs/sdd-coder-usage/FEAT-563.jsonl). Their availability depends on preserving the local artifacts.
- Evaluation supplied by the user: source of the native figures. The profiler cited through an abbreviated path and the original transcripts were not verified in this review.

No prompts, routing, code or policies have been changed. The proposals need specification and validation before adoption.

## 8. Second profiler pass: answers, corrections and additional proposals

Evidence level: **verified against the local transcripts** of the four runs (FEAT-578, FEAT-565, FEAT-572, FEAT-564). Scripts and raw outputs in `artifacts/logs/sdd-worker-profiling/` (`profile_sdd_worker.py`, `analyze_orchestrator.py`, `first-pass-20260921.txt`, `second-pass-20260921.txt`); the directory is under `.gitignore`, so reproducibility depends on keeping it together with `~/.claude/projects/`. They are still four features: what follows describes this cohort, not a law.

### 8.1 Answers to the open questions of §2

**36.2% versus 39.0% (§2.1).** It was a defect of the aggregate, not rounding. The model row was computed as `active − Σ(union per category)`, which subtracts the overlap between categories twice (a pytest that runs while a background agent is alive). The measured overlap is 1,148 s. With `active − union(all tools)` the residual is **15,504 s = 39.0%**, which matches the sum by rows. Fixed in the script; the per-category rows overlap each other and do not add up to 100%.

**What a `turn` is (§2.2).** The `assistant` rows of the transcript are *content blocks*, not requests: a request with `thinking` + `tool_use` produces two rows with the same `requestId`. Grouping by `requestId`:

| Feature | Assistant rows | Real requests | Median latency | p90 | Median context (tokens) | Max. context |
|---|---:|---:|---:|---:|---:|---:|
| FEAT-578 | 707 | 419 | 6.5 s | 18.7 s | 160 k | 359 k |
| FEAT-565 | 551 | 305 | 4.1 s | 9.6 s | 247 k | 408 k |
| FEAT-572 | 655 | 348 | 3.3 s | 10.7 s | 306 k | 513 k |
| FEAT-564 | 2,201 | 1,155 | 4.2 s | 16.9 s | 525 k | 966 k |

The "turn" figures of the first pass were inflated by ~1.85×. Latency is measured directly as *previous event → last block of the request*; its sum (16,531 s) is consistent with the residual (15,504 s), so the residual **is, in essence, the latency of the orchestrator's requests** and not mysterious time. It does not separate first token from generation: the transcript does not expose it.

**What the "idle" gaps are (§2.2).** The objection was correct and it changes the baseline. Classifying each gap by the event that ends it:

| Threshold | Total | Ends in user prompt | Ends in background task notification | Unclassified (`attachment`) |
|---|---:|---:|---:|---:|
| 60 s | 8.50 h | 297 min (11) | 136 min (18) | 68 min (5) |
| 120 s | 8.29 h | 297 min (11) | 133 min (16) | 68 min (5) |
| 300 s | 7.59 h | 289 min (8) | 109 min (7) | 58 min (3) |

The result is not very sensitive to the threshold, but **only ~5 h is demonstrable human waiting**. The remaining 133 min is machine work that the profiler did not see, because a `Bash` with `run_in_background` and an MCP call sent to the background return their `tool_result` instantly:

- FEAT-578: five background test runs **killed by timeout (exit 124)** of ~590 s each (47.8 min): merge-tier selection, full suite with xdist and three successive attempts of the same `ai-parrot-integrations` suite.
- FEAT-572: a merge-tier selection of **1,985 s** that ended with exit 1.
- FEAT-564: `coder_prepare_native` hung for **1,667 s** until failing; plus two background suites (165 s and 286 s, exit 0).
- FEAT-565: seven `coder_wait` calls of ~145 s sent to the background.

Consequences: real active time is ≥ 13.2 h (not 11.0 h) and **tests weigh ~18% of corrected active time** (3,289 s in the foreground + ~5,300 s in the background), not 8.3%. This confirms the caution at the end of §2.4: inside the seat tests are marginal, in integration and closeout they are not.

**70–80% generation in native coders (§2.4).** Verified with n = 15: residual 72.4%, tools 27.6%, pytest 7.0% of the span. For `code-reviewer` (n = 4): residual 67.5%, pytest 15.0%. "Residual" with the same caveat as above.

**Reaction delay (§2.3).** From *native coder end* to the orchestrator's first output: median 3 s, max 55 s. From *coder end* to the next `coder_merge`: median 3 s, but 4 of 12 deliveries waited 240–1,657 s. In the 1,657 s case (FEAT-565) the orchestrator spent 691 s inside `coder_wait` and 436 s unattributed while the native delivery was already ready: it is exactly the risk described in §2.3. Caveat: the pairing is "next merge", not by `task_id`; in FEAT-572 the delays of ~395 s coincide with the dispatch of the next coder before consolidating, which may be legitimate pipelining.

### 8.2 New findings

**a) The orchestrator's residual is not in the control plane.** Attributing each request's latency to the first action it emits:

| Next action | Requests | % of model time | s/request | Output tokens/request |
|---|---:|---:|---:|---:|
| Bash (other: grep, ls, inline python…) | 589 | 26.4% | 7.4 | 694 |
| Edit | 218 | 11.7% | 8.9 | 997 |
| Bash git | 299 | 11.2% | 6.2 | 520 |
| Text only / end of turn | 180 | 10.0% | 9.2 | 146 |
| Read | 269 | 8.6% | 5.3 | 460 |
| Bash pytest | 226 | 8.6% | 6.3 | 581 |
| Write | 35 | 8.2% | 38.5 | 5,216 |
| All `coder_*` together | 209 | 6.3% | 5.0 | 330–990 |

Deciding MCP calls is cheap. What is expensive is the orchestrator's own manual work: shell inspection, git, edits and re-reads. This supports §3.1 and bounds its target: it is not the control tools, it is everything surrounding the consolidation.

**b) FEAT-564 was not an orchestration run.** No MCP attempt is observed, there is a single `coder_merge`, and the orchestrator itself made 91 source-code edits and 67 test edits, with 145 pytest executions (79 exact repetitions; ×20 on the same directory). It is the "implement it yourself" fallback path, executed in the most expensive context in the system (median 525 k tokens, maximum 966 k) and serially. Since it weighs 45% of the baseline, the "39%" mostly describes that mode; without FEAT-564 the residual is 27.6% (the figure from §2.1). In the other three the orchestrator edits almost only SDD state (46 of 71 edits).

**c) The baseline is contaminated by an already fixed defect.** In FEAT-572 and FEAT-578, 25 of 34 MCP attempts failed in 0 s with `CoderFailure: seat '<x>' … is not eligible for unknown task` (issue `e01c03baf493`, fix merged into `dev` during FEAT-572): the plan assigned seats that dispatch rejected. Each rejection cost replanning: `coder_plan` was called 35 times (8–12 per feature) with ~9 KB per response, 11.5% of all payload returned to the orchestrator. These runs are not usable as a control for an experiment; a post-fix baseline is needed.

**d) Context is a cost problem more than a time problem.** 1,369 of 2,227 requests ran with more than 250 k tokens of context. Median latency barely changes between 100–150 k (3.7 s) and >250 k (4.3 s); the mean rises from 5.1 to 7.7 s. The cache absorbs the time, not the bill.

**e) What fills the orchestrator's context** (characters of `tool_result`): Read 33.9%, Bash other 19.1%, pytest 13.3%, `coder_plan` 11.5%, git 6.1%.

**f) Observed consolidation cost:** ~50 orchestrator requests per integrated task (FEAT-565: 51; FEAT-572: 50), with a median of 14–34 between consecutive merges.

**g) Test repetition:** 116 of the orchestrator's 226 pytest runs repeat exactly a target already run in the same session. They are fix-retry loops, not new validation.

### 8.3 Additional proposals and priority adjustments

| Order | Change | Evidence (§8) | Effort / risk |
|---|---|---|---|
| P0 | Budget and fail-fast for background suites | 8.1: 81 min in runs that ended in timeout or error | Low / low |
| P0 | Bounded fallback: do not implement in the orchestrator's context | 8.2 b: 45% of the baseline | Low–medium / medium |
| P0 | Profiler: background tasks, real requests, classified gaps | 8.1 | Low / low |
| P1 | Admission parity plan ↔ dispatch and incremental `coder_plan` | 8.2 c | Medium / low |
| P1 | Per-operation deadline on MCP control calls | 8.1: `coder_prepare_native` 1,667 s | Low / low |
| P1 | Consolidate on receiving the delivery, not on returning from the wait | 8.1: 4/12 deliveries, up to 1,657 s | Medium / medium |
| P2 | Hygiene of the orchestrator's test loop | 8.2 g | Low / low |
| P2 | Context hygiene (cost) | 8.2 d, e | Medium / low |

**P0 — Background suites with a budget.** No suite should be launched without an expected duration. Candidate rules: record the duration of each `merge`/`feature` selection and use it as the budget for the next one; on exit 124, **do not retry the same selection** (in FEAT-578 it was done three times in a row, ~30 min): reduce the scope, partition or escalate to the user; propagate the failure reason instead of a bare code. It ties in with §3.5: the broad escalation is where the time is, not the per-task test. Measure first how long each level takes today when cold.

**P0 — Bounded fallback.** When the MCP path is not available, the worker today may implement the tasks itself. Doing so in its own context is the slowest and most expensive option observed. Alternative to test: make the fallback dispatch native `sdd-coder` seats task by task (fresh context, same delivery contract), and require self-implementation to meet an explicit condition and a cap (e.g. number of source-code edits by the orchestrator) that forces it to stop and report. The indicator is direct: source-code edits made by the orchestrator per feature; in three of four runs it was ≤ 5.

**P0 — Profiler.** Pair each background launch with its `task-notification` to treat it as a busy interval; count requests by `requestId`; classify each gap by its ending event and report "human waiting", "uninstrumented machine waiting" and "unclassified" separately; publish the overlap rule. Turn it into a versioned script once it stabilizes (today it lives in an ignored directory). This makes concrete the P0 of §3 and step 1 of §6.

**P1 — Plan ↔ dispatch parity.** A 0 s failure is not a model failure: it is a contract error the plan should have prevented. Checkable invariant: every seat assigned by `coder_plan` passes dispatch admission for that task. In addition, classify these rejections separately in telemetry so they neither count as attempts nor trigger suspensions, and allow `coder_plan` to return only what changed relative to the previous plan (or a compact summary), given its weight in the context. First verify whether the fix for `e01c03baf493` already covers the invariant.

**P1 — Deadlines on control calls.** The toolkit wrapper already measures `elapsed_ms`; a per-operation deadline is missing. `coder_prepare_native` has a median of a few seconds and one case of 1,667 s: a deadline on the order of tens of seconds with a structured error would have returned 27 minutes. It requires the operation to be idempotent or to clean up its partial sub-worktree.

**P1 — Consolidate per delivery.** It provides the measurement §2.3 asked for and a first step cheaper than §3.6: while native seats are alive, prefer short MCP waits or consolidate pending native hand-backs first before returning to `coder_wait`. It requires neither new events nor a continuous planner. Measure with pairing by `task_id` before deciding.

**P2 — Test loop.** For fix-retry loops: `--lf`/`-x` on the failing target and, if the loop exceeds N iterations, treat it as a correction task for a seat instead of continuing in the orchestrator. It does not affect coverage at the `merge`/`feature` levels.

**P2 — Context.** Since latency barely scales with context, classify it as a cost optimization: reads by diff or by range instead of whole files during review, pytest output summarized by default with the full log in a file, compact MCP responses (§3.2). Do not expect appreciable time savings from this.

**Adjustments to §3.** §3.1 gains a concrete indicator (*orchestrator requests per integrated task*, today ~50) and a more precise scope: git and SDD state, not the `coder_*` tools. §3.5 rises in priority for the broad levels and falls for the task level. §3.6 can wait for the result of "consolidate per delivery".

### 8.4 Scenarios of §5, revised

The three scenarios of §5 used a base of 11 h 01 min that underestimates active time and an attribution now known to be mixed. With the corrected base (≥ 13.2 h):

| Hypothetical scenario | Measured base | Equivalent |
|---|---|---:|
| Eliminate background runs that ended in timeout/error | 5 × ~590 s + 1,985 s | ~81 min |
| Avoid the `coder_prepare_native` hang with a deadline | 1,667 s | ~27 min |
| Avoid the 116 exact pytest repetitions (median ~9 s) | 116 × ~9 s, plus the associated request (~6 s) | ~29 min |
| Reduce orchestrator requests by 25% in real orchestration runs (without FEAT-564) | residual 6,010 s across three features | ~25 min |

The first two rows are time that produced nothing and do not compete with quality; that is why they move to P0. They are still sums over four runs, not predictions, and the first three depend on incidents that may not recur with the same frequency.

### 8.5 The 26% of "inspection Bash": what it is and what makes it cheaper

Breakdown of the 589 calls (verified against the same transcripts):

| Category | n | % |
|---|---:|---:|
| Read worktree files or logs (`cat`, `sed -n`, `tail`) | 194 | 32.9% |
| Search (`grep`, `find`, `ls`, `wc`, `ps`) | 184 | 31.2% |
| No useful effect (`echo "waiting"`, `true`, `python -c "uuid4()"`) | 71 | 12.1% |
| Inline Python (JSON index queries, checks) | 60 | 10.2% |
| Read SDD task / spec / index | 43 | 7.3% |
| Active waiting (`sleep`, `until kill -0`) | 19 | 3.2% |
| File operations (`mv`, `mkdir`, `jq` on the index) | 17 | 2.9% |

**The cost is the round trip, not the execution.** Each inspection costs ~7.4 s of model request plus ~3.8 s of execution. Parallelizing the commands inside a tool saves nothing appreciable: they are millisecond operations. What saves time is **collapsing chains**: 68% of read-only calls (inspection Bash + Read + git status/log/diff) occur in chains of three or more consecutive calls (140 chains, median 4), where each step depends on the previous one and therefore the model does not emit them in parallel.

**There is a floor of ~3.6 s per Bash call that does not belong to the command.** `true` and `echo waiting` take the same as a `grep`. Execution distribution: Bash p25 3.3 s / median 3.8 s; Read median 1.9 s; Edit 0.1 s. The difference is the `PreToolUse` hooks. Timed on a trivial input: `wikitoolkit claude-hook` **2.05 s**; `parrot_tools.tool_optimizations.hooks` 0.06 s; `dangerous-actions-blocker.sh` 0.05 s; `rtk hook` 0.003 s. `-X importtime` shows the cause: the `wikitoolkit` CLI imports at startup `parrot.knowledge.wiki.decisions.cli → parrot.clients.base` (1.31 s: pandas, `pythonrepl`, `parrot.memory`, `documentdb`) for a hook that only queries SQLite. Over the orchestrator's 1,573 Bash + Read calls in these four runs that is **~54 min**, not counting sub-agents, which inherit the hooks. The hook also emits navconfig debug lines on stdout.

Proposals, in order of benefit/effort ratio:

1. **P0 — Lazy imports in the `wikitoolkit` CLI. Done (2026-09-21).** Commit `121090047` moved the `AbstractClient` annotations under `TYPE_CHECKING` in `decisions/` (2.05 s → 0.45 s and clean stdout, because navconfig is no longer imported); `aiohttp` is now imported inside `DocumentAcquirer` in `documents.py` (0.45 s → 0.32 s). What remains is the startup of Python plus the CLI's own click/pydantic/yaml; going lower would require a separate entry point for the hook (the `claude_code.hook` module alone imports in 0.27 s), with marginal gain.
2. **P1 — Eliminate no-effect calls** from the worker prompt: do not narrate with `echo`, and have `coder_begin_execution` return the identifier instead of generating it with `python -c uuid4`. 71 calls × ~11 s ≈ 13 min.
3. **P1 — Purposeful read operations in the MCP toolkit**, not a generic inspection tool (which would be Bash under another name). Candidates, each replacing an observed chain:
   - `coder_task_context(task_id)`: task, index entry, dependency state and declared files.
   - `coder_delivery_report(task_id)`: branch, commits, `diff --stat`, out-of-scope files, sub-worktree state and lint/test evidence. It is the "normalized delivery" of §3.1 and absorbs a good part of the 299 git calls.
   - `coder_bg_status(handle)`: alive/finished, exit code and bounded log tail; replaces the `ps | grep`, `tail`, `wc -l` and active waits.
4. **Bounded and structured** output in all three: Read is already 33.9% of the context payload (§8.2 e); a tool that returns whole files worsens the problem it is meant to solve.

Upper bound of point 3: if every chain of ≥ 3 were reduced to one call, ~650 round trips (~11 s each) would be avoided, about 2 h out of 13.2 h. Part of those chains is genuine exploration whose next step depends on the result, so the reasonable expectation is a fraction; measure it with the indicator from §8.3 (*requests per integrated task*).
