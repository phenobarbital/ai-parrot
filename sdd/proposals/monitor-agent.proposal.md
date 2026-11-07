---
id: FEAT-841
title: Release escrow for the SDD flow — hold the worktree until an external, head-bound APPROVED verdict releases it
slug: monitor-agent
type: feature
mode: enrichment
status: discussion
source:
  kind: file
  jira_key: null
  jira_url: null
  file_path: sdd/proposals/sdd-escrow.brainstorm.md
  fetched_at: 2026-11-07
  summary_oneline: Escrow monitor agent — worker emits work.completed, feature held AWAITING_VERDICT, /sdd-done refuses without a signed APPROVED verdict in the ledger
overall_confidence: medium
base_branch: dev
projects: [sdd-tooling, ai-parrot]
tags: [escrow, separation-of-powers, sdd-done, sdd-worker, ledger, hitl]
research_state: sdd/state/FEAT-841/
created: 2026-11-07
updated: 2026-11-07
---

# FEAT-841 — Release escrow for the SDD flow

> **Mode**: enrichment
> **Confidence**: medium
> **Source**: `file: sdd/proposals/sdd-escrow.brainstorm.md` + the owner's inline framing (2026-11-07)
> **Audit**: [`sdd/state/FEAT-841/`](../state/FEAT-841/)

---

## 0. Origin

The owner's framing, verbatim (Spanish), followed by the brainstorm it builds on. The full source is at
`sdd/state/FEAT-841/source.md`.

> Usar `sdd/proposals/sdd-escrow.brainstorm.md` para construir un agente de supervision externa al flujo SDD. Es un
> escrow de release, no de review. El valor no está en que agentes relean el diff (eso ya lo hace /pr-review y el
> code-reviewer del worker). El valor está en que el worktree queda en estado held hasta que un veredicto externo lo
> libera, y que ese veredicto lo produce alguien que no participó en el trabajo. Separación de poderes: sdd-worker nunca
> puede marcar su propio trabajo como listo. Eso cambia el contrato: sdd-worker termina emitiendo un evento
> `work.completed` al bus, no un "done". El estado pasa a AWAITING_VERDICT en state.json, y /sdd-done en el host se
> niega a correr si no hay un veredicto APPROVED firmado en el ledger.

The brainstorm (`sdd-escrow.brainstorm.md`, 2026-11-05) recommends Option B: a standalone escrow runtime consuming
`work.completed`, running deterministic gates first, optional LLM experts, a closed `Verdict` model
(`APPROVED | RESCHEDULE | ESCALATE_HITL`), ledger events for every verdict, `RESCHEDULE` materialised as child TASKs,
`max_rounds` with HITL escalation, and an opt-in `--escrow[=policy]` flag on the worker launch (default off).

**Initial signals** (extracted, not interpreted):
- Verbs: construir, emitir, held / release, "se niega a correr", firmado → additive, enforcement-shaped.
- Named entities: `sdd-worker`, `work.completed`, bus, `state.json`, `AWAITING_VERDICT`, ledger, `/sdd-done`,
  `/pr-review`, the worker's code-reviewer, HITL, `AgentRegistry`, `ToolManager`, `close_task.sh`.
- Constraints stated by the owner: escrow of **release**, not of review; verdict by a non-participant; the worker can
  never mark its own work ready; opt-in per launch (brainstorm).
- Acceptance criteria provided: none formal; the four sentences above are the contract.

---

## 1. Synthesis Summary

