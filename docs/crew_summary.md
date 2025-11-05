# Método `summary()` - Documentación Completa

## 📋 Visión General

El método `summary()` genera reportes completos o resúmenes ejecutivos de todos los resultados del crew, con dos modos de operación optimizados para diferentes casos de uso.

---

## 🎯 Modos de Operación

### 1. **`mode="full_report"`** (Sin LLM)
- ✅ Concatena todos los resultados en orden
- ✅ Rápido y determinístico
- ✅ No consume tokens del LLM
- ✅ Ideal para documentación completa

**Uso:**
```python
report = await crew.summary(mode="full_report")
```

### 2. **`mode="executive_summary"`** (Con LLM Iterativo)
- ✅ LLM procesa resultados en chunks
- ✅ Genera mini-summaries parciales
- ✅ Combina en resumen ejecutivo final
- ✅ Garantiza completitud sin truncamiento
- ✅ Progress feedback con tqdm

**Uso:**
```python
summary = await crew.summary(
    mode="executive_summary",
    summary_prompt="Create executive summary highlighting ROI and risks"
)
```

---

## 🔧 Arquitectura Técnica

### **Flujo: `mode="full_report"`**

```
┌─────────────────────────────────────┐
│  1. Ordenar por execution_order    │
│     (respeta sequential/flow)       │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  2. Para cada AgentResult:          │
│     - Formatear markdown            │
│     - Omitir si tiene error         │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  3. Concatenar todo                 │
│     Header + Metadata + Results     │
└──────────────┬──────────────────────┘
               │
               ▼
           Markdown Report
```

**Tiempo**: O(n) donde n = número de resultados

---

### **Flujo: `mode="executive_summary"`**

```
┌─────────────────────────────────────┐
│  1. Dividir en chunks adaptativos   │
│     (max_tokens_per_chunk=4000)     │
│     - Respetar execution_order      │
│     - Estimar tokens (~4 chars=1t)  │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  2. Para cada chunk (con progress): │
│     ┌─────────────────────────────┐ │
│     │ LLM → Mini-Summary          │ │
│     │ (1500 tokens máx)           │ │
│     └─────────────────────────────┘ │
│     Repetir para todos los chunks   │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  3. Final Pass:                     │
│     - Combinar mini-summaries       │
│     - LLM → Executive Summary       │
│     - (4096 tokens máx)             │
└──────────────┬──────────────────────┘
               │
               ▼
      Executive Summary Markdown
```

**Llamadas LLM**: n_chunks + 1 (final pass)
- Ejemplo: 20 agentes con 4000 tokens/chunk → ~5-6 llamadas LLM

---

## 📝 Métodos Auxiliares Implementados

### 1. `_chunk_results_adaptive()`
**Propósito**: Dividir resultados en chunks adaptativos por tokens

**Características**:
- Respeta `execution_order` estrictamente
- Estima tokens: `len(text) // 4`
- Agrupa hasta `max_tokens_per_chunk`
- Omite resultados con errores (status='failed')

**Código clave**:
```python
for agent_id in self.execution_memory.execution_order:
    result = self.execution_memory.get_results_by_agent(agent_id)
    if result and not has_error(result):
        estimated_tokens = len(result.to_text()) // 4
        # Agregar a chunk si cabe, sino crear nuevo chunk
```

**Ejemplo**:
```python
chunks = crew._chunk_results_adaptive(max_tokens_per_chunk=3000)
# chunks = [[result1, result2], [result3, result4, result5], ...]
```

---

### 2. `_format_result_for_report()`
**Propósito**: Formatear AgentResult como markdown estructurado

**Formato generado**:
```markdown
## Agent Name

**Task**: Task description here

**Result**:
Result content here (or in code block if >500 chars)
```

**Configuración**:
- `include_metadata=False` por default (según requerimientos)
- Bloques de código para resultados largos

---

### 3. `_generate_full_report()`
**Propósito**: Generar reporte completo sin LLM

**Estructura del output**:
```markdown
# AgentCrew Name - Full Execution Report

**Generated**: 2025-01-06T10:30:00

## Execution Summary

- **Mode**: parallel
- **Total Agents**: 5
- **Status**: completed
- **Total Time**: 12.34s

---

## Agent Results

## Agent 1 Name
**Task**: ...
**Result**: ...

---

## Agent 2 Name
...
```

**Características**:
- Header con metadata del crew
- Resultados en orden de ejecución
- Separadores entre agentes
- Omite agentes con errores

---

### 4. `_generate_executive_summary()`
**Propósito**: Generar executive summary con LLM iterativo

