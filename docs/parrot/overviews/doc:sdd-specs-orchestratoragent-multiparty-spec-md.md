---
type: Wiki Overview
title: 'Feature Specification: Multi-Party Conferencing for OrchestratorAgent'
id: doc:sdd-specs-orchestratoragent-multiparty-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: El `OrchestratorAgent` (`parrot/bots/flows/agents/orchestrator.py`) agrega
relates_to:
- concept: mod:parrot.bots.flows.agents
  rel: mentions
- concept: mod:parrot.bots.flows.core.storage
  rel: mentions
- concept: mod:parrot.models.conference
  rel: mentions
- concept: mod:parrot.models.outputs
  rel: mentions
- concept: mod:parrot.models.responses
  rel: mentions
- concept: mod:parrot.tools
  rel: mentions
---

---
type: feature
base_branch: dev
---

# Feature Specification: Multi-Party Conferencing for OrchestratorAgent

**Feature ID**: FEAT-223
**Date**: 2026-06-05
**Author**: Jesus Lara + Claude
**Status**: approved
**Target version**: 0.x

> Prior exploration: `sdd/proposals/orchestratoragent-multiparty.proposal.md`
> (research-grounded, confidence: high). Research audit: `sdd/state/FEAT-223/`.

---

## 1. Motivation & Business Requirements

### Problem Statement

El `OrchestratorAgent` (`parrot/bots/flows/agents/orchestrator.py`) agrega
especialistas y los consume vía `AgentTool` (un agente expuesto como Tool). Hoy
el orquestador funciona en modo **LLM-driven tool selection**: el LLM decide a qué
especialistas llamar dentro de un loop ReAct y luego sintetiza. No existe un camino
**determinista** en el que **todos** los especialistas respondan la misma pregunta,
**crucen** sus respuestas, y **voten** cuál es la mejor con un **porcentaje de
confianza**.

El cross-pollination existente en `AgentTool` (`include_previous_results` /
`_build_cross_pollination_context`) es **secuencial y en texto libre**: inyecta los
resultados previos en orden de ejecución, sin ronda simultánea ni voto estructurado.

### Goals

- Añadir un modo **Multi-Party Conferencing** a `OrchestratorAgent`: broadcast en
  paralelo → cruce anónimo de respuestas → voto estructurado con confianza →
  agregación determinista → iteración hasta convergencia.
- Reusar las primitivas existentes: `self.specialist_agents`, `_init_execution_memory`,
  `agent.ask(structured_output=...)`, `asyncio.gather` (patrón de `run_parallel`).
- Ser **aditivo**: no alterar el loop ReAct LLM-driven actual de `ask()`.
- Devolver un resultado **auditable** (todas las rondas, votos y desglose de confianza).

### Non-Goals (explicitly out of scope)

- Transporte Matrix / multi-homeserver — cubierto por `matrix-collaborative-crew`.
- Pipeline de deliberación de finanzas — cubierto por `massive-deliberation`.
- Persistencia durable de conferencias más allá de `ExecutionMemory` en proceso.
- Síntesis LLM del consenso final — *rechazada en la propuesta* a favor del voto
  ponderado determinista (ver `proposals/orchestratoragent-multiparty.proposal.md` §3,
  Opción C). El Orchestrator NO sintetiza la respuesta final.

---

## 2. Architectural Design

### Overview

Se añade un método **nuevo y determinista** a `OrchestratorAgent`:

```python
async def confer(
    question: str,
    agents: Optional[List[str]] = None,
    max_rounds: int = 3,
    until_convergence: bool = True,
    **kwargs,
) -> AIMessage:  # .structured_output == ConferenceResult, .content == final_answer
```

`confer()` NO usa el loop ReAct: itera directamente `self.specialist_agents`.

**Flujo (3 fases, decisiones resueltas en la propuesta):**

1. **Round-0 (Independiente)** — broadcast en paralelo (`asyncio.gather`) de la MISMA
   pregunta a todos los especialistas seleccionados → recoger respuesta de cada uno.
2. **Round-k (Cross-pollinate + Vote)** — para cada agente, construir un bloque
   **anónimo** ("Answer A / Answer B / …", sin atribuir autor para reducir sesgo de
   autoridad) con un mapa interno `label_to_agent`, y llamar
   `agent.ask(question + peer_block, structured_output=PeerVote)`. Cada agente elige
   con qué respuesta se queda (**puede ser la propia**), aporta su `revised_answer` y
   un `confidence` de 0-100.
