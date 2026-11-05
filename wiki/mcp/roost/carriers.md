# Roost carriers

Roost has four carriers (`CarrierKind`): `in_process`, `same_host`, `network` and `matrix`. They all implement
`parrot.roost.carriers.base.Carrier` (`send`, `subscribe`, `unsubscribe`, `close`).

| Carrier | Use | Payload rule |
|---|---|---|
| in-process | agents in one process | objects passed by reference, including the `PermissionContext` |
| same-host | agents on one machine | by reference where possible, handles otherwise |
| network (event bus) | agents on the same network | handle or serialized typed object, never JSON text in `body` |
| matrix | human-visible rooms | typed envelope plus a mandatory readable `body` |

## Network bus configuration

The bus carrier uses a **dedicated** `navigator_eventbus.EventBus` (Streams transport), distinct from the telemetry
instance, configured through `PARROT_ROOST_BUS_URL` and `PARROT_ROOST_BUS_PREFIX` (navconfig with environment
fallback). Topics: `roost.<agent_name>`, `roost.cap.<category>` and the dead-letter topic `roost.dlq`. Receive is
idempotent by `idempotency_key`. Both the serialized `PermissionContext` and `auth_token` travel on this carrier.

## Matrix framing (FEAT-195)

Matrix is **one carrier among four**, not the architecture. Messages are `m.parrot.roost` events whose `body` is
mandatory human-readable text (so an ordinary client such as Element shows them) alongside the typed envelope
fields. Blackboard keys are `m.parrot.blackboard` state events with `state_key` = key: a write replaces the state,
it never appends. Matrix state has no server-side CAS, so writers in other processes can race inside the
read-compare-set window. The live gate L-S6 (`packages/ai-parrot-integrations/tests/test_matrix_roost_gate_ls6.py`)
runs only with `PARROT_TEST_MATRIX=1` against `docker-compose.matrix.yml`.

## Codecs

`EnvelopeCodec` is a sync protocol (`encode(msg) -> bytes`, `decode(bytes) -> RoostMessage`, `content_type`).
`JsonEnvelopeCodec` ships in core; with the Squawk satellite present its Cap'n Proto codec is selected instead.
Unknown `content_type`s on the bus go to the DLQ.