The request is to change the SDD contract so that finishing a feature no longer means "the worker said so". Today the
worker closes its last task (which stamps the feature's `completed_at`), runs its own reviewer, and prints "completed —
run `/sdd-done`"; `/sdd-done` on the host then refuses only on the E2E gate, blocking closeout hooks, and (under
`--merge`) ledger blockers. Nothing external stands between the worker's self-declaration and the merge. Escrow inserts
exactly one thing: a **held state** between `work.completed` and `/sdd-done`, released only by an `escrow.approved`
ledger event produced outside the worker and bound to the worktree's head SHA, enforced by a code gate in `/sdd-done`
built on the FEAT-703 / FEAT-764 convention ("the exit code is the contract", no `--force`). The research shows the
pieces already exist in shape: a head-bound completion receipt (`worker_notification.py`), a sandbox-side ledger
emitter (`close_task.py`), a closed event model with content-addressed ids (`ledger/events.py`), a human-only decision
precedent (`LedgerService.acknowledge`), and a host launch point (`parrot sdd launch worker`). What does **not** exist is
any signature in the ledger, any worker-owned `state.json`, or any bus reachable from the sandbox — so the five open
questions below are about where the held state lives, what "signed" must mean, and who judges in v1.
Recommendation: proceed to `/sdd-spec` with those questions as its Open Questions; the architectural fork was already
settled by the brainstorm.

---

## 2. Codebase Findings

> All entries are grounded in `sdd/state/FEAT-841/findings/` (39 digests, 221 citations probe-verified, 0 stale).

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `.claude/commands/sdd-done.md` | §4.6 E2E gate, `write_hook_context`, §7 stamp, §9 blockers | 208-216, 237-289, 444-506, 568-600 | host closeout pipeline; §4.6 is the model for a non-force-able gate; §7 is the first mutation a verdict guard must precede; §9 is the force-able, `--merge`-only shape to avoid | F002, F033 |
| 2 | `.agents/skills/sdd-done/SKILL.md` | Codex twin | — | changes together with the Claude command | F033, F021, F026 |
| 3 | `packages/ai-parrot/src/parrot/sdd/_assets/claude/commands/sdd-done.md` | shipped asset twin | — | third copy shipped by the installer | F033 |
| 4 | `.claude/agents/sdd-worker.md` | `## Completion` | 624-772 | review checkpoint → own code-reviewer → never push → optional receipt → prints "✅ completed, run /sdd-done"; the seam where "done" becomes `work.completed` | F003, F034, F027 |
| 5 | `packages/ai-parrot/src/parrot/sdd/scripts/worker_notification.py` | `record_completion`, `_head`, `_receipt`, `handle_stop` | 110-120, 208-242, 244-286 | stdlib-only, sandbox-safe receipt bound to git HEAD, all-tasks-done precondition, one-shot host Stop hook | F004, F034 |
| 6 | `packages/ai-parrot/src/parrot/sdd/scripts/close_task.py` | `update_index`, `_emit_task_closed_inprocess` | 65-88, 129-144 | stamps feature `completed_at` on the last close; already appends `task.closed` from inside the sandbox | F005 |
| 7 | `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py` | `LedgerEventKind`, `LedgerEvent`, `compute_event_id`, `IssueAcknowledgedPayload` | 7-20, 59-70, 86-95, 103-122 | closed Literal of 12 kinds, content-addressed id, free-string actor, no signature | F006 |
| 8 | `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/shared_log.py` | `is_shareable`, `export_events`, `import_events` | 73-75, 144-167, 209-212 | local journal ↔ committed `sdd/ledger/events.jsonl`; new kinds shareable by default | F007, F019 |
| 9 | `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/outbox.py` | `verify_event_identity` | 106-110 | the only integrity check: `event_id` matches content | F006, F007 |
| 10 | `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py` | `LedgerService.acknowledge`, `merge_blockers` | 393-410, 465-494 | the one human-only decision (actor must start with `human:`); feature-scoped blocker query | F036 |
| 11 | `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/approvals.py` | `ApprovalEntry`, `GitCommitApprovalAdapter.verify` | 31-46, 96-125 | strongest precedent for a verified approval: trust through the recording commit | F008 |
| 12 | `packages/ai-parrot/src/parrot/knowledge/wiki/actor.py` | `current_actor`, `scoped_actor` | 19-37 | actor strings come from env/context, not a credential | F008 |
| 13 | `packages/ai-parrot/src/parrot/sdd/scripts/run_closeout_hooks.py` | `run_event`, `finalize`, `exit_code` | 168-236, 257-258, 280-286 | FEAT-764 dispatcher: exit 0/1/2/3; agent hooks pending → record → finalize | F009, F035 |
| 14 | `packages/ai-parrot/src/parrot/sdd/scripts/closeout_builtins.py` | `BUILTINS`, `telegram_send`, `push_send` | 166, 252, 300-314 | builtin registry + one-way human notification | F010 |
| 15 | `packages/ai-parrot/src/parrot/sdd/scripts/closeout_hooks_config.py` | `EVENTS`, `HookKind`, `HookSpec` | 1-60 | hooks are repo-opt-in TOML; escrow cannot rely on TOML alone | F035, F021 |
| 16 | `packages/ai-parrot/src/parrot/sdd/scripts/check_e2e_closeout.py` | module | — | FEAT-703 standalone gate script; template for the verdict gate | F035, F002 |
| 17 | `packages/ai-parrot/src/parrot/sdd/scripts/review_checkpoint.py` | `_checkpoint_summary`, `main` | 38-56, 84-87 | head-bound review checkpoint, exit 3 on stale; worker-written, so evidence not verdict | F011 |
| 18 | `packages/ai-parrot/src/parrot/sdd/launch_cli.py` | `worker` | 17-57 | host entry point → `feature_launcher.launch`; where `--escrow` and a sibling verdict session attach | F023 |
| 19 | `packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py` | `launch` | — | builds the sandbox/console and wires the notification env + Stop hook | F023 |
| 20 | `sdd/tasks/index/pageindex-generation-publication.json` | index header | 1-12 | the only feature-execution state (10 header keys incl. `completed_at`, three contract-style blocks) | F020, F013 |
| 21 | `sdd/templates/state.schema.json` | `SDDProposalState` | 1-5 | `sdd/state/<FEAT>/state.json` is proposal research state, closed schema | F012 |
| 22 | `packages/ai-parrot/src/parrot/sdd/scripts/worktree_status.py` | `dev_closed` | 482-514 | `/sdd-status` already derives "finished on dev" from `completed_at` | F025 |
| 23 | `packages/ai-parrot/src/parrot/human/manager.py` | `HumanInteractionManager.request_human_input` | 321 | in-process async HITL approval; no host CLI; channels dormant | F014, F037, F030 |
| 24 | `packages/ai-parrot/src/parrot/roost/carriers/bus.py` | `build_roost_bus` | 201-220 | the only bus in-repo (navigator_eventbus over Redis); unused by SDD scripts, unreachable from the sandbox | F038, F017 |
| 25 | `.claude/commands/pr-review.md` | `/pr-review` | 1-26 | post-PR, Jira-keyed review layer escrow must not duplicate | F024 |

