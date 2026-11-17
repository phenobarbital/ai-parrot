---
kind: file
jira_key: null
file_path: sdd/proposals/sdd-escrow.brainstorm.md
fetched_at: 2026-11-07T01:13:33Z
summary_oneline: Escrow monitor agent — hold the worktree until an external signed APPROVED verdict releases it; sdd-worker emits work.completed, /sdd-done refuses without it
---

# Inline framing (user, 2026-11-07, verbatim)

Usar @sdd/proposals/sdd-escrow.brainstorm.md para construir un agente de supervision externa al flujo SDD. Es un escrow de release, no de review. El valor no está en que agentes relean el diff (eso ya lo hace /pr-review y el code-reviewer del worker). El valor está en que el worktree queda en estado held hasta que un veredicto externo lo libera, y que ese veredicto lo produce alguien que no participó en el trabajo. Separación de poderes: sdd-worker nunca puede marcar su propio trabajo como listo. Eso cambia el contrato: sdd-worker termina emitiendo un evento work.completed al bus, no un "done". El estado pasa a AWAITING_VERDICT en state.json, y /sdd-done en el host se niega a correr si no hay un veredicto APPROVED firmado en el ledger.

# File source: sdd/proposals/sdd-escrow.brainstorm.md (verbatim)

---
# SDD flow type and base branch.
type: feature
base_branch: dev
---

# Brainstorm: Escrow — external process-completion supervision agents (first application: the SDD flow)

**Date**: 2026-11-05
**Author**: Jesus Lara (drafted with Claude)
**Status**: exploration
**Recommended Option**: B
**Related**: `claude/sdd-work-ledger.brainstorm.md` (ledger plane, `events.jsonl`), `claude/agentic-e2e-testing.brainstorm.md` (e2e sub-agents), `principles.md` ("probabilistic proposes, deterministic decides")

---

## Problem Statement

Today `sdd-worker` orchestrates `sdd-coder` sub-agents, lands the result in the feature worktree / local branch, and the feature is considered "worked" until a human runs `/sdd-done` on the host. Nothing between those two points verifies — independently of the agents that did the work — that the work is *complete* against the spec and the project's policies. `/sdd-codereview` exists, but it is (a) invoked by the same flow that produced the code, (b) advisory, and (c) its unfixed findings leak (the problem the ledger brainstorm addresses).

Two gaps:

1. **No separation of powers.** The worker effectively grades its own homework. Any check it runs can be skipped, rationalised, or simply not triggered on failure.
2. **No generic "watch a long process and judge it" primitive.** The need is not SDD-specific: trading-swarm runs, scraping pipelines, e2e test campaigns, contract-agent batch jobs all end in a state that *someone* should validate before downstream effects happen. Each would reinvent "wait for completion event → evaluate → approve / send back / ask a human".

**Escrow** names the concept: the output of a long process is *held* until an external verdict releases it. The verdict is produced by agents that did not participate in the work, under a declared policy, with an explicit path to human approval (HITL). First application: the SDD flow, between `sdd-worker` completion and `/sdd-done`.

**Owner constraint (2026-11-05):** escrow must be **opt-in per launch** — a flag on the worker launch. For a small spec, running a review crew is expensive and pointless; escrow is for long / multi-task features. Default **off**.

## Constraints & Requirements

- **Opt-in flag, deterministic.** `/sdd-start --escrow[=<policy>]` (and the equivalent on `sdd-worker` / dev_loop launch). The decision to run escrow is never taken by an LLM. A *suggestion* heuristic (task count, touched-file count, `effort` sum from the task index) may print "consider `--escrow`", but only the flag enables it.
- **Separation of powers.** The agents that produce the verdict are distinct from `sdd-worker` / `sdd-coder`, run with their own session / `ToolManager`, and see the *result* (worktree diff, test output, spec, task index, ledger events), never the worker's conversation.
- **Probabilistic proposes, deterministic decides.** Hard gates (tests, lint, coverage, scope, secrets) are code, not prompts. LLM experts answer only questions a gate cannot. The final verdict is a closed Pydantic model; the *release* action is executed by deterministic code from that model.
- **Held state is enforced, not advisory.** While a feature is `awaiting_verdict` or `rescheduled`, `/sdd-done` refuses to merge unless an `escrow.approved` event exists for the current head SHA (or `--override-escrow` with a recorded reason).
- **Rescheduling produces SDD artifacts, not prose.** `RESCHEDULE` materialises corrections as new TASKs in the feature's task index (children of the original task, linked to the verdict id). The re-launched worker sees only those tasks.
- **Bounded loops.** `max_rounds` per policy (default 2). Reaching it escalates to HITL; the escrow never re-schedules indefinitely.
- **Event-driven, bus-agnostic.** Escrow is triggered by a `work.completed` event. v1 transport is the ledger's `events.jsonl` (already the SDD event sink); the same consumer must be mountable on navigator-eventbus / Redis for non-SDD processes.
- **Every verdict is a ledger event**, including approvals. `events.jsonl` is the audit trail; `ledger.db` indexes `verdict:` pages with `judges`, `rescheduled-to`, `about` edges.
- **No new heavy dependency.** Reuse `AgentRegistry`, `ToolManager`, structured outputs, the ledger plane, `/sdd-codereview`'s reviewer prompts where sensible, the existing HITL integrations (Telegram / Teams) for `ESCALATE`.
- **Language split:** identifiers, event kinds, policy files and docs in English.
- **Validation-first:** a spike proves (a) the worker can emit `work.completed` with a stable head SHA and the `/sdd-done` guard reads it, (b) hard gates run headless in the worktree, (c) the structured verdict round-trips through the chosen client(s), before `/sdd-spec`.

