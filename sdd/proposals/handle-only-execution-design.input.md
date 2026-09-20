# Plan-then-Execute — ciclos de tools deterministas con WorkingMemory

> Contexto: pipelines con muchas tool-calls cuyos payloads no caben (ni deben caber) en la ventana de ningún modelo. Complementa `claude/security-advisory-crew-design.md`.
>
> **Revisión (v2).** La versión anterior de este doc diseñaba un *ejecutor LLM ciego*: un modelo barato con 8K de salida (MiniMax en Bedrock) encadenando tool-calls cuyos resultados se desviaban a WorkingMemory. Tras discutirlo, la conclusión es que ese modelo sobra. Lo que sigue es la arquitectura resultante; §8 explica qué del diseño anterior sobrevive.

## 0. Conclusión primero

**El ejecutor LLM era el problema equivocado.** La pregunta original —"cómo guío a un modelo de 8K de salida para que encadene tool-calls sin ver los resultados"— tiene una respuesta mejor que cualquier guiatura: **no pongas un modelo en el bucle**.

Un modelo thinking (Opus) escribe **una vez** el plan completo como spec estructurado. Un runner determinista lo ejecuta —en paralelo donde el DAG lo permita—. Los resultados van directos a `WorkingMemory` sin pasar por ningún contexto. El mismo modelo que escribió el plan lee después los artefactos cuyos nombres él mismo asignó.

Por qué es estrictamente mejor que el bucle LLM:

| | Bucle LLM (MiniMax tool a tool) | Plan-then-execute |
|---|---|---|
| Tokens en el bucle | O(N²) — el historial se re-envía en cada iteración | **0** |
| Paralelismo | Imposible: el paso k+1 requiere ver terminar el k | DAG → dispatch incremental del scheduler |
| Latencia (N=50, tools I/O-bound) | serial, ~N × latencia_tool | ~profundidad del DAG |
| Fallos posibles | tool inexistente, args inválidos, bucle infinito, parada prematura | detectados en **validación**, antes de ejecutar |
| Reproducible / auditable | no | sí — el plan es un artefacto versionable |

El paralelismo es el argumento más fuerte, y es el que la comparación de costes suele tapar: un bucle LLM es **inherentemente serial** por construcción. Para el flow de Security (N reportes de S3 → parsear → diff → mapear), pasar de serial a fan-out es un orden de magnitud en latencia, no un 20%.

## 1. Arquitectura

```
[1] PLANNER — Opus, una llamada, thinking on
      structured_output=ExecutionPlan
      No ejecuta nada. No ve datos. Sólo el catálogo de tools y el objetivo.
            │
            ▼
[2] VALIDATOR — código, 0 tokens
      · toda tool existe en el ToolManager
      · args validan contra el `args_schema` de cada tool
      · el grafo de dependencias es acíclico y toda referencia resuelve
      · toda clave de artefacto es única
      ⇒ un plan inválido falla AQUÍ, no en el paso 47
            │
            ▼
[3] EJECUTOR — AgentsFlow.run_flow(), 0 tokens
      el scheduler YA existe y ya paraleliza (§3)
      cada ToolNode: execute_tool(...) → wm.store_result(key=<del plan>)
      los payloads NUNCA entran en un contexto LLM: no hay LLM aquí
            │
            ▼ (ExecutionManifest: claves, facets, errores)
[4] ANALYST — Opus, long-context
      ya conoce las claves (las escribió en [1])
      wm_get_result / wm_compute_and_store con techo de rehidratación
```

Las cuatro etapas viven **dentro de un `BasicAgent` normal**. El Security Agent no se convierte en un Flow: invoca uno. Ver §6.

La propiedad bonita del diseño: **el planificador nombra los artefactos, así que el analista ya tiene el mapa**. No hace falta que explore con `wm_list_stored`, ni guiatura de descubrimiento. La "búsqueda en WorkingMemory" se reduce a leer claves que el propio modelo eligió.

## 2. El plan debe ser un `FlowDefinition`, no un formato nuevo

Ya existe casi todo en el repo, y conviene no reinventarlo:

- `ToolNode` (`flows/crew/tool_node.py:168`) se autodescribe como *"Deterministic tool-caller crew node (no LLM involved)"*, con placeholders `{input}` y `{nodes.<name>.output}` resueltos por `resolve_templates()` (`tool_node.py:88`), que lanza `TemplateResolutionError` ante referencias desconocidas — **eso ya es media validación de plan, gratis**.
- `AgentsFlow` (`flows/flow/flow.py:173`) es un scheduler de DAG con `add_node`/`add_edge` (`:300`/`:317`), `from_definition`/`to_definition` (`:428`/`:593`) y **`suspend`/`resume` con checkpointing** (`:1046`/`:1074`).

