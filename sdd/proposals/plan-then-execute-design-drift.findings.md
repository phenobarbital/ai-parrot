---
type: findings
base_branch: dev
stage: findings
status: open
owner: jesuslarag
created: 2026-09-20
source_document: artifacts/proposals/handle-only-execution-design.md
covers:
  - FEAT-419 (ExecutionPlanToolkit)
  - FEAT-538 (Recoverable Task Memory)
  - FEAT-399 (AgentsFlow State Checkpointing)
  - FEAT-550 (Bedrock token budget)
---

# Plan-then-Execute — deriva entre el diseño y lo implementado

Registro de auditoría, no una propuesta. Compara el documento de diseño
`handle-only-execution-design.md` (v2) contra el árbol en `dev` a fecha
2026-09-20, sección por sección. Las filas marcadas **→ brainstorm** se
cubren en `plan-then-execute-hardening.brainstorm.md`; el resto queda aquí
como follow-up futuro.

## 0. Procedencia del documento fuente

El diseño vive en `artifacts/proposals/handle-only-execution-design.md`, y
`artifacts/` está en `.gitignore` (línea 279). No está versionado, no aparece
en `git log`, y no es visible desde ningún worktree. Las cinco citas que
existían en el árbol lo referencian con el nombre `claude_handle-only-execution-design.md`,
que tampoco existe en disco. **Cualquier trabajo que dependa de este diseño
debe copiarlo a una ruta versionada primero.**

Nota sobre el nombre: el documento es una revisión v2 y su §8 ya descartó el
diseño "handle-only" original (`HandleOnlyCodec`, el prompt `EXECUTION MODE —
HANDLE ONLY`, ejecución por chunks). Verificado: `HandleOnlyCodec` no existe
en el árbol. `FilterLevel` sí existe pero pertenece a FEAT-380 (compression),
no a este diseño. El nombre del archivo es un fósil.

## 1. Nunca hubo una spec de este diseño

El documento se citó como **input** de `sdd/proposals/workingmemory-toolkit.proposal.md`,
pero la spec resultante (FEAT-538) lo descartó explícitamente:

> "The proposal's three referenced design documents were not supplied as
> independent inputs; their contents are not assumed."
> — `sdd/specs/workingmemory-toolkit.spec.md:423`

Sólo sobrevivió lo que ya estaba transcrito dentro de la propuesta. FEAT-419
(`ExecutionPlanToolkit`) implementa la misma arquitectura pero **no cita el
documento en ningún punto**: su linaje es `execution-plan-tool.brainstorm.md`.
La relación es convergencia conceptual, no descendencia documental.

## 2. Implementado conforme al diseño

| § | Elemento | Evidencia |
|---|---|---|
| §1 | Arquitectura de 4 etapas (planner → validator → ejecutor → analista) | `parrot/tools/execution_plan/` (FEAT-419) |
| §2 | `ExecutionPlan` = `FlowDefinition` + `for_each` + `when` | `parrot/bots/flows/plan/` (models, paths, guards, facets, validator, compile) |
| §3 | Claves asignadas por el plan, no por contador de runtime | `ForEach.store_as`, `plan/models.py:157` |
| §3.2 | Lock en el write path del catálogo | `working_memory/internals.py:834` + `SyncCatalogWriteError` (FEAT-538) |
| §6a | `node_factories` con closure sobre `ToolManager` / WM | `execution_plan/toolkit.py:200` |
| §6b | Registrar `ToolNode` en `NODE_REGISTRY` | `ensure_tool_node_registered(PlanToolNode)`, `toolkit.py:192` (idempotente) |
| §6c | Rechazar nodos `type: "agent"` | Más fuerte que lo pedido: `PlanNode` no tiene `agent_ref` → tool-only **por tipo**, no por guard |
| §6 | Proyectar a manifiesto, nunca `ctx.results` | `build_manifest()`, `toolkit.py:349` |
| §10 | Backend de catálogo pluggable con spill | FEAT-538: `task_memory/artifacts.py:200` `spill()`, `blob.py`, `store/`, `migrations/`, `retention.py` |

## 3. Desviaciones de diseño (resueltas de otra forma)

