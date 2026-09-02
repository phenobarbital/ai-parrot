---
id: F005
query_id: Q005
type: read
intent: What the child does before it can answer its first frame (bootstrap cost)
executed_at: 2026-09-02T13:37:50+02:00
duration_ds: 800
parent_id: null
depth: 0
---

# F005 — worker.py: the child cannot answer any frame until the full parrot + pandas import and REPL bootstrap complete

## Summary

`main()` (290-337) parses argv, arms `PR_SET_PDEATHSIG`, applies rlimits, then calls `serve()`. `serve()` (250-287) constructs `WorkerNamespace` **before** entering the read loop; `WorkerNamespace.__init__` (138-157) does `from parrot.tools.pythonrepl import PythonREPLTool` (which drags in the whole `parrot` package init — navconfig, settings, tool registry — plus pandas/numpy) and instantiates `PythonREPLTool` (running its setup + bootstrap code). Only then is `repl_worker: ready` logged (275) and the first frame read (278). There is no "ready" frame sent to the host; the host has no way to know when this point is reached except by getting a reply.

## Citations

- path: `packages/ai-parrot/src/parrot/tools/repl_worker/worker.py`
  lines: 138-157
  symbol: `WorkerNamespace.__init__`
  excerpt: |
    # Local import: heavy (pandas/numpy) — must run AFTER rlimits are applied
    from parrot.tools.pythonrepl import PythonREPLTool
    self._tool = PythonREPLTool(report_dir=output_dir, sanitize_input_enabled=..., **(repl_kwargs or {}))
- path: `packages/ai-parrot/src/parrot/tools/repl_worker/worker.py`
  lines: 250-287
  symbol: `serve`
  excerpt: |
    namespace = WorkerNamespace(output_dir=output_dir, repl_kwargs=repl_kwargs)
    logger.info("repl_worker: ready (max_workers config=%s), entering service loop", config.max_workers)
    while True:
        message = read_frame(in_stream)
- path: `packages/ai-parrot/src/parrot/tools/repl_worker/worker.py`
  lines: 290-337
  symbol: `main`
  excerpt: |
    set_parent_death_signal()
    apply_rlimits(config)
    in_stream = os.fdopen(read_fd, "rb", buffering=0)
    out_stream = os.fdopen(write_fd, "wb", buffering=0)
    serve(config, in_stream, out_stream, output_dir=output_dir, repl_kwargs=repl_kwargs)