Si el `ExecutionPlan` **es** un `FlowDefinition`, heredas persistencia, reanudación y serialización sin escribir nada. Un pipeline de 300 reportes que muere en el 280 se reanuda; con un runner propio, no.

Lo que sí hay que añadir al lenguaje de plan es **una primitiva de map**, y es la decisión de diseño central:

```json
{
  "id": "parse_all",
  "for_each": "$.list_reports.output.keys[*]",
  "tool": "s3_get_latest_report",
  "args": {"key": "{item}"},
  "store_as": "report_{index}",
  "max_concurrency": 8
}
```

Sin `for_each`, el plan tiene que enumerar los 340 pasos, lo cual (a) requiere que Opus conozca la cardinalidad *antes* de ejecutar nada —imposible— y (b) hace que el plan crezca con los datos, gastando la ventana de salida del planificador. Con `for_each`, **un buen plan tiene ~30 nodos tanto si toca 3 reportes como 3.000**. La expansión la hace el runner en tiempo de ejecución, no el LLM.

La otra primitiva necesaria son las **guardas**: `"when": "$.triage.facets.critical > 0"`, evaluadas contra las `facets` del manifiesto (baratas, estructurales, sin cargar el cuerpo). Con `for_each` + `when`, el "control de flujo dependiente de datos" —la única justificación real que quedaba para un LLM en el bucle— desaparece.

## 3. No hay que escribir el runner: el scheduler ya existe

Corrección respecto a lo que planteaba una versión previa de este doc (construir un runner con `asyncio.gather` + `Semaphore`): **no hace falta**. `AgentsFlow.run_flow()` (`flow.py:896`) ya lo hace, y mejor:

> *"Each node runs as a separate `asyncio.create_task`; a single `asyncio.Queue` collects completion events. The scheduler dispatches downstream nodes incrementally — fast nodes do not wait for slow siblings."*

Eso es **dispatch incremental**, no una barrera por niveles: un nodo arranca en cuanto sus dependencias concretas terminan, sin esperar a hermanos lentos. Es estrictamente mejor que `gather` por capas.

Sobre `to_thread`: **no es la primitiva para el fan-out**. Las tools son I/O-bound (S3, HTTP, Postgres) y la librería es async de arriba abajo; meter I/O async en threads añade overhead y contención sin ganar nada. `to_thread` sí es correcto —y ya se usa así— para la **reducción CPU-bound posterior**: `WorkingMemoryToolkit` lo aplica cuando un DataFrame supera `thread_offload_cells` (1M celdas) para `describe()`/`copy(deep=True)`. Fan-out con el scheduler; `to_thread` sólo en la reducción pandas.

Dos cosas a vigilar bajo concurrencia:

1. **Las claves las asigna el plan, no un contador de runtime.** El contador del `CompressionTee` (`_next_counter`, `tee.py:117`) es seguro en asyncio de un solo hilo pero *no* si algo se mueve a threads. Claves del plan = deterministas, referenciables antes de ejecutar, y sin carrera posible.
2. **`WorkingMemoryCatalog` es un `dict` plano sin lock** (`internals.py:458`). Con `gather` puro (mismo event loop) no hay problema; en cuanto entre `to_thread` en el camino de escritura, hace falta lock. Documentarlo o poner el lock ya.

## 4. `ResultPolicy`: enforcement, no guiatura

El punto conceptual que más valor tiene de toda esta discusión: **lo que ibas a poner en el prompt, ponlo en el enforcement.**

"No llames a `wm_get_result` con `include_raw`" como regla de prompt es una regla que el modelo puede violar bajo presión. Como parámetro del toolkit, no puede.

```python
@dataclass
class ResultPolicy:
    default_level: FilterLevel = FilterLevel.MINIMAL
    max_rehydrate_bytes: int = 2_000_000     # 0 ⇒ este agente no lee raw jamás
    control_fields: tuple[str, ...] = ()      # lo que SÍ vuelve al contexto
```

Hay un agujero real que tapar antes de dar cualquier guiatura de extracción: **`get_result(include_raw=True)` no tiene tope** (`working_memory/tool.py:280-288`). Mete `entry.data` entero en la respuesta; el `max_length=500` sólo aplica al fallback de `repr()` para objetos no serializables. Un `wm_get_result(key, include_raw=true)` sobre un JSON de 40 MB lo vuelca completo en la ventana de Opus, en una sola tool-call, sin aviso.

Hace falta: tope de bytes, paginación (`offset`/`limit`) o proyección (JSONPath), y que el error **diga qué hacer en su lugar** — típicamente `wm_compute_and_store`. Sin eso, la guiatura será "extrae lo que necesites" y el modelo extraerá todo.