### 2.2 Constraints Discovered

- **The gate is code; the exit code is the contract; no `--force` reaches an un-bypassable gate.** FEAT-703 and
  FEAT-764 set this as the house rule for `/sdd-done`. *Implication*: the verdict guard is a standalone check script run
  before §7; any human override is a separately recorded human-actor ledger event, never a flag that skips the gate.
  *Evidence*: F002, F021, F026, F035
- **Three twins + contract test.** Every `/sdd-done` gate change edits the Claude command, the Codex skill and the
  shipped asset, plus `tests/sdd_scripts/test_*_contract.py`; the worker prompt has two identical twins.
  *Evidence*: F026, F033, F034
- **Closed event kinds, content ids, self-declared actors, nothing signed.** `LedgerEventKind` is a Literal; `event_id`
  is a SHA-1 of the content; `actor` is a free string resolved from env. *Implication*: new kinds need the Literal,
  payload models and the index reducer; "signed" is a new mechanism. *Evidence*: F006, F008
- **The only human-gated decision is a string-prefix check.** `acknowledge` refuses non-`human:` actors — any process can
  satisfy it. *Implication*: separation of powers needs process separation and/or a host-only secret, not an actor
  string. *Evidence*: F036
- **The sandbox writes `.parrot/ledger` but cannot import `parrot` and has no network beyond `gh`.** `close_task`
  already emits `task.closed` from inside it through an override interpreter; the receipt helper is stdlib-only
  (`python -S`). *Implication*: `work.completed` can be emitted worker-side with the receipt pattern or host-side by
  the Stop hook. *Evidence*: F004, F005
