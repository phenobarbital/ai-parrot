# F004 — FlowEventPublisher: per-event run_id resolution (brainstorm nuance)

**Query**: Q005 (read flow.py:60-140)
**File**: packages/ai-parrot/src/parrot/flows/dev_loop/flow.py

## Facts
- `FlowEventPublisher` (:71) publishes `flow.<event>` envelopes to
  `flow:{run_id}:flow` via XADD, `maxlen=10_000 approximate` (:113-118).
- **Run-id resolution is per-event from the context**: the engine passes
  the run's `FlowContext` in `info["context"]`; run_id read from
  `context.shared_data["run_id"]` (:97-99); the mutable holder dict is only
  a FALLBACK for unseeded contexts (:100-101). Docstring (:74-79) states
  concurrent runs on the same flow instance publish to their own streams.
- Every failure swallowed (`except Exception: pass`, :119-120) —
  "telemetry must never break the run". Lazy Redis (:122-128), `close()` (:130).
- Envelope shape: `{kind: "flow.<event>", ts, run_id, node_id, payload}`
  (:104-110); payload strips `flow`/`context` keys.
- Flow event names: `node_started`, `node_completed`, `node_failed`,
  `node_skipped` (matches brainstorm).

## Delta vs brainstorm
The brainstorm described run_id as holder-based. Current code is already
context-first (holder = fallback). The session-state shim must follow the
same pattern: resolve `SessionHost` per event by run_id (registry lookup),
NOT capture one host at publisher construction.
