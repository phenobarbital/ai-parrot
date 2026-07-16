---
type: Wiki Overview
title: 'Brainstorm: AgentCrew → `parrot.bots.flows.core` Migration'
id: doc:sdd-proposals-agentcrew-primitives-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Migrar **internamente** `parrot.bots.orchestration.crew.AgentCrew` para
  que consuma las primitivas de `parrot.bots.flows.core` definidas en FEAT-134. La
  migración es **invisible** para los usuarios: la API pública (`run_sequential`,
  `run_parallel`, `run_flow`, `run_loop`, `task_f'
relates_to:
- concept: mod:parrot.bots
  rel: mentions
- concept: mod:parrot.bots.flows.core
  rel: mentions
---

# Brainstorm: AgentCrew → `parrot.bots.flows.core` Migration

**Date**: 2026-04-30
**Author**: Jesus
**Depends on**: `flow-primitives` (FEAT-134, approved)
**Status**: discussion

---

## Objetivo

Migrar **internamente** `parrot.bots.orchestration.crew.AgentCrew` para que consuma las primitivas de `parrot.bots.flows.core` definidas en FEAT-134. La migración es **invisible** para los usuarios: la API pública (`run_sequential`, `run_parallel`, `run_flow`, `run_loop`, `task_flow`, `add_agent`, etc.) y todos sus invariantes observables permanecen idénticos.

El valor real del Spec 2 es doble:

1. **Eliminar duplicación.** Hoy AgentCrew tiene su propio `AgentNode` (sin FSM), su propio `FlowContext`, sus propios type aliases. Tras Spec 1 todo eso vive duplicado: las clases viejas de crew.py y las nuevas de `flows.core`. Spec 2 borra las viejas de crew.py y deja a crew.py importando desde core.
2. **Validar las primitivas en producción.** Spec 1 entregó las primitivas con tests de contrato puros. Spec 2 las pone bajo carga de un consumidor real, con LLMs reales, en los flujos que el equipo ya usa. Si una primitiva está mal diseñada, Spec 2 la descubre **antes** de que Spec 3 (DAG engine) construya encima.

Spec 2 cierra cuando:
- crew.py no define ya `AgentNode`, `FlowContext`, `AgentRef`, `DependencyResults`, `PromptBuilder` localmente — todos vienen de `flows.core`.
- Todos los tests existentes pasan sin modificación.
- El nuevo test suite de regresión con LLMs reales pasa.
- Cualquier cliente que hacía `from parrot.bots.orchestration.crew import AgentNode, FlowContext` sigue funcionando (re-export desde Spec 1 garantiza esto).

## Por qué AgentCrew y no AgentsFlow primero

AgentCrew tiene usuarios reales y tests de integración. AgentsFlow no. Migrar AgentCrew primero es la única forma honesta de validar las primitivas — cualquier defecto en `AgentTaskMachine`, `FlowContext.can_execute`, o el manejo del `node_id`-vs-`agent.name` se manifiesta inmediatamente en los flujos que el equipo ya corre. Si dejamos esto para Spec 3, AgentsFlow construye su DAG engine sobre primitivas no validadas, y descubrimos los defectos cuando ya hay código encima.

Es la mitigación del riesgo D9 del brainstorm de Spec 1, hecha realidad.

---

## Inventario: qué cambia, qué NO cambia

### Lo que cambia (interno)

- **`AgentNode` de crew.py se elimina.** AgentCrew adopta `AgentNode` de `flows.core.node` (con FSM por nodo, con `node_id` separado de `agent.name`).
- **`FlowContext` de crew.py se elimina.** Importa desde `flows.core.context`. Ya viene con backward-compat: `get_input_for_agent` (alias de `get_input_for_node`) y `agent_metadata` (alias de `node_metadata`).
- **Type aliases (`AgentRef`, `DependencyResults`, `PromptBuilder`) se eliminan.** Importan desde `flows.core.types`.
- **`CrewResult` y `AgentExecutionInfo` ya son aliases de `FlowResult` y `NodeExecutionInfo`** (Spec 1 lo dejó así). No hay nada que migrar aquí.
- **Dead code removed**: la clase `AgentTask` ya fue eliminada por Spec 1.
- **Storage imports** (`ExecutionMemory`, `PersistenceMixin`, `SynthesisMixin`): hoy crew.py importa desde `parrot.bots.flow.storage`. Spec 1 lo movió a `flows.core.storage` con re-export. **Decisión a tomar (D5)**: ¿actualizamos los imports a la ruta nueva, o dejamos los re-exports trabajar?

### Lo que NO cambia (público observable)

- API pública de `AgentCrew`: ningún método se renombra, ninguna firma cambia, ningún parámetro se añade ni se quita.
- Output structure de `CrewResult` retornado por cualquier `run_*` method.
- Semántica de `status`: `completed` / `partial` / `failed` con la misma lógica de `determine_run_status`.
- Orden de ejecución determinista en `run_sequential`.
- Comportamiento de `asyncio.gather(return_exceptions=True)` en `run_parallel`: errores van a `context.errors`, agente NO marca como completed, status final puede ser `partial`.
- Comportamiento de `task_flow` con `TransitionCondition.ON_SUCCESS`, `ON_ERROR`, `ON_CONDITION`, `ALWAYS`.
- Comportamiento de `run_loop`: condition evaluation, max_iterations, sintaxis de break.
- Semántica de timeout (`agent_execution_timeout`): si vence, agente queda en error, no detiene el flow.
- Lifecycle hooks (`on_agent_complete`, si existen) — disparados en el mismo momento, con los mismos args.
- Imports históricos: `from parrot.bots.orchestration.crew import AgentNode, FlowContext` sigue funcionando.

### Lo que está fuera de alcance

- Refactor de AgentsFlow → Spec 3.
- Nuevos node types (Scatter/Gather/Decision/Loop/HITL) → Spec 3.
- Cambios al motor de Handlers REST → out of scope.
- Cambios a `AgentCrew.add_agent()`, `add_tool()`, helpers de configuración → out of scope.
- Cualquier mejora de performance o feature nueva — Spec 2 es **migración pura**, sin valor agregado funcional.

---

## Hipótesis de diseño (a validar en brainstorm)

**H1. Migración incremental, no big-bang.** Por modo de ejecución, en orden de complejidad creciente:

1. `run_sequential` — el más simple, pipeline puro, fácil de razonar.
2. `run_parallel` — añade `asyncio.gather` y manejo de errores parciales.
3. `run_flow` — DAG con dependencias, primer consumidor real del FSM por nodo en AgentCrew.
4. `run_loop` — el más particular (estado iterativo, condition LLM-evaluated, no un grafo).

Cada modo es un task SDD independiente con sus propios tests de regresión. Si un modo revela un defecto en las primitivas, paramos, ajustamos en Spec 1 (parche), y continuamos. Big-bang acumularía riesgo y dificultaría debugging.

**H2. El FSM por nodo no cambia comportamiento observable, solo lo formaliza.** Hoy `FlowContext.completed_tasks: Set[str]` es un FSM implícito de dos estados (`pending` / `completed`). Migrar a `AgentTaskMachine` lo convierte en explícito de seis estados, pero los puntos de transición coinciden con los puntos donde hoy se modifica `completed_tasks`. Si esto es verdad, el cambio es invisible. **Si no es verdad** — si hay puntos de la lógica donde el comportamiento depende sutilmente del modelo binario actual — Spec 2 lo descubre vía tests y hay que decidir caso por caso.

**H3. `node_id` separado de `agent.name` no afecta a AgentCrew hoy.** AgentCrew nunca instancia el mismo agente dos veces en un workflow (es un caso futuro de Spec 3). Por tanto, `node_id == agent.name` para todos los nodos creados por AgentCrew, y la separación introducida en Spec 1 es transparente. La migración solo necesita pasar `node_id=agent.name` explícitamente al construir `AgentNode`.

**H4. `_format_prompt` se mueve sin cambios.** El método `AgentNode._format_prompt` (en crew.py) que arma "Task + Context from previous agents" tiene un formato específico que **es invariante observable** (un prompt distinto produce respuestas LLM distintas). Spec 1 dejó esto explícito: cada engine mantiene su propia lógica de prompt building, solo se comparte el `PromptBuilder` type alias. Por tanto, `_format_prompt` permanece en crew.py o se mueve a un helper local sin alterar bytes.

**H5. Tests de regresión con LLM real son la única forma honesta de validar.** Mocks no detectan: cambios sutiles en orden de ejecución, cambios en formato de prompt, cambios en cómo se serializa el dependency context. Necesitamos al menos un set canónico de tests con un LLM barato y determinista (temperature=0).

---

## Estrategia de migración (a decidir)

**Opción A — Por modo, secuencial.** Una task SDD por modo (`sequential` → `parallel` → `flow` → `loop`), cada una con sus tests. Total ~4-6 tasks.
- Pros: aislamiento de fallos, fácil revertir un modo si rompe.
- Contras: más overhead de coordinación SDD; cada modo necesita su propio test setup.

**Opción B — Big-bang en una task.** Una task migra toda la implementación; tests cubren todos los modos.
- Pros: menos overhead, refactor coherente.
- Contras: si rompe algo, debugging es más caro; reversión es todo-o-nada.

**Opción C — Por tipo de primitiva.** Una task por primitiva migrada (1: types, 2: FlowContext, 3: AgentNode, 4: re-export shim cleanup).
- Pros: granularidad fina.
- Contras: estado intermedio raro (AgentCrew usa half-old-half-new) que confunde tests.

**Mi inclinación**: Opción A. La granularidad por modo es natural para tests (ya hay `test_agent_crew_sequential`, `test_agent_crew_parallel`, etc. probablemente) y mapea limpiamente a casos de uso.

---

## Invariantes observables explícitos (la lista que el spec debe enumerar)

Esta es la lista que Spec 2 debe convertir en tests de regresión. Si un cambio de implementación rompe alguno, hay que revertirlo o ajustarlo en Spec 1.

### Estructurales (CrewResult)

- `result.output` igual al output del último agente en `sequential`, al output sintetizado en `parallel`/`flow`, al output de la última iteración en `loop`.
- `result.status` calculado por `determine_run_status(success_count, failure_count)`.
- `result.agents` (alias de `result.nodes`): lista en el orden en que los agentes completaron, no en el orden en que fueron añadidos.
- `result.errors`: dict `{agent_name: error_str}` solo para agentes que fallaron.
- `result.total_time` ≈ tiempo de pared del `run_*` method.
- `result.metadata['mode']` ∈ `{'sequential', 'parallel', 'flow', 'loop'}`.
- `result.execution_log`: lista de eventos en orden cronológico.

### Comportamentales (sequential)

- Los agentes ejecutan en el orden estricto en que fueron añadidos vía `add_agent`.
- El output del agente N se pasa como dependency context al agente N+1.
- Si el agente K falla, los agentes K+1..N **no** ejecutan; status final = `partial` (o `failed` si K=1).

### Comportamentales (parallel)

- Todos los agentes arrancan dentro del mismo `asyncio.gather`.
- Errores se capturan vía `return_exceptions=True`; un fallo individual no aborta los otros.
- Status final: `completed` si todos OK; `partial` si algunos OK + algunos fallaron; `failed` si todos fallaron.
- Orden de `result.agents` puede no coincidir con orden de adición (depende de cuándo cada uno completa).

### Comportamentales (flow)

- Un agente solo ejecuta cuando todas sus dependencies están en estado `completed`.
- `task_flow(A, B, condition=ON_SUCCESS)`: B ejecuta solo si A completó sin error.
- `task_flow(A, B, condition=ON_ERROR)`: B ejecuta solo si A falló.
- `task_flow(A, B, condition=ON_CONDITION, predicate=fn)`: B ejecuta solo si `await fn(A.result)` retorna truthy.
- Múltiples transitions desde el mismo source con diferentes priorities: orden de evaluación = priority desc.
- Cycle detection: añadir una transition que cerraría un ciclo se rechaza con un warning, no con excepción.
- Retry: agente fallido con `retry_count < max_retries` puede re-ejecutar; `max_retries` por defecto = 3.

### Comportamentales (loop)

- Iteración 0: prompt = `initial_task`.
- Iteración N: prompt = output de iteración N-1 (no acumula context completo).
- Stop condition: evaluada por LLM contra el output actual + condition string.
- `max_iterations` cap respetado.
- `result.metadata['iterations']` = número real de iteraciones ejecutadas.

### Lifecycle / hooks

- Si existe `on_agent_complete` callback, se dispara después de que el agente entra en `completed` (o `failed`), antes de que las transitions se procesen.
- Args y firma del callback: por verificar contra el código actual.

---

## Decisiones abiertas

**D1 — Estrategia de migración (Opción A/B/C arriba).** Mi inclinación: A. ¿Confirmas?

**D2 — Test suite de regresión: ¿qué LLM usar?**
- **Gemini Flash** (`gemini-2.5-flash`): barato, rápido, ya integrado, soporta `temperature=0`.
- **Groq + Llama 3 8B**: el más rápido y barato, pero menos predecible.
- **Mock LLM** que retorna respuestas canned por prompt: cero costo, totalmente determinista, pero **no valida el contrato real** (puede pasar mientras un cambio sutil rompe en producción).

  Recomendación: **mix**. Mocks para invariantes estructurales (orden de ejecución, status calculation, callback timing). Gemini Flash con `temperature=0` para invariantes que dependen de output real (sequential pipeline donde el output de A alimenta a B).

**D3 — ¿Cómo se gatean los tests con LLM real?**
- Pytest marker `@pytest.mark.real_llm` + opt-in vía env var (`PARROT_TEST_REAL_LLM=1`).
- Skip por defecto en CI, on-demand local.
- ¿O un job CI dedicado nightly con presupuesto limitado?

**D4 — Tests de regresión vs tests existentes: ¿cómo se relacionan?**
- ¿Los tests existentes de AgentCrew (`tests/test_agent_crew_*.py` o similar) ya capturan los invariantes, y solo necesitamos verificar que pasan? 
- ¿O necesitamos tests nuevos específicos para invariantes que los existentes no cubren?

  La auditoría de tests existentes es trabajo previo al Spec 2 — vale la pena tener un task 0 de "audit current AgentCrew test coverage and identify invariant gaps".

**D5 — Imports de storage: ruta vieja vs ruta nueva.**
- Hoy crew.py: `from ..flow.storage import ExecutionMemory, PersistenceMixin, SynthesisMixin`.
- Post Spec 1: `from .flows.core.storage import ...` también funciona (ruta canónica nueva).
- ¿Actualizamos crew.py a la ruta nueva (queda más limpio) o dejamos la vieja con re-export (menos diff)?

  Recomendación: actualizar a la ruta nueva. Spec 2 es la oportunidad natural para limpiar imports internos del propio repo. Los re-exports son para usuarios externos, no para nosotros.

**D6 — ¿AgentCrew adopta `AgentLike` Protocol o sigue tipando como `Union[BasicAgent, AbstractBot]`?**
- Hoy: `agent: Union[BasicAgent, AbstractBot]` en signatures.
- Post-migración: `flows.core.node.AgentNode.agent: AgentLike`.
- Si crew.py expone `add_agent(agent: AgentLike)` en lugar de `Union[BasicAgent, AbstractBot]`, técnicamente es un widening (acepta más tipos) y por tanto backward-compatible. Pero los type checkers de los usuarios pueden quejarse si dependían de la firma estrecha.

  Recomendación: dejar la firma pública estrecha (`Union[BasicAgent, AbstractBot]`) y solo internamente usar `AgentLike`. Cambio de firma pública es out-of-scope del Spec 2.

**D7 — ¿Limpiamos el `AgentNode._format_prompt` actual o lo dejamos?**
- Es lógica privada de crew.py; no es parte de las primitivas (Spec 1 deliberadamente lo excluyó).
- Post-migración, debería ser una función helper en crew.py o un método del consumidor — no un método de `AgentNode` (porque `AgentNode` ahora viene de core y no debe cargar lógica específica de crew).

  Decisión menor pero hay que dejarlo claro: `_format_prompt` se vuelve función libre o método de `AgentCrew` (no de `AgentNode`).

**D8 — Definition of Done: criterios cuantitativos.**
- ¿Performance baseline? Tiempo de ejecución de un crew flow tipo X no debe regresar más de Y%.
- ¿Memory baseline? `AgentTaskMachine` añade overhead vs el booleano actual; ¿es despreciable?
- ¿Coverage threshold? Tests nuevos cubren al menos X% de las nuevas paths de FSM.

  Mi inclinación: performance baseline ligero (verificar que un flow de 5 agentes en parallel no tarda más del 10% más), memoria no preocupa, coverage no enforced (ya hay tests funcionales).

**D9 — ¿Qué hacemos si Spec 2 descubre un defecto en Spec 1?**
- ¿Spec 2 se pausa y se abre Spec 1.1 de parche?
- ¿Spec 2 incluye un side-task de ajustar primitivas si es necesario?

  Recomendación: depende del defecto. Bug menor → ajustar dentro de Spec 2. Defecto de diseño → pausar, abrir spec corto de parche, retomar Spec 2. Documentar este protocolo en el spec.

**D10 — Fechas de los re-exports: ¿deprecation timeline?**
- Spec 1 dejó re-exports activos sin warnings.
- ¿Cuándo se eliminan? ¿Hay un Spec futuro de cleanup?

  Probable respuesta: nunca para usuarios externos (mantener compat indefinida); para imports internos del repo, eliminar conforme se actualicen. Documentar política.

---

## Estrategia de testing (a refinar en /sdd-brainstorm)

### Tests existentes a verificar

Audit previo al spec: enumerar tests actuales que cubren AgentCrew y clasificar por:
- ¿Cubren invariante observable? (sí/no)
- ¿Usan LLM real o mock? 
- ¿Cubren caso de error / edge case o solo happy path?

Esta auditoría va como Task 0 del Spec 2 o como parte del `/sdd-spec`.

### Tests nuevos a añadir

Casos canónicos por modo (con LLM real, `temperature=0`, Gemini Flash):

**Sequential**
- 3 agentes en pipeline; verificar orden de ejecución y propagación de output.
- 3 agentes, agente medio falla; verificar que el tercero NO ejecuta y status = `partial`.

**Parallel**
- 3 agentes en paralelo, todos OK; verificar `gather` semantics.
- 3 agentes, uno falla; verificar `partial` status, error en `errors`, otros completaron.
- 3 agentes, todos fallan; verificar `failed` status.

**Flow**
- DAG: A → B,C → D (B y C dependen de A; D depende de B y C); verificar que B y C ejecutan en paralelo después de A.
- Conditional: A → B (`ON_SUCCESS`), A → C (`ON_ERROR`); verificar branching.
- Predicate: A → B (`ON_CONDITION`, predicate); verificar evaluación de predicate sobre el result real de A.
- Retry: A configurado con `max_retries=2` + side effect que falla las primeras 2 veces; verificar retry hasta éxito.

**Loop**
- Loop con condition simple ("output contains 'DONE'"); verificar iteraciones hasta cumplimiento.
- Loop con `max_iterations=3` y condition que nunca se cumple; verificar cap respetado.

**Cross-cutting (con mocks)**
- Cycle detection: rechazo correcto de `task_flow` que crearía ciclo.
- Callback firing: `on_agent_complete` invocado en momentos correctos con args correctos.
- Timeout: agente que excede `agent_execution_timeout` queda en error sin abortar el flow.

### Diferencia con tests de Spec 1

Spec 1 testeó **primitivas en aislamiento** (FSM legal transitions, ready-set computation, FlowContext semantics) sin LLM, sin AgentCrew. Spec 2 testea **integración** del consumidor real con LLM real. Son complementarios, no redundantes.

---

## Riesgos identificados

**R1 — `_format_prompt` cambia de bytes y por tanto las respuestas LLM cambian.** Probabilidad baja si lo movemos sin tocar la lógica, pero posible si hay refactor incidental. Mitigación: tests con `temperature=0` y respuestas comparadas por similaridad (no exacta), y test específico que afirma el bytes-equality del prompt construido en un caso canónico.

**R2 — `AgentTaskMachine` añade overhead que regresa la latencia perceptiblemente.** El FSM no es free — instanciar `StateMachine` por nodo, llamar `.schedule()` / `.start()` / `.succeed()` añade microsegundos. Probabilidad baja de impacto observable (el costo del LLM call es órdenes de magnitud mayor), pero verificar.

**R3 — Cambio en orden de operaciones que rompe asumptions de tests existentes.** Hoy AgentCrew marca `completed_tasks.add(name)` en un punto específico; con FSM, la transición a `completed` ocurre en un punto que puede no coincidir exactamente. Si algún test asume que `context.completed_tasks` está actualizado en un timing específico, puede romper.

**R4 — Concurrent state mutation en `run_parallel`.** Hoy varias tasks asyncio mutan `FlowContext.completed_tasks` simultáneamente; está OK porque set-add es atómico en CPython. Con FSM por nodo, cada nodo tiene su propio FSM (no hay shared state), pero la actualización a `FlowContext` sí es shared. Verificar que la sección crítica no cambia.

**R5 — El callback `on_agent_complete` (si existe) cambia su timing.** Si el callback hoy se dispara dentro de `mark_completed`, y post-migración se dispara dentro de `fsm.succeed()`, puede haber diferencias sutiles de orden. Mitigación: test que verifica timing exacto con un callback de instrumentación.

**R6 — Loops imports después de añadir core como dependency.** crew.py ya está en `parrot.bots.orchestration.crew`; importará desde `parrot.bots.flows.core`. Verificar que `flows.core` no importa nada que indirectamente dependa de `orchestration.crew`.

**R7 — Spec 2 descubre que las primitivas requieren cambio.** El más probable. Mitigación: tener un protocolo claro de qué hacemos (D9) y no escalar el scope del Spec 2 para acomodar cambios de primitiva — abrir Spec 1.1 de parche y volver.

---

## Worktree strategy (preliminary)

- **Default isolation**: `per-spec` — un solo worktree, tasks secuenciales por modo de ejecución.
- **Rationale**: Las migraciones por modo (`sequential` → `parallel` → `flow` → `loop`) son secuenciales por naturaleza; cada una se valida contra los tests antes de la siguiente. Paralelizar en worktrees separados crearía conflicto de merges en `crew.py` que es el archivo central que toca cada task.
- **Cross-feature dependencies**: Spec 2 depende de FEAT-134 (Spec 1) ya mergeado a `dev`.

---

## Entregable concreto del Spec 2

- `parrot/bots/orchestration/crew.py` ya no define localmente: `AgentNode`, `FlowContext`, `AgentRef`, `DependencyResults`, `PromptBuilder`. Todos importados de `parrot.bots.flows.core`.
- Imports de storage actualizados a la ruta canónica (D5).
- `_format_prompt` permanece como helper local (D7).
- Test suite de regresión con LLM real (`tests/test_agent_crew_regression/`) cubriendo los casos canónicos enumerados.
- Todos los tests existentes pasan sin modificación.
- Re-exports desde Spec 1 siguen funcionando (verificación explícita en tests).
- Sin nuevas dependencias externas.
- Sin cambios a la API pública.

---

## Lo que NO entra en Spec 2

- Refactor de AgentsFlow → Spec 3.
- Nuevos tipos de nodo → Spec 3.
- Cualquier feature funcional nueva.
- Refactor de Handlers REST.
- Cambios a la firma de `AgentCrew.add_agent()` (mantener `Union[BasicAgent, AbstractBot]` aunque internamente sea `AgentLike`).
- Eliminación de re-exports de Spec 1 (esos quedan indefinidamente para usuarios externos).
- Mejoras de performance (a menos que la migración cause regresión, en cuyo caso se ajusta lo necesario para mantener baseline).

---

## Open Questions consolidadas

- D1: Estrategia de migración — Opción A/B/C
- D2: LLM para tests de regresión — Gemini Flash / Groq / mocks / mix
- D3: Cómo se gatean tests con LLM real — pytest marker / env var / job CI nightly
- D4: Audit de tests existentes — task 0 dentro del spec
- D5: Imports de storage — ruta nueva vs ruta vieja
- D6: `AgentLike` Protocol en signatures públicas — sí/no
- D7: Destino de `_format_prompt` — helper local de crew.py
- D8: Performance/coverage thresholds — baseline mínimo
- D9: Protocolo si Spec 2 descubre defecto en Spec 1 — parche corto vs ajuste in-line
- D10: Deprecation timeline de re-exports — política a documentar