**Parámetros clave**:
- `max_tokens_per_chunk`: 4000 (default)
- `summary_prompt`: Personalizable o usa default

**Process tracking**:
```python
# Con tqdm (si disponible)
from tqdm.asyncio import tqdm
for chunk_idx, chunk in tqdm(chunks, desc="Summarizing chunks"):
    ...

# Sin tqdm (fallback)
logger.info(f"Processing chunk {chunk_idx}/{total_chunks}...")
```

**Prompts usados**:

**Para cada chunk**:
```
# Chunk X of Y - Agent Results

[Resultados formateados]

---

**Task**: Provide a concise summary of the key findings from these agents.
Focus on main insights and important information. This summary will be combined
with other summaries to create a final executive summary.
```

**Final pass**:
```
# AgentCrew Name - Agent Summaries to Synthesize

## Summary Part 1
*Agents: Agent1, Agent2*

[Mini-summary 1]

---

## Summary Part 2
...

---

{summary_prompt}

**Important**: Create a cohesive executive summary that synthesizes ALL...
```

**Output estructura**:
```markdown
# AgentCrew Name - Executive Summary

**Generated**: 2025-01-06T10:30:00

## Execution Overview

- **Mode**: flow
- **Total Agents**: 10
- **Status**: completed
- **Chunks Processed**: 3

---

## Summary

[Executive summary content generated by LLM]
```

---

## 🚀 Uso Completo

### Ejemplo 1: Full Report Simple
```python
from parrot.bots.orchestration import AgentCrew
from parrot.bots.agent import BasicAgent
from parrot.clients.google import GoogleGenAIClient

# Setup crew
crew = AgentCrew(
    agents=[researcher, analyzer, writer],
    name="ResearchCrew"
)

# Ejecutar
await crew.run_sequential(task="Analyze AI trends")

# Generar reporte completo
report = await crew.summary(mode="full_report")

# Guardar a archivo
with open("full_report.md", "w") as f:
    f.write(report)
```

### Ejemplo 2: Executive Summary con Custom Prompt
```python
# Setup con LLM
crew = AgentCrew(
    agents=[researcher, analyzer, writer],
    llm=GoogleGenAIClient(),
    name="ResearchCrew"
)

# Ejecutar
await crew.run_parallel(
    tasks=[
        {'agent_id': 'researcher', 'query': 'Research market'},
        {'agent_id': 'analyzer', 'query': 'Analyze data'},
        {'agent_id': 'writer', 'query': 'Write summary'}
    ]
)

# Generar executive summary personalizado
summary = await crew.summary(
    mode="executive_summary",
    summary_prompt="""
    Create an executive summary for C-level executives that:
    1. Highlights business impact and ROI
    2. Identifies key risks and mitigation strategies
    3. Provides clear go/no-go recommendations
    4. Uses bullet points for scannability

    Maximum 2 pages.
    """,
    max_tokens_per_chunk=5000  # Chunks más grandes
)

print(summary)
```

### Ejemplo 3: Progress Tracking con tqdm
```python
# Instalar tqdm si no está
# pip install tqdm

# Ejecutar con muchos agentes
crew = AgentCrew(agents=many_agents, llm=llm)
await crew.run_flow(initial_task="Complex workflow")

# Summary con progress bar
summary = await crew.summary(mode="executive_summary")

# Output en terminal:
# Summarizing chunks: 100%|██████████| 8/8 [00:45<00:00,  5.67s/chunk]
```

---

## ⚙️ Configuración y Optimización

### **Ajustar tamaño de chunks**
```python
# Chunks más pequeños → más llamadas LLM, más detalle
summary = await crew.summary(
    mode="executive_summary",
    max_tokens_per_chunk=2000
)

# Chunks más grandes → menos llamadas, más síntesis
summary = await crew.summary(
    mode="executive_summary",
    max_tokens_per_chunk=6000
)
```

### **Pasar kwargs al LLM**
```python
summary = await crew.summary(
    mode="executive_summary",
    max_tokens=8192,        # Respuesta más larga
    temperature=0.5,        # Más creativo
    top_p=0.9,
    user_id="user123",
    session_id="session456"
)
```

### **Reusar summary guardado**
```python
# Primera vez
summary = await crew.summary(mode="executive_summary")
print(summary)

# Reusar sin regenerar
cached_summary = crew.summary  # Guardado en self.summary
print(cached_summary)
```

---

## 📊 Performance y Escalabilidad

### **Estimación de tiempo: `full_report`**
- **10 agentes**: ~0.1s (solo formateo)
- **50 agentes**: ~0.5s
- **100 agentes**: ~1s

**Bottleneck**: Ninguno (solo IO)

