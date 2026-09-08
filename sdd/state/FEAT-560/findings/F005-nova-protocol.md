---
id: F005
query_id: Q001
type: read
intent: Comparar contratos y localizar brechas de paridad de voz
executed_at: 2026-09-07T05:33:34.494414+00:00
parent_id: null
depth: 1
---

# F005 — Nova ya implementa toolConfiguration y toolResult; existe una dependencia de progreso a investigar.

## Summary

_build_prompt_start configura audio/texto/tools. _send_tool_result emite contentStart(TOOL), toolResult y contentEnd correlacionados. stream_voice encola al recibir contentEnd(TOOL) y espera al siguiente evento no-tool para ejecutar. Riesgo inferido: si el proveedor espera toolResult antes de enviar ese evento, hay espera circular; los tests con listas de eventos precargadas no demuestran ausencia de ese riesgo.

## Citations

- path: `packages/ai-parrot-client-amazon/src/parrot/clients/amazon/nova/audio.py`
  lines: 622-631
  symbol: `NovaAudio._build_tool_configuration`
  excerpt:

```python
            specs.append(
                {
                    "toolSpec": {
                        "name": name,
                        "description": description,
                        "inputSchema": {"json": schema_value},
                    }
                }
            )
```

- path: `packages/ai-parrot-client-amazon/src/parrot/clients/amazon/nova/audio.py`
  lines: 643-665
  symbol: `NovaAudio._build_prompt_start`
  excerpt:

```python
        prompt_start: Dict[str, Any] = {
            "promptName": prompt_name,
            "textOutputConfiguration": {"mediaType": "text/plain"},
            "audioOutputConfiguration": {
                "mediaType": "audio/lpcm",
                "sampleRateHertz": self.OUTPUT_SAMPLE_RATE_HZ,
                "sampleSizeBits": 16,
                "channelCount": 1,
                "voiceId": voice_id,
```

- path: `packages/ai-parrot-client-amazon/src/parrot/clients/amazon/nova/audio.py`
  lines: 667-683
  symbol: `NovaAudio._send_tool_result`
  excerpt:

```python
    async def _send_tool_result(self, stream: Any, prompt_name: str, tool_use_id: str, result: Any) -> None:
        """Send a tool result as the three-frame sequence Nova requires.

        ``contentStart(TOOL)`` -> ``toolResult`` -> ``contentEnd``.
        ``toolUseId`` is carried on the contentStart's
        ``toolResultInputConfiguration``; the ``toolResult`` frame itself is
        keyed by ``contentName``, not ``toolUseId``.

        Args:
```

- path: `packages/ai-parrot-client-amazon/src/parrot/clients/amazon/nova/audio.py`
  lines: 1087-1110
  symbol: `NovaAudio.stream_voice`
  excerpt:

```python
                # FEAT-416 (TASK-2148): flush any queued tool-call batch
                # before handling a non-tool event, so all tool results are
                # sent back before the model resumes (Nova Sonic protocol
                # requirement) — this is the "next non-tool event" boundary
                # described in spec §3 Module 4. No-op when nothing is
                # queued (the default, single-tool-at-a-time case).
                is_tool_event = "toolUse" in event or (event.get("contentEnd") or {}).get("type") == "TOOL"
                if not is_tool_event and turn_state.pending_tools:
                    for tool_response in await self._flush_pending_tools(
```

- path: `packages/ai-parrot-client-amazon/src/parrot/clients/amazon/nova/audio.py`
  lines: 1200-1233
  symbol: `NovaAudio.stream_voice`
  excerpt:

```python
                tool_use = event.get("toolUse")
                if tool_use:
                    # Gap 2: Nova executes the tool call on contentEnd(TOOL),
                    # not on toolUse — stash it, do NOT execute here.
                    tool_use_id = tool_use.get("toolUseId", str(uuid.uuid4()))
                    turn_state.pending_tool = LiveToolCall(
                        id=tool_use_id,
                        name=tool_use.get("toolName"),
                        arguments={},
```
