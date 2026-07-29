---
type: Wiki Overview
title: 'Feature Proposal: `parrot.flow` Primitives'
id: doc:sdd-proposals-proposal-flow-primitives-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Hoy las primitivas de orquestación de agentes viven duplicadas y divergentes
  entre dos módulos del framework:'
relates_to:
- concept: mod:parrot
  rel: mentions
- concept: mod:parrot.bots
  rel: mentions
- concept: mod:parrot.handlers.crew
  rel: mentions
- concept: mod:parrot.models.crew
  rel: mentions
---


# Feature Proposal: `parrot.flow` Primitives

**Date**: 2026-04-28
**Author**: Jesus
**Status**: discussion

---

## Why

Hoy las primitivas de orquestación de agentes viven duplicadas y divergentes entre dos módulos del framework:

- **`parrot.bots.orchestration.crew`** (AgentCrew) — motor estable, con usuarios internos. Soporta modos sequential, parallel, flow y loop. Usa `AgentNode` plano (sin FSM, con booleanos implícitos) y `FlowContext` como estado compartido.
- **`parrot.bots.flow.fsm`** (AgentCrewFSM / AgentsFlow) — motor más rico conceptualmente (FSM por nodo, transitions condicionales con predicates, retry), pero sin tracción real de uso.

Conceptualmente ambos motores comparten ~80% de su modelo (un grafo de agentes con dependencias que se ejecuta respetando un orden topológico), pero implementan ese 80% con clases distintas y contratos divergentes. Esto genera tres costos:

1. **Duplicación de código** entre dos motores que conceptualmente son el mismo.
2. **Divergencia de comportamiento** difícil de razonar — el equipo no sabe cuál motor usar para qué caso.
3. **Bloqueo del refactor de AgentsFlow** (planeado como Spec 3 separado, donde AgentsFlow se convierte en un motor DAG verdadero con scatter/gather/decision/loop/HITL nodes). Hacer ese refactor sin primitivas comunes obliga a reinventar abstracciones que AgentCrew ya validó en producción, o a divergir aún más.

Esta propuesta NO refactoriza AgentsFlow ni cambia AgentCrew funcionalmente. Su único objetivo es **destilar** las primitivas comunes a un módulo compartido para que tanto AgentCrew (Spec 2 — migración interna sin cambio de API) como AgentsFlow (Spec 3 — refactor completo a DAG engine) construyan sobre la misma base validada.

El tiempo es ahora porque el refactor de AgentsFlow está en cola inmediata. Construirlo sobre primitivas dispersas garantiza arrastrar la deuda; consolidarlas primero la paga una sola vez.

## What Changes

**Para usuarios de AgentCrew** (público externo, scripts internos, handlers REST): **cero cambio observable**. La API pública (`AgentCrew.run_sequential()`, `run_parallel()`, `run_flow()`, `run_loop()`, `task_flow()`) permanece idéntica. Imports actuales siguen funcionando vía re-exports. Todos los invariantes observables (output structure de `CrewResult`, semántica de errores parciales, orden de ejecución determinista, callbacks de `on_agent_complete`) se preservan.

**Para desarrolladores del framework**:

- Aparece un módulo nuevo (nombre tentativo `parrot.flow.primitives`, sujeto a discusión) que expone las clases base compartidas:
  - `Node` (ABC) + `AgentNode` (concrete con FSM) + `StartNode` + `EndNode`
  - `AgentTaskMachine` — FSM por nodo (`idle / ready / running / completed / failed / blocked`)
  - `FlowContext` — estado compartido del workflow
  - `FlowTransition` + `TransitionCondition` — aristas condicionales (opcionales por nodo)
  - Types: `AgentRef`, `PromptBuilder`, `AgentLike` (Protocol para evitar import cycles)
- Los modelos de respuesta (`CrewResult`, `AgentExecutionInfo`, `build_agent_metadata`, `determine_run_status`) **NO cambian** — ya están consolidados en `parrot.models.crew` y constituyen el contrato de salida común correcto.
- Tests de contrato (unit, sin LLM real) viven junto a las primitivas y validan invariantes de FSM, semántica de transitions, ready-set computation, serialización round-trip de FlowContext.

**Lo que explícitamente NO entra en este Spec** (para fijar alcance):

- Refactor de AgentCrew para consumir las primitivas → Spec 2 (`agent-crew-primitives-migration`).
- Refactor de AgentsFlow a DAG engine real con scatter/gather/decision/loop/HITL nodes → Spec 3 (`agents-flow-dag-engine`).
- Backend de checkpoint/Redis para persistir estado del flow → Spec 3 (cuando exista un consumidor real que lo demande).
- Cambios a `CrewResult` o `AgentExecutionInfo` (ya estables y unificados).
- Cambios a Handlers REST de crew.

## Capabilities

### New Capabilities

- `flow-primitives`: Módulo compartido con las primitivas de orquestación de agentes (Node, AgentNode, AgentTaskMachine, FlowContext, FlowTransition, TransitionCondition) extraídas del código existente de AgentCrew y AgentCrewFSM. Incluye test suite de contratos sobre invariantes puros (FSM, ready-set, transitions). No incluye motor de ejecución, scheduler, ni node types avanzados — solo las primitivas que ambos consumidores (AgentCrew y AgentsFlow) necesitan compartir.

### Modified Capabilities

<!-- Ningún spec existente cambia sus REQUISITOS en este Spec. La migración interna de AgentCrew ocurre en Spec 2, y aunque toca la implementación, no altera el contrato observable de la capability. -->