3. **Agregación (voto ponderado por confianza, determinista)** —
   `scores[label] += vote.confidence`; gana el `label` con mayor puntaje agregado; su
   `revised_answer` es la respuesta final. **Convergencia**: repetir Round-k usando las
   `revised_answer` como nuevas candidatas hasta que el ganador se estabilice entre
   rondas consecutivas o se alcance `max_rounds` (default 3).

Cada ronda se persiste en `ExecutionMemory` para auditoría.

### Component Diagram

```
OrchestratorAgent.confer(question)
  │
  ├─ _init_execution_memory(question)            (existente)
  │
  ├─ Round-0: _broadcast_round(question, agents) ──→ asyncio.gather(agent.ask(...))
  │                                                     → {agent_name: answer}
  ├─ loop k=1..max_rounds:
  │     ├─ _build_anonymous_peer_block(answers)  ──→ (peer_block, label_to_agent)
  │     ├─ _collect_votes(question, peer_block)  ──→ asyncio.gather(
  │     │                                              agent.ask(..., structured_output=PeerVote))
  │     │                                              → {agent_name: PeerVote}
  │     ├─ _tally_weighted_votes(votes)          ──→ (winner_label, vote_breakdown)
  │     ├─ persist ConferenceRound → ExecutionMemory
  │     └─ if until_convergence and winner stable: break
  │
  └─ _build_conference_result(...) ──→ AIMessage(content=final_answer,
                                                 structured_output=ConferenceResult)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `OrchestratorAgent` | extends (new method) | `confer()` + helpers; reusa `specialist_agents`, `_init_execution_memory` |
| `BasicAgent.ask(structured_output=...)` | uses | mecanismo del voto tipado por agente |
| `StructuredOutputConfig` | uses | envoltura de `PeerVote` (o pasar el modelo directamente) |
| `AIMessage` | returns | `content=final_answer`, `structured_output=ConferenceResult`, `is_structured=True` |
| `ExecutionMemory` | uses | almacén/auditoría de cada `ConferenceRound` |
| `AgentTool._build_cross_pollination_context` | references (pattern) | base del bloque peer, adaptado a formato anónimo + truncación 2000 chars |
| `AgentCrew.run_parallel` | references (pattern) | patrón `asyncio.gather` para el broadcast |

### Data Models

```python
# parrot/models/conference.py  (NEW)
from typing import Dict, List
from pydantic import BaseModel, Field


class PeerVote(BaseModel):
    """Voto estructurado de un agente tras ver las respuestas anónimas de sus pares."""
    chosen_label: str = Field(
        ...,
        description="Etiqueta anónima (A, B, C, ...) de la respuesta con la que se queda. Puede ser la propia.",
    )
    revised_answer: str = Field(
        ...,
        description="Respuesta final del agente (puede mantener la propia o adoptar otra).",
    )
    confidence: float = Field(
        ..., ge=0, le=100,
        description="Confianza del agente en su elección, 0-100.",
    )
    rationale: str = Field(..., description="Justificación breve de la elección.")


class ConferenceRound(BaseModel):
    """Estado de una ronda de cross-pollination + voto."""
    round_index: int
    answers: Dict[str, str]          # label -> answer (anónimo)
    label_to_agent: Dict[str, str]   # label -> agent_name (mapa interno, no expuesto al LLM)
    votes: Dict[str, PeerVote]       # agent_name -> voto


class ConferenceResult(BaseModel):
    """Resultado agregado del conferencing."""
    winner_agent: str
    final_answer: str
    confidence_score: float          # confianza agregada del ganador
    rounds: List[ConferenceRound]
    vote_breakdown: Dict[str, float] # label/agent -> confianza acumulada de la última ronda
    converged: bool
```

### New Public Interfaces

```python
# parrot/bots/flows/agents/orchestrator.py
class OrchestratorAgent(BasicAgent):
    async def confer(
        self,
        question: str,
        agents: Optional[List[str]] = None,   # subconjunto de specialist_agents; None = todos
        max_rounds: int = 3,
        until_convergence: bool = True,
        **kwargs,
    ) -> AIMessage: ...