**`wm_compute_and_store` es la pieza que hace innecesario rehidratar.** Con `OperationSpecInput` (`working_memory/models.py:104` — filter, aggregate, join, merge, correlate, pivot, rank, group_correlate…) el analista declara la operación y recibe un `compact_summary` de 30 líneas sobre datos que nunca cruzan su contexto. Es la vía barata por defecto; `include_raw` debería ser la excepción justificada.

## 5. El escape hatch: replan acotado

Determinista puro falla cuando la realidad diverge del plan: una tool da error, un reporte no existe, un conteo sale 0 donde el plan asumía datos.

La respuesta **no** es volver a meter un LLM en el bucle. Es un ciclo de replanificación acotado: ejecutar → si hay nodos fallidos o guardas insatisfechas, devolver a Opus el `ExecutionManifest` + los errores → recibir un **plan delta** → ejecutar sólo eso. Máximo 1–2 rondas, con tope duro.

Coste: 0–2 llamadas LLM adicionales, frente a las N del bucle por pasos. Ese es el rol que le quedaba a MiniMax, reducido de N llamadas a casi ninguna — y ejecutado por un modelo que sí razona bien sobre fallos.

## 6. El Security Agent **invoca** un flow; no *es* un flow

Requisito explícito: el Security Agent sigue siendo un `BasicAgent` normal. El flow es su motor de ejecución interno, no su identidad. Se resuelve con **una tool**, sin herencia ni cambios de clase base:

```python
class RunExecutionPlanTool(AbstractTool):
    name = "run_execution_plan"
    args_schema = ExecutionPlanInput          # el plan validado

    async def _execute(self, plan, **kw) -> ExecutionManifest:
        flow = AgentsFlow.from_definition(
            plan.to_flow_definition(),
            agent_registry=EMPTY_REGISTRY,     # ver (d)
            node_factories={"tool": self._tool_node_factory},
            checkpoint=True, durable=True,
        )
        result = await flow.run_flow(plan.objective)
        return project_manifest(result)        # claves + facets + errores; NUNCA payloads
```

El agente hace `ask()` como siempre; entre sus tools hay una que resulta ser un DAG. Cuatro detalles concretos:

**(a) `node_factories` es exactamente el hook para compartir el `ToolManager` y la `WorkingMemory` del agente.** Su docstring lo dice literalmente: factories que *"close over live dependencies (dispatcher, toolkits, …) that cannot travel through the plain `NodeDefinition.config` dict"*, invocadas fresh en cada `run_flow()` para seguridad concurrente. La instancia viaja por el **closure**, no por el JSON del plan — que es justo lo que hace falta para que el analista lea después el mismo catálogo:

```python
def _tool_node_factory(self, node_def, deps, succs):
    return ToolNode(..., tool_manager=self.tool_manager, working_memory=self._wm)
```

**(b) Falta registrar `ToolNode` en `NODE_REGISTRY`.** Hoy el registry tiene `{agent, start, end, decision, interactive_decision, synthesis}` (`flow.py:1791-2029`) — **`tool` no está**: `ToolNode` es un concepto de `AgentCrew` (`add_tool_node`), no de `AgentsFlow`. Pero ya hereda de `..core.node.Node` (`tool_node.py:48,168`), la misma base que `AgentNode`, así que es estructuralmente compatible. Es literalmente `register_node("tool")(ToolNode)`. Una línea.

**(c) El validador debe rechazar nodos `type: "agent"`.** Sin ese guard, un plan con un nodo agente que apunte al propio Security Agent da recursión infinita: agente → tool → flow → agente. Un plan de ejecución es **tool-only por contrato**, y eso refuerza la propiedad que buscamos: el flow es plomería de datos, no una jerarquía de agentes.

**(d) `from_definition` exige `agent_registry` aunque no haya nodos agente.** `flow.py:497-501` hace `if agent_registry is None: raise ValueError(...)` incondicionalmente, pero sólo lo usa para resolver `agent_ref` de nodos `type == "agent"` — de los que un plan puro no tiene ninguno. O pasas un `AgentRegistry()` vacío, o relajas el check a "requerido sólo si el definition contiene nodos agente". Fricción menor, pero sorprende.

**Y checkpointing gratis:** `from_definition(checkpoint=True, durable=True)` da `suspend`/`resume` por `flow_id`, más registro en `FlowRecoveryService` para suspensión en shutdown graceful. Un pipeline de 300 reportes que muere en el 280 se reanuda.

