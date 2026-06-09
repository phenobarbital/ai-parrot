---
id: F003
query_id: Q003
type: read
intent: Locate the AgentTalk response object and the response.response / .data / .output fields
executed_at: 2026-06-08T23:34:00Z
depth: 0
---

# F003 — `AIMessage` already separates the speakable text (`response`) from non-speakable payloads (`output`/`data`)

## Summary

`models/responses.py::AIMessage` is the canonical agent answer. Its fields map
**exactly** to the requester's mental model and validate their concern:
`response: Optional[str]` is the clean textual answer (the right TTS source),
while `output: Any` and `data: Optional[Any]` carry dataframes/markdown/JSON
that cannot be spoken or streamed naively. `AgentResponse` (line 1022) wraps
`response: Optional[AIMessage]`, `data`, `output`. So the TTS path should read
`AIMessage.response` (string) and the frontend display path should consume
`output`/`data`/`media`/`images`.

## Citations

- path: `packages/ai-parrot/src/parrot/models/responses.py`
  lines: 72-110
  symbol: `AIMessage`
  excerpt: |
    output: Any = Field(description="...can be text, structured data, dataframe...")
    response: Optional[str] = Field(default=None,
        description="The textual response from the model, if applicable")
    data: Optional[Any] = Field(default=None,
        description="Structured data associated with the response")
    media: Optional[List[Path]] = ...   # images/files/documents too

- path: `packages/ai-parrot/src/parrot/models/responses.py`
  lines: 1022-1056
  symbol: `AgentResponse`
  excerpt: |
    response: Optional[AIMessage] = ...
    data: Optional[str] = ...
    output: Optional[Any] = ...

## Notes

Direct confirmation of the requester's design instinct: split the WS reply into
`audio_base64` (synthesized from `.response`) + a structured `content` block
(`output`/`data`/`media`) for display. No new model needed.