### **Estimación de tiempo: `executive_summary`**
- **10 agentes** (2-3 chunks): ~30-45s
  - 2 mini-summaries: ~10s cada uno
  - 1 final pass: ~15s
  - Total: 3 llamadas LLM

- **50 agentes** (10-12 chunks): ~2-3 minutos
  - 10 mini-summaries: ~10s cada uno
  - 1 final pass: ~20s
  - Total: 11 llamadas LLM

- **100 agentes** (20-25 chunks): ~5-7 minutos
  - 20 mini-summaries: ~10s cada uno
  - 1 final pass: ~30s
  - Total: 21 llamadas LLM

**Bottleneck**: Llamadas al LLM (I/O bound)

**Optimización**: Usar chunks más grandes si el LLM lo soporta
```python
# Para modelos con context window grande (ej: claude-opus-4, gemini-pro)
summary = await crew.summary(
    mode="executive_summary",
    max_tokens_per_chunk=8000  # Reduce llamadas a la mitad
)
```

---

## 🛡️ Manejo de Errores

### **Agentes fallidos**
```python
# Escenario: 5 agentes, 2 fallaron
crew = AgentCrew(agents=[a1, a2, a3, a4, a5], llm=llm)
await crew.run_sequential(task="Process data")

# a2 y a4 fallaron

summary = await crew.summary(mode="executive_summary")
# Resultado: Solo procesa a1, a3, a5
# Los errores se omiten automáticamente
```

**Logging**:
```
INFO: Generating executive summary with iterative LLM...
DEBUG: Skipping failed agent: a2
DEBUG: Skipping failed agent: a4
INFO: Processing 2 chunks for executive summary
INFO: Processing chunk 1/2...
INFO: Processing chunk 2/2...
INFO: Generating final executive summary...
INFO: Executive summary generated successfully
```

### **Error en chunk processing**
```python
# Si un chunk falla al procesarse
# Se agrega placeholder y continúa
# Ejemplo output:
"""
## Summary Part 2
*Agents: analyzer, validator*

[Error processing chunk 2]

---
"""
```

### **Sin LLM configurado**
```python
crew = AgentCrew(agents=[...])  # Sin llm parameter

# Esto funciona:
report = await crew.summary(mode="full_report")

# Esto falla con error claro:
summary = await crew.summary(mode="executive_summary")
# ValueError: executive_summary mode requires LLM.
# Either use mode='full_report' or pass llm to AgentCrew constructor.
```

---

## 📋 Checklist de Implementación

### ✅ Implementado
- [x] `_chunk_results_adaptive()` - Chunking adaptativo
- [x] `_format_result_for_report()` - Formateo markdown
- [x] `_generate_full_report()` - Reporte sin LLM
- [x] `_generate_executive_summary()` - Summary con LLM
- [x] `summary()` - Método principal
- [x] Respetar execution_order estrictamente
- [x] Omitir agentes con errores
- [x] Progress feedback con tqdm/logging
- [x] Default summary prompt
- [x] Guardar en self.summary
- [x] Manejo robusto de errores
- [x] Documentación completa

### ⚠️ Pendiente (Opcional)
- [ ] Formato JSON/structured output (además de markdown)
- [ ] Streaming de resultados parciales
- [ ] Cache de mini-summaries para re-runs
- [ ] Parallel processing de chunks (actualmente secuencial)
- [ ] Métricas detalladas (tokens usados, tiempos por chunk)

---

## 🔍 Comparación: `ask()` vs `summary()`

| Característica | `ask()` | `summary()` |
|---------------|---------|-------------|
| **Propósito** | Responder preguntas específicas | Generar reportes completos |
| **Input** | Pregunta del usuario | Modo + prompt (opcional) |
| **Búsqueda** | Híbrida (FAISS + textual) | Secuencial por execution_order |
| **Re-ejecución** | Sí (vía tools) | No |
| **LLM requerido** | Sí | Solo para executive_summary |
| **Chunks** | Top-K semántico | Todos los resultados |
| **Interactivo** | Sí | No |
| **Output** | AIMessage | String markdown |

**Uso combinado**:
```python
# 1. Generar summary completo
summary = await crew.summary(mode="executive_summary")

# 2. Hacer preguntas interactivas sobre detalles
response = await crew.ask("What were the key risks identified?")
```

---

## 📚 Referencias

- **Código fuente**: `/mnt/user-data/outputs/crew.py` (líneas 2389-2869)
- **Métodos relacionados**:
  - `ask()`: Preguntas interactivas
  - `run()`: Ejecución con synthesis
  - `clear_memory()`: Limpiar resultados
  - `get_memory_snapshot()`: Inspeccionar memoria

---
