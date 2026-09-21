---
id: FEAT-588
slug: fixgroup-47eb801095a6
title: "Make the sdd-coder retry ladder reachable for complex/unknown tasks"
type: feature
status: approved
base_branch: dev
created: 2026-09-21
revision: 0.3
source: "ledger issue:569e81756247 (bug, major) via /sdd-fix group fixgroup:47eb801095a6"
projects: [ai-parrot, dev-loop]
tags: [sdd-coder, retry, roster, complexity, FEAT-561, FEAT-559]
---

# FEAT-588 — Make the sdd-coder retry ladder reachable for complex/unknown tasks

## 1. Problem

A `complex`- or `unknown`-classified sdd-coder task that fails attempt 1 is
blocked with `complex_model_unavailable: no eligible retry seat for <TASK-ID>`
and never retries — even with a healthy strong seat idle.

The retry set is computed as

```
eligible(strong_models)  -  tried{attempt-1 seat}  -  {every native seat}
```

With the **shipped** roster
(`packages/ai-parrot/src/parrot/mcp/_toolkit_templates/sdd-coder.yaml:32-34`)
`strong_models` is exactly `{(codex, gpt-5.6-terra), (native, sonnet)}`. A task
that starts on `gpt-5.6-terra` therefore retries into
`{terra, sonnet} - {terra} - {sonnet} = {}` — **structurally empty on every
first-attempt failure**, for every complex/unknown task, in the default
configuration. This is not a capacity condition and no amount of waiting
changes it.

### Why the native seat is skipped

Both retry selectors exclude `kind == "native"` unconditionally:

| Selector | Location | Guard |
|---|---|---|
| `SddCoderEngine._select_retry_seat` (pool path) | `engine.py:3105-3110` and `engine.py:3136` | `if seat.kind == "native": continue` |
| `ChunkAssigner.retry_seat` (legacy path) | `roster.py:411` | `if candidate.label in excluded or candidate.kind == "native":` |

**The guards are correct and must not simply be deleted.** A native seat has no
dispatcher — it is a Claude Code `Agent` call that `sdd-worker` makes itself via
`coder_prepare_native` — so returning one from either selector lands on
`_run_attempt`'s first line, `assert seat.backend is not None`
(`engine.py:2590`), which raises *outside* that function's `try:` block and is
caught only by `run_chunk`'s outer `asyncio.gather(..., return_exceptions=True)`,
discarding attempt 1's `AttemptRecord` entirely. That is precisely the crash
TASK-3554 fixed.

The defect is the resulting **asymmetry**: a native strong seat is
dispatch-capable for attempt 1 (through `prepare_native`) but invisible to
attempt 2. TASK-3554 named closing that asymmetry as explicitly out of its own
scope and as "a known follow-up" — this feature is that follow-up.

### The "seat was busy" reading is wrong

`_select_retry_seat` returns `None` immediately in this case. Its
"any healthy-but-busy seat worth waiting for" loop (`engine.py:3129-3148`)
applies the *same* two filters (skip native, skip `tried_seats`), so no
candidate ever reaches the busy check and it never waits. The block reproduces
with every other seat idle, yet the diagnostic text sends operators hunting a
scheduling race that does not exist.

## 2. Goals / Non-goals

**Goals**

- G1 — A complex/unknown task whose only remaining eligible strong seat is
  `kind: native` gets a real attempt 2 on that seat, via the same
  `sdd-worker`-driven handoff `prepare_native` already provides for attempt 1.
- G2 — When the restricted retry set is non-empty but all-native and the
  handoff cannot be offered, the diagnostic says so, instead of the generic
  "no eligible retry seat" that reads as transient capacity.
- G3 — A roster that can never retry a complex task is reported at
  `coder_begin_execution`, not on first failure.
- G4 — The shipped template no longer ships exactly the reproducing roster.

**Non-goals**

- NG1 — Deleting either `kind == "native"` guard from the two selectors. Both
  stay; the native handoff is a *separate* return path, never a `RosterSeat`
  handed to `_run_attempt`. Re-introducing the TASK-3554 crash is the single
  biggest risk in this feature.
- NG2 — Making native retry available on the **legacy** (`pool is None`)
  path. `ChunkAssigner.retry_seat` returns `Optional[RosterSeat]` and has no
  channel for a handoff; the pool path is what every real
  `coder_plan`/`coder_run_chunk` call uses.
- NG3 — Changing `eligible_seats()`'s strong-model restriction or
  `_eligible_retry_labels`'s fail-closed behaviour (both TASK-3554, both
  correct).
- NG4 — Fixing `issue:e7bdce192812` (the `google_coding` schema-path bug) to
  restore a third strong MCP seat. Related and separately filed; a config
  mitigation is not a fix for this defect, as §1 shows.

## 3. Design

### Module 1 — Native retry handoff (the core change)

`_run_task`'s retry branch (`engine.py:3217-3253`) currently binds
`retry: Optional[RosterSeat]` and, when it is `None` and `eligible_labels is not
None`, writes the `complex_model_unavailable` diagnostic.