### 3.1 El fan-out de `for_each` sí necesitó `gather` + `Semaphore`

§3 afirma que no hace falta escribir runner porque `AgentsFlow.run_flow()`
ya hace dispatch incremental. Cierto **a nivel de DAG**. Pero la expansión de
`for_each` ocurre *dentro* de un nodo, donde el scheduler no llega:
`plan/node.py:281` usa `asyncio.Semaphore(spec.max_concurrency)` y `:327`
`asyncio.gather`. Default 8, tope 64 (`plan/models.py:155`).

Sin impacto: es correcto y coincide con los valores del ejemplo del diseño.
Se registra sólo para que nadie "arregle" el gather creyéndolo un descuido.

### 3.2 `describe_fn` por tool → `FacetSpec` declarativo en el plan

§8 pedía un `describe_fn` por tool. No existe en ninguna parte del árbol. En
su lugar las facets son declarativas: el plan declara qué extraer con paths
(`plan/facets.py`, `MAX_FACET_STR=200`, conteos de grupo acotados).

Valoración: la solución implementada es mejor que la diseñada — la guarda
declara lo que necesita en vez de que cada tool adivine. **No reabrir.**

### 3.3 `agent_registry` obligatorio — se aceptó la fricción

§6d proponía relajar el check de `flow.py` a "requerido sólo si hay nodos
agente". No se relajó; el toolkit pasa un `AgentRegistry()` vacío
(`toolkit.py:172`). Coste: una instancia inútil por toolkit. Follow-up
cosmético, prioridad baja.

### 3.4 `max_iterations` en Bedrock → techo de coste, no de iteraciones

§8 pedía `max_iterations` en `BedrockConverseClient`. Los bucles
`while True:` siguen ahí (`amazon/bedrock.py:1215` en `ask()`, `:1954` en
`resume()`), pero cada ronda pasa ahora por `_budgeted_attempt` con
`BudgetExhausted` (FEAT-550): techo en tokens, no en vueltas. El path de
streaming sí recibió un tope de rondas: `_max_tool_rounds = 25` (`:1628`).

El riesgo de coste está cubierto por otra vía. **Cerrado, no reabrir** —
salvo que se quiera un tope de rondas explícito en `ask()`/`resume()` por
paridad con el streaming, que sería un follow-up independiente de este diseño.

## 4. Pendiente — cubierto por el brainstorm

| § | Elemento | Estado | Destino |
|---|---|---|---|
| §5 | Replan acotado (manifiesto + errores → plan delta → ejecutar sólo eso, 1–2 rondas con tope duro) | No existe nada en el árbol | **→ brainstorm** |
| §6 | Checkpointing del plan | Apagado a propósito: `checkpoint=False`, `toolkit.py:219`. FEAT-399 (Redis + TTL 24h + durable opt-in) está **completo** y sin consumir por el toolkit | **→ brainstorm** |
| §4 | `ResultPolicy` encendido por defecto | Implementado (`tool.py:451`) pero tras la guarda `if self._catalog.is_enabled`; `WorkingMemoryToolkit()` por defecto cae al camino legacy sin tope | **→ brainstorm** |
| §8 | Helper de desenvoltura de toolkits | Sigue roto: `agent.py:234` hace `isinstance(tool, WorkingMemoryToolkit)` sobre wrappers `ToolkitTool`, no matchea nunca | **→ brainstorm** |

Detalle de los dos últimos, por ser los de mayor riesgo:

**§4 — el agujero de `include_raw` sigue abierto por defecto.** El fix es
fiel al diseño: doble techo (bytes serializados + página decodificada),
paginación `offset`/`limit`, `max_rehydrate_bytes` con default `2_000_000`
(exactamente el valor del diseño, `task_memory/config.py:131`), techo duro
que el caller puede bajar pero nunca subir (`_resolve_raw_budget`), `0` ⇒
nunca rehidrata, y mensaje de error que redirige a `wm_compute_and_store`.
Pero `WorkingMemoryToolkit.__init__` tiene `task_memory: Optional[Any] = None`
e `is_enabled` es `self._backend is not None`: sin backend adjunto se ejecuta
el camino legacy, preservado byte-idéntico por decisión explícita de FEAT-538
(AC13). El escenario del diseño — `wm_get_result(key, include_raw=true)` sobre
un JSON de 40 MB — sigue siendo posible en la configuración por defecto, que
es justamente la que el ejemplo de `docs/toolkits/execution_plan_toolkit.md`
enseña a montar.

