---
type: Wiki Overview
title: FEAT-223 — Multi-Party Conferencing for `OrchestratorAgent`
id: doc:sdd-proposals-orchestratoragent-multiparty-proposal-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: El `OrchestratorAgent` agrega especialistas y los consume vía `AgentTool`
  (un agente
---

---
id: FEAT-223
title: Multi-Party Conferencing (cross-pollination + structured confidence vote) for OrchestratorAgent
type: feature
mode: enrichment
status: review
base_branch: dev
source: inline
jira_key: null
overall_confidence: high
research_state: sdd/state/FEAT-223/
---

# FEAT-223 — Multi-Party Conferencing for `OrchestratorAgent`

## §0 Origin

El `OrchestratorAgent` agrega especialistas y los consume vía `AgentTool` (un agente
expuesto como Tool). Hoy el orquestador funciona en modo **LLM-driven tool selection**:
el LLM decide a qué especialistas llamar dentro de un loop ReAct y luego sintetiza.

La propuesta: añadir un modo de **Multi-Party Conferencing** (cross-pollination
determinista):

1. **Todos** los especialistas responden a la **misma** pregunta (en paralelo).
2. Se **cruzan** las respuestas entre ellos.
3. A cada agente se le pide, vía **structured output**, *"¿con cuál respuesta te
   quedas?"* — recibiendo la pregunta original + las respuestas de los demás, y
   devolviendo su elección + un **porcentaje de confianza** + justificación.
4. El orquestador agrega los votos y produce una respuesta final.

> Fuente literal en `sdd/state/FEAT-223/source.md`.

## §1 Synthesis Summary

**Confianza global: alta.** La funcionalidad es directamente realizable sobre primitivas
que **ya existen** en el framework; no requiere tocar `abstract_client.py` ni añadir
plumbing de LLM. El trabajo es **una capa de orquestación nueva** sobre `OrchestratorAgent`.

Tres piezas habilitan todo:

- **Fan-out en paralelo** ya existe (`AgentCrew.run_parallel` usa `asyncio.gather`) — el
  orquestador ya posee `self.specialist_agents: Dict[str, BasicAgent|AbstractBot]`. [F001, F005]
- **Structured output por agente** es de primera clase: `agent.ask(..., structured_output=PeerVote)`
  devuelve `AIMessage.structured_output` tipado. Este es el mecanismo exacto para el voto
  con confianza. [F004]
- **Cross-pollination de contexto** está medio construida: `AgentTool` ya inyecta
  resultados previos (`include_previous_results`, `_build_cross_pollination_context`),
  pero de forma **secuencial y en texto libre**, sin voto estructurado ni ronda
  simultánea. [F002]

Lo que **no** existe: un camino determinista "broadcast a todos → cruzar → votar con
structured output → agregar". Eso es lo nuevo.

## §2 Codebase Findings

### §2.1 Localization (verificada)

| Símbolo | Ubicación | Rol en la feature | Evidencia |
|---|---|---|---|
| `OrchestratorAgent` | `bots/flows/agents/orchestrator.py:20` | Hogar del nuevo método `confer()`; reusa `specialist_agents` + `_init_execution_memory` | F001 |
| `OrchestratorAgent.ask` | `…/orchestrator.py:285-297` | Patrón actual passthrough/synthesis a respetar | F001 |
| `OrchestratorAgent._init_execution_memory` | `…/orchestrator.py:199-204` | Crea/wirea `ExecutionMemory` compartida | F001 |
| `AgentTool._build_cross_pollination_context` | `tools/agent.py:313-355` | Formato de bloque de contexto peer (a adaptar → anónimo) | F002 |
| `QuestionInput.include_previous_results` | `tools/agent.py:42-49` | Cross-pollination existente (secuencial) | F002 |
| `BasicAgent.ask(structured_output=…)` | `bots/base.py:733`, L1076-1082 | **Primitiva clave**: voto tipado por agente | F004 |
| `AIMessage.structured_output` / `is_structured` | `models/responses.py:194` | Portador del voto devuelto | F004 |
| `StructuredOutputConfig` | `models/outputs.py:75` | Config de salida estructurada | F004 |
| `ExecutionMemory` | `bots/flows/core/storage/memory.py:19` | Bus compartido / auditoría de rondas | F003 |
| `AgentCrew.run_parallel` | `bots/flows/crew/crew.py:1966` | Patrón `asyncio.gather` a replicar para Round-0 | F005 |

> Nota de path: el repo es un monorepo; el path del prompt
> `parrot/bots/flows/agents/orchestrator.py` resuelve a
> `packages/ai-parrot/src/parrot/bots/flows/agents/orchestrator.py`.

### §2.2 Constraints (del código)

- **Async-first**: el broadcast debe usar `asyncio.gather` sobre `agent.ask(...)`;
  nada de I/O bloqueante. [CONTEXT.md, F005]
- **No romper `ask()` existente**: el modo conferencing es **aditivo** (nuevo método),
  no debe alterar el loop ReAct LLM-driven actual. [F001]
- **Especialistas heterogéneos**: un agente puede no tener `ask`/`structured_output`
  uniforme (existe fallback `conversation`/`invoke` en `AgentTool._execute`). El
  conferencing debe degradar con elegancia si un especialista no soporta structured
  output (capturar el voto como texto y normalizar). [F002, F004]
- **Truncación de contexto**: `_build_cross_pollination_context` ya trunca a 2000 chars
  por resultado para no reventar la ventana — el bloque anónimo debe mantener ese límite. [F002]

### §2.3 Recent History

`orchestrator.py` y `tools/agent.py` se consolidaron recientemente (FEAT-143
flows-consolidation; `b20e7343` capturó el `AIMessage` completo en `AgentTool`). El área
está activa y estable — buen momento para extender. [git log]

## §3 Hypothesis / Scope

**Hipótesis (confianza: alta):** Multi-Party Conferencing se implementa como un **método
nuevo y determinista** en `OrchestratorAgent`, p.ej.
`async def confer(question, agents=None, max_rounds=3, until_convergence=True) -> ConferenceResult`,
que NO usa el loop ReAct sino que itera `self.specialist_agents` directamente.

### Diseño propuesto (Opción A — recomendada)

**Nuevos modelos Pydantic** (en `parrot/models/` — junto a `outputs.py`):

```python
class PeerVote(BaseModel):
    chosen_label: str        # "A" | "B" | ... (etiqueta anónima del answer elegido)
    revised_answer: str      # respuesta final del agente (puede mantener la propia)
    confidence: float = Field(..., ge=0, le=100)
    rationale: str

class ConferenceRound(BaseModel):
    round_index: int
    answers: Dict[str, str]          # label -> answer (anónimo)
    label_to_agent: Dict[str, str]   # mapeo interno (no se expone al LLM)
    votes: Dict[str, PeerVote]       # agent_name -> vote

class ConferenceResult(BaseModel):
    winner_agent: str
    final_answer: str
    confidence_score: float          # confianza agregada del ganador
    rounds: List[ConferenceRound]
    vote_breakdown: Dict[str, float] # agent/label -> confianza acumulada
    converged: bool
```

**Algoritmo `confer()`:**

1. **Round-0 (Independiente)** — broadcast en paralelo (`asyncio.gather`) de la MISMA
   pregunta a todos los especialistas seleccionados; recoger respuestas. (Mirror de
   `run_parallel`.) [F005]
2. **Round-k (Cross-pollinate + Vote)** — para cada agente, construir un bloque
   **anónimo** "Answer A / Answer B / …" (variante de `_build_cross_pollination_context`,
   sin atribuir autor para reducir sesgo de autoridad) y llamar
   `agent.ask(question + peer_block, structured_output=PeerVote)`. Recoger `PeerVote` de
   cada uno. [F002, F004]
3. **Agregación — voto ponderado por confianza** (determinista, sin LLM extra):
   `scores[label] += vote.confidence` sobre todos los votos; el `label` con mayor puntaje
   gana; su `revised_answer` (del agente dueño) es la respuesta final.
4. **Convergencia** — repetir Round-k usando las `revised_answer` como nuevas respuestas
   candidatas hasta que el ganador se estabilice entre rondas **o** se alcance `max_rounds`
   (default 3). Marcar `converged`.
5. Empaquetar `ConferenceResult`; persistir cada `ConferenceRound` en `ExecutionMemory`
   para auditoría/snapshot. [F003]

**Integración con `ask()`**: exponer vía un flag/modo (p.ej. `ask(..., mode="conference")`
o método público `confer()` que la API pueda invocar), reutilizando
`_init_execution_memory` y devolviendo un `AIMessage` cuyo `structured_output` sea el
`ConferenceResult` y cuyo `content` sea `final_answer`. [F001, F004]

### Decisiones de diseño (resueltas con el usuario)

| Decisión | Elección |
|---|---|
| Alcance del voto | **Cualquiera, incl. la propia** — `PeerVote` lleva `revised_answer`; un agente puede mantener su postura con alta confianza. |
| Resolución del consenso | **Voto ponderado por confianza** (determinista, sin LLM adicional). |
| Nº de rondas | **Iterar hasta convergencia**, `max_rounds=3`, `until_convergence=True`. |
| Atribución al cruzar | **Anónimas** (Answer A/B/C) con mapa interno `label_to_agent`. |

### Alternativas consideradas

- **Opción B — nuevo modo `run_conference()` en `AgentCrew`** (`crew.py`). Reusa más
  infra de crew, pero el usuario pidió explícitamente que viva en `OrchestratorAgent`.
  Útil como refactor futuro si se quiere fuera del orquestador.
- **Opción C — solo prompt-engineering dentro del loop `ask()` actual** (que el LLM
  orqueste la conferencia). Rechazada: no determinista, sin voto estructurado real, sin
  porcentaje de confianza fiable.

### Fuera de alcance

- Transporte Matrix / multi-homeserver (cubierto por `matrix-collaborative-crew`). [F005]
- Pipeline de deliberación de finanzas (`massive-deliberation`). [F005]
- Persistencia durable de conferencias más allá de `ExecutionMemory` en proceso.

## §4 Confidence Map

- ✓ **alta** — Localización exacta de `OrchestratorAgent`, `AgentTool`, `ExecutionMemory` [F001-F003]
- ✓ **alta** — `structured_output` soporta el voto con confianza sin nuevo plumbing [F004]
- ✓ **alta** — `asyncio.gather`/`run_parallel` como patrón de broadcast [F005]
- ✓ **alta** — Cross-pollination de contexto ya existe y es adaptable a formato anónimo [F002]
- ◐ **media** — Uniformidad de `structured_output` entre TODOS los proveedores/especialistas;
  algunos agentes podrían requerir fallback de parseo a texto (mitigado en §2.2).

## §5 Open Questions

Todas las preguntas de diseño materiales fueron resueltas con el usuario (ver tabla de
decisiones en §3). No quedan unknowns que el codebase no pueda responder.

- [x] Alcance del voto → cualquiera incl. la propia.
- [x] Resolución del consenso → voto ponderado por confianza.
- [x] Rondas → iterar hasta convergencia (max_rounds=3).
- [x] Atribución → anónimas (A/B/C).

## §6 Recommended Next Step

→ **`/sdd-spec FEAT-223`** — La localización es exacta y verificada y las decisiones de
diseño están cerradas. Listo para formalizar en un spec con tareas (modelos Pydantic,
método `confer()`, agregación de votos, convergencia, integración con `ask()`/API, tests).

Alternativas:
- `/sdd-brainstorm FEAT-223` — solo si se quiere reconsiderar Opción B (vivir en `AgentCrew`).

## §7 Research Audit

- Estado: `sdd/state/FEAT-223/`
- Findings: F001-F005 (`sdd/state/FEAT-223/findings/`)
- Síntesis: `sdd/state/FEAT-223/synthesis.json`
- Archivos leídos: `orchestrator.py` (340L), `tools/agent.py` (447L),
  `core/storage/memory.py` (158L), `base.py` (ask region), `crew.py` (run_parallel);
  greps sobre structured_output / confidence / deliberation; git log de los 2 ficheros
  núcleo; docs prior-art (`matrix-collaborative-crew.brainstorm.md`,
  `massive-deliberation.md`).