```

---

## 3. Module Breakdown

### Module 1: Conference data models
- **Path**: `packages/ai-parrot/src/parrot/models/conference.py` (new)
- **Responsibility**: `PeerVote`, `ConferenceRound`, `ConferenceResult` (Pydantic v2).
  Exportar desde `parrot/models/__init__.py`.
- **Depends on**: nada (solo `pydantic`).

### Module 2: Broadcast + anonymized peer-context helpers
- **Path**: `packages/ai-parrot/src/parrot/bots/flows/agents/orchestrator.py` (extend)
- **Responsibility**: `_broadcast_round()` (fan-out paralelo de la pregunta a los
  especialistas vía `asyncio.gather`), `_build_anonymous_peer_block()` (bloque
  "Answer A/B/C" + `label_to_agent`, truncación 2000 chars/resp).
- **Depends on**: Module 1; `self.specialist_agents`.

### Module 3: Structured voting + weighted tally + convergence loop
- **Path**: `packages/ai-parrot/src/parrot/bots/flows/agents/orchestrator.py` (extend)
- **Responsibility**: `_collect_votes()` (fan-out de `agent.ask(structured_output=PeerVote)`
  con fallback de parseo a texto si un especialista no soporta structured output),
  `_tally_weighted_votes()` (suma de `confidence` por label → ganador), y el método
  público `confer()` con el bucle de rondas + detección de convergencia + empaquetado
  en `AIMessage`/`ConferenceResult`. Persistir cada `ConferenceRound` en
  `ExecutionMemory`.
- **Depends on**: Module 1, Module 2; `BasicAgent.ask`, `ExecutionMemory`.

### Module 4: Tests
- **Path**: `packages/ai-parrot/tests/.../test_orchestrator_conference.py` (new)
- **Responsibility**: unit + integración con especialistas mock.
- **Depends on**: Modules 1-3.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_peervote_confidence_bounds` | M1 | `confidence` fuera de [0,100] es rechazado por Pydantic |
| `test_anonymous_peer_block_labels` | M2 | Genera labels A/B/C, `label_to_agent` correcto, NO incluye nombres de agente en el texto |
| `test_peer_block_truncation` | M2 | Cada respuesta se trunca a 2000 chars |
| `test_broadcast_parallel` | M2 | `_broadcast_round` invoca a todos los especialistas y recoge una respuesta por cada uno |
| `test_weighted_tally_winner` | M3 | Gana el label con mayor suma de `confidence` |
| `test_weighted_tally_self_vote` | M3 | Un agente puede votar por su propia respuesta y contar |
| `test_vote_fallback_no_structured` | M3 | Especialista sin structured output → voto normalizado desde texto, sin romper la ronda |
| `test_convergence_stops_early` | M3 | Con `until_convergence=True`, para cuando el ganador se estabiliza antes de `max_rounds` |
| `test_max_rounds_cap` | M3 | Nunca excede `max_rounds` rondas |

### Integration Tests
| Test | Description |
|---|---|
| `test_confer_end_to_end` | 3 especialistas mock → `confer()` devuelve `AIMessage` con `ConferenceResult` en `structured_output`, `content == final_answer`, rondas persistidas en `ExecutionMemory` |
| `test_ask_unaffected` | El `ask()` ReAct existente sigue funcionando igual (no regresión) |

