# FEAT-500 — REPL worker bootstrap profile (baseline + host procedure)

**Feature**: FEAT-500 — REPL Worker Readiness Handshake & Non-Lethal Namespace Timeouts
**Spec**: `sdd/specs/bug-workerpool-repl.spec.md` (§3 Module 7, G7, AC10)
**Open question**: U3b — *measure spawn→ready and `-X importtime` on the
affected host*. Owner: Jesus Lara (needs host access). Non-blocking for
FEAT-500; the numbers feed the **follow-up import-trim spec** (a declared
Non-Goal here).
**Sources**: research findings
`sdd/state/FEAT-518/findings/F015-probe-baseline-unloaded.md`,
`F016-probe-death-spiral-under-load.md`,
`F018-probe-importtime-profile.md`.

This file is the baseline the import-trim follow-up starts from. It is a
measurement log, not documentation — the user-facing docs live in
[`docs/repl-worker-sandbox.md`](../../docs/repl-worker-sandbox.md)
("Measuring worker bootstrap on your host").

---

## 1. Why this matters

The worker's bootstrap cost *is* the FEAT-500 bug's precondition. While
`WorkerHandle.start()` had no readiness handshake and every namespace request
had a hard-coded 5 s budget, any host where bootstrap exceeded 5 s put the
pool into a permanent restart loop (see `F016`). FEAT-500 removes the
5 s cliff (readiness is awaited, non-exec timeouts are non-lethal and
configurable), so a slow bootstrap is now merely *slow* rather than *fatal* —
but it is still worth ~2.4 s per cold worker, and ~80 % of it is framework
init the REPL child never uses.

---

## 2. Local baseline — import profile (F018)

Command (idle 12-core dev box, warm page cache):

```bash
python -X importtime -c "from parrot.tools.pythonrepl import PythonREPLTool" 2> importtime.log
sort -t'|' -k2 -n importtime.log | tail -25
```

**Total: 1.41 s cumulative** for the single import `WorkerNamespace.__init__`
performs.

| Cumulative | Chain | Note |
|---|---|---|
| **0.90 s** | `parrot.tools` package `__init__` | the dominant cost |
| 0.58 s | └ `parrot.plugins` → `navconfig.logging` (0.37 s) → `navconfig` (0.34 s) | env / vault / logstash setup |
| **0.28 s** | `parrot.security.redaction` → `parrot.security.vault_utils` (0.27 s) → `parrot.interfaces.documentdb` (0.25 s) | vault + DocumentDB interface |
| **0.25 s** | `parrot.tools.abstract` → `parrot.core.events.lifecycle` (0.22 s) + `parrot.conf` (0.21 s) → `parrot.models.google` (0.21 s) → `parrot.interfaces.file` (0.20 s) → `navigator` (0.20 s) → `navigator_auth` (0.19 s) → `navigator_eventbus` (0.18 s) | the whole navigator auth stack |
| **0.22 s** | `pandas` | ~16 % of the total |

**Conclusion (F018)**: ≈80 % of the worker's import cost is `parrot` framework
init — navconfig, vault utilities, the DocumentDB interface, the events bus,
Google model configs and the `navigator` auth stack — **none of which the REPL
child process uses**. Only ~16 % is pandas, the thing the worker actually
needs. On a host where navconfig/vault/logstash perform network I/O at import
time, this share scales with *latency*, not CPU.

## 3. Local baseline — spawn→ready timings (F015 / F016)

| Condition | spawn → `repl_worker: ready` | Source |
|---|---|---|
| Idle 12-core host, 1 session + 2 prewarmed spares booting concurrently | **≈2.4 s** | F015 |
| Same host under ~3× CPU oversubscription | **12–14 s** | F016 |

F015 timeline detail (idle): spawn `13:40:02.761` → `STARTING APP: Navigator`
`13:40:04.71` (≈1.95 s just to reach the parrot package init) → `repl_worker:
ready` `13:40:05.20`. Bare import alone measured 1.74 s wall.

**This is why `bootstrap_timeout_ms` defaults to 30 000 and must not be
lowered casually** (spec §7 "Prewarm contention"): the loaded-host figure is
already 12–14 s, and it is per-worker with three workers booting concurrently
per tool instance.

---

## 4. Affected host — TO BE FILLED IN (U3b)

Run these on the host that showed the incident and paste the output below.
Nothing in FEAT-500 waits on this; it scopes the follow-up import-trim spec.

### 4a. Import profile

```bash
# In the same venv/env the server runs under:
python -X importtime -c "from parrot.tools.pythonrepl import PythonREPLTool" 2> importtime.log
sort -t'|' -k2 -n importtime.log | tail -25
```

| Cumulative | Chain | Note |
|---|---|---|
| _(paste)_ | | |

Total: _(paste)_

### 4b. Real spawn→ready, from the running server's logs

`WorkerHandle` logs the spawn at DEBUG and the worker logs its own readiness;
since FEAT-500 the ready line also carries the measured `bootstrap_ms`, and
the host logs it per prewarmed spare.

```bash
grep -E "spawned worker pid=|repl_worker: ready|prewarmed worker ready|worker is dead|possible restart loop" server.log
```

Expected healthy shape (one spawn, one ready, no restarts):

```
WorkerHandle: spawned worker pid=81228
repl_worker: ready in 2412 ms (max_workers config=0), entering service loop
WorkerPool: prewarmed worker ready (pid=81228, bootstrap_ms=2412, pool size=1)
```

| Measurement | Value |
|---|---|
| spawn → ready, idle | _(paste)_ |
| spawn → ready, under production load | _(paste)_ |
| `bootstrap_ms` range observed | _(paste)_ |
| any `possible restart loop` warnings? | _(paste)_ |

### 4c. Host context

| Item | Value |
|---|---|
| CPU cores / load average at measurement | _(paste)_ |
| navconfig / vault / logstash reachable at import? (network I/O) | _(paste)_ |
| Cold or warm page cache | _(paste)_ |

---

## 5. Follow-up

Trimming the worker's import surface is an explicit **Non-Goal of FEAT-500**
(spec §1): it touches package `__init__` layering across `parrot.tools`,
`parrot.security` and `parrot.conf` and deserves its own spec. The target
suggested by §2 above is to make
`parrot.tools.repl_worker.worker` reach `PythonREPLTool` without dragging in
`parrot.plugins` → `navconfig.logging`, `parrot.security.redaction` → vault →
documentdb, or `parrot.tools.abstract` → events/conf → `navigator` auth.
Ceiling if all of it were removed: ~0.22 s (pandas) + interpreter start,
versus 1.41 s today.
