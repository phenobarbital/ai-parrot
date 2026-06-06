# F004 — First-class structured_output (THE enabling primitive)

## Citations
- `AbstractBot.ask` / `BasicAgent.ask` accept
  `structured_output: Optional[Union[Type[BaseModel], StructuredOutputConfig]]`:
  - `packages/ai-parrot/src/parrot/bots/base.py:733` (signature),
    L1076-1082 (wraps a bare `BaseModel` subclass into `StructuredOutputConfig(output_type=...)`).
  - `bots/abstract.py:3674` (ask), `:3729` (ask_stream).
- `ask_stream` mirrors it: `base.py:1306`, L1471-1477.
- `StructuredOutputConfig` defined at `packages/ai-parrot/src/parrot/models/outputs.py:75`.
- `AIMessage` (`models/responses.py:72`) carries `structured_output: Optional[Any]`
  (L194), `is_structured` (set by `AIMessageFactory`, L391-420). `to_*`/render prefers
  `structured_output` when `is_structured` (L378-380).
- Real usage example: `bots/abstract.py:3876` calls `ask(..., structured_output=InfographicResponse)`
  and reads `response.structured_output`.

## Relevance
The "structured output a cada agente que reciba la pregunta + respuestas + con cuál se
queda + % confianza" is directly buildable: define a Pydantic `PeerVote` model and call
each specialist's `agent.ask(question=..., structured_output=PeerVote)`. The returned
`AIMessage.structured_output` is the typed vote. No new LLM plumbing required — every
provider client already supports it.
