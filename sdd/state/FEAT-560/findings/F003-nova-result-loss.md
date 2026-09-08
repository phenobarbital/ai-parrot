---
id: F003
query_id: Q001
type: read
intent: Comparar contratos y localizar brechas de paridad de voz
executed_at: 2026-09-07T05:33:34.494414+00:00
parent_id: null
depth: 1
---

# F003 — Nova ejecuta herramientas pero pierde la envoltura multimodal.

## Summary

NovaAudio._flush_pending_tools llama _execute_tool y publica LiveVoiceResponse sin metadata visual. AbstractClient._execute_tool delega al manager y extrae result.result cuando recibe ToolResult. ToolManager.execute_tool extrae result.result y retorna out tras hooks/compresión. Añadir solamente metadata después de esa llamada no recupera los campos descartados.

## Citations

- path: `packages/ai-parrot-client-amazon/src/parrot/clients/amazon/nova/audio.py`
  lines: 785-798
  symbol: `NovaAudio._flush_pending_tools`
  excerpt:

```python
            start = time.monotonic()
            try:
                args = _parse_tool_arguments(raw_input)
                # Record what was actually attempted before executing, so
                # LiveToolCall.arguments reflects the real arguments even if
                # _execute_tool() itself raises.
                pending.arguments = args
                result = await self._execute_tool(pending.name, args)
                pending.result = result
```

- path: `packages/ai-parrot-client-amazon/src/parrot/clients/amazon/nova/audio.py`
  lines: 807-822
  symbol: `NovaAudio._flush_pending_tools`
  excerpt:

```python
        responses: List[LiveVoiceResponse] = []
        for (pending, _raw_input), result in zip(pending_tools, results, strict=True):
            tool_calls_list.append(pending)
            usage.tool_calls_executed += 1
            usage.tool_execution_time_ms += pending.execution_time_ms
            await self._send_tool_result(stream, prompt_name, pending.id, result)
            responses.append(
                LiveVoiceResponse(
                    text="",
```

- path: `packages/ai-parrot/src/parrot/clients/base.py`
  lines: 1456-1467
  symbol: `AbstractClient._execute_tool`
  excerpt:

```python
            perm_ctx = getattr(self, "_permission_context", None)
            result = await self.tool_manager.execute_tool(tool_name, merged, permission_context=perm_ctx)
            if isinstance(result, ToolResult):
                if result.status == "error":
                    # FEAT-500 (G3/AC5): `ValueError('')` told the LLM
                    # nothing. A tool that errors without a message still
                    # gets a readable one here.
                    raise ValueError(result.error or f"Tool {tool_name} returned status=error without a message")
                return result.result
```

- path: `packages/ai-parrot/src/parrot/tools/manager.py`
  lines: 1807-1820
  symbol: `ToolManager.execute_tool`
  excerpt:

```python
                        # original `result.error` (code-review fix).
                        try:
                            self._bind_compression_tee()
                            await self._compression_tee.store(tool_name, result.result, "error")
                        except Exception as tee_exc:  # noqa: BLE001
                            self.logger.warning(
                                "Compression tee failed while capturing " "error payload for %s: %s",
                                tool_name,
                                tee_exc,
```

- path: `packages/ai-parrot/src/parrot/tools/manager.py`
  lines: 1842-1852
  symbol: `ToolManager.execute_tool`
  excerpt:

```python
                # `_compressed` marker travel with it.
                self._bind_compression_tee()
                out, comp_meta = await self._compression_stage.run(
                    tool_name,
                    out,
                    status=result.status if isinstance(result, ToolResult) else "success",
                    metadata=meta,
                    return_direct=getattr(tool, "return_direct", False),
                )
```
