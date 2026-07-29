# F004 — The websocket-only coupling the source complains about

- **Query**: Q008/Q012 (wiki module summary `mod:parrot.flows.dev_loop.streaming`,
  file page `commands.py`, `examples/dev_loop/README.md`)
- **Citations**:
  - `packages/ai-parrot/src/parrot/flows/dev_loop/streaming.py::FlowStreamMultiplexer`
    — aiohttp WS fan-in over two Redis streams: `flow:{run_id}:flow` +
    `flow:{run_id}:dispatch:{node_id}`; emits flat JSON envelopes
    `{"source": "flow"|"dispatch", "node_id": ..., ...}`. Built for the
    nav-admin Svelte UI ("the UI never speaks Redis directly", spec G4).
    FEAT-322 added `view="state"` (snapshot + sequenced envelopes).
  - `packages/ai-parrot/src/parrot/flows/dev_loop/commands.py` — REST write
    side (FEAT-322): `POST /runs/{run_id}/gates/{gate_id}/resolve`,
    `POST /runs/{run_id}/cancel`; thin adapters over `DevLoopRunner`.
  - `examples/dev_loop/server.py` + `static/index.html` — the only current
    "UI": aiohttp server + vanilla-JS client; `quickstart.py` is a one-shot
    programmatic run with no interactivity.
- **Implication**: reads = WS (or in-process envelope sink), writes = REST
  (or direct runner methods). A CLI in *server mode* consumes exactly these
  two surfaces; in *embedded mode* it can subscribe to the SessionHost's
  `on_envelope` sink directly (see F002).