_(ninguna — los cambios de implementación de AgentCrew se gestionan en el Spec 2 separado y no alteran los requisitos del spec actual de AgentCrew)_

## Impact

**Usuarios finales de Parrot** (consumidores de AgentCrew vía API o código):
- Ningún cambio observable. Imports siguen funcionando, comportamiento idéntico.

**Desarrolladores del framework**:
- Nuevo módulo a conocer y mantener (`parrot.flow.primitives`).
- Habilita el Spec 2 (migración interna de AgentCrew) y desbloquea el Spec 3 (DAG engine).
- Los tests de contrato actúan como documentación viva de las primitivas — cualquier consumidor futuro tiene una especificación ejecutable de qué garantizan las primitivas.

**APIs / contratos**:
- API pública de AgentCrew: sin cambios.
- Imports internos: rutas viejas (`from parrot.bots.orchestration.crew import AgentNode, FlowContext`) siguen funcionando vía re-export.
- Nuevas rutas canónicas (`from parrot.flow.primitives import …`) disponibles para nuevo código.

**Dependencias**:
- Sin nuevas dependencias externas. `python-statemachine` ya está en uso por `AgentCrewFSM`.

**Otros sistemas**:
- Handlers REST de crew (`parrot.handlers.crew`): sin cambios.
- BotManager / AgentRegistry: sin cambios.
- Storage de ExecutionMemory: sin cambios.

**Riesgo principal**:
- Migrar AgentCrew internamente al `AgentTaskMachine` (Spec 2) podría revelar diferencias sutiles de timing u orden de callbacks. Mitigación: enumerar invariantes observables explícitamente como parte del codebase contract del Spec 2 y testear con agentes reales (no mocks) antes de mergear.

## Open Questions

- **D1 — Naming del módulo**. ¿`parrot.flow.primitives`? ¿`parrot.flow.core`? ¿`parrot.bots.flow.core` (cabe en namespace existente pero amarra a `bots/`)? ¿`parrot.orchestration.primitives`? Hay tensión entre crear un namespace top-level limpio (`parrot.flow`) vs. encajar en la jerarquía existente (`parrot.bots.flow.*` ya tiene `storage` y `tools`).

- **D2 — Destino de `AgentTask` (de `crew.py`)**. Actualmente parece superpuesto con `FlowNode` / futuro `AgentNode`. ¿Se elimina, se fusiona en `AgentNode`, o se mantiene como vista ligera para casos donde no se quiere el FSM completo?

- **D3 — Identidad del Node: `node_id` vs `agent.name`**. Hoy ambos motores usan `agent.name` como identificador único. El caso real "spawn dos developers en paralelo (TaskNode + FlowtaskNode)" requiere dos instancias del mismo agente con IDs distintos. ¿Las primitivas separan `node_id` de `agent.name` desde Spec 1 (anticipando Spec 3), o lo dejamos para cuando AgentsFlow lo necesite?

- **D4 — Jerarquía: `Node` ABC + `AgentNode` concreto, o solo `AgentNode`**. Si Spec 3 introducirá ScatterNode, GatherNode, DecisionNode como subclases, conviene tener `Node` (ABC) desde Spec 1. Si todo nodo termina siendo `AgentNode` con flags, una sola clase basta. La decisión afecta cómo se estructura la API pública del módulo.

- **D5 — Dependencia hacia el agente: clase concreta vs Protocol**. Hoy `crew.py` importa `BasicAgent` y `AbstractBot` directamente. Las primitivas idealmente dependen solo de un `Protocol` (`AgentLike`: `name`, `async invoke()` o equivalente) para que `parrot.flow` no arrastre el árbol completo de bots y para evitar import cycles. ¿Vale la pena el rigor del Protocol, o aceptamos la dependencia directa por simplicidad?

- **D6 — Prompt building: API unificada o por consumidor**. Hoy:
  - `crew.py::AgentNode._format_prompt` arma "Task + Context from previous agents" desde el dict de input.
  - `fsm.py::FlowTransition.build_prompt` usa `instruction` / `prompt_builder` / fallback default.

  ¿Las primitivas exponen una API unificada de prompt building (`PromptBuilder` Protocol + helper `default_prompt_builder`), o cada consumidor mantiene su lógica?

- **D7 — `FlowContext.get_input_for_agent` mezcla concerns**. Empaqueta `{task, dependencies}` como dict para que se reformatee después. ¿Eso es primitiva (todos lo necesitan) o lógica de consumidor (el shape lo decide quién lo consume)?

- **D8 — Re-export strategy**. `parrot.bots.orchestration.crew` exporta `AgentNode`, `FlowContext`. Si los movemos al nuevo módulo:
  - **Opción A**: re-exportar desde el módulo viejo (mantiene imports estables; deuda técnica latente).
  - **Opción B**: forzar migración (limpio; rompe imports internos del repo y posibles consumidores externos).

  Para AgentCrew (con usuarios) la respuesta natural es Opción A. Para AgentsFlow no aplica (sin usuarios). ¿Documentamos las rutas viejas como "deprecated, será eliminado en vX.Y"?

- **D9 — Migración interna de AgentCrew al FSM-por-nodo: ¿cambia algo observable?** Riesgo principal del Spec 2 que hay que anticipar aquí. Hay que enumerar explícitamente los invariantes observables que NO deben cambiar:
  - Output structure de `CrewResult` (output, content, agents, errors, status, metadata).
  - Semántica de `partial` status en parallel/flow.
  - Orden de ejecución determinista en sequential.
  - Timing y firmas de callbacks (`on_agent_complete`).
  - Comportamiento de timeouts y retries.

