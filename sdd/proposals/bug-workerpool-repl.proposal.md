---
id: FEAT-518
title: PythonREPL WorkerPool death spiral — cold workers SIGKILLed by the 5 s namespace-API timeout
slug: bug-workerpool-repl
type: hotfix
mode: investigation
status: discussion
source:
  kind: inline
  jira_key: null
  jira_url: null
  fetched_at: 2026-09-02
  summary_oneline: PythonREPL WorkerPool death spiral — every python_repl_pandas call fails after 5s with an empty ValueError and the worker is restarted
overall_confidence: high
base_branch: main
research_state: sdd/state/FEAT-518/
created: 2026-09-02
updated: 2026-09-02
---

# FEAT-518 — PythonREPL WorkerPool death spiral: cold workers SIGKILLed by the 5 s namespace-API timeout

> **Mode**: investigation
> **Confidence**: high (root cause reproduced on `dev`)
> **Source**: `inline` (`/sdd-proposal bug-workerpool-repl -- …`, server log excerpt from the `flex_dashboard` bot, 2026-09-02 13:33–13:34)
> **Audit**: [`sdd/state/FEAT-518/`](../state/FEAT-518/)
> **Type / base**: `hotfix` on `main` is *proposed* (the released code is affected, F013) — see U1. If the user prefers a feature flow, flip `type: feature` / `base_branch: dev` in this frontmatter before `/sdd-spec`.

---

## 0. Origin

Full log excerpt preserved at `sdd/state/FEAT-518/source.md`. Representative slice:

> ```
> [WARNING] 13:34:15,209 parrot.tools.repl_worker.pool(pool.py:241) :: WorkerPool: session 'pythonrepl-2fd6…' worker is dead, restarting
> [DEBUG]   13:34:15,209 parrot.tools.repl_worker.pool(pool.py:265) :: WorkerPool: session 'pythonrepl-2fd6…' bound to a prewarmed worker
> [DEBUG]   13:34:15,210 parrot.tools.repl_worker.handle(handle.py:187) :: WorkerHandle: spawned worker pid=70860
> [DEBUG]   13:34:15,210 parrot.tools.repl_worker.pool(pool.py:187) :: WorkerPool: prewarmed worker ready (pool size=2)
> [ERROR]   13:34:20,213 python_repl_pandas.Tool(pythonrepl.py:960) :: Error executing Python code: 
> [WARNING] 13:34:20,213 parrot.tools.repl_worker.pool(pool.py:241) :: WorkerPool: session 'pythonrepl-2fd6…' worker is dead, restarting
> …
> [NOTICE]  13:34:25,217 :: 📤 Raw Result Type: <class 'ValueError'>
> ```
> "agents using PythonREPL were not able to use it, dying every time they called"

**Initial signals** (extracted, not interpreted):
- Verbs: "is dying", "worker is dead, restarting", "not able to use it", "failed" → bug.
- Named entities: `WorkerPool` / `pool.py:187/241/265`, `WorkerHandle` / `handle.py:187`, `pythonrepl.py:945/960`, tool `python_repl_pandas`, `flex_dashboard` bot, `GoogleGenAIClient`, `manager.py:1864`, `base.py:1504`.
- Hard signals: every failure sits on an exact **5.0 s grid**; every error message is **empty**; `prewarmed worker ready` is logged in the **same millisecond** as `spawned worker pid=`.
- Acceptance criteria provided: no.

---

## 1. Synthesis Summary

`python_repl_pandas` is `PythonPandasTool`, which seeds every freshly bound worker with its `df_locals` through the namespace API before sending the caller's code. Those namespace calls (`WorkerHandle.set_var` / `get_var` / `list_vars`) carry a **hard-coded 5.0 s timeout**, and `WorkerHandle._send` **SIGKILLs the worker on any timeout** and re-raises a bare `TimeoutError` (whose `str()` is empty). Neither `WorkerHandle.start()` nor `WorkerPool._top_up_prewarmed()` waits for the child to finish its bootstrap (full `parrot` package init + pandas/numpy import + `PythonREPLTool` setup, ≈2.4 s idle and 12–14 s under CPU contention), so a "prewarmed" spare is often still booting when it is bound. On a host where bootstrap exceeds 5 s, the first seeding call kills the worker, `WorkerPool.acquire` binds the next spare — spawned only one cycle earlier — and the loop repeats forever: a self-sustaining death spiral in which no worker ever lives long enough to become ready. Reproduced on `dev` with the report's exact log lines (F016). Recommended fix direction: make readiness explicit (a bootstrap handshake reusing the existing, unused `WorkerHandle.ping`), give namespace calls a sane budget, and stop treating a namespace-call timeout on a booting worker as a hang — then spec it with `/sdd-spec FEAT-518`.