**El punto crítico de la tool:** debe proyectar `FlowResult` a manifiesto, **no** devolver `ctx.results` tal cual. `FlowContext.results` contiene las salidas completas de cada nodo; devolverlas al agente sería meter los payloads en el contexto justo después de haber diseñado todo para evitarlo. Ahí es donde se aplica `ResultPolicy` (§4).

## 7. Cuándo este diseño **no** aplica

Honestidad sobre los límites: plan-then-execute exige que el objetivo sea planificable de antemano. Para trabajo genuinamente exploratorio —donde no sabes qué buscas hasta que ves el resultado anterior, y `for_each` + guardas no bastan para expresarlo— la llamada al planificador se desperdicia y hay que iterar con un modelo en el bucle.

El flow de Security **no** es de ese tipo: listar reportes → parsear → diff → mapear a controles es un pipeline conocido. Merece la pena comprobar esta pregunta explícitamente antes de aplicar el patrón a un caso nuevo.

## 8. Qué sobrevive del diseño anterior (v1) y qué no

**Cae:**

- **`HandleOnlyCodec` / `FilterLevel.AGGRESSIVE`.** Era andamiaje para un problema que ya no existe: si no hay LLM en el bucle, los resultados nunca pasan por un contexto *por construcción*. El runner llama a `execute_tool()` y escribe a WM él mismo. No hace falta ningún codec. (Sigue teniendo sentido implementarlo si algún día se quiere un ejecutor LLM, pero deja de ser prerrequisito.)
- **El prompt de "EXECUTION MODE — HANDLE ONLY"** y el `ExecutionManifest` como salida del ejecutor. El manifiesto ahora lo produce el runner en código, no un modelo.
- **La ejecución por chunks** para acotar el crecimiento del historial. Sin historial, sin problema.

**Sobrevive, y sube de prioridad:**

- **`max_iterations` en `BedrockConverseClient`** (`bedrock.py:738` es `while True:`). Sigue siendo un riesgo de coste para *cualquier* agente sobre Bedrock, no sólo el ejecutor. `base.py:1292` ya reenvía el kwarg si el cliente lo declara en su firma → ~15 líneas.
- **El helper de desenvoltura de toolkits.** `BasicAgent._inject_answer_memory_into_toolkits()` (`agent.py:145`) hace `isinstance(tool, WorkingMemoryToolkit)` sobre wrappers `ToolkitTool` y **no matchea nunca**; `manager.py:1799-1802` lo hace bien desenvolviendo `bound_method.__self__`. Unificar.
- **Las `facets` / `describe_fn` por tool.** Cambian de motivación —ya no son para que un modelo pequeño ramifique, sino para que las **guardas del plan** evalúen condiciones sin cargar cuerpos— pero siguen siendo necesarias.
- **`ResultPolicy` y el techo de rehidratación** (§4).
- **El backend persistente para `WorkingMemoryCatalog`** (§9).

## 9. Roadmap

1. ~~**`ExecutionPlan` = `FlowDefinition` + `for_each` + `when`**~~ — **hecho.** Módulo `plan/`: `models.py` (schema), `paths.py` (selector), `guards.py` (CEL), `facets.py`, `validator.py`, `compile.py`.
2. ~~**`PlanToolNode` + `make_tool_node_factory`**~~ — **hecho.** Despacha por `ToolManager.execute_tool()`, escribe a WM y publica `ArtifactRef`. 60 tests en verde. Queda pendiente `register_node("tool")(PlanToolNode)` y la tool `run_execution_plan` con proyección a manifiesto vía `build_manifest()` (§6).
3. **`ResultPolicy` + tope/paginación en `get_result(include_raw=True)`**, con mensaje de error que redirija a `wm_compute_and_store`.
4. **`max_iterations` en Bedrock** y helper de toolkits (independientes, baratos, quitan riesgo hoy).
5. **Replan acotado** (§5).
6. **Aplicar al flow de Security**: planner Opus → runner → analista sobre el mismo `WorkingMemoryToolkit` compartido (instancia única vía `shared_tool_manager`).
7. **`describe_fn` por tool** para los parsers de security (conteos por severidad como facets).

## 10. Riesgo estructural

`WorkingMemoryCatalog` es un `dict` en el proceso: sin TTL, sin límite de bytes, sin persistencia (`internals.py:458`). Con ejecución paralela sobre reportes de scanners de cientos de MB, eso es la RAM del proceso durante todo el pipeline — y multiplicada por el fan-out, que es justamente lo que este diseño maximiza.

Necesita un backend pluggable con *spill* a disco/S3 e índice en Postgres: exactamente el patrón de `PostgresS3SecurityReportStore`. Conviene fijar la interfaz **antes** del paso 2, porque el ejecutor es su primer consumidor pesado y cambiar el catálogo después toca a todos.