Lo que **no** aterrizó de §4 es la forma del dataclass: no hay clase
`ResultPolicy` con `default_level` ni `control_fields`; hay parámetros y
config. `parrot/mcp/result_policy.py` es homónimo pero no relacionado — es el
cap de ~30K tokens del conector MCP (FEAT-477).

**§8 — el bug se convirtió en convención.** Además de seguir roto, el
workaround está ahora documentado como si fuera el diseño:
`docs/toolkits/execution_plan_toolkit.md` instruye inyección por constructor
"never auto-detected: `BasicAgent._inject_answer_memory_into_toolkits()` does
not match wrapped `ToolkitTool`s". `manager.py` ya desenvuelve bien vía
`bound_method.__self__`; la unificación sigue siendo el fix de ~15 líneas que
describía el diseño. Al arreglarlo hay que revisar esa doc.

## 5. Pendiente — follow-up futuro, fuera del brainstorm

### 5.1 §9.6 — el caso de uso que motivó el diseño nunca se migró

`parrot_tools/security/advisory_engine.py` no menciona `ExecutionPlan`,
`plan_execute` ni `WorkingMemory`. El flow de Security Advisory —listar
reportes de S3 → parsear → diff → mapear a controles SOC2/NIST, el pipeline
para el que se diseñó todo— sigue sin usar `ExecutionPlanToolkit`.

Consecuencia: el toolkit no tiene ningún consumidor de producción con
fan-out real, así que las decisiones de concurrencia, spill y techo de RAM
no se han validado contra carga. Es el follow-up de mayor valor de esta lista.

### 5.2 §10 — el orden recomendado no se siguió

El diseño pedía fijar la interfaz del backend persistente **antes** del
ejecutor, porque el ejecutor es su primer consumidor pesado. Aterrizó al
revés: FEAT-419 embarcó "v1 pure in-RAM, **no guardrail** (explicit user
decision)" (`sdd/specs/execution-plan-tool.spec.md`, Non-Goals) y FEAT-538
construyó el backend después.

Estado hoy: `ExecutionPlanToolkit` recibe un `WorkingMemoryToolkit` por
constructor (`toolkit.py:103`) y nunca le adjunta `task_memory`. Un plan con
fan-out sobre reportes de cientos de MB llena la RAM del proceso sin TTL,
sin límite de bytes y sin spill — el riesgo estructural de §10 tal cual,
pese a que la maquinaria para evitarlo ya existe. Relacionado con 4/§4:
ambos se destraban adjuntando el backend, pero éste es el problema de
capacidad, no el de contexto.

### 5.3 Reanudación real de un plan largo

Con `checkpoint=False` (ver §4), un plan de 300 reportes que muere en el 280
no se reanuda: se re-emite y `ForEach.skip_existing` evita rehacer lo ya
hecho. Eso es idempotencia, no reanudación, y sólo funciona mientras el
proceso viva — el run registry es in-RAM. Si el brainstorm resuelve el
checkpointing con Redis, verificar que esta propiedad quede realmente
cubierta y no sólo el `suspend`/`resume` del flow.

### 5.4 `agent_registry` vacío

Ver 3.3. Cosmético.

## 6. Cómo verificar este documento

Todas las referencias son anclas por símbolo o por ruta, no por línea
garantizada; `dev` avanza. Re-verificar antes de implementar:

```bash
grep -n "checkpoint=False" packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py
grep -n "_catalog.is_enabled" packages/ai-parrot/src/parrot/tools/working_memory/tool.py
grep -n "isinstance(tool, WorkingMemoryToolkit)" packages/ai-parrot/src/parrot/bots/agent.py
grep -rn "ExecutionPlan" packages/ai-parrot-tools/src/parrot_tools/security/
```