---

## 2. Codebase Findings

> All entries are grounded in `sdd/state/FEAT-518/findings/`. **No fabricated paths or symbols.**

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `packages/ai-parrot/src/parrot/tools/repl_worker/handle.py` | `WorkerHandle._send` | 240-263 | request gate; on `asyncio.wait_for` timeout → SIGKILL worker + re-raise bare `TimeoutError` | F004 |
| 2 | `packages/ai-parrot/src/parrot/tools/repl_worker/handle.py` | `get_var` / `set_var` / `list_vars` | 405-419 | namespace API, **hard-coded `5.0` s**, no error handling (`execute` = 60.25 s, `inject_dataframe` = 30 s, `ping` = 10 s) | F004 |
| 3 | `packages/ai-parrot/src/parrot/tools/repl_worker/handle.py` | `WorkerHandle.start` | 154-197 | `Popen` then return — no readiness handshake | F004 |
| 4 | `packages/ai-parrot/src/parrot/tools/repl_worker/handle.py` | `WorkerHandle.ping` | 431-449 | 10 s health check whose docstring already acknowledges multi-second bootstrap; **zero callers** | F004, F014 |
| 5 | `packages/ai-parrot/src/parrot/tools/repl_worker/pool.py` | `WorkerPool._top_up_prewarmed` | 166-187 | appends the spare and logs `prewarmed worker ready` right after spawn | F003 |
| 6 | `packages/ai-parrot/src/parrot/tools/repl_worker/pool.py` | `WorkerPool.acquire` | 231-268 | crash-restart: `is_alive` is the only health signal; binds the **oldest** spare (`pop(0)`) | F003 |
| 7 | `packages/ai-parrot/src/parrot/tools/repl_worker/worker.py` | `WorkerNamespace.__init__` / `serve` | 138-157, 250-287 | child imports `parrot.tools.pythonrepl` + builds `PythonREPLTool` before reading its first frame; sends no "ready" frame | F005 |
| 8 | `packages/ai-parrot/src/parrot/tools/pythonpandas.py` | `PythonPandasTool._get_worker_handle` | 137-181 | re-seeds `df_locals` into every new handle identity: DataFrames via `inject_dataframe` (30 s), scalars via `set_var` (5 s), **set-iteration order** | F009, F016 |
| 9 | `packages/ai-parrot/src/parrot/tools/pythonpandas.py` | `PythonPandasTool._process_dataframes` | 505-522 | 4 scalar metadata entries per DataFrame name and per alias → the `set_var` seeding load | F009 |
| 10 | `packages/ai-parrot/src/parrot/tools/pythonpandas.py` | `PythonPandasTool._execute` | 939-995 | `list_vars` before and `list_vars`/`get_var` after each run, in `try/except` — swallowed, but each timeout already killed the worker | F010 |
| 11 | `packages/ai-parrot/src/parrot/tools/pythonrepl.py` | `PythonREPLTool._execute` | 944-962 | log sites `:945` / `:960`; any escaping exception → `{status:'error', error:str(e)}` | F006 |
| 12 | `packages/ai-parrot/src/parrot/clients/base.py` | tool wrapper | 1495-1506 | `raise ValueError(result.error)` → the reported empty `ValueError` | F007 |
| 13 | `packages/ai-parrot/src/parrot/tools/repl_worker/protocol.py` | `WorkerConfig` | 326-341 | `deadline_ms=60000`, `prewarm_pool_size=2`; **no** namespace-timeout / bootstrap-grace field | F011 |

### 2.2 Constraints Discovered