---

## Options Explored

### Option A: Escrow as a mandatory extra stage of `/sdd-codereview`

Extend `/sdd-codereview` to produce a verdict and have `/sdd-done` require it.

✅ **Pros:**
- Smallest change; reviewer prompts and report format already exist.
- No new agent, no bus.

❌ **Cons:**
- Same flow, same session lineage: no separation of powers.
- Review is per-task; escrow must judge the *feature* (all tasks done? spec covered? scope creep?).
- Not reusable for non-SDD processes.
- Mandatory would violate the opt-in constraint; optional-but-inside-codereview keeps it advisory.

📊 **Effort:** Low

---

### Option B: `EscrowAgent` + policy files + ledger events, launched by `--escrow` — *recommended*

A standalone escrow runtime (registered in `AgentRegistry`) consuming `work.completed` events and executing a **policy**:

```
work.completed(feature, head_sha, worktree, tasks[])
  → load policy (sdd/escrow/<policy>.yaml, or policy named in the event)
  → run hard gates (deterministic, in the worktree)         → GateReport
  → if gates fail hard: verdict RESCHEDULE without experts  (cheap path)
  → run experts (LLM, structured output, read-only tools)   → ExpertOpinion[]
  → judge (LLM or deterministic aggregator per policy)      → Verdict
  → act: emit escrow.<verdict> event; on RESCHEDULE create child TASKs + relaunch worker;
         on ESCALATE open HITL approval request and block
```

Policy = YAML, versioned in repo:

```yaml
# sdd/escrow/default.yaml
version: 1
max_rounds: 2
gates:                      # deterministic, all must pass
  - tests: { cmd: "uv run pytest -q", must_pass: true }
  - lint:  { cmd: "uv run ruff check .", must_pass: true }
  - scope: { every_task_has_commit: true, no_unresolved_verify_markers: true }
  - secrets: { scan_diff: true }
experts:                    # LLM, advisory or blocking
  - name: spec-conformance
    question: "Does the diff implement the spec as written, or reinterpret it?"
    mode: blocking
  - name: scope-debt
    question: "What was introduced outside the task scope that belongs in the ledger?"
    mode: advisory          # files issues, never blocks
  - name: principles
    question: "Which project invariants (principles.md) does the change violate?"
    mode: blocking
judge:
  kind: single              # single | majority | judge   (judge = N experts + arbiter LLM)
  model: claude             # client name from parrot.clients
escalate_on: [max_rounds_reached, gate_error, expert_disagreement]
```

Verdict model (closed):

```python
class Correction(BaseModel):
    task_ref: str                # TASK-NNN the correction derives from
    title: str
    rationale: str
    files: list[str] = []
    severity: Literal["critical", "major"]

class Verdict(BaseModel):
    decision: Literal["APPROVED", "RESCHEDULE", "ESCALATE_HITL"]
    feature: str
    head_sha: str
    round: int
    gate_report: GateReport
    opinions: list[ExpertOpinion]
    corrections: list[Correction] = []     # required when RESCHEDULE
    reason: str | None = None              # required when ESCALATE_HITL
```

