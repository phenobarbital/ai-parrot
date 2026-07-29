# F003 — DevLoopRunner: the natural AHP "host"

**Query**: Q004 (read runner.py, full 322 lines)
**File**: packages/ai-parrot/src/parrot/flows/dev_loop/runner.py

## Facts
- `DevLoopRunner` (:100) hosts runs behind `asyncio.Semaphore(FLOW_MAX_CONCURRENT_RUNS)` (:126, conf at :124).
- Run identity: `run()` mints `run-<uuid8>` (:177), `run_revision()` mints
  `rev-<uuid8>` (:245). Externally-minted ids accepted.
- Introspection surface already exists: `active_runs` property (:143),
  `is_active(run_id)` (:147) — the seed of an AHP root-channel session
  catalogue (`listSessions` ≅ `active_runs`).
- `run()` seeds `shared_data` with `bug_brief`/`work_brief`/`run_id` (:178-182)
  and sets `flow._run_id_holder["run_id"]` before `run_flow(ctx)` (:194-196).
- `run_revision()` (:211) builds the revision flow lazily once (`_rev_flow`,
  :248-256), synthesizes `ResearchOutput` + `WorkBrief` with a lint-only
  ShellCriterion (:263-283), seeds `mode: "revision"` shared state (:284-297).
- Optional deps (dispatcher, jira/git toolkits, redis_url,
  codereview_dispatcher) kept on the runner (:131-135) — legacy
  `DevLoopRunner(flow)` construction still works.
- `build_dev_loop_revision_flow` (:45) shows the flow-building pattern:
  definition → factories → materialize → explicit edges, publisher attached
  via `AgentsFlow(on_node_event=publisher)` (:82).

## Constraint discovered (single shared flow, concurrent runs)
Both `run()` and `run_revision()` reuse ONE `AgentsFlow` instance across
concurrent runs; per-run identity is carried by `ctx.shared_data["run_id"]`
(and the holder dict only as fallback — see F004). Therefore a per-run
`SessionHost` CANNOT be attached to the flow or publisher as a single
reference — the shim must resolve the host **by run_id** through a registry
owned by the runner (`Dict[run_id, SessionHost]`), mirroring how the
publisher already resolves the stream key per event.