- **Timeouts are not configurable.** The 5.0 s lives in `handle.py`, not in `WorkerConfig`. *Implication*: no deployment knob mitigates this; the fix is code. *Evidence*: F004, F011
- **Every timeout is lethal.** `_send` kills the process on timeout regardless of request type, then raises `TimeoutError` with an empty message. *Implication*: the fix must decide whether namespace timeouts stay lethal (U2) and must give the error a message either way. *Evidence*: F004, F017
- **Seeding precedes the caller's request.** `PythonPandasTool` pushes all of `df_locals` on every new handle; iteration is over a `set`, so whether a scalar (5 s) or a DataFrame (30 s) hits the cold worker first is hash-dependent. *Implication*: fix the shared layer, do not reorder seeding as a "fix". *Evidence*: F009, F016
- **G5 contract.** `execute()` never raises — it returns the loss dict with `lost_variables`. A namespace-timeout kill bypasses that contract entirely (exception with blank text, no lost-variables list). *Implication*: route this failure into the same G5 shape. *Evidence*: F004, F006
- **Shared callers.** `PandasAgent` (`bots/data.py`), working-memory wiring (`bots/agent.py:251`), and `tools/agent.py` also call the 5 s namespace API. *Implication*: fix in `handle.py` / `pool.py`, not in `PythonPandasTool` alone. *Evidence*: F008
- **Bootstrap cost.** ≈2.4 s idle (1.74 s is `import parrot.tools.pythonrepl`), 12–14 s under 3× CPU oversubscription; the default pool boots 3 workers at once per tool instance. *Implication*: 5 s is inside normal production variance and the spare pool worsens contention. *Evidence*: F015, F016
- **Existing awareness, partial.** `test_e2e_runaway_loop_recovery` documents that `deadline_ms` must cover cold-start bootstrap; the same reasoning was never applied to the namespace API, and `ping()` was written but never wired. *Evidence*: F014

### 2.3 Recent History (Relevant)

| Commit | When | Author | Message | Touched |
|--------|------|--------|---------|---------|
| `f2c34cb44` | 2026-08-20 | Jesus | fix(security): resolve 121 CodeQL alerts | `pythonrepl.py` |
| `486bb24bc` | 2026-08-16 | Jesus | TASK-2220 — REPL worker & config cleanup | `repl_worker/` |
| `8008233a8` | 2026-08-16 | Jesus | TASK-2218 — remove matplotlib/seaborn from PythonREPLTool | `pythonrepl.py`, `pythonpandas.py` |
| `c7b512a90` | 2026-07-28 | Jesus Lara | code-review sweep Modules 1-8 (drain task, executor, `_classify_death`) | all three |
| `d6a836e40` | 2026-07-28 | Jesus Lara | TASK-1944 — port `.locals`/`.globals` call sites to namespace API (introduces seeding) | `pythonpandas.py` |
| `c84a3c161` / `c4520041e` | 2026-07-27 | Jesus Lara | TASK-1942 WorkerPool / TASK-1941 WorkerHandle | `pool.py`, `handle.py` |

No change on these paths in the 13 days before the incident; `origin/main` is byte-identical to `dev` on all three files (F012, F013). **Not a regression — a latent cold-start race exposed by host load.**

---

## 3. Hypothesis

### Hypothesis 1 — Cold worker killed by the 5 s seeding call; the pool then feeds it the next, equally cold spare  · Confidence: **high**

**Supporting evidence**: F003, F004, F005, F009, F010, F016, F017
**Contradicting evidence**: —
**Reasoning**: The sequence per tool call is fully explained and was reproduced line-for-line (F016 Probe B):

1. `PythonPandasTool._execute` → `list_vars()` (pre-exec audit) → `_get_worker_handle` → `pool.acquire` → new handle → seeding `set_var(...)` with 5 s budget → worker still importing → **timeout → SIGKILL → `TimeoutError('')`** → swallowed by `except Exception: pre_keys = set()`. *(5 s)*
2. `super()._execute` logs `:945` → acquire → `worker is dead, restarting` (`pool.py:241`) → `bound to a prewarmed worker` (`:265`, spawned 5 s ago, still booting) → top-up spawns another and logs `prewarmed worker ready` (`:187`) → seeding `set_var` → **timeout → SIGKILL → `TimeoutError('')`** → `:960` logs a blank message → returns `{'status':'error','result':'ToolError: TimeoutError: ','error':''}`. *(5 s)*
3. Post-exec audit `list_vars()` → same again, swallowed. *(5 s)* → `AbstractTool.execute` builds `ToolResult(error='')` → `AbstractClient` raises `ValueError('')` → `manager.py:1864`, `base.py:1504`, `client.py:1961` all log blank → `Raw Result Type: <class 'ValueError'>`.

