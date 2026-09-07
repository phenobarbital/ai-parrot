---
id: F006
query_id: Q001
type: read
intent: Comparar contratos y localizar brechas de paridad de voz
executed_at: 2026-09-07T05:33:34.494414+00:00
parent_id: null
depth: 1
---

# F006 — La ejecución común aplica controles y Gemini inyecta contexto de sesión.

## Summary

ToolManager.execute_tool documenta guardrails y permisos para los dos tipos de herramientas. Gemini inyecta session_id/user_id/turn_id sobrescribiendo argumentos generados por el modelo. Nova pasa solo nombre y argumentos a _execute_tool; no establece _tool_context en el archivo de audio inspeccionado. La solución debe preservar controles, estados no exitosos y contexto confiable sin cambiar globalmente AbstractClient.

## Citations

- path: `packages/ai-parrot/src/parrot/tools/manager.py`
  lines: 1514-1531
  symbol: `ToolManager.execute_tool`
  excerpt:

```python
    async def execute_tool(
        self,
        tool_name: str,
        parameters: Dict[str, Any],
        permission_context: Optional["PermissionContext"] = None,
    ) -> Any:
        """Execute a registered tool function.

        Args:
```

- path: `packages/ai-parrot-client-google/src/parrot/clients/google/live.py`
  lines: 238-245
  symbol: `LiveToolAdapter.execute_tool`
  excerpt:

```python
            # Securely inject context variables, overriding any LLM-provided values
            # This prevents the LLM from hallucinating session IDs (e.g. "sess456")
            for key, value in context.items():
                if value is not None:
                    # We unconditionally overwrite LLM-provided args with trusted context
                    tool_args[key] = value

        try:
```

- path: `packages/ai-parrot-client-google/src/parrot/clients/google/live.py`
  lines: 987-1000
  symbol: `GeminiLiveClient.stream_voice`
  excerpt:

```python
                                # Pass session context to tool execution
                                tool_context = {
                                    "session_id": session_id,
                                    "user_id": str(user_id) if user_id is not None else None,
                                    "turn_id": turn_id,
                                }
                                # Merge context into args for logging visibility
                                effective_args = dict(fc.args) if fc.args else {}
                                effective_args.update(tool_context)
```

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

- path: `packages/ai-parrot/src/parrot/clients/base.py`
  lines: 1439-1457
  symbol: `AbstractClient._execute_tool`
  excerpt:

```python
        try:
            ctx = tool_context or getattr(self, "_tool_context", None)
            if ctx:
                # Only inject context keys the target tool actually accepts —
                # otherwise tools whose signature does not declare
                # ``user_id`` / ``session_id`` raise ``TypeError`` and the
                # whole tool call fails. When introspection cannot determine
                # the accepted set (or the tool takes ``**kwargs``), the
                # full context is forwarded as before.
```
