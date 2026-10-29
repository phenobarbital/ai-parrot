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
  `capnp.AsyncIoStream.create_server(callback, host, port, ssl=ctx)`,
  `capnp.AsyncIoStream.create_connection(host, port, ssl=ctx, server_hostname=...)`,
  `capnp.TwoPartyServer(stream, bootstrap=impl)`, and
  `capnp.TwoPartyClient(stream).bootstrap().cast_as(SCHEMA.Spike)`.
- `capnp.run(coro)` is used by the command-line entry point and is documented
  by pycapnp as the shortcut that wraps a coroutine in `capnp.kj_loop()`.

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

Measured 2026-10-30 on loopback mTLS (Python 3.12.3, pycapnp 2.2.4, pyarrow 26.0.0),
`python sdd/state/FEAT-746/spikes/G2-capnp-arrow/spike.py 1500000`:

| Criterion | Result | Evidence |
|---|---|---|
| Arrow frames stay within the configured 4 MiB limit | PASS | Full run: 106 frames, max 1,048,512 B (1 MiB ceiling), 109,733,536 B at ~222 MiB/s; every frame is an independently readable Arrow IPC stream. |
| Cancellation leaves valid partial data | PASS | Cancel at frame 10 → `Sink.done("PARTIAL")`, 11 valid frames (11,083,752 B). |
| mTLS SAN and Hello token are available server-side | PASS | Server read peer SAN `squawk://external/caller` from the TLS transport; `hello` echoed the same SAN and the Hello token/agent id were observed. |
| pycapnp cooperates with asyncio | PASS | Server and client run on the stdlib asyncio loop inside `capnp.kj_loop()`; whole run 1.13 s wall, 485 MiB max RSS. |

`PARROT_SPIKE=1 pytest packages/ai-parrot-squawk/tests/spikes/test_g2_capnp_arrow.py` passes (cancel path, 80k rows).

### Why the first run reported FAIL

The earlier "loopback bind denied" verdict was produced in a sandbox that refused
binds; once binds were available three spike defects surfaced and were fixed:

1. `main()` called `capnp.run(...)`, which in pycapnp 2.2.4 returns an un-awaited
   coroutine (nothing ran); `run()` already enters `kj_loop()`, so `asyncio.run` is used.
2. `_peer_san` read `_AsyncIoStream.protocol`, a private (`cdef`) attribute. The server
   now builds the listener with `loop.create_server` and pycapnp's own
   `AsyncIoStream._connect` factory, keeping the protocol whose `transport` is
   `cdef public`, and reads the peer certificate from it.
3. Teardown closed the listener before the client connection; since Python 3.12
   `Server.wait_closed()` waits for open connections, so it hung. The client side is
   closed first now.

## Amendment

**PASS — Cap'n Proto RPC over mTLS with Arrow IPC framing meets G2.** No gRPC
fallback is needed (consistent with AC17: no `grpcio`). M3/M4 may build on
`pycapnp` with: a 1 MiB operational frame ceiling under the 4 MiB limit;
peer identity taken from the TLS transport of the connection's protocol (not a
private stream attribute); client-first teardown.