Each cycle consumes the oldest spare (`pop(0)`), which is exactly the one spawned during the previous cycle, so while bootstrap > 5 s **no worker ever reaches `repl_worker: ready`**. Under load the reproduction also showed the escape hatch: the spiral ends only if a spare happens to finish booting before it is consumed (14 s in Probe B).

**Suggested next probe** (on the affected host):
```bash
# 1. Measure real bootstrap there
python -X importtime -c "from parrot.tools.pythonrepl import PythonREPLTool" 2>&1 | sort -t'|' -k2 -n | tail -15
# 2. Watch spawn -> ready in the drain logs for one session id
grep -E "spawned worker pid=|repl_worker: ready|worker is dead" server.log | grep <session-id>
```

### Hypothesis 2 — The first death of the reported session had another trigger; the spiral is the failed recovery  · Confidence: medium

**Supporting**: F003, F011 · **Contradicting**: — · **Reasoning**: the excerpt starts mid-spiral. An idle-TTL eviction (30 min), a 60 s `deadline_ms` kill, or a memory crash could have killed worker #1. Irrelevant to the fix: recovery is broken regardless, and on a slow host the first-ever use enters the spiral directly (Probe B).
**Next probe**: search the full log for the first `worker is dead` / `evicting idle session` / `REPL worker terminated (` for that session id.

### Hypothesis 3 — Production bootstrap is slow because each worker re-runs the whole `parrot` package init  · Confidence: medium

**Supporting**: F005, F015, F016 · **Reasoning**: 1.95 s just to reach `STARTING APP: Navigator` on an idle dev box; navconfig/vault/logstash init and the tool-registry import all run in every child. Trimming the worker's import surface is a worthwhile secondary task but not the fix.

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | No readiness check in `start()` / `_top_up_prewarmed()`; spare marked ready in the same ms it is spawned | F003, F004 | high | direct read; matches the same-ms log pair in the report |
| C2 | Namespace API = hard-coded 5.0 s; `_send` SIGKILLs on timeout | F004 | high | direct read `handle.py:255-263, 407, 412, 417` |
| C3 | `PythonPandasTool` re-seeds `df_locals` on every new handle, before the caller's request | F009 | high | direct read `pythonpandas.py:169-181` |
| C4 | Blank error text = `str(TimeoutError()) == ''` propagated via `:960` → `ToolResult.error` → `ValueError(result.error)` | F006, F007, F017 | high | every hop read; verified on 3.12 |
| C5 | The report's signature is reproducible on `dev` (scalar seeded into a cold worker under load) | F016 | high | Probe B matches line numbers, cadence, text, dict |
| C6 | Survival depends on `df_locals` set-iteration order (DataFrame first = 30 s, scalar first = 5 s) | F009, F016 | high | Probe A vs B |
| C7 | Bootstrap ≈2.4 s idle, 12–14 s under 3× oversubscription (dev box) | F015, F016 | high | measured from the worker's own `ready` log |
| C8 | Production bootstrap exceeded 5 s during the incident | F016, F017 | medium | inferred — no other in-repo explanation for 5 s + blank; host unmeasured |
| C9 | Not a regression; code unchanged since 2026-08-20 and identical on `main` | F012, F013 | high | git log / diff |
| C10 | `ping()` is unused; no cold-worker namespace test exists | F014 | high | grep over src + tests |
| C11 | The session's *first* worker death was the same cold-start timeout | F003 | low | report begins mid-spiral |

Distribution: **9** high, **1** medium, **1** low.

---

## 5. Open Questions

### Resolved (during proposal phase)

*(none — autonomous session, no interactive Q&A gate)*

### Unresolved (defer to spec / implementation)

- [ ] **U1 — Hotfix on `main` or feature on `dev`?** — *Owner*: user
  *Blocks claims*: C9 (base branch choice only)
  *Plausible answers*: a) **hotfix, base `main`, sync-down to `staging`/`dev`** (proposed — production agents are unusable) · b) feature flow on `dev`
