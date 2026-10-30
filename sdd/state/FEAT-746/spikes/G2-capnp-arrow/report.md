# G2 — Arrow IPC over Cap'n Proto RPC

## Scope

This spike exercises a pandas frame carried as independent Arrow IPC streams over
loopback mTLS Cap'n Proto RPC. It also exercises a client-supplied `Sink`
capability, a returned `Op` cancellation capability, and the `Hello` identity
path used by M3/M4.

## Environment and API surface

- pycapnp: `2.2.4` (the satellite pin is `pycapnp>=2.2.4`)
- pyarrow: `26.0.0`; pandas: `3.0.6`; cryptography: `50.0.2`
- Exact pycapnp API: `async with capnp.kj_loop()`,
  `loop.create_server(factory, host, port, ssl=ctx)` with a factory around
  `capnp.AsyncIoStream._connect(callback)` (see "Spike fixes"),
  `capnp.AsyncIoStream.create_connection(host, port, ssl=ctx, server_hostname=...)`,
  `capnp.TwoPartyServer(stream, bootstrap=impl)`, and
  `capnp.TwoPartyClient(stream).bootstrap().cast_as(SCHEMA.Spike)`.
- The command-line entry point drives `run()` with `asyncio.run`; `run()` enters
  `capnp.kj_loop()` itself (the context manager `capnp.run(coro)` wraps).

## Reproduction

```bash
PARROT_SPIKE=1 pytest packages/ai-parrot-squawk/tests/spikes/test_g2_capnp_arrow.py -q
python sdd/state/FEAT-746/spikes/G2-capnp-arrow/spike.py 1500000
```

The regression uses 80,000 rows (roughly 5 MiB raw numeric payload). The full
run uses 1,500,000 rows (roughly 100 MiB in eight float64 columns before IPC
overhead). The program prints frame count, largest frame, bytes received, and
throughput in MiB/s for both a complete and a cancelled run.

## Criteria

Measured 2026-10-30 on a developer host that permits loopback listeners
(issue:60de633baac2 rerun), pycapnp 2.2.4 / pyarrow 26.0.0 / pandas 3.1.0 /
cryptography 50.0.2, Python 3.12, three full runs. Raw output:
`results.json`.

| Criterion | Result | Evidence |
|---|---|---|
| ~100 MB frame streams in frames within the 4 MiB limit | PASS | 1,500,000 rows → 106 frames, 109,733,536 bytes; largest frame 1,048,512 bytes (≤ the 1 MiB operational ceiling, well under 4 MiB); every frame opens as a standalone Arrow IPC stream. Identical on all three runs. |
| Cancellation leaves valid partial data | PASS | `Op.cancel()` at frame 10 → `Sink.done("PARTIAL")` after 11 frames (11,083,752 bytes), all independently readable. Identical on all three runs; the opt-in regression (`cancel_at_frame=1`, 80k rows) passes. |
| mTLS SAN and Hello token available server-side | PASS | Server read `squawk://external/caller` from the client certificate's URI SAN and observed the `Hello` token on every run; `Hello` echoed the SAN back. |
| pycapnp cooperates with asyncio | PASS | Server, client, client-supplied `Sink` callbacks and the returned `Op` capability all run on one asyncio loop inside `capnp.kj_loop()` (what `capnp.run()` wraps). |

Throughput: 118 / 172 / 146 MiB/s for the full stream. The timer also covers
generating the three RSA-2048 certificates and building the 1.5M-row frame, so
it is a lower bound on transport throughput, not a tuned benchmark.

## Spike fixes needed to run at all

The first version had never executed past the sandboxed bind, and three bugs
surfaced on a real host — each one is relevant to M3/M4:

1. **The TLS peer certificate is not reachable from `AsyncIoStream`.** In
   pycapnp 2.2.4 `AsyncIoStream.protocol` is a private `cdef` attribute, so
   `stream.protocol.transport` raises `AttributeError`. The fix builds the
   listener with `loop.create_server(protocol_factory, ssl=...)`, where the
   factory calls `capnp.AsyncIoStream._connect(callback)` (exactly what
   `AsyncIoStream.create_server` does) and keeps the protocol so the callback
   can read `protocol.transport.get_extra_info("ssl_object")`. `_connect` is a
   private pycapnp API: M4 must pin pycapnp and cover this path with a test.
2. **Shutdown order deadlocks on Python ≥ 3.12.** `Server.wait_closed()` waits
   for every accepted connection, so awaiting it before closing the client
   stream hangs forever (and swallowed the 30 s `done` timeout). Close the
   client stream first, then the listener, with a bounded `wait_closed`.
3. **`capnp.run()` is a coroutine.** `main()` called it synchronously and
   printed coroutine objects; it now uses `asyncio.run(run(...))`, which enters
   `capnp.kj_loop()` itself.

A server-side `Sink.done` reply that lands after the client has disconnected
logs `KjException: Peer disconnected`; it is harmless for the measurement but
M4's producer must treat a disconnect after `done` as normal.

## Amendment

**PASS — Cap'n Proto RPC stays the native transport for M3/M4; the gRPC
fallback is not triggered.** The PARTIAL-era prescription (M3/M4 on gRPC opaque
bytes) is withdrawn. M4 inherits three requirements from the fixes above: read
mTLS identity through a protocol factory around `AsyncIoStream._connect` (pin
`pycapnp` and test it, since it is private API), close client streams before
awaiting `Server.wait_closed()`, and tolerate a peer disconnect after a
terminal `Sink.done`.
