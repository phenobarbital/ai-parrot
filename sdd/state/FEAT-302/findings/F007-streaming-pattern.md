---
id: F007
slug: streaming-pattern
query: Read claude.py and gpt.py streaming
type: read
---

## Finding: Streaming Convention

All clients follow the same async generator pattern:

```python
async def ask_stream(...) -> AsyncIterator[Union[str, AIMessage]]:
    async with sdk_stream(payload) as stream:
        async for text_chunk in stream:
            yield text_chunk  # str chunks
    yield ai_message  # AIMessage sentinel (last yield)
```

Consumers detect end-of-stream via `isinstance(chunk, AIMessage)`.
`AIMessage` carries `usage`, `stop_reason`, `model`, `provider`, `turn_id`.

For Bedrock Converse, streaming events are: `messageStart`, `contentBlockStart`,
`contentBlockDelta` (text, reasoningContent, toolUse), `contentBlockStop`,
`messageStop`, `metadata` (usage/metrics).

The new client must map these events to the str-chunk / AIMessage pattern.