- **There is no bus the SDD plane uses.** navigator_eventbus needs Redis and a server; Squawk has no pub/sub API.
  *Implication*: v1 transport is the ledger event log; Redis is at most a v2 host-side mirror.
  *Evidence*: F017, F018, F038, F031
- **Verdicts are events and travel eventually.** New kinds are shareable by default and ride the FEAT-694 hooks /
  FEAT-758 outbox, but another machine sees them only after commit + import; `issues.jsonl` is never the place.
  *Implication*: the guard reads the local journal and the committed log; same-host is immediate, cross-host eventual.
  *Evidence*: F007, F019, F039
- **No worker-owned `state.json` exists.** `sdd/state/<FEAT>/state.json` is proposal research state
  (`additionalProperties: false`); `.autopilot/state.json` is the autopilot tracker; the per-spec index header is the only
  execution state and is untyped JSON. *Implication*: AWAITING_VERDICT cannot land in an existing `state.json` (U1).
  *Evidence*: F012, F013, F020
- **Head-binding precedents exist.** The completion receipt re-validates HEAD on consumption; the review checkpoint
  exits 3 on `checkpoint_stale`. *Implication*: bind every verdict to `head_sha`; a verdict for another HEAD is stale.
  *Evidence*: F004, F011
- **"Done" is self-declared today.** `close_task` stamps the feature `completed_at`; the worker ends with "completed,
  run /sdd-done". *Implication*: these two moments become "work completed, awaiting verdict". *Evidence*: F005, F003
- **Review already exists twice.** The worker's code-reviewer (same lineage) and `/pr-review` (post-PR). *Implication*:
  escrow judges release readiness, not the diff. *Evidence*: F003, F024
- **Host-dispatched agents are launched by the session running `/sdd-done`.** *Implication*: a judge launched that way
  is separate from the worker, not from the operator — acceptable for v1, must be stated. *Evidence*: F009, F035
- **HITL is in-process and dormant.** `HumanInteractionManager` is async, server-side; Teams/Telegram channels untouched
  since 2026-06-01; `/sdd-done` has one-way `telegram.send` / `push.send`. *Implication*: v1 ESCALATE = notify + host
  CLI approve/reject. *Evidence*: F014, F037, F030, F010
- **HEAD moves inside `/sdd-done`.** §4.5 lint and §7 stamping commit on the feature branch. *Implication*: the guard
  runs before any closeout commit and compares against HEAD at gate time. *Evidence*: F002, F033

### 2.3 Recent History (Relevant)

