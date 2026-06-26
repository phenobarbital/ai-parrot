# F005 — AgentCard.to_dict already camelCase; supportedInterfaces decision SUPERSEDES brainstorm §11

**Query**: Q007/Q008 (read `a2a/models.py`)
**Verdict**: IMPLEMENTED — brainstorm §11 "dual-emit" recommendation is OUT OF DATE.

- `packages/ai-parrot/src/parrot/a2a/models.py:332` `AgentCard`; `to_dict()` (l.353) already emits **camelCase**: `protocolVersion`, `preferredTransport`, `defaultInputModes/OutputModes`, etc. (Hyp #2 of brainstorm already fixed.)
- `protocol_version="0.3.0"`, `preferred_transport="JSONRPC"` defaults (l.345-349) with comments citing a2a-dotnet `[JsonRequired]`.
- Explicit NOTE (l.372-381): **deliberately does NOT emit `supportedInterfaces`** — verified against a2a-dotnet source: v0.3 `AgentCard` has no such field; correct OPTIONAL field is `additionalInterfaces` (`{url, transport}`); flat `url`+`preferredTransport` already fully describe the endpoint; v0.3 deserializer ignores unknown fields.
- `Part`/`Message`/`Task` to_dict carry the `kind` discriminator (l.56-78, 146-157, 267-278) for the a2a-dotnet PartConverter / event-union router.

**Implication**: Brainstorm §11 hypothesis #1 (need `supportedInterfaces`) is **REFUTED by current code's documented analysis**. The card serialization fix is effectively DONE. Remaining card risk = empirical autopopulate confirmation (OQ#9), not a code change.
