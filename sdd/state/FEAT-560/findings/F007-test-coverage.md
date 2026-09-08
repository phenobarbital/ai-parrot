---
id: F007
query_id: Q001
type: read
intent: Comparar contratos y localizar brechas de paridad de voz
executed_at: 2026-09-07T05:33:34.494414+00:00
parent_id: null
depth: 1
---

# F007 — Las pruebas existentes no verifican el ciclo dual completo de Nova.

## Summary

test_nova_tool_result sustituye _execute_tool por un AsyncMock con resultado simple, por lo que no observa pérdida de ToolResult. test_live_tool_routing sí usa una herramienta con voice_text/display_data. La suite conformance inspeccionada cubre opciones, roles, reconexión y capacidades, sin caso display_data. La integración avatar usa respuestas construidas y transportes mockeados, sin ejecutar Nova.

## Citations

- path: `packages/ai-parrot/tests/clients/test_nova_tool_result.py`
  lines: 32-47
  symbol: `_run`
  excerpt:

```python

    async def audio():
        yield b"\x00\x01" * 8
        yield None

    execute = execute or AsyncMock(return_value="Sunny, 25C")
    with (
        patch.dict(sys.modules, {"aws_sdk_bedrock_runtime": MagicMock()}),
        patch.object(client, "_open_stream", return_value=AsyncMock()),
```

- path: `packages/ai-parrot/tests/clients/test_live_tool_routing.py`
  lines: 14-23
  symbol: `VoiceTool`
  excerpt:

```python
    name = "voice_tool"
    description = "Returns a bulky result plus voice/display fields."

    async def _execute(self, **kwargs):
        return ToolResult(
            result=[{"a": i, "b": None} for i in range(500)],
            voice_text="Here are your five hundred rows.",
            display_data={"chart": "bar", "series": [1, 2, 3]},
        )
```

- path: `packages/ai-parrot/tests/voice/test_provider_conformance.py`
  lines: 147-169
  symbol: `TestDropInEquivalence`
  excerpt:

```python
class TestDropInEquivalence:
    """Same mocked audio + same VoiceConfig (provider aside) -> same frame
    types in the same order. Payloads may differ (audio bytes, token
    counts); structure may not (spec §4)."""

    @pytest.mark.asyncio
    async def test_role_sequence_structurally_identical(self, monkeypatch):
        gemini_client = build_client(monkeypatch, "gemini")
        nova_client = build_client(monkeypatch, "nova")
```

- path: `packages/ai-parrot-integrations/tests/voice/test_voicechat_avatar_integration.py`
  lines: 55-67
  symbol: `test_gemini_audio_to_avatar_end_to_end`
  excerpt:

```python
@pytest.mark.asyncio
async def test_gemini_audio_to_avatar_end_to_end(patched_stack, handler, connection, mocker):
    """Dual delivery: browser response_chunk AND avatar send_audio_frame receive
    the same PCM bytes (no transform) when is_complete=True.

    Proves:
    - `AvatarWebSocket.send_audio_frame` called with identical PCM (no resample).
    - `AvatarWebSocket.finish_speaking` called on is_complete.
    - Browser `response_chunk` message also sent (connection.ws.send_json called).
```