| Commit | When | Author | Message | Touched |
|--------|------|--------|---------|---------|
| `0af88638ed` | 2026-10-19 | Jesus | TASK-4462 — rewire /sdd-done twins onto the code-enforced E2E gate ("enforcement is an invariant, not an instruction") | both sdd-done twins, `tests/sdd_scripts/test_e2e_closeout_contract.py` |
| `a6c7f56188` | 2026-10-28 | Jesus | TASK-4870 — wire closeout hooks into both sdd-done twins | both twins, `test_sdd_done_hooks_contract.py` |
| `fde39a8294` … `744c163179` | 2026-10-28 | Jesus | closeout hooks runner born, review-fixed, hardened | `run_closeout_hooks.py` |
| `a606cd1450` / `9976896626` | 2026-11-03/04 | Jesus Lara | FEAT-793 worker completion protocol (PR #1950) | `.claude/agents/sdd-worker.md`, `worker_notification.py` |
| `e4fff64f38` | 2026-11-03 | Jesus Lara | gh-only sandbox; `/sdd-done` is host-side | both worker/done twins |
| `e20d9b1ade` / `46270bd951` | 2026-10-22 | Jesus | FEAT-694 shared ledger log landed | `knowledge/wiki/ledger/` |
| `22a628adf5` … `3593d016d4` | 2026-10-28 | Jesus | FEAT-758 ledger outbox | `knowledge/wiki/ledger/` |
| `cd54e4b7d7` | 2026-11-03 | Jesus Lara | ledger close/unclaim respect the claimant | `ledger/service.py` |
| `c1b1327d7c` … | 2026-10-29/30 | Jesus | FEAT-746 Squawk landed with same-day review churn; nothing since | `packages/ai-parrot-squawk/` |
| `fc6448af80` | 2026-06-01 | Jesus | last commit on `parrot/human` channels (dormant) | `integrations/.../human/` |
| — | 365 days | — | **no** commit on any branch mentions escrow / `work.completed` / `awaiting_verdict`; "verdict" appears only in FEAT-709's fail-closed `--verdict` runner | — |

Evidence: F026, F027, F028, F029, F030, F031, F032.

---

## 3. Probable Scope

### What's New

- **Ledger event kinds** `work.completed`, `escrow.approved`, `escrow.rescheduled`, `escrow.escalated`,
  `escrow.human_decision`, with payload models carrying `feature_id`, `head_sha`, `launch_id`, `round`, `verdict_id`
  (and `corrections[]` on reschedule). Shareable, content-addressed. *Evidence*: F006, F007
- **`check_escrow_verdict` gate** (`parrot sdd escrow check --feature … --worktree …`): fixed exit-code contract, no
  force parameter; passes only when an `escrow.approved` for this feature and launch exists whose `head_sha` equals the
  worktree HEAD at gate time, and no later `work.completed` for a newer HEAD supersedes it. *Evidence*: F002, F035, F021
- **`Verdict` model** bound to `head_sha` (`APPROVED | RESCHEDULE | ESCALATE_HITL`), with deterministic release actions
  (emit event; on RESCHEDULE create child TASKs; on ESCALATE notify). *Evidence*: F011, F004
- **Host-side verdict runner and CLI** `parrot sdd escrow run | show | approve | reject`, plus a read-only judge agent
  `.claude/agents/sdd-escrow.md` (Codex twin) launched by the host after `work.completed`; `approve | reject` is the human
  fallback that records a `human:` `escrow.human_decision`. *Evidence*: F023, F036, F015, F016
- **`--escrow[=policy]`** on `parrot sdd launch worker`: deterministic opt-in per launch; records enablement + `launch_id`
  where the guard and `/sdd-status` read it and exports it to the worker env. *Evidence*: F023
- **Policy files** `sdd/escrow/<policy>.yaml`: gates first (tests, lint, scope-completeness, head integrity, review
  checkpoint present), experts optional. *Evidence*: F001

### What Changes

- **`.claude/agents/sdd-worker.md`::`## Completion`** (both twins) — the ending becomes: receipt → emit
  `work.completed` (head-bound) → print "held: awaiting verdict". The worker never prints "completed" nor instructs
  `/sdd-done`. *Evidence*: F003, F034
- **`worker_notification.py`::`record_completion` / `handle_stop`** — the receipt becomes the `work.completed` emission
  (stdlib JSON line with a stdlib-computed `event_id`, or a host-side append from the Stop hook). *Evidence*: F004, F005
- **`.claude/commands/sdd-done.md`** (+ Codex skill + shipped asset) — new step before §5/§7: run the gate; any non-zero
  → `write_hook_context` + `on_failure` + abort; no `--force` path; contract test. *Evidence*: F002, F033, F026
- **`ledger/events.py`::`LedgerEventKind`** + payloads; index reducer learns `verdict:` pages / `judges`,
  `rescheduled-to` edges via incremental sync. *Evidence*: F006, F039
- **`launch_cli.py`::`worker`** — `--escrow[=policy]`; `feature_launcher` writes enablement + `launch_id`.
  *Evidence*: F023
- **`worktree_status.py`::`dev_closed`** — derive `escrow: awaiting_verdict | approved @sha | rescheduled | escalated`
  for `/sdd-status`. *Evidence*: F025
- **`closeout_builtins.py`::`BUILTINS`** — optional `escrow.notify` reusing `telegram.send` / `push.send`.
  *Evidence*: F010

### What's Untouched (Non-Goals)

- `/pr-review` and the worker's own code-reviewer — the review layer is not duplicated.
- `close_task.py` `task.closed` semantics and per-task index stamping.
- `.parrot/sdd_hooks.toml` semantics — escrow is not a repo-opt-in hook; it is enforced whenever the launch enabled it.
- `sdd/ledger/issues.jsonl` and `check_ledger_snapshot` — verdicts are events, never snapshot rows.
- `HumanInteractionManager`, Teams/Telegram channels, Squawk, Roost, navigator_eventbus — v2 transports only.
- `sdd/state/<FEAT>/state.json` schema — stays proposal research state.

### Patterns to Follow

- FEAT-703: one script, twins branch solely on its exit code, contract test pins the doc surface. *Evidence*: F026, F035
- FEAT-764: pending → record → finalize for host-dispatched agent work; unrecorded pending = failure.
  *Evidence*: F009, F021
- `worker_notification` receipt: all-tasks-done precondition, 40-hex HEAD, atomic 0600 write, one-shot consumption.
  *Evidence*: F004
- `review_checkpoint`: facts resolved locally via git, never from a caller-supplied SHA; exit 3 on stale.
  *Evidence*: F011
- `LedgerService.acknowledge` (human-only decisions) and `GitCommitApprovalAdapter` (trust through the recording
  commit). *Evidence*: F036, F008
- FEAT-709 `--verdict` runners fail closed and honour a deadline. *Evidence*: F032

### Integration Risks

- **Verdict spoofing**: the worker can append `escrow.approved` with any actor to the journal it already writes
  `task.closed` to. *Impact*: separation of powers would be nominal. *Mitigation*: a host-only launch secret (not
  mounted in the sandbox) folded into the verdict's hash, or verification through a host-recorded artifact the sandbox
  cannot write — decision U2. *Evidence*: F008, F036, F005
- **Stale verdicts**: §4.5 lint reflows and §7 stamping commit during `/sdd-done`. *Mitigation*: gate before any
  closeout commit; compare against HEAD at gate time; re-run escrow on head move. *Evidence*: F002, F011
- **Eventual cross-machine visibility**. *Mitigation*: v1 same-host; guard reads local + committed logs; verdicts ride
  the outbox. *Evidence*: F019, F039, F007
- **Reducer / shareable filter** must learn the new kinds without the rebuild path. *Evidence*: F039, F007
- **Judge launched by the operator's session** (FEAT-764 shape). *Mitigation*: state it; v2 detached session or
  service. *Evidence*: F009, F035
- **HITL transport dormant**. *Mitigation*: v1 = notify builtins + `parrot sdd escrow approve|reject`.
  *Evidence*: F030, F010

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | No escrow, `work.completed` or AWAITING_VERDICT exists in code, config, commands or git history on any branch | F001, F032 | high | repo-wide grep and `git log --all` both empty |
| C2 | `/sdd-done` refuses in code at §4.6 and §4.8, neither force-able; §9 runs only under `--merge` and is force-able | F002, F033 | high | verbatim lines read |
| C3 | A new gate is a script whose exit code both twins obey, no force parameter, contract test; three twins change together | F026, F035, F021, F033 | high | commit file lists; FEAT-703/764 spec text |
| C4 | Completion is self-declared: `close_task` stamps `completed_at`, the worker self-reviews and prints "completed, run /sdd-done" | F003, F005, F034 | high | direct reads |
| C5 | `record_completion` is a head-bound, all-tasks-done, stdlib-only receipt consumed once by a host Stop hook | F004, F034 | high | function bodies read |
| C6 | `LedgerEventKind` is a closed Literal; `event_id` content-addressed; actor free string; nothing signed | F006, F008 | high | events.py read; hmac/attest grep empty |
| C7 | The ledger's only human-gated decision is `acknowledge` (prefix `human:`), satisfiable by any process | F036 | high | service.py 393-410 |
| C8 | `GitCommitApprovalAdapter` is the strongest precedent for a verified approval | F008 | medium | applicability to ledger events inferred |
| C9 | New kinds are shareable by default, cross-machine only once committed; a verdict must be an event | F007, F019, F039 | high | `is_shareable`; FEAT-694 G1-G4; FEAT-712 non-goal |
| C10 | No worker-owned `state.json`; execution state is only the untyped index header | F012, F013, F020 | high | grep + header read |
| C11 | The sandbox writes `.parrot/ledger` but cannot import `parrot` and has no network beyond `gh` | F005, F004, F038 | high | `close_task` 129-144; `python -S`; Roost needs Redis |
| C12 | The ledger log is the only viable v1 transport; navigator_eventbus optional v2; Squawk is not a bus | F017, F018, F038, F031 | high | greps across packages |
| C13 | A verdict needs head-SHA binding with stale detection, as receipt and review checkpoint do | F004, F011 | high | `_receipt`; exit codes |
| C14 | HITL approval exists only in-process; channels dormant; `/sdd-done` has one-way notify builtins | F014, F037, F030, F010 | high | lines + git log + BUILTINS |
| C15 | Natural hook points are `parrot sdd launch worker` and the FEAT-764 pending/record/finalize cycle | F023, F009, F035 | medium | entry points verified; choice is a design decision |
| C16 | Lint and stamping move HEAD during `/sdd-done`; the guard must run before any closeout commit | F002, F033 | medium | §7 commit read; §4.5 behaviour in the PR flow inferred |
| C17 | Review exists twice already; escrow's value is the held state + external release | F003, F024 | high | both surfaces read |
| C18 | The brainstorm's VERIFY items are resolved: ledger plane landed, header fields superset, HITL in core, fallback sink unnecessary | F028, F039, F020, F014 | high | history + reads |

Distribution: **15** high, **3** medium, **0** low.

---

## 5. Open Questions

### Resolved (during proposal phase)

_None — this run was unattended; the gates were auto-passed and Q&A skipped (see §7)._

### Unresolved (defer to spec)

- [ ] **U1 — Where does the held state live?** There is no worker `state.json` today (C10). — *Owner*: Jesus
  *Blocks claims*: C10, C15
  *Plausible answers*: a) **a projection of ledger events** (held = `work.completed` for HEAD without a later
  `escrow.approved` for the same HEAD), with only `escrow: {enabled, policy, launch_id}` written into the per-spec index
  header at launch — single source of truth, no dual write (recommended) · b) an `escrow` block in the index header
  mirrored on every verdict (brainstorm) · c) a new `sdd/state/<FEAT-ID>/escrow.json`.
