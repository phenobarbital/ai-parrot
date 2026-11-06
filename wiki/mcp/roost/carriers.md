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

## Matrix crew wiring (FEAT-827)

`MatrixCrewTransport` does not build Roost endpoints by itself. Pass a `roost_endpoint_factory` and every agent
that gets an `AgentSwarmToolkit` also gets a started `RoostEndpoint`, so its `ask_agent` runs as a Roost `query`
instead of a tunnel round trip:

```python
def build_endpoint(agent_name: str, wake: WakeCallback) -> RoostEndpoint:
    engine = ProtocolEngine()
    config = RoostAgentConfig(grant=InterAgentGrant(scopes=[...]))  # who this agent may ask
    return RoostEndpoint(
        agent_name=agent_name, config=config, engine=engine, wake=wake,
        dispatcher=GatingDispatcher(self_name=agent_name, config=config, engine=engine,
                                    handlers=HandlerRegistry(), grant=GrantPolicy()),
        carriers={CarrierKind.IN_PROCESS: shared_carrier}, tool_manager=tool_manager,
    )

transport = MatrixCrewTransport.from_yaml("matrix_crew.yaml", roost_endpoint_factory=build_endpoint)
```

- `wake` is that agent's `MatrixCrewAgentWrapper.handle_roost_wake`. It serves addressed `query` messages only,
  runs the agent with the inbound `RoostMessage.hops` as its swarm depth (`ctx.current_hops`), and answers with
  `inform` (answer text + `tokens`) or a typed `failure` (`TIMEOUT` / `INTERNAL`). Always use it as the wake: a
  hand-written wake that does not seed the depth restarts every onward `ask_agent` at 0.
- Everything else — engine, carriers, grants, ledger, permission context — is the integrator's choice. A factory
  or `start()` error aborts `MatrixCrewTransport.start()`; the transport never falls back to tunnels silently.
- The toolkit is attached only when tunnels are enabled (`tunnels.enabled`), so the factory is ignored otherwise.
- The Matrix carrier carries `hops` in the `m.parrot.roost` event content; events without the field read as 0.
- **Known limit**: an agent woken by a query cannot yet make an onward Roost call — the reply waits behind its
  own wake and the call ends in `timeout` (`issue:a409d14b8130`). Single-hop asks work.

## Codecs

`EnvelopeCodec` is a sync protocol (`encode(msg) -> bytes`, `decode(bytes) -> RoostMessage`, `content_type`).
`JsonEnvelopeCodec` ships in core; with the Squawk satellite present its Cap'n Proto codec is selected instead.
Unknown `content_type`s on the bus go to the DLQ.
