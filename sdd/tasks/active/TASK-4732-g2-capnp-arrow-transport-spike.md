# TASK-4732: G2 — Arrow IPC over Cap'n Proto RPC spike (cancellation, PARTIAL, mTLS identity)

**Feature**: FEAT-746 — Squawk: typed binary inter-agent protocol
**Spec**: `sdd/specs/inter-agent-protocol.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4737
**Assigned-to**: unassigned

---

## Context

Spec §3 gate **G2 — S2 Arrow over Cap'n Proto RPC**, a **hard v0 gate** (Q6, S2). The native transport decision (Cap'n Proto RPC via `pycapnp`) has no precedent in this repo; before M3/M4 are decomposed, this spike must prove that a 100 MB pandas frame streams as Arrow IPC batches over `pycapnp` asyncio RPC with mTLS, that a client cancel mid-stream leaves a `PARTIAL` whose received batches are all valid, and that the peer identity (TLS SAN + a `Hello` token) is available server-side. On FAIL the amendment switches M3/M4 to the gRPC fallback with opaque `bytes` fields in the same message set (spec §7 risk 1).

---

## Scope

- Implement `sdd/state/FEAT-746/spikes/G2-capnp-arrow/spike.capnp` (a minimal `interface Spike { hello; stream }` + `interface Sink { frame; done }` + `interface Op { cancel }`) and `spike.py` (server + client in one process over loopback TLS, self-signed CA generated at runtime with `cryptography`).
- Stream a 100 MB frame as Arrow IPC stream frames ≤ 4 MiB each; count frames, measure throughput; cancel at ~40 % and assert every received frame reassembles into a valid `pyarrow.Table`.
- Record whether `capnp.AsyncIoStream.create_server(..., ssl=ctx)` exposes the peer certificate (SAN `URI:squawk://<network>/<agent>`), and whether `capnp.run()` cooperates with an existing asyncio loop.
- Write `report.md` with PASS/FAIL per criterion and the amendment (Cap'n Proto confirmed, or gRPC fallback with the exact message-set mapping).
- Ship `packages/ai-parrot-squawk/tests/spikes/test_g2_capnp_arrow.py` (opt-in `PARROT_SPIKE=1`; runs a 5 MB variant end-to-end over loopback).

**NOT in scope**: the production schema `squawk.capnp` (M3), `SquawkServer`/`SquawkClient` (M4), any gRPC code (only a written fallback mapping if G2 fails).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `sdd/state/FEAT-746/spikes/G2-capnp-arrow/spike.capnp` | CREATE | Minimal spike schema |
| `sdd/state/FEAT-746/spikes/G2-capnp-arrow/spike.py` | CREATE | Loopback mTLS server+client, streaming, cancel |
| `sdd/state/FEAT-746/spikes/G2-capnp-arrow/report.md` | CREATE | Gate report + amendment |
| `packages/ai-parrot-squawk/tests/spikes/test_g2_capnp_arrow.py` | CREATE | Opt-in 5 MB regression |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import capnp                     # pycapnp>=2.2.4 — declared by TASK-4737 in packages/ai-parrot-squawk/pyproject.toml; NOT installed in the shared venv until the operator syncs
import pyarrow as pa, pyarrow.ipc  # core dependency (packages/ai-parrot/pyproject.toml:180)
import pandas as pd
from cryptography import x509     # transitive dependency of navigator-auth; declared by TASK-4737 for the satellite
from parrot.tools.repl_worker.transport import encode_dataframe, StrictTransportError   # verified: packages/ai-parrot/src/parrot/tools/repl_worker/transport.py:83, :46 (strict Arrow IPC rules to mirror)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/repl_worker/transport.py:83
def encode_dataframe(df, ...) -> EncodedDataFrame   # Arrow IPC stream, strict no-pickle — copy its conversion rules, do not call it for the wire (it targets shared memory)
```

### Does NOT Exist
- ~~`parrot.squawk.schema.squawk.capnp`~~, ~~`parrot.squawk.transport.rpc_server`~~ — M3/M4 are gated on this spike.
- ~~`grpcio` in the satellite pyproject~~ — never add it here; a FAIL verdict only *documents* the fallback.
- ~~`capnp` in the shared `.venv`~~ — if `import capnp` fails, the operator must sync the workspace (`uv sync`) from the main checkout; never `pip install` from the worktree.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "sdd/state/FEAT-746/spikes/G2-capnp-arrow/spike.capnp", "action": "CREATE"},
    {"path": "sdd/state/FEAT-746/spikes/G2-capnp-arrow/spike.py", "action": "CREATE"},
    {"path": "sdd/state/FEAT-746/spikes/G2-capnp-arrow/report.md", "action": "CREATE"},
    {"path": "packages/ai-parrot-squawk/tests/spikes/test_g2_capnp_arrow.py", "action": "CREATE"}
  ],
  "contract_symbols": ["sym:packages/ai-parrot/src/parrot/tools/repl_worker/transport.py#encode_dataframe"]
}
```

---

## Implementation Notes

### Key Constraints
- pycapnp 2.x asyncio API: `capnp.load(path)`, `capnp.AsyncIoStream.create_connection(host, port, ssl=ctx)`, `capnp.AsyncIoStream.create_server(callback, host, port, ssl=ctx)`, `capnp.TwoPartyClient(stream)`, `capnp.TwoPartyServer(stream, bootstrap=impl)`, run under `async with capnp.kj_loop():` (2.x) — verify the exact names against the installed version's `help(capnp)` and record them in the report; do not guess.
- Streaming shape: the client passes a `Sink` capability to `stream()`; the server calls `sink.frame(bytes)` per Arrow frame and `sink.done(status)`; the server returns an `Op` capability whose `cancel()` sets an `asyncio.Event` the producer checks between frames — this is exactly the M3 design (`ProgressSink` / `Operation`), so the spike validates it.
- Cancellation semantic (spec AC09): after `cancel`, the server stops emitting and calls `done("PARTIAL")`; the client reassembles the received frames with `pa.ipc.open_stream` per frame and asserts each is a valid batch.
- Exclusive task: opens loopback ports.

### References in Codebase
- `packages/ai-parrot/src/parrot/tools/repl_worker/transport.py:83-167` — strict Arrow conversion rules.
- `sdd/state/FEAT-571/spikes/` — report layout.

---

## Implementation Blueprint

### Steps (in order)
1. Write `spike.capnp` — *why*: fixes the three-interface shape M3 will generalize.
2. Write `spike.py`: `make_certs(tmp)`, `frames_from_df(df, max_bytes)`, `SpikeImpl` (server), `run_client(cancel_at)`, `main()` printing a JSON summary — *why*: each criterion maps to one function so FAIL is attributable.
3. Run with 100 MB, cancel at 40 %; capture the peer cert on the server side — *why*: those are the three pass criteria.
4. Write the report and the amendment — *why*: G2's output is a go/no-go for M3/M4.

### `sdd/state/FEAT-746/spikes/G2-capnp-arrow/spike.capnp` (CREATE)
```capnp
@0xd4f6a2c1b3e5f701;
interface Sink { frame @0 (data :Data, index :UInt32) -> (); done @1 (status :Text) -> (); }
interface Op { cancel @0 () -> (); }
interface Spike {
  hello @0 (agentId :Text, token :Data) -> (sessionId :Text, peerSan :Text);
  stream @1 (rows :UInt32, maxFrameBytes :UInt32, sink :Sink) -> (op :Op);
}
```

### `sdd/state/FEAT-746/spikes/G2-capnp-arrow/spike.py` (CREATE)
```python
"""G2 — 100 MB pandas frame as Arrow IPC frames over pycapnp RPC with mTLS, cancel → PARTIAL (FEAT-746)."""
from __future__ import annotations

import asyncio
import json
import ssl
import sys
import time
from pathlib import Path
from typing import Iterator

import capnp
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.ipc

SCHEMA = capnp.load(str(Path(__file__).with_name("spike.capnp")))
MAX_FRAME = 4 * 1024 * 1024


def make_certs(tmp: Path) -> tuple[ssl.SSLContext, ssl.SSLContext]:
    """Self-signed CA + server + client certs; client SAN URI squawk://external/caller."""
    # FILL IN: cryptography x509 builder — bounded by: CA signs both; client cert carries the SAN URI; server ctx requires client cert
    raise NotImplementedError


def frames_from_df(df: pd.DataFrame, max_bytes: int) -> Iterator[bytes]:
    """Arrow IPC *stream* frames, each a self-contained stream of one or more batches ≤ max_bytes."""
    table = pa.Table.from_pandas(df, preserve_index=False)
    # FILL IN: slice `table` into row ranges whose serialized size ≤ max_bytes; yield pa.ipc serialized bytes per slice — bounded by MAX_FRAME
    raise NotImplementedError


class OpImpl(SCHEMA.Op.Server):
    def __init__(self, cancel: asyncio.Event) -> None:
        self._cancel = cancel

    async def cancel(self, **kwargs):
        self._cancel.set()


class SpikeImpl(SCHEMA.Spike.Server):
    def __init__(self, peer_san: str) -> None:
        self._peer_san = peer_san

    async def hello(self, agentId, token, **kwargs):
        return "sess-1", self._peer_san

    async def stream(self, rows, maxFrameBytes, sink, **kwargs):
        cancel = asyncio.Event()
        df = build_frame(rows)

        async def produce() -> None:
            status = "OK"
            for i, frame in enumerate(frames_from_df(df, maxFrameBytes)):
                if cancel.is_set():
                    status = "PARTIAL"
                    break
                await sink.frame(data=frame, index=i)
            await sink.done(status=status)

        asyncio.ensure_future(produce())
        return OpImpl(cancel)


def build_frame(rows: int) -> pd.DataFrame:
    rng = np.random.default_rng(746)
    return pd.DataFrame({f"c{i}": rng.random(rows) for i in range(8)} | {"label": rng.choice(["a", "b", "c"], rows)})


async def run(rows: int, cancel_at_frame: int | None) -> dict:
    """Start server + client on loopback; return the measurements dict."""
    # FILL IN: create_server/create_connection with the ssl contexts; peer SAN read from the server-side transport's ssl object;
    # client Sink impl collects frames and calls op.cancel() when index == cancel_at_frame; reassemble with pa.ipc.open_stream per frame
    # — bounded by: every received frame must parse; status must be "PARTIAL" when cancelled, "OK" otherwise
    raise NotImplementedError


def main() -> int:
    rows = int(sys.argv[1]) if len(sys.argv) > 1 else 1_500_000  # ≈100 MB with 8 float64 columns
    out = {"full": asyncio.run(run(rows, None)), "cancelled": asyncio.run(run(rows, 10))}
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```
**Why this shape**: `Sink`/`Op` mirror the spec's `ProgressSink`/`Operation` (§3 M3), so a PASS validates the production design and a FAIL localizes which capnp feature is missing. mTLS + token in `hello` validates the M10 identity path.

### `packages/ai-parrot-squawk/tests/spikes/test_g2_capnp_arrow.py` (CREATE)
```python
"""G2 regression — 5 MB variant over loopback (opt-in)."""
from __future__ import annotations

import asyncio
import importlib.util
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("PARROT_SPIKE") != "1", reason="spike: set PARROT_SPIKE=1")
pytest.importorskip("capnp")
SPIKE = Path(__file__).resolve().parents[4] / "sdd/state/FEAT-746/spikes/G2-capnp-arrow/spike.py"


def _load():
    spec = importlib.util.spec_from_file_location("g2_spike", SPIKE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_cancel_leaves_valid_partial():
    g2 = _load()
    out = asyncio.run(g2.run(80_000, cancel_at_frame=1))
    assert out["status"] == "PARTIAL" and out["frames_valid"] is True
```

### FILL IN checklist
- [ ] `spike.py::make_certs` — cert generation; bounded by mTLS required + SAN URI on the client cert
- [ ] `spike.py::frames_from_df` — slicing; bounded by MAX_FRAME per frame
- [ ] `spike.py::run` — wiring + measurements; bounded by the three pass criteria
- [ ] `report.md` — PASS/FAIL per criterion and the amendment (Cap'n Proto confirmed | gRPC opaque-bytes fallback mapping)

---

## Acceptance Criteria

- [ ] 100 MB frame streams in ≤ 4 MiB frames; throughput and frame count recorded
- [ ] Cancel mid-stream ⇒ `done("PARTIAL")` and every received frame reassembles (AC09 evidence)
- [ ] Peer SAN and `hello` token observed server-side (M10 evidence)
- [ ] `report.md` names the exact pycapnp API used (version pinned) and carries the amendment
- [ ] `PARROT_SPIKE=1 pytest packages/ai-parrot-squawk/tests/spikes/test_g2_capnp_arrow.py -q` passes (or the report explains the FAIL and the fallback)

---

## Validation Commands

- `pytest packages/ai-parrot-squawk/tests/spikes/test_g2_capnp_arrow.py -q`

---

## Test Specification

See the blueprint test; skipped by default, `importorskip("capnp")` guards environments without the satellite synced.

---

## Agent Instructions

1. **Work in the feature worktree** (`python -m scripts.sdd.ensure_worktree --slug inter-agent-protocol --feature-id FEAT-746`)
2. **Read the spec** §2 Overview (transport), §3 G2/M3/M4, §7 risk "Cap'n Proto RPC in Python"
3. **Check dependencies** — TASK-4737 `"done"`; `python -c "import capnp"` works in the shared venv (ask the operator to `uv sync` otherwise — never install from the worktree)
4. **Verify the Codebase Contract**
5. **Update status** in the index → `"in-progress"`, commit only the index
6. **Implement** from the blueprint
7. **Verify** — run the Validation Commands with `PARROT_SPIKE=1`
8. **Commit the code** — only the listed files
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4732 inter-agent-protocol verified`
10. **Completion Note** — quote the verdict and the amendment verbatim; a FAIL is a valid, complete outcome

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
