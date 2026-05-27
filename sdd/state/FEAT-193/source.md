---
kind: inline
jira_key: null
fetched_at: 2026-05-27T16:13:00Z
summary_oneline: Enable simultaneous tool-calling + structured output in GoogleGenAIClient for newer Gemini models (3.x family) that support it natively, while preserving the two-phase fallback for older models
---

# Source: Google GenAI Client — Tool-Calling + Structured Output (combined-call upgrade)

De acuerdo a una última evaluación `examples/google/test_structured_output.py` hemos encontrado un partial acceptance de que los `gemini-3.1-flash-lite`, `gemini-3.5-flash` y `gemini-3.1-pro-preview` ahora aceptan Tool-Calling y Structured Output al mismo tiempo. No está 100% probado, pero éste es el análisis hecho hasta ahora:

## Análisis (resumen de la evaluación)

### 1. Compatibilidad por modelo
- **`gemini-2.5-pro`** — Incompatible. La API devuelve un error `400 Bad Request` indicando explícitamente que no soporta `response_mime_type: 'application/json'` junto con `tools`.
- **`gemini-3.1-flash-lite`** — Compatible pero inestable. Es el único modelo de la serie 3.x que genera advertencias del SDK (`non-text parts in the response: ['function_call']`).
- **`gemini-3.5-flash` y `gemini-3.1-pro-preview`** — Totalmente compatibles. Funcionan sin advertencias y manejan la transición entre la llamada a la herramienta y la respuesta estructurada de forma limpia.

### 2. El warning en `3.1-flash-lite`
La advertencia se debe al comportamiento interno del SDK de Google GenAI durante el Automatic Function Calling (AFC):
1. Cuando el modelo decide usar una herramienta, devuelve una respuesta con `function_call` pero sin texto.
2. El SDK, al procesar esta respuesta intermedia, intenta acceder a `.text`, disparando la advertencia.
3. El resultado estructurado (JSON) sólo se genera en el segundo turno, después de que el modelo recibe la salida de la herramienta.

### 3. Inestabilidad en `3.1-flash-lite`
`3.1-flash-lite` muestra tendencia a entrar en bucles infinitos de AFC si el prompt no es extremadamente directo, intentando llamar a herramientas incluso cuando se le pide explícitamente que no lo haga.

### Recomendación técnica original
- Usa `gemini-3.5-flash` — el más eficiente y estable para esta combinación.
- Evita `gemini-2.5-pro` para este flujo específico.
- Para `gemini-3.1-flash-lite`: si es imprescindible, ignora la advertencia del SDK (el JSON final llega vía `response.text`), pero ten en cuenta el riesgo de latencia por turnos AFC innecesarios.

## Cambios propuestos

Hay que hacer cambios en `examples/google/structured_with_tools.py` para permitir hacer ese mismo ejercicio con los distintos modelos: `gemini-3.1-flash-lite`, `gemini-3.1-pro-preview`, `gemini-3.5-flash`.

Si el structured_output + tool calling está funcionando para estos modelos hay que realizar las siguientes tareas:

### Tareas
- Modificar los métodos `ask()` y `ask_stream()` de `GoogleGenAIClient` para que se comporten así:
  - **Si el modelo es inferior** a los definidos, mantener el flujo como está hoy (primero tool-calling, segundo structured output — flujo de dos pasos).
  - **Si el modelo es de los definidos** (`gemini-3.1-flash-lite`, `gemini-3.1-pro-preview`, `gemini-3.5-flash`), modificar el código para que se realice tool-calling y structured output en una sola llamada combinada.