- [ ] **U2 — What must "signed" mean in v1**, given no signatures exist and actors are self-declared (C6, C7)? —
  *Owner*: Jesus · *Blocks claims*: C6, C7, C8
  *Plausible answers*: a) process separation + a host-only launch secret folded into the verdict event (the sandbox
  cannot read it; the gate recomputes it) · b) `GitCommitApprovalAdapter`-style: the verdict must be committed on the
  ledger branch by a host process and the gate verifies the commit · c) actor-prefix convention only
  (`escrow:` / `human:`), spoofing accepted and documented.
- [ ] **U3 — Is there any human override of a missing or negative verdict in `/sdd-done`?** — *Owner*: Jesus
  *Blocks claims*: C3
  *Plausible answers*: a) no flag: the only release is a `human:` `escrow.human_decision=approve` recorded via
  `parrot sdd escrow approve --reason` (keeps "the gate takes no force parameter") · b) `--override-escrow "<reason>"`
  recording `escrow.overridden` (brainstorm) · c) no override at all; escalation resolves only through RESCHEDULE.
- [ ] **U4 — Who produces the v1 verdict?** The owner's framing suggests gates over diff re-reading. — *Owner*: Jesus
  *Blocks claims*: C15, C17
  *Plausible answers*: a) deterministic gates only in v1 (tests, lint, scope-completeness, head integrity, review
  checkpoint present); LLM experts are a policy opt-in · b) a read-only `.claude/agents/sdd-escrow.md` judge launched by
  the host after `work.completed` (FEAT-764 agent-hook shape) · c) an in-process `AgentRegistry` bot (brainstorm's
  `EscrowAgent`) — a different runtime from the SDD agents.
