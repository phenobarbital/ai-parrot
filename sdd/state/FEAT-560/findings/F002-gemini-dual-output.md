---
id: F002
query_id: Q001
type: read
intent: Comparar contratos y localizar brechas de paridad de voz
executed_at: 2026-09-07T05:33:34.494414+00:00
parent_id: null
depth: 1
---

# F002 — Gemini conserva los dos canales de ToolResult.

## Summary

LiveToolAdapter.execute_tool utiliza AbstractTool.execute, prioriza voice_text, separa display_data y trata estados distintos de success como error. stream_voice publica display_data en metadata del evento de herramienta. Es salida visual originada en herramientas; no demuestra JSON del modelo validado contra un esquema.

## Citations

- path: `packages/ai-parrot-client-google/src/parrot/clients/google/live.py`
  lines: 285-306
  symbol: `LiveToolAdapter.execute_tool`
  excerpt:

```python
            display_data = None

            if isinstance(result, ToolResult):
                if result.status == "success":

                    # Extract display data if available
                    if result.display_data:
                        display_data = result.display_data

```

- path: `packages/ai-parrot-client-google/src/parrot/clients/google/live.py`
  lines: 1074-1089
  symbol: `GeminiLiveClient.stream_voice`
  excerpt:

```python
                                # Prepare metadata with display_data if present
                                metadata = {}
                                if display_data:
                                    metadata["display_data"] = display_data

                                # Yield tool call event
                                yield LiveVoiceResponse(
                                    text="",
                                    tool_calls=[tool_call],
```

- path: `packages/ai-parrot/src/parrot/tools/abstract.py`
  lines: 250-266
  symbol: `ToolResult`
  excerpt:

```python
class ToolResult(BaseModel):
    """Standardized tool result format."""

    success: bool = Field(default=True, description="Indicates if the tool executed successfully")
    status: str = Field(default="success", description="Status of the operation")
    result: Any = Field(description="The actual result of the tool operation")
    error: Optional[str] = Field(default=None, description="Error message if any")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
```