Introduce a third outcome between "got an MCP seat" and "blocked": **a native
handoff**. `_select_retry_seat` keeps returning only MCP seats (NG1); a new,
separate helper answers the narrower question *"is there an untried, healthy,
eligible native seat?"* and `_run_task` consumes it only after
`_select_retry_seat` has returned `None`.

The handoff is surfaced on `TaskResult` as a new optional field carrying a
`NativePrep`-shaped reservation, under the **already-declared**
`TaskOutcome` member `"retry_native"` (`models.py:37`). The engine never runs
the attempt itself.

**`retry_native` is a reserved name with no implementation.** FEAT-549's spec
(`sdd/specs/sdd-worker-subagents.spec.md:296`) and TASK-3115 both put it in the
`TaskOutcome` literal, but a repo-wide search finds **no producer, no consumer,
and no test** — `models.py:37` is its only occurrence in `packages/`. So this
feature implements the outcome the original design reserved for exactly this
case; it does not invent a new one, and `TaskOutcome` itself needs no edit.
This is also what makes Q1's "distinct outcome" cheap: the distinction was
always intended.

**Constraint discovered during research — `prepare_native` cannot be reused
as-is.** It raises `task_not_in_plan` when `not planned.native`
(`engine.py:1762-1764`), and a task that reached retry was by definition planned
onto an MCP seat, so `planned.native` is `False`. The reservation path must
either take an explicit override or be factored so the worktree/branch/
attempt-uid allocation is shared without the `planned.native` precondition.
Branch naming must keep the existing `<feature_branch>--<TASK-NNN>-a<N>[-<exechex>]`
shape with `attempt=2`.

Pool bookkeeping must stay consistent: the native seat's identity is admitted
through the execution pool before the worktree is created (as `prepare_native`
does today), the seat is marked tried, and attempt 1's `AttemptRecord` is
preserved and emitted exactly as the current code does before a retry.

### Module 2 — Honest diagnostics (G2)

When `eligible_labels` is non-empty, `_select_retry_seat` returned `None`, and
every remaining eligible-untried seat is `kind == "native"` **and** no handoff
could be offered, the message must name the real cause — the retry ladder being
MCP-only — rather than "no eligible retry seat". Keep the
`complex_model_unavailable` error code (callers match on it) and keep attempt
1's own error appended as today.

### Module 3 — Roster warning at execution start (G3)

`coder_begin_execution` should report a roster whose `complexity.strong_models`
resolves to fewer than two *retry-capable* seats, since such a roster cannot
retry any complex task. `ExecutionPoolView` is `extra="forbid"`
(`models.py`), so this is a deliberate additive field (e.g.
`roster_warnings: List[str] = []`) — not an ad-hoc dict key. The warning is
advisory: it never blocks the execution.

### Module 4 — Shipped template (G4)

`packages/ai-parrot/src/parrot/mcp/_toolkit_templates/sdd-coder.yaml` ships
exactly the reproducing roster. Add a second strong **MCP** seat to
`roster` + `complexity.strong_models`, mirroring the operator mitigation
already applied in `.parrot/mcp-toolkits.yaml:106,114` (`gpt-5.6-luna`, backend
`codex`), with a comment explaining the two-MCP-strong-seat requirement.

Note this is defence in depth, not the fix: with Module 1 landed, a
single-MCP-strong-seat roster retries onto the native seat instead of blocking.

## 4. Acceptance criteria

- **AC-1** — A complex/unknown task that fails attempt 1 on the only MCP strong
  seat, with a healthy untried native strong seat present, produces a native
  handoff rather than `complex_model_unavailable`.
- **AC-2** — That handoff carries a valid reservation: attempt 2 branch/worktree
  under the feature's pool, `seat_label` of the native seat, the task's
  `assessment_id`, and the owning `execution_id`.
- **AC-3** — Attempt 1's `AttemptRecord` is preserved in `TaskResult.attempts`
  and its `failed` outcome is emitted exactly once, as it is for an MCP retry.
- **AC-4** — `_run_attempt` is never called with a `kind == "native"` seat. A
  regression test asserts both `_select_retry_seat` and
  `ChunkAssigner.retry_seat` still never return one (TASK-3554, NG1).
- **AC-5** — With no eligible untried seat of any kind, behaviour is unchanged:
  `complex_model_unavailable`, attempt 1 preserved, no crash.
- **AC-6** — When the remaining eligible-untried set is all-native and no
  handoff can be offered, the diagnostic names the MCP-only retry ladder; the
  error code stays `complex_model_unavailable`.
- **AC-7** — `coder_begin_execution` reports a roster with fewer than two
  retry-capable strong seats, and does not block the execution.
- **AC-8** — The shipped template resolves to at least two strong MCP seats.
- **AC-9** — The legacy (`pool is None`) path is unchanged (NG2).
- **AC-10** — `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/ -q`
  passes; `ruff check` and `black --check` clean on every changed file.

## 5. Codebase Contract (anti-hallucination)