- [ ] **U2 — Should a namespace-API timeout on an alive worker stay lethal?** — *Owner*: user / spec
  *Blocks claims*: C2 (fix shape)
  *Plausible answers*: a) keep lethal, but only *after* readiness is confirmed (a post-ready timeout then means a real hang) · b) make namespace timeouts non-lethal; only the `execute()` deadline kills · c) raise namespace timeouts to `deadline_ms` and keep lethal
- [ ] **U3 — What is spawn→ready on the affected host, and what dominates?** — *Owner*: user (needs host access)
  *Blocks claims*: C8
  *Plausible answers*: a) > 5 s from `parrot` package init (navconfig/vault/logstash) → also trim the worker import surface · b) > 5 s from CPU contention → handshake alone suffices · c) < 5 s normally, incident was a load spike

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-518`** — *Rationale*: root cause is reproduced and localized (C1–C6 high); what remains are bounded design decisions, not an architectural fork. The spec should cover, at minimum:

1. **Readiness handshake** — `WorkerHandle.start()` (or `WorkerPool._spawn_handle`) waits for the worker to answer (`ping()` exists, 10 s, unused) or the worker writes an explicit `ready` frame after `WorkerNamespace` is built; spares are appended to `_prewarmed` only once ready; `acquire()` never binds a not-yet-ready spare (or awaits its readiness, bounded).
2. **Namespace-API budget** — replace the hard-coded `5.0` with a `WorkerConfig` field (and/or derive from `deadline_ms`), so operators have a knob; consider a `bootstrap_timeout_ms`.
3. **Timeout semantics** (U2) — decide lethal vs soft for non-exec requests; whichever is chosen, the error must carry a message and, if the worker is killed, the G5 loss dict (`lost_variables`) must be produced instead of a bare `TimeoutError('')`.
4. **Spiral breaker** — `acquire()` should prefer the *readiest* spare (not `pop(0)`), and a session that has failed N consecutive cold-start cycles should surface a clear error instead of burning spares.
5. **Regression test** — turn Probe B (F016) into a deterministic test: a worker whose bootstrap is artificially delayed beyond the namespace timeout must still serve `set_var` + `execute` successfully.
6. **Secondary** (H3) — measure and trim the worker's import surface (`-X importtime`), since every spawn re-runs the full `parrot` package init.

### Alternatives

- **`/sdd-brainstorm FEAT-518`** — if you want to compare readiness-handshake designs (ping-poll vs explicit `ready` frame vs event-fd) or revisit the spare-pool model itself.
- **`/sdd-task FEAT-518`** — *not recommended*: the fix touches three modules and one protocol contract; a single task would under-specify U2.
- **Manual review** — not needed; research was not truncated.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-518/state.json` |
| Source (raw) | `sdd/state/FEAT-518/source.md` |
| Research plan | `sdd/state/FEAT-518/research_plan.json` |
| Findings (digests) | `sdd/state/FEAT-518/findings/F001-*.md` … `F017-*.md` |
| Synthesis (JSON) | `sdd/state/FEAT-518/synthesis.json` |
| Synthesis reasoning | `sdd/state/FEAT-518/synthesis.thinking.log` |

**Budget consumed** (profile `default`):
- Files read: 13 / 40
- Grep calls: 15 / 25
- Git calls: 4 / 10
- Wiki calls: 2 (free)
- Local probes: 3 (idle baseline, loaded + DataFrame seeding, loaded + scalar seeding)
- Wall time: ≈480 s / 300 s (exceeded by the load probes; research was otherwise complete — not truncated)
- Truncated: **no**

**Mode determination**: `auto` → `investigation` (negations: "dying", "dead", "not able", "failed").

**Gates**: the session ran autonomously; the plan gate and review gate were auto-approved (equivalent to `--no-gate`) and the Q&A phase was skipped — U1–U3 are left for the user in §5.

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` |
| Synthesis prompt | `sdd/templates/synthesis.prompt.md v1.0` |
| Plan prompt | `sdd/templates/research_plan.prompt.md v1.0` |
| Schema versions | state=1.0, synthesis=1.0, research_plan=1.0 |
| Operator | Jesus Lara (via Claude Code, autonomous session) |