### Test Data / Fixtures
```python
@pytest.fixture
def mock_specialists():
    # Tres BasicAgent mock cuyo ask() devuelve AIMessage con structured_output=PeerVote
    ...
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `OrchestratorAgent.confer()` existe con la firma especificada y es aditivo
      (el `ask()` ReAct existente no cambia su comportamiento).
- [ ] Round-0 hace broadcast **en paralelo** (`asyncio.gather`) de la MISMA pregunta a
      todos los especialistas seleccionados (o el subconjunto `agents`).
- [ ] El cruce de respuestas se presenta **anónimo** (Answer A/B/C); los nombres de
      agente NO aparecen en el texto enviado al LLM; existe `label_to_agent` interno.
- [ ] Cada agente vota vía `agent.ask(structured_output=PeerVote)`; el voto admite
      **quedarse con la propia respuesta** y lleva `confidence` 0-100 + `rationale`.
- [ ] El consenso se resuelve por **voto ponderado por confianza** (determinista, sin
      LLM adicional).
- [ ] El conferencing **itera hasta convergencia** con `max_rounds=3` y
      `until_convergence=True` por defecto; nunca excede `max_rounds`.
- [ ] `confer()` devuelve un `AIMessage` con `content=final_answer` y
      `structured_output=ConferenceResult` (`is_structured=True`); cada `ConferenceRound`
      queda en `ExecutionMemory`.
- [ ] Degradación elegante: un especialista sin structured output no rompe la ronda
      (voto normalizado desde texto).
- [ ] Async-first: sin I/O bloqueante en `confer()` ni en los helpers.
- [ ] Todos los tests pasan (`pytest packages/ai-parrot/tests/ -k conference -v`).
- [ ] Sin cambios incompatibles en la API pública existente.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** Verificado por `read`/`grep` el 2026-06-05.
> Paths bajo `packages/ai-parrot/src/` (monorepo).

### Verified Imports
```python
from parrot.bots.flows.agents import OrchestratorAgent
# verified: parrot/bots/flows/agents/__init__.py:17,27
from parrot.tools import AgentTool
# verified: parrot/tools/__init__.py:157,240
from parrot.models.responses import AIMessage
# verified: parrot/models/responses.py:72 (structured_output L194, is_structured follows)
from parrot.models.outputs import StructuredOutputConfig, OutputMode
# verified: parrot/models/outputs.py:75 (output_type: type @ L77)
from parrot.bots.flows.core.storage import ExecutionMemory
# verified: parrot/bots/flows/core/storage/__init__.py:13,19 (also re-exported from .core:49)
```

### Existing Class Signatures
```python
# parrot/bots/flows/agents/orchestrator.py
class OrchestratorAgent(BasicAgent):                                   # L20
    agent_tools: Dict[str, AgentTool]                                 # L37
    specialist_agents: Dict[str, Union[BasicAgent, AbstractBot]]      # L38
    def add_agent(self, agent, tool_name=None, description=None,
                  use_conversation_method=True, context_filter=None)  # L123
    async def add_agent_by_name(self, agent_name, ...)                # L167
    def _init_execution_memory(self, question: str)                   # L199  (creates ExecutionMemory, wires into each AgentTool)
    def _collect_agent_results(self) -> Dict[str, NodeResult]         # L206
    def _build_synthesis_response(self, orchestrator_response, agent_results) -> AIMessage  # L247
    async def ask(self, question: str, **kwargs) -> AIMessage         # L285  (ReAct loop; MUST stay unchanged)
    def list_agents(self) -> List[str]                               # L326

# parrot/bots/base.py
class ... :
    async def ask(self, question: str, ..., 
                  structured_output: Optional[Union[Type[BaseModel], StructuredOutputConfig]] = None,
                  output_mode: OutputMode = OutputMode.DEFAULT, use_tools: bool = True,
                  **kwargs) -> AIMessage                              # L718-740 (wraps bare BaseModel → StructuredOutputConfig @ L1076-1082)

# parrot/tools/agent.py
class AgentTool(AbstractTool):                                        # L52
    args_schema = QuestionInput                                      # L62  (QuestionInput @ L32: question/mode/include_previous_results)
    async def _execute(self, **kwargs) -> str                        # L152
    def _build_cross_pollination_context(self, max_result_length=2000) -> Optional[str]  # L313 (skips own result @ L337-339)

# parrot/bots/flows/core/storage/memory.py
@dataclass
class ExecutionMemory(VectorStoreMixin):                              # L19
    original_query: Optional[str]; results: Dict[str, NodeResult]     # L32-33
    execution_order: List[str]                                       # L35
    def add_result(self, result: NodeResult, vectorize: bool = True) -> None  # L55
    def get_snapshot(self) -> Dict[str, Any]                         # L134

# parrot/models/outputs.py
@dataclass
class StructuredOutputConfig:                                         # L75
    output_type: type                                               # L77

# parrot/models/responses.py
class AIMessage(BaseModel):                                           # L72
    structured_output: Optional[Any]                                # L194
    is_structured: bool                                             # (immediately after L194)

# parrot/bots/flows/crew/crew.py
class AgentCrew(...):
    async def run_parallel(self, tasks: List[Dict[str, Any]], ...) -> FlowResult  # L1966 (asyncio.gather fan-out — pattern reference only)
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `confer()` | `_init_execution_memory()` | method call | `orchestrator.py:199` |
| `confer()` | `self.specialist_agents` iteration | attribute | `orchestrator.py:38` |
| `_collect_votes()` | `specialist.ask(structured_output=PeerVote)` | method call | `base.py:718,733` |
| `confer()` | `AIMessage(structured_output=ConferenceResult)` | construction | `responses.py:72,194` |
| `_*_round()` | `ExecutionMemory.add_result()` | method call | `memory.py:55` |

