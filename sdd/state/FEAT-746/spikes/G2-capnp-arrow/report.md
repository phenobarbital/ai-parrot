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

| Criterion | Result | Evidence |
|---|---|---|
| Arrow frames stay within the configured 4 MiB limit | FAIL | The spike uses a 1 MiB operational ceiling and standalone Arrow IPC streams, but the loopback server cannot start in this sandbox. |
| Cancellation leaves valid partial data | FAIL | `Op.cancel()` and `Sink.done("PARTIAL")` are implemented, but the loopback server cannot start in this sandbox. |
| mTLS SAN and Hello token are available server-side | FAIL | The server parses the TLS peer certificate's `URI:squawk://external/caller` SAN, but no TLS connection can be made in this sandbox. |
| pycapnp cooperates with asyncio | FAIL | The server and client are implemented under the active asyncio loop inside `capnp.kj_loop()`, but the loopback listener is denied. |

## Amendment

**FAIL — gate evidence is unavailable in this execution environment.** The
required loopback bind fails before the server starts with
`PermissionError: [Errno 1] Operation not permitted`; the same result occurs
with a raw Python `socket.bind(("127.0.0.1", 0))` probe. The opt-in regression
skips only for that explicit sandbox restriction and otherwise fails normally.

Until an operator runs the reproduced command on a host that permits loopback
listeners, M3/M4 must use the specified gRPC fallback: retain the same
transport-neutral `Hello`, `Call`, `Result`, `Progress`, and `Error` message
set, map Arrow IPC data to opaque `bytes` fields, map `ProgressSink` to server
streaming, and map `Operation.cancel` to RPC cancellation. This is an
environmental gate failure, not evidence that pycapnp itself is incompatible.