Verified against `dev` @ `46948f3ea`+ (post-FEAT-587) on 2026-09-21. **Line
numbers in `issue:569e81756247` are stale** — `engine.py` grew by ~600 lines
after it was filed. Use these:

| Symbol | Location | Note |
|---|---|---|
| `SddCoderEngine._select_retry_seat` | `engine.py:3059` | native guard at `:3105-3110` (search loop) and `:3136` (busy-wait loop) |
| `_run_task` retry branch | `engine.py:3217-3253` | `no_retry_error` at `:3233` |
| `SddCoderEngine._eligible_retry_labels` | `engine.py:1659` | fail-closed `set()` on missing assessment (TASK-3554) — do not change |
| `SddCoderEngine._run_attempt` | `assert` at `engine.py:2590` | the crash site; MCP-only by contract |
| `SddCoderEngine.prepare_native` | `engine.py:1745` | raises `task_not_in_plan` when `not planned.native` (`:1762-1764`) |
| `SddCoderEngine.begin_execution` | `engine.py` (`async def begin_execution`) | Module 3 target |
| `eligible_seats` | `roster.py:241` | strong-model filter; `backend = "native" if seat.kind == "native"` at `:277` |
| `ChunkAssigner.retry_seat` | `roster.py:386` | native guard at `:411` |
| `NativePrep` | `models.py:360` | fields incl. `attempt_uid`, `assessment_id`, `execution_id`, `bg_handle` |
| `TaskResult` | `models.py` (`class TaskResult`) | Module 1 surface |
| `TaskOutcome` | `models.py:30-39` | `"retry_native"` at `:37` — **declared, never produced/consumed/tested**; implement it, do not rename |
| `ExecutionPoolView` | `models.py` | `model_config = ConfigDict(extra="forbid")` |
| Shipped template | `packages/ai-parrot/src/parrot/mcp/_toolkit_templates/sdd-coder.yaml:22-34` | 1 MCP strong seat + 1 native |
| Operator mitigation | `.parrot/mcp-toolkits.yaml:96,106,114` | gitignored, per-machine — not a fix |

**Tests to extend** (do not create parallel files):
`packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py`
(class `TestComplexityDispatchAdmission`, which already holds
`test_no_eligible_retry_seat_reports_complex_model_unavailable`) and
`test_roster.py`.

**Does NOT exist / do not grep for it**: `packages/ai-parrot/build/` holds a
stale pre-FEAT-587 copy of `engine.py`; the
`feat-FEAT-584-sdd-execution-optimization--pool/` worktrees hold pre-`ed267c217`
code. Neither is the source of truth.

## 6. Risks

- **R1 (high)** — Re-introducing the TASK-3554 crash by letting a native seat
  reach `_run_attempt`. Mitigated by NG1 + AC-4.
- **R2** — Double-emitting attempt 1's outcome, or losing it, on the new path.
  `_run_task` returns exactly one `TaskResult`; AC-3 pins this.
- **R3** — Pool accounting drift (seat admitted but never released, or a
  reservation created for a task already holding one). `prepare_native`'s
  existing duplicate-call reuse is the behaviour to mirror.
- **R4** — `sdd-worker` must actually route the new handoff; an unrouted field
  is a silent no-op that looks fixed in tests. The orchestrator side is in
  scope.

## 7. Related

- `issue:e01c03baf493` — open, same subsystem, not in this group (empty
  `about` prevents the planner from connecting them). Consider together.
- `issue:e7bdce192812` — `google_coding` schema path; blocks a third strong MCP
  seat. Separate (NG4).
- TASK-3554 (`sdd/tasks/completed/`) — added both native guards; named this
  work as its follow-up.
- FEAT-561 `sdd/specs/complex-sdd-tasks.spec.md` — the strong-model allowlist.
- FEAT-587 — retired `dirty_task_worktree`, removing one *cause* of attempt-1
  failure. It does not affect this defect: the retry set is empty regardless of
  why attempt 1 failed.

## 8. Open questions — RESOLVED

Both resolved by Jesus on 2026-09-21, before decomposition. Each confirmed the
spec's stated assumption; no design change followed.

- **Q1 — RESOLVED: distinct.** The native retry handoff gets its own outcome,
  separate from the routing `sdd-worker` already uses for a *planned* native
  attempt 1, so telemetry can distinguish "planned native" from "retried onto
  native". Module 1 and AC-1/AC-2 assume this; the orchestrator must route the
  new outcome (R4). Realized by the pre-declared, never-implemented
  `TaskOutcome` member `"retry_native"` (`models.py:37`) — see §3 Module 1.
- **Q2 — RESOLVED: yes.** Module 3's warning also fires when `strong_models`
  is empty — a roster in which *every* complex/unknown task blocks at
  admission is the most extreme case of the condition the warning exists to
  report, and reporting it at `coder_begin_execution` is strictly better than
  discovering it per task. Same advisory channel, same non-blocking contract
  (AC-7).

## 9. Design Research Cross-Check

Status: skipped (spec authored directly from a ledger issue by `/sdd-fix`; no
brainstorm or proposal artifact exists for this group).