- [ ] **U5 — When escrow is not enabled for a launch**, does the worker keep today's ending, or always emit
  `work.completed` with `/sdd-done` enforcing only when enabled? — *Owner*: Jesus · *Blocks claims*: C4
  *Plausible answers*: a) always emit `work.completed`; enforce only when enabled (recommended, uniform audit trail) ·
  b) emit only when enabled; behaviour otherwise unchanged.

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-841`** — *Rationale*: localization is high-confidence (C1–C7, C9–C14) and the architectural fork was
already explored in `sdd-escrow.brainstorm.md` (Option B chosen by the owner); U1–U5 are policy decisions the spec's
Open Questions can settle, not alternatives needing another brainstorm. Overall confidence is medium only because the
scope hinges on U1 and U2.

### Alternatives

- **`/sdd-brainstorm FEAT-841`** — only if U2 (signing) or U4 (who judges) is answered in a way that reopens the
  runtime choice (in-process bot vs host-launched agent vs gates-only).
- **`/sdd-task FEAT-841`** — not suitable; this touches three `/sdd-done` twins, both worker twins, the ledger model and
  the launcher.
- **Manual review** — not needed; research was not truncated and no contradictions surfaced.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-841/state.json` |
| Source (raw) | `sdd/state/FEAT-841/source.md` |
| Research plan | `sdd/state/FEAT-841/research_plan.json` (48 queries) |
| Findings (digests) | `sdd/state/FEAT-841/findings/F001-*.md` … `F039-*.md` (lane originals in `findings/.audit/`) |
| Citation probe | `sdd/state/FEAT-841/findings/.audit/citation_probe.json` (221 checks, 0 stale, 9 adjudicated by read) |
| Synthesis (JSON) | `sdd/state/FEAT-841/synthesis.json` |
| Synthesis reasoning | `sdd/state/FEAT-841/synthesis.thinking.log` |

**Budget consumed** (default profile, three parallel lanes):
- Files read: 25 / 40
- Grep calls: 13 / 25
- Git calls: 10 / 10
- Wall time: ~591 s / 300 s per-lane cap not exceeded (longest lane 591 s including fork overhead)
- Truncated: **no** (all 48 planned queries executed; 44 lane findings merged into 39)

**Mode determination**: `auto` → resolved to `enrichment` (additive verbs; no broken behaviour).

**Gates**: the plan gate and the review gate were auto-passed because no operator was at the terminal; Phase 5 Q&A was
skipped for the same reason, so `status: discussion` and U1–U5 are unresolved.

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` (FEAT-708 parallel lanes) |
| Synthesis prompt | `sdd/templates/synthesis.prompt.md v1.0` |
| Plan prompt | `sdd/templates/research_plan.prompt.md v1.0` |
| Schema versions | state=1.0, synthesis=1.0, research_plan=1.0 |
| Operator | Jesus Lara (unattended run, drafted with Claude) |