SDD integration:
- `/sdd-start --escrow[=<policy>]` writes `escrow: {policy, enabled: true, round: 0}` into the feature's task-index header; the worker, on finishing its task batch, emits `work.completed` instead of leaving the feature silently idle.
- `/sdd-done` §guard: reads the index header; if `escrow.enabled` and no `escrow.approved` for `HEAD`, exit with the pending state and the last verdict summary.
- `RESCHEDULE` → `sdd-task --from-verdict <verdict-id>` creates child TASKs (`depends_on: [original]`, `discovered-from: verdict:<id>`), bumps `round`, relaunches `sdd-worker` scoped to them.
- `ESCALATE_HITL` → approval request via the existing human-in-the-loop integrations; the human's `approve` / `reject` becomes an `escrow.human_decision` event; `reject` may carry corrections → same RESCHEDULE path.

✅ **Pros:**
- Clean separation of powers; escrow is a different agent with a read-only tool manifest over the worktree.
- Cheap path first: most RESCHEDULEs come from gates, no LLM spent.
- Policy is data: single-expert for SDD, `judge` + consensus for trading or anything with higher error cost.
- Reusable: the consumer is generic (event → policy → verdict → action); SDD is one policy and one action adapter.
- Full audit trail for free via the ledger; "feature X needed 3 rounds" is a query.

❌ **Cons:**
- New runtime to host: who runs the consumer? (dev_loop process, `parrot escrow serve`, or a Claude Code hook that fires it inline — see Open Questions).
- Policy YAML is one more format to document.
- Expert prompts are a calibration problem; blocking experts with bad calibration turn autonomy into friction. Mitigated by starting experts in `advisory` and promoting to `blocking` with data.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| Pydantic v2 | policy + verdict models | already in stack |
| `parrot.clients.*` structured outputs | expert / judge responses | existing |
| ledger plane (`events.jsonl`, `ledger.db`) | trigger + audit | from the ledger feature; escrow depends on it |
| navigator-eventbus | non-SDD triggers (v2) | optional extra |

🔗 **Existing Code to Reuse (⚠️ VERIFY — not re-read in this session):**
- `AgentRegistry` / decorator registration for `EscrowAgent`, experts and judge.
- Per-session `ToolManager` with a closed, read-only manifest (`git diff`, `git log`, file read, test-output read) — mirrors the `python_repl` allowlist-first gate.
- `/sdd-codereview` reviewer prompts as the seed of the `spec-conformance` expert.
- `sdd/tasks/index/<slug>.json` header for the `escrow` block; `close_task.sh` / `sdd-start` §8 as the point that emits `work.completed` once all tasks of the launch are closed.
- Ledger brainstorm: `LedgerLog.append`, `LedgerIndex.apply`, event id scheme — add kinds `work.completed`, `escrow.started`, `escrow.gate_report`, `escrow.opinion`, `escrow.approved`, `escrow.rescheduled`, `escrow.escalated`, `escrow.human_decision`.
- HITL integrations in `parrot/human/` (Telegram / Teams approval flows).

---

### Option C: Escrow as an external service (A2A / MCP) with its own store

Run escrow as a separate process exposing an A2A endpoint; worker calls it at the end; escrow keeps its own DB of verdicts.

✅ **Pros:**
- Strongest isolation; multi-host; could serve several repos.

❌ **Cons:**
- Over-scoped for a single-developer, local loop; requires a running service for `/sdd-done` to work.
- Duplicates the audit trail the ledger already provides.
- Worker *calling* escrow re-couples them; the event model keeps them decoupled.

📊 **Effort:** High