### Does NOT Exist (Anti-Hallucination)
- ~~`OrchestratorAgent.confer()`~~ / ~~`.run_conference()`~~ — no existen aún (a crear).
- ~~`parrot.models.conference`~~ — el módulo no existe aún (Module 1 lo crea).
- ~~`AgentCrew.run_conference()`~~ — no existe; `run_parallel` es solo referencia de patrón.
- ~~`PeerVote` / `ConferenceResult` / `ConferenceRound`~~ — no existen aún.
- ~~Un voto "anónimo" built-in en `AgentTool`~~ — `_build_cross_pollination_context`
  es **atribuido** y secuencial; hay que construir el bloque anónimo nuevo.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Async-first: `asyncio.gather` para los fan-outs (broadcast y voto), igual que
  `AgentCrew.run_parallel` (`crew.py:1966`).
- Pydantic v2 para todos los modelos (`PeerVote`/`ConferenceRound`/`ConferenceResult`).
- Logging con `self.logger` (heredado de `BasicAgent`), nunca `print`.
- Reusar `_init_execution_memory()` y `self.specialist_agents`; NO reimplementar el
  bus de memoria.
- Pasar el modelo Pydantic directamente a `ask(structured_output=PeerVote)` — `base.py`
  lo envuelve en `StructuredOutputConfig` automáticamente (L1076-1082).
- Truncar cada respuesta a 2000 chars en el bloque peer (paridad con
  `_build_cross_pollination_context`).

### Known Risks / Gotchas
- **Uniformidad de structured output** entre proveedores/especialistas: algún agente
  podría no devolver `structured_output` poblado. Mitigación: fallback que parsea el
  `content` a un `PeerVote` con `confidence` por defecto (p.ej. 50) y registra warning.
- **No convergencia**: si el ganador oscila, el `max_rounds` cap (3) garantiza término;
  marcar `converged=False`.
- **Coste/latencia**: N agentes × (1 + rounds) llamadas LLM. Mitigación: `agents`
  permite acotar el panel; documentar el coste.
- **Anonimización**: asegurar que el texto enviado al LLM no filtre el nombre del agente
  (ni vía role/goal en el prompt) para no reintroducir sesgo de autoridad.
- **Empates en el tally**: definir desempate determinista (p.ej. menor índice de label),
  documentado y testeado.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `pydantic` | `>=2` (ya en uso) | modelos del conference |
| `asyncio` | stdlib | fan-out concurrente |

---

## 8. Open Questions

> Decisiones materiales resueltas en la propuesta (con el usuario) — carry-forward:

- [x] Alcance del voto — *Resuelto en propuesta*: cualquiera, **incl. la propia**
      (`PeerVote.chosen_label` puede ser la propia; lleva `revised_answer`).
- [x] Resolución del consenso — *Resuelto en propuesta*: **voto ponderado por
      confianza** (determinista, sin LLM adicional).
- [x] Nº de rondas — *Resuelto en propuesta*: **iterar hasta convergencia**,
      `max_rounds=3`, `until_convergence=True`.
- [x] Atribución al cruzar — *Resuelto en propuesta*: **anónimas** (Answer A/B/C) con
      mapa interno `label_to_agent`.

> Pendientes (decidibles en implementación):

- [ ] Estrategia exacta de desempate en `_tally_weighted_votes` — *Owner: implementer*
      (propuesta por defecto: menor índice de label).
- [ ] Valor de `confidence` por defecto del fallback sin structured output —
      *Owner: implementer* (propuesta: 50).
- [ ] ¿Exponer también `confer()` vía `ask(..., mode="conference")` además del método
      público? — *Owner: Jesus* (no bloquea; el método público es suficiente para v1).: si, agregar ask(... mode='conference')

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` (una sola worktree, tareas secuenciales).
- Las tareas tienen dependencias lineales (M1 → M2 → M3 → M4); no hay paralelismo
  real que justifique múltiples worktrees.
- **Cross-feature dependencies**: ninguna. Todas las primitivas requeridas
  (`structured_output`, `ExecutionMemory`, `specialist_agents`) ya existen en `dev`.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-06-05 | Jesus Lara + Claude | Initial draft from FEAT-223 proposal |
