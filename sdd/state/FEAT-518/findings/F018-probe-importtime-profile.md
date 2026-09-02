---
id: F018
query_id: Q017
type: read
intent: U3 follow-up — what dominates the worker's bootstrap import (local proxy for the affected host)
executed_at: 2026-09-02T14:05:00+02:00
duration_ms: 5000
parent_id: F015
depth: 1
---

# F018 — `python -X importtime`: the parrot framework init is ~80 % of worker bootstrap; pandas is ~16 %

## Summary

`from parrot.tools.pythonrepl import PythonREPLTool` = **1.41 s** cumulative (idle dev box, warm page cache). Breakdown (cumulative µs): `parrot.tools` package `__init__` 900 ms — of which `parrot.plugins` 583 ms → `navconfig.logging` 368 ms → `navconfig` 343 ms (env/vault/logstash setup); `parrot.security.redaction` 283 ms → `parrot.security.vault_utils` 272 ms → `parrot.interfaces.documentdb` 246 ms; `parrot.tools.abstract` 246 ms → `parrot.core.events.lifecycle` 217 ms + `parrot.conf` 214 ms → `parrot.models.google` 213 ms → `parrot.interfaces.file` 202 ms → `navigator` 200 ms → `navigator_auth` 189 ms → `navigator_eventbus` 184 ms. **`pandas` itself: 223 ms.** So the worker pays for navconfig, vault utilities, the DocumentDB interface, the events bus, Google model configs and the whole `navigator` auth stack — none of which the REPL child uses. On a host where navconfig/vault/logstash do network I/O at import, this part scales with latency, not CPU.

## Citations

- path: `packages/ai-parrot/src/parrot/tools/repl_worker/worker.py`
  lines: 144-146
  symbol: `WorkerNamespace.__init__` (the import measured)
  excerpt: |
    from parrot.tools.pythonrepl import PythonREPLTool
- path: `packages/ai-parrot/src/parrot/tools/__init__.py`
  symbol: package init (pulls `parrot.plugins` → `navconfig.logging`)
- path: `packages/ai-parrot/src/parrot/tools/abstract.py`
  symbol: module import (pulls `parrot.core.events.lifecycle`, `parrot.conf`)
- path: `packages/ai-parrot/src/parrot/security/redaction.py`
  symbol: module import (pulls `parrot.security.vault_utils` → `parrot.interfaces.documentdb`)

## Notes

Local proxy only — the affected host was not measured (U3 stays partially open: the spec should include a probe task that runs the same command there). Raw log kept in the session scratchpad.