*(Keep as the v2 deployment shape: Option B's consumer behind A2A once non-SDD processes need it across hosts.)*

---

## Recommendation

**Option B.** It is the only option that gives true separation of powers, honours the opt-in flag, keeps the deterministic/probabilistic split, and yields a reusable primitive instead of an SDD-only check. The ledger plane is the natural event sink and audit trail, so escrow should be specced as *depending on* the ledger feature rather than carrying its own storage.

Scope guidance for v1:
- Gates: tests, lint, scope-completeness, secrets. Few and strict.
- Experts: one blocking (`spec-conformance`), one advisory (`scope-debt` → files ledger issues). `principles` expert advisory until calibrated.
- Judge: `single`. `majority` / `judge` kinds implemented but not default.
- Relaunch: via the same mechanism `/sdd-start` uses today (child TASKs + worker), not a new scheduler.
- HITL: reuse an existing approval integration; v1 can be "print the verdict and wait for `/sdd-escrow approve|reject`" on the host if the integration is not wired yet.

---

## Feature Description

### User-Facing Behavior

- `/sdd-start --escrow` (or `--escrow=strict`) enables escrow for that launch; the index header records it. Without the flag, behaviour is unchanged.
- `/sdd-status` shows `escrow: awaiting_verdict | round 1/2 | approved @<sha>` per feature.
- `/sdd-escrow run <FEAT-ID>` triggers evaluation manually (also what the hook / consumer calls); `/sdd-escrow show <FEAT-ID>` prints the last verdict; `/sdd-escrow approve|reject <FEAT-ID> [--reason]` is the host-side HITL fallback.
- `/sdd-done` refuses while escrow is pending or rescheduled; `--override-escrow "<reason>"` records an `escrow.overridden` event and proceeds.
- A `RESCHEDULE` shows up as new TASKs in `/sdd-next`, tagged `from: verdict:<id>`.

### Internal Behavior

1. `EscrowPolicy` (Pydantic) loads `sdd/escrow/<name>.yaml`; validation fails loudly on unknown gate / expert kinds.
2. `GateRunner` executes gates in the worktree with a timeout; produces `GateReport{passed, results[]}`. Any gate error (not failure) → `ESCALATE_HITL` by policy.
3. `ExpertRunner` fans out experts concurrently (asyncio), each with a read-only `ToolManager`, structured output `ExpertOpinion{verdict: pass|fail|unsure, findings[], confidence}`.
4. `Judge` aggregates per policy kind; `single` = the one blocking expert; `majority` = vote; `judge` = arbiter LLM over opinions, structured `Verdict`.
5. `EscrowActions` (deterministic): emit events; `RESCHEDULE` → create child TASKs + relaunch; `ESCALATE` → open approval; `APPROVED` → stamp index header.
6. Trigger: `work.completed` appended by the worker's closing step; consumer is either (a) inline in the closing step when `escrow.enabled` (v1, simplest) or (b) a `parrot escrow watch` tailing `events.jsonl` / a bus (v2).

### Edge Cases & Error Handling

- Head SHA moves after a verdict (human edits in the worktree) → verdict is bound to `head_sha`; `/sdd-done` sees mismatch → `stale_verdict`, requires re-run.
- Gate tool missing (no `pytest`) → gate *error*, not fail → escalate, never approve.
- Expert client unavailable → opinion `unsure`; blocking `unsure` → escalate by policy, never silent pass.
- `RESCHEDULE` with zero corrections → model validation error → escalate.
- Round > `max_rounds` → escalate; corrections preserved in the verdict for the human.
- Escrow invoked on a feature launched without `--escrow` → runs, records verdict, but does **not** block `/sdd-done` (explicit flag governs enforcement).

---

## Capabilities

### New Capabilities
- `escrow-policy`: policy schema + loader (`sdd/escrow/*.yaml`).
- `escrow-gates`: deterministic gate runner (tests, lint, scope, secrets) with reports.
- `escrow-experts`: expert agents with read-only tool manifest and structured opinions.
- `escrow-judge`: aggregation kinds `single | majority | judge`.
- `escrow-actions`: event emission, child-TASK creation, relaunch, HITL request, index stamping.
- `sdd-escrow-integration`: `--escrow` flag, index header block, `/sdd-done` guard, `/sdd-escrow` command, `/sdd-status` line.

### Modified Capabilities
- `sdd-start`: flag parsing + `work.completed` emission at batch close.
- `sdd-done`: escrow guard + override.
- `sdd-task`: `--from-verdict`.
- `wiki-ledger-log` / `wiki-ledger-index`: new event kinds, `verdict:` pages, `judges` / `rescheduled-to` edges.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/escrow/` (new) | new | `policy.py`, `gates.py`, `experts.py`, `judge.py`, `actions.py`, `runtime.py` |
| ledger plane (`knowledge/wiki/ledger/`) | depends on / extends | new event kinds + page category `verdict:` |
| `.claude/commands/sdd-{start,done,task,status}.md` | modifies | flag, guard, `--from-verdict`, status line |
| `.claude/commands/sdd-escrow.md` (new) | new | `run / show / approve / reject` |
| `scripts/sdd/close_task.sh` or worker closing step | modifies | emit `work.completed` when batch complete |
| `sdd/escrow/default.yaml`, `strict.yaml` | new | tracked policies |
| `parrot/human/*` | depends on | HITL approval transport (v1 may use host fallback) |
| `sdd/WORKFLOW.md` | modifies | escrow section |

No breaking changes; everything behind the flag.

---

## Code Context

### User-Provided Code
_None — constraints in prose: opt-in flag on worker launch; only for long features; external agents validate or reschedule before the human runs `/sdd-done`; single agent or expert group with judge/consensus; HITL approvals; triggered by another process or a bus._

### Verified Codebase References
_**None re-verified in this session.** The references below are carried from `claude/sdd-work-ledger.brainstorm.md` (verified against `main` on 2026-09-13) and must be re-checked in the spike before `/sdd-spec`:_

- ⚠️ VERIFY `sdd/tasks/index/<slug>.json` header fields (`feature, feature_id, spec, type, base_branch, created_at, completed_at, tasks[]`) — target for the `escrow` block.
- ⚠️ VERIFY `/sdd-start` commits on the feature branch inside the worktree (§4 flip, §7.6 code, §8 close); `/sdd-done` runs on the base branch, PR or `--merge`.
- ⚠️ VERIFY `scripts/sdd/close_task.sh <TASK-ID> <feature-slug> [verified|partial|forced]` — candidate emission point for `work.completed` (last task of the launch closed).
- ⚠️ VERIFY `sdd/state/<FEAT-ID>/state.json` is `/sdd-proposal` research state only — **not** a task-execution state; the escrow state must live in the task index header, not there.
- ⚠️ VERIFY `/sdd-codereview` buckets 🔴/🟡/🟢 and reviewer prompts — seed for `spec-conformance`.
- ⚠️ VERIFY `AgentRegistry` decorator API and per-session `ToolManager` construction for a read-only manifest.
- ⚠️ VERIFY which HITL approval flow exists in `parrot/human/` today and over which transport.
- ⚠️ VERIFY whether the ledger feature (`knowledge/wiki/ledger/`) has landed; escrow's event sink depends on it. If not landed, v1 escrow may write `sdd/escrow/<FEAT-ID>/verdicts.jsonl` in the main worktree as a temporary sink with the same event schema.

### Does NOT Exist (Anti-Hallucination)
- ~~any `--escrow` flag, `sdd-escrow` command, or `parrot/escrow/` package~~ — assumed absent; confirm with grep.
- ~~a blocking guard in `/sdd-done` beyond the ledger brainstorm's proposed `--ack-open-critical`~~ — not implemented as of 2026-09-13.
- ~~`work.completed` / `escrow.*` event kinds~~ — not in the ledger brainstorm's kind list.
- ~~task-execution state in `sdd/state/`~~ — see above.

---

## Parallelism Assessment

- **Internal parallelism**: yes. Lane 1: policy + verdict models + gate runner (pure Python, testable offline). Lane 2: experts + judge (needs clients, structured output). Lane 3: SDD command integration (markdown + bash + `close_task.sh`). Lane 4: ledger event kinds (coordinate with the ledger feature). Lanes 1–2 are independent; 3 depends on 1's models; 4 depends on the ledger feature's status.
- **Cross-feature independence**: depends on `sdd-work-ledger` for the event sink; coordinate event schema. Touches the same SDD command files as the ledger feature — land one before the other or merge carefully.
- **Recommended isolation**: `mixed` — Lane 1 first in one worktree, then per-lane.
- **Rationale**: models and gates are a self-contained core; the rest is additive.

---

## Open Questions

- [ ] **Where does the consumer run in v1?** Inline in the worker's closing step (simplest, no daemon) vs. `parrot escrow watch` tailing `events.jsonl` / bus (truer to "vigilance agent"). — *Owner: Jesus*
- [ ] **Flag granularity**: `--escrow` boolean with policy by feature `type`, or `--escrow=<policy>` explicit? Should `/sdd-task` suggest it from task count / effort (print-only)? — *Owner: Jesus*
- [ ] **Which client runs experts?** Cheap non-thinking model for experts + stronger model for `judge`, or same as `sdd-coder`? Cost ceiling per round? — *Owner: Jesus* (spike measures)
- [ ] **Relaunch mechanism**: can `sdd-worker` be invoked headless from the escrow action with a task subset, or does `RESCHEDULE` stop at "child TASKs created, run `/sdd-start`"? — *Owner: Jesus*
- [ ] **HITL transport for v1**: Telegram / Teams approval already usable from a Claude Code context, or host-side `/sdd-escrow approve` only? — *Owner: Jesus*
- [ ] **Does escrow replace `/sdd-codereview` per task when enabled**, or run after it at feature level? Avoid double LLM review cost. — *Owner: Jesus*
- [ ] **Consensus semantics**: `majority` of what — blocking experts only? tie → escalate? — *Owner: Jesus*
- [ ] **Policy ownership**: repo-tracked only, or also `~/.parrot/escrow/` user-level defaults? — *Owner: Jesus*
