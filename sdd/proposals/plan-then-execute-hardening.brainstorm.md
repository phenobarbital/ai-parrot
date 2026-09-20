---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
projects: [ai-parrot, docs]
tags: [execution-plan, checkpointing, working-memory, replan, result-policy]
---

# Brainstorm: Plan-then-Execute Hardening — replan acotado, reanudación real y techo de rehidratación

**Date**: 2026-09-20
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: B

---

## Problem Statement

`ExecutionPlanToolkit` (FEAT-419) implementa la arquitectura plan-then-execute del
diseño `handle-only-execution-design.md`: un modelo thinking escribe el plan una
vez, el código lo valida estáticamente y lo ejecuta sobre `AgentsFlow` con cero
tokens LLM en el bucle, y los payloads van a `WorkingMemory` sin tocar ningún
contexto. Esa parte funciona y está en verde.

Quedaron cuatro brechas entre lo diseñado y lo construido. La auditoría completa,
con evidencia por fichero y línea, está en
`sdd/proposals/plan-then-execute-design-drift.findings.md` §4; el diseño fuente se
copió a `sdd/proposals/handle-only-execution-design.input.md` porque el original
vive bajo `artifacts/`, que está en `.gitignore` y por tanto es invisible para
cualquier worktree.

**1. No hay replan acotado.** El diseño §5 pide que, cuando la realidad diverge del
plan (una tool falla, un reporte no existe, un conteo sale 0), el manifiesto y los
errores vuelvan al planner, que devuelve un plan delta que se ejecuta sólo sobre lo
fallido — máximo 1–2 rondas con tope duro. Hoy no existe nada: el manifiesto reporta
`partial | failed` y ahí se acaba la historia. El agente puede volver a emitir el plan
entero, pero eso no es un delta y gasta una autoría completa.

**2. El checkpointing está apagado a propósito y la reanudación es ficticia.**
`toolkit.py:219` pasa `checkpoint=False` con un comentario explícito: encenderlo
exigiría un checkpoint store vivo antes de que despache el primer nodo, lo que
contradiría el "v1 pure in-RAM" de FEAT-419. La consecuencia es que la promesa del
diseño §6 —"un pipeline de 300 reportes que muere en el 280 se reanuda"— no se
cumple: lo que hay es idempotencia (`ForEach.skip_existing` evita rehacer lo hecho)
y sólo mientras el proceso viva, porque el registro de runs es un `dict` en RAM
(`self._runs`, `toolkit.py:158`). Un reinicio pierde el run entero, incluido el
`run_id` que el agente tiene en su contexto.

Lo que cambia el cálculo: **FEAT-399 está completo** — Redis efímero con TTL 24h,
historial acotado, tier durable opt-in, lease por flow, `suspend`/`resume`. No hay
que construir nada de eso. Y Redis es default en la infraestructura de ai-parrot.

**3. El techo de rehidratación existe pero está apagado por defecto.** El agujero
que el diseño §4 describe —`wm_get_result(key, include_raw=true)` volcando un JSON
de 40 MB en la ventana del analista, en una sola tool-call, sin aviso— tiene su fix
implementado en FEAT-538 (`tool.py:451` `_apply_raw_policy`), fiel al diseño hasta
en el default de 2 MB. Pero vive detrás de `if self._catalog.is_enabled`, y
`WorkingMemoryToolkit()` sin `task_memory=` cae al camino legacy sin tope,
preservado byte-idéntico por decisión explícita de FEAT-538 (AC13). Esa es
exactamente la configuración que el ejemplo de `docs/toolkits/execution_plan_toolkit.md`
enseña a montar.

**4. El helper de desenvoltura de toolkits lleva roto desde siempre.**
`agent.py:234` `_inject_answer_memory_into_toolkits()` hace
`isinstance(tool, WorkingMemoryToolkit)` sobre la lista de tools registradas, que
contiene wrappers `ToolkitTool`, no toolkits. Nunca matchea. `ToolManager` ya
resuelve esto bien (`manager.py:2589`, vía `bound_method.__self__`). El bug se
documentó como si fuera diseño: la referencia del toolkit instruye inyección por
constructor *"never auto-detected"*.

**Afectados**: desarrolladores que construyen agentes con planes deterministas
(hoy, un solo consumidor interno y ningún flow de producción con fan-out real);
ops, cuando un plan largo muere a mitad; y cualquier agente que monte
`WorkingMemoryToolkit` suelto, por la brecha 3.

## Constraints & Requirements

- Decisiones cerradas en la discovery de este brainstorm (§ Open Questions las
  refleja como resueltas):
  - **D1** El replan lo dispara el agente con una tool propia, nunca automáticamente
    dentro de `plan_execute`. La propiedad "cero tokens LLM durante la ejecución"
    no se toca.
  - **D2** El delta sólo puede re-emitir nodos con `status="error"` o nunca
    despachados. Jamás toca un nodo ok, ni añade nodos nuevos.
  - **D3** La reanudación es cross-restart real: otro proceso recoge un `run_id`
    y continúa.
  - **D4** El estado del run se **deriva del checkpoint**, no se persiste un
    segundo objeto que pueda desincronizarse.
  - **D5** La reanudación la dispara el agente (`plan_resume`), nunca un servicio
    en el arranque.
  - **D6** El techo de rehidratación se enciende **en contexto de plan**, adjuntando
    un backend de artefactos; no se invierte el default global de
    `WorkingMemoryToolkit` (AC13 de FEAT-538 sigue en pie fuera del plan).
  - **D7** El toolkit adjunta el tier durable cuando está configurado y cae a
    in-memory si no; el manifiesto declara qué nivel de reanudación tiene el run.
  - **D8** Sin Redis el run se ejecuta igual, sin checkpoint, y el manifiesto y
    `plan_status` lo dicen como dato — no como log que nadie lee.
  - **D9** El helper se arregla sin flag: es la conducta que el código siempre
    dijo tener.
- El módulo `parrot/bots/flows/plan/` es **contrato congelado** de FEAT-419
  (60 tests). Esta feature no redefine `ExecutionPlan`, `PlanNode`, `ForEach`,
  `when` ni `PlanToolNode._resolve_args`.
- El agente invocante sigue siendo un `BasicAgent`. Ninguna tool nueva lo convierte
  en Flow ni en Crew.
- Toda respuesta de tool sigue acotada por construcción: manifiestos y
  `ArtifactRef`, nunca payloads.
- El allowlist `allowed_tools` sigue siendo la frontera de seguridad: un plan delta
  se valida contra el mismo catálogo que el plan original.
- Python 3.10+, Pydantic v2, async nativo, `aiohttp`. Sin dependencias nuevas:
  Redis entra por `asyncdb`, que FEAT-399 ya usa.
- Conducta sin configurar: un `ExecutionPlanToolkit` montado como hoy debe seguir
  funcionando. Las capacidades nuevas no pueden exigir infra para arrancar.

---

## Options Explored

### Option A: Cirugía local — cuatro cambios independientes, sin capa nueva

Cada brecha se arregla donde vive, sin introducir abstracciones. `plan_repair` y
`plan_resume` se añaden como dos tools más del toolkit, cada una con su propio
manejo de estado. `_run_plan` pasa `checkpoint=True` y un `flow_factory`. El
`RunRecord` se enriquece con lo necesario para que `plan_status` responda tras un
reinicio, leyendo el checkpoint cuando el run no está en `self._runs`. El
constructor del toolkit adjunta un backend de artefactos a la WorkingMemory que
recibe. El helper se arregla reutilizando el idiom de `manager.py`.

✅ **Pros:**
- Diffs pequeños y localizados; cada brecha es revisable por separado.
- Máxima paralelización: cuatro tareas casi sin solape de ficheros.
- Riesgo de regresión mínimo sobre FEAT-419, que está estable y en verde.
- La brecha 4 (helper) y la 3 (techo) son entregables en días, no semanas.

❌ **Cons:**
- El estado de un run queda repartido entre dos sitios: `self._runs` para los vivos
  y el checkpoint para los resucitados. Dos caminos de lectura en `plan_status`,
  `plan_artifacts`, `plan_repair` y `plan_resume` — cuatro sitios donde pueden
  divergir, que es justo lo que D4 quería evitar.
- `plan_repair` y `plan_resume` acaban duplicando lógica: ambas necesitan cargar un
  run, comprobar que se puede continuar, tomar un lease y fusionar manifiestos.
- No hay un punto único donde declarar "este run es reanudable a nivel X" (D7/D8),
  así que la degradación se reporta a mano en cada tool.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `asyncdb` | Cliente Redis del `RedisCheckpointStore` | Ya en el árbol vía FEAT-399; sin dependencia nueva |
| `pydantic` v2 | Modelos de las tools nuevas | Ya es el estándar del repo |

🔗 **Existing Code to Reuse:**
- `parrot/tools/execution_plan/toolkit.py:165` — `_run_plan()`, punto único donde
  se construye el flow y se registra el run.
- `parrot/tools/manager.py:2589` — el idiom correcto de desenvoltura.
- `parrot/bots/flows/core/checkpoint/` — store, lease y modelos de FEAT-399.

---

### Option B: `PlanRun` como entidad derivada del checkpoint

Se introduce una única abstracción: el **run** deja de ser un `dict` en RAM y pasa
a ser una entidad con una fuente de verdad, el checkpoint del flow. `self._runs`
sobrevive sólo como caché del proceso vivo y como único almacén para los runs
degradados (sin Redis, D8).

Todas las operaciones sobre un run —`plan_status`, `plan_artifacts`, `plan_repair`,
`plan_resume`— pasan por un resolvedor común: dado un `run_id`, devuelve el run
(de la caché o reconstruido desde el checkpoint), su nivel de reanudabilidad y su
manifiesto. El `run_id` del toolkit y el `flow_id` de FEAT-399 se unifican en un
solo identificador, de modo que el agente sigue viendo un único token opaco.

`plan_repair` y `plan_resume` se construyen sobre ese resolvedor y comparten el
lease por flow que FEAT-399 ya provee, así que dos agentes no pueden continuar el
mismo run a la vez. El replan pide al planner un delta acotado a los nodos fallidos
(D2), lo valida contra el mismo allowlist y lo ejecuta como un run hijo que hereda
las claves ya escritas; el manifiesto consolidado suma padre e hijo.

El techo de rehidratación se enciende adjuntando un backend de artefactos según
D6/D7: durable si el despliegue lo tiene configurado, in-memory si no.

✅ **Pros:**
- Una sola fuente de verdad para el estado del run (D4), y un solo sitio donde
  decidir y declarar el nivel de reanudación (D7/D8).
- `plan_repair` y `plan_resume` comparten la máquina de estados en vez de
  duplicarla: ambas son "continuar un run", con distinta causa.
- El lease de FEAT-399 resuelve la concurrencia sin inventar nada.
- Cross-restart cae por su propio peso: si el estado se deriva del checkpoint,
  el proceso que lo lee es irrelevante.
- Deja el toolkit en forma para el consumidor de producción que aún no existe
  (el flow de Security Advisory, findings §5.1).

❌ **Cons:**
- Toca el núcleo de un toolkit estable: `_run_plan`, las cuatro tools y el registro.
  Mayor superficie de regresión que la Opción A.
- Exige decidir qué significa exactamente "derivar el manifiesto del checkpoint"
  — el checkpoint guarda `results` y `completion_order`, y hay que confirmar que
  eso basta para reconstruir los `ArtifactRef` sin recomputar nada.
- Menos paralelizable: el resolvedor es dependencia de casi todo lo demás.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `asyncdb` | Redis del checkpoint store | Vía FEAT-399, sin dependencia nueva |
| `pydantic` v2 | Modelos de run, delta y manifiesto consolidado | Estándar del repo |
| `ormsgpack` | Serialización de checkpoints | Ya la usa FEAT-399; nunca pickle |

🔗 **Existing Code to Reuse:**
- `parrot/bots/flows/flow/flow.py:1421` — `AgentsFlow.resume()` con `flow_factory`,
  el hook que hace viable reconstruir un flow con nodos de dependencias vivas.
- `parrot/bots/flows/core/checkpoint/store/redis.py:53` — `RedisCheckpointStore`,
  con `list_flows()`, `acquire_lease()` y TTL.
- `parrot/tools/execution_plan/planner.py:174` — `PlanPlanner.repair()`, cuyo idiom
  de una llamada por ronda se replica para el delta (es reparación estructural, no
  replan — ver Code Context).
- `parrot/bots/flows/plan/node.py:535` — `PlanToolNode` ya escribe con
  `await catalog.aput_generic()` cuando el catálogo está enabled.

---

### Option C: `plan_continue` — una sola tool para reanudar y replanificar

Variante de B que lleva la unificación hasta la superficie: en vez de dos tools,
una sola `plan_continue(run_id)` que inspecciona por qué el run no terminó y actúa
en consecuencia — si murió el proceso, reanuda desde el checkpoint; si terminó con
nodos fallidos, pide el delta al planner. El agente aprende una operación en lugar
de dos, y el tope de rondas es uno solo para ambas causas.

✅ **Pros:**
- Superficie mínima para el modelo: un `run_id` fallido siempre se trata igual.
- Imposible que el agente elija mal la tool, porque no hay elección.
- Un único tope acotando el gasto total de continuar un run.

❌ **Cons:**
- Fusiona dos causas que el operador querrá distinguir: "se cayó el pod" y "el
  reporte no existía" tienen implicaciones distintas y una sola tool las aplana.
- Una reanudación no gasta tokens y un replan sí; esconderlo tras la misma tool
  hace impredecible el coste de la llamada, que es justo lo que este diseño
  optimiza.
- Contradice D1 en espíritu: el agente pide "continuar", no "replanificar", y
  puede acabar pagando una autoría sin haberla pedido.

📊 **Effort:** High

📦 **Libraries / Tools:** las mismas que la Opción B.

🔗 **Existing Code to Reuse:** las mismas que la Opción B.

---

### Option D: Sin registro — el run *es* el flow suspendido (no convencional)

El toolkit elimina su registro por completo. No hay `RunRecord`, ni caché, ni
`self._runs`: `plan_status(run_id)` consulta el checkpoint store
(`list_flows()` / `latest()`) y reconstruye lo que necesite al vuelo. El estado del
run vive exclusivamente donde FEAT-399 ya lo pone, y el toolkit se vuelve stateless
entre llamadas.

✅ **Pros:**
- La simplificación más radical posible: cero estado propio, cero desincronización
  concebible, cross-restart gratis en todos los caminos por construcción.
- El toolkit pasa a ser seguro de montar en varios procesos sin coordinación.
- Elimina `_evict_completed_runs()` y toda la gestión de ciclo de vida del registro.

❌ **Cons:**
- Convierte Redis en requisito duro, lo que contradice D8 frontalmente: un
  despliegue sin checkpoint store perdería incluso `plan_status`, que hoy funciona
  siempre. Habría que reintroducir un almacén in-RAM para el modo degradado — es
  decir, volver a tener dos caminos, que es lo que esta opción prometía eliminar.
- Cada `plan_status` durante un run largo se convierte en I/O a Redis; hoy es una
  lectura de `dict`. El polling es justo el patrón que el soft-timeout fomenta.
- `plan_artifacts` depende de `self._run_contexts`, que no se persiste: habría que
  derivarlo también del checkpoint o aceptar que sólo funciona durante el run.

📊 **Effort:** High

📦 **Libraries / Tools:** las mismas que la Opción B.

🔗 **Existing Code to Reuse:**
- `parrot/bots/flows/core/checkpoint/store/redis.py:139` — `list_flows(status=...)`,
  que ya permite enumerar runs sin registro propio.

---

## Recommendation

**Option B** es la recomendada.

La Opción A es tentadora por su bajo riesgo, y de hecho **dos de sus cuatro piezas
son correctas tal cual**: el fix del helper (brecha 4) y el encendido del techo de
rehidratación (brecha 3) no necesitan ninguna abstracción nueva y deben
implementarse como cirugía local en cualquier opción que se elija. La diferencia
está en las otras dos. En cuanto la reanudación tiene que ser cross-restart (D3) y
el estado tiene que derivarse del checkpoint (D4), la Opción A obliga a escribir
ese "derivar del checkpoint" cuatro veces —una por tool— y a decidir cuatro veces
qué hacer cuando el checkpoint no existe. Eso no es cirugía local: es la misma capa
de B, implementada de forma difusa y sin nombre.

Frente a C: unificar `resume` y `repair` en una sola tool ahorra superficie para el
modelo, pero mezcla una operación gratuita con una que cuesta tokens. Dado que todo
este diseño existe precisamente para hacer predecible el gasto, esconder una
autoría del planner detrás de una tool llamada "continuar" es el tipo de comodidad
que se paga en facturas sorpresa. Dos tools, dos costes visibles.

Frente a D: es la más elegante y la que peor encaja con D8. La opción muere en su
propia letra pequeña — al reintroducir el modo degradado vuelve a tener dos
caminos, sin la ventaja de haberlos evitado. Merece quedar registrada porque, si
algún día Redis pasa a ser requisito duro del toolkit, D es hacia dónde debería
converger B.

Lo que se acepta al elegir B: más superficie de regresión sobre un toolkit estable
y en verde, y una feature menos paralelizable, porque el resolvedor de runs es
dependencia de casi todo lo demás. Se mitiga ordenando las tareas: las dos piezas
independientes (helper y techo de rehidratación) van primero y aterrizan valor sin
tocar el núcleo; el resolvedor, el checkpointing y el replan van después, en ese
orden, cada uno sobre el anterior.

---

## Feature Description

### User-Facing Behavior

El desarrollador que monta un `ExecutionPlanToolkit` no cambia nada de su wiring
actual y obtiene tres cosas nuevas.

**Reanudación.** Cuando un plan largo muere —el pod se reinicia, el proceso cae— el
`run_id` que el agente tiene en su contexto sigue siendo válido. Un proceso nuevo
responde `plan_status(run_id)` con el progreso real y la indicación de que el run
es reanudable; el agente llama a `plan_resume(run_id)` y la ejecución continúa sin
repetir los nodos completados. Si el despliegue no tiene checkpoint store, todo
esto sigue funcionando *dentro* del proceso y tanto el manifiesto como
`plan_status` declaran que el run no es reanudable — el agente lo lee como dato,
no hay promesa incumplida.

**Replan acotado.** Cuando un run termina `partial` o `failed`, el manifiesto ya
dice qué nodos fallaron y por qué. El agente puede llamar a `plan_repair(run_id)`:
el planner recibe el plan original más el manifiesto con los errores y devuelve un
delta que re-emite únicamente los nodos fallidos o bloqueados. El delta se valida
contra el mismo allowlist y se ejecuta; el resultado es un manifiesto consolidado
que suma lo que ya estaba bien y lo que se ha recuperado. Hay un tope duro de
rondas: agotado, `plan_repair` se niega y lo dice. Un run que terminó bien no se
repara.

**Techo de rehidratación.** El analista que lee los artefactos ya no puede volcarse
un payload arbitrario en el contexto: `wm_get_result(..., include_raw=true)` sobre
un valor grande no devuelve el payload, devuelve por qué no cabe y qué hacer en su
lugar (`wm_compute_and_store`). Los valores tabulares se pueden paginar. Esto
aplica a la WorkingMemory que el plan usa; un `WorkingMemoryToolkit` montado por
fuera conserva su conducta actual.

Además, `answer_memory` pasa a inyectarse de verdad en los toolkits registrados —
lo que el código siempre dijo hacer y nunca hizo.

### Internal Behavior

**Resolución de runs.** Una pieza común traduce `run_id` en el estado del run. Busca
primero en la caché del proceso; si no está, reconstruye desde el checkpoint. Es el
único sitio que sabe que un run puede venir de dos orígenes, y el único que decide
el nivel de reanudabilidad —completo, sólo dentro del proceso, o ninguno— a partir
de qué tiers hay realmente conectados. Todas las tools consultan este resolvedor;
ninguna lee el registro directamente.

**Ejecución con checkpoint.** `_run_plan` deja de forzar `checkpoint=False` y
habilita el checkpointing cuando hay store disponible, unificando `run_id` y
`flow_id`. La reconstrucción del flow al reanudar usa `flow_factory`, porque
`PlanToolNode` lleva dependencias vivas (el `ToolManager`, la WorkingMemory, el
contexto de permisos, el id de run) que no viajan por el `NodeDefinition`; es el
mismo `make_tool_node_factory` que usa el arranque, invocado de nuevo. La ausencia
de store no es un error: se ejecuta sin checkpoint y el nivel de reanudabilidad del
run lo refleja.

**Replan.** El planner recibe el plan y el manifiesto y produce un delta. La
validación del delta es la del plan original —mismo `validate_plan`, mismo catálogo
acotado por `allowed_tools`— más una comprobación adicional: ningún nodo del delta
puede corresponder a un nodo que terminó ok. El delta se ejecuta como una
continuación del run, heredando las claves ya escritas, de modo que
`ForEach.skip_existing` sigue protegiendo el trabajo hecho. El manifiesto
consolidado es el del padre con los nodos recuperados actualizados.

**Techo de rehidratación.** Al construirse, el toolkit se asegura de que la
WorkingMemory que va a usar tenga un backend de artefactos adjunto: el durable si el
despliegue lo tiene configurado, uno in-memory si no. Con el backend presente,
`_apply_raw_policy` entra en juego sin tocar su código. El camino de escritura del
plan ya es compatible: `PlanToolNode` usa la API awaited del catálogo cuando está
enabled.

**Helper.** La detección del toolkit propietario de una tool se unifica en un único
sitio, con el idiom que `ToolManager` ya usa, y `BasicAgent` pasa a consumirlo. La
documentación que hoy enseña el workaround como diseño se corrige.

### Edge Cases & Error Handling

- **Sin Redis.** El run arranca igual, sin checkpoint. El manifiesto y `plan_status`
  declaran el nivel de reanudación. `plan_resume` sobre un run así explica que no
  hay checkpoint, no lanza una excepción opaca.
- **Backend in-memory + reanudación en otro proceso.** El checkpoint dice que un
  nodo se completó, pero su artefacto murió con el proceso anterior. Por eso D7
  prefiere el tier durable cuando existe, y por eso el nivel de reanudabilidad que
  declara el run depende del tier real, no de que haya checkpoint. Es la tensión
  que hay que resolver con más cuidado de toda la feature — ver Open Questions.
- **Dos agentes continúan el mismo run.** El lease por flow de FEAT-399 lo impide;
  el segundo recibe un rechazo explícito.
- **Tope de rondas agotado.** `plan_repair` se niega y devuelve el manifiesto tal
  cual, con el motivo. Nunca una ronda extra silenciosa.
- **El delta vuelve inválido.** Se aplica la política de reparación que ya existe
  para la autoría: una ronda de corrección estructural, y si sigue inválido, error
  con la lista completa de issues.
- **El delta intenta tocar un nodo ok.** Se rechaza en validación, no en ejecución.
- **`run_id` desconocido.** Conducta actual preservada: error explícito listando
  los runs conocidos.
- **Un run completado hace mucho.** El TTL de Redis (24h por defecto) lo expira;
  `plan_status` debe distinguir "no existió" de "expiró", porque para el agente son
  situaciones distintas.
- **Arreglar el helper cambia conducta.** `answer_memory` empieza a inyectarse donde
  nunca se inyectó. Es deliberado (D9), y la feature lo cubre con tests.

---

## Capabilities

### New Capabilities
- `plan-run-resolution`: estado del run derivado del checkpoint, con nivel de
  reanudabilidad declarado, compartido por todas las tools del toolkit.
- `plan-resume`: reanudación cross-restart de un run por su `run_id`, disparada por
  el agente.
- `plan-repair`: replan acotado a nodos fallidos, con tope duro de rondas y
  manifiesto consolidado.

### Modified Capabilities
- `execution-plan-tool` (FEAT-419): `_run_plan` deja de forzar `checkpoint=False`;
  el registro de runs pasa a ser caché; el toolkit garantiza el backend de
  artefactos de su WorkingMemory.
- `workingmemory-toolkit` (FEAT-538): el techo de rehidratación se activa en
  contexto de plan. AC13 sigue vigente fuera de él.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/tools/execution_plan/toolkit.py` | modifies | `_run_plan`, las cuatro tools, el registro; dos tools nuevas |
| `parrot/tools/execution_plan/models.py` | extends | Modelos de run resuelto, nivel de reanudación, args de las tools nuevas |
| `parrot/tools/execution_plan/planner.py` | extends | Método hermano de `repair()` para el delta desde un manifiesto |
| `parrot/bots/agent.py` | modifies | `_inject_answer_memory_into_toolkits` pasa a usar el idiom correcto |
| `parrot/tools/manager.py` | extends | El idiom de desenvoltura se expone como helper reutilizable |
| `parrot/bots/flows/plan/` | depends on | **Congelado.** Se consume `ForEach.skip_existing`, `build_manifest`, `ArtifactRef` |
| `parrot/bots/flows/flow/flow.py` | depends on | `resume(flow_factory=...)`, `suspend()`; no se modifica |
| `parrot/bots/flows/core/checkpoint/` | depends on | Store, lease, TTL de FEAT-399; no se modifica |
| `parrot/tools/working_memory/tool.py` | depends on | `_apply_raw_policy` se consume tal cual; no se toca su lógica |
| `docs/toolkits/execution_plan_toolkit.md` | modifies | Retirar el workaround documentado como diseño; documentar las tools nuevas |
| Despliegue | depends on | Redis pasa a ser recomendado, nunca obligatorio |

Sin dependencias nuevas. Sin breaking changes fuera del contexto de plan: un agente
que hoy usa `WorkingMemoryToolkit` suelto no cambia de conducta, salvo por la
inyección de `answer_memory` que el código siempre prometió.

---

## Code Context

### User-Provided Code

El usuario aportó el documento de diseño completo, ahora versionado en
`sdd/proposals/handle-only-execution-design.input.md`. Los fragmentos que fijan
requisitos de esta feature:

```python
# Source: sdd/proposals/handle-only-execution-design.input.md §4
# Forma PROPUESTA en el diseño — NO es la forma implementada (ver abajo).
@dataclass
class ResultPolicy:
    default_level: FilterLevel = FilterLevel.MINIMAL
    max_rehydrate_bytes: int = 2_000_000     # 0 ⇒ este agente no lee raw jamás
    control_fields: tuple[str, ...] = ()      # lo que SÍ vuelve al contexto
```

Del §5, el contrato del replan, verbatim:

> ejecutar → si hay nodos fallidos o guardas insatisfechas, devolver a Opus el
> `ExecutionManifest` + los errores → recibir un **plan delta** → ejecutar sólo eso.
> Máximo 1–2 rondas, con tope duro.

### Verified Codebase References

#### Classes & Signatures

```python
# From packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py:99
class ExecutionPlanToolkit(AbstractToolkit):
    def __init__(
        self,
        ...
        soft_timeout: float = 60.0,     # line 107
    ):
        self.soft_timeout = soft_timeout                        # line 150
        self._runs: Dict[str, RunRecord] = {}                   # line 158
        self._run_tasks: Dict[str, "asyncio.Task"] = {}         # line 160
        self._run_contexts: Dict[str, FlowContext] = {}         # line 161

    async def _run_plan(self, plan, source) -> ToolResult:      # line 165
        ...
    @tool_schema(PlanStatusArgs)
    async def plan_status(self, run_id: str) -> ToolResult:     # line 388
    @tool_schema(PlanArtifactsArgs)
    async def plan_artifacts(self, run_id: str) -> ToolResult:  # line 411
    @tool_schema(PlanExecuteArgs)
    async def plan_execute(self, ...) -> ToolResult:            # line 435
    @tool_schema(PlanValidateArgs)
    async def plan_validate(self, ...) -> ToolResult:           # line 463

# From packages/ai-parrot/src/parrot/tools/execution_plan/models.py:34
class RunRecord(BaseModel):
    run_id: str                                                  # line 56
    plan_name: str                                               # line 57
    source: Literal["objective", "plan_name"]                    # line 58
    status: Literal["running", "completed", "partial", "failed"] # line 59
    started_at: datetime                                         # line 60
    finished_at: Optional[datetime] = None                       # line 61
    manifest: Optional[ExecutionManifest] = None                 # line 62
    nodes_total: int                                             # line 63
    nodes_done: int = 0                                          # line 64
    flow_error: Optional[str] = None                             # line 65

# From packages/ai-parrot/src/parrot/tools/execution_plan/models.py:68
class RunningSummary(BaseModel):
    run_id: str                                   # line 73
    status: Literal["running"] = "running"        # line 74
    plan_name: str                                # line 75
    nodes_total: int                              # line 76
    nodes_done: int                               # line 77
    hint: str = "poll plan_status(run_id)"        # line 78

# From packages/ai-parrot/src/parrot/tools/execution_plan/planner.py:127
class PlanPlanner:
    def __init__(self, planner_llm, catalog: Sequence[ToolCatalogEntry]) -> None:  # line 136
    async def author(self, objective: str) -> ExecutionPlan:                       # line 151
    async def repair(                                                              # line 174
        self, plan_json: Dict[str, Any], report: ValidationReport
    ) -> ExecutionPlan:
        """Re-prompt once with ``report``'s text embedded verbatim."""

# From packages/ai-parrot/src/parrot/bots/flows/flow/flow.py:1421
class AgentsFlow(PersistenceMixin):
    @classmethod
    async def resume(
        cls,
        flow_id: str,
        checkpoint_id: Optional[int] = None,
        *,
        agent_registry: AgentRegistry,
        store: Optional[Union[str, CheckpointStore]] = None,
        durable_store: Optional[Union[str, CheckpointStore]] = None,
        flow_factory: Optional[Callable[[FlowDefinition], "AgentsFlow"]] = None,
        seed_context: Optional[FlowContext] = None,
        expected_input: Optional[CheckpointInputMetadata] = None,
    ) -> "AgentsFlow":
        ...
    async def suspend(self) -> FlowCheckpoint:   # line 1394

# From packages/ai-parrot/src/parrot/bots/flows/core/checkpoint/store/redis.py:53
class RedisCheckpointStore(CheckpointStore):
    async def put(self, checkpoint: FlowCheckpoint) -> None:                    # line 93
    async def latest(self, flow_id: str) -> FlowCheckpoint | None:              # line 112
    async def get(self, flow_id: str, checkpoint_id: int) -> FlowCheckpoint|None # line 120
    async def history(self, flow_id: str, limit: int = 10) -> list[FlowCheckpoint]  # line 128
    async def list_flows(self, status: str | None = None) -> list[dict[str, Any]]   # line 139
    async def acquire_lease(self, flow_id: str, holder: str, ttl: int = 60) -> bool # line 182

# From packages/ai-parrot/src/parrot/tools/working_memory/tool.py
class WorkingMemoryToolkit(AbstractToolkit):
    DEFAULT_MAX_REHYDRATE_BYTES: int = 2_000_000         # line 272
    def __init__(
        self,
        session_id: Optional[str] = None,
        max_rows: int = 10,
        max_cols: int = 30,
        tool_locals_registry: Optional[dict[str, dict]] = None,
        answer_memory: Optional[Any] = None,
        thread_offload_cells: Optional[int] = None,
        task_memory: Optional[Any] = None,        # ← el interruptor de FEAT-538
        **kwargs,
    ):
    async def get_result(                          # line 400
        self, key: str, max_length: int = 500, include_raw: bool = False,
        max_rehydrate_bytes: Optional[int] = None, offset: int = 0,
        limit: Optional[int] = None,
    ) -> dict:
    def _apply_raw_policy(self, summary, entry, *, max_length,        # line 451
                          max_rehydrate_bytes, offset, limit) -> None:
    def _resolve_raw_budget(self, requested: Optional[int]) -> int:   # line 274

# From packages/ai-parrot/src/parrot/tools/working_memory/internals.py:794
class WorkingMemoryCatalog:
    def __init__(
        self,
        session_id: Optional[str] = None,
        *,
        backend: Optional["ArtifactStore"] = None,   # atarlo habilita el techo
        scope: Optional["TaskScope"] = None,         # OBLIGATORIO si hay backend
        task_id: Optional[str] = None,
    ) -> None:
        # Raises ValueError si backend sin scope (line 824)
        self._lock = asyncio.Lock()                  # line 834
    @property
    def is_enabled(self) -> bool: ...                # el backend está adjunto
    @property
    def backend(self) -> Optional["ArtifactStore"]: ...

# From packages/ai-parrot/src/parrot/tools/working_memory/task_memory/artifacts.py:290
class InMemoryArtifactStore: ...
    async def spill(...)                              # line 200 (SpillHandler)

# From packages/ai-parrot/src/parrot/bots/agent.py:234 — EL BUG
class BasicAgent(...):
    def _inject_answer_memory_into_toolkits(self) -> None:
        for tool in tool_iter:
            # NUNCA matchea: `tool` es un ToolkitTool, no el toolkit
            if isinstance(tool, WorkingMemoryToolkit) and tool._answer_memory is None:
                tool._answer_memory = self.answer_memory

# From packages/ai-parrot/src/parrot/tools/manager.py:2589 — EL IDIOM CORRECTO
owner = getattr(getattr(tool, "bound_method", None), "__self__", None)
if isinstance(owner, WorkingMemoryToolkit):
    return owner

# From packages/ai-parrot/src/parrot/bots/flows/plan/models.py
class ForEach(BaseModel):
    max_items: int = Field(default=1000, ge=1, le=100_000)      # line 154
    max_concurrency: int = Field(default=8, ge=1, le=64)        # line 155
    skip_existing: bool = True                                  # line 157
class PlanMetadata(BaseModel):                                  # line 257
    checkpoint: bool = True                                     # line 264 (hoy IGNORADO)
```

#### Verified Imports

```python
# Confirmados contra los __init__.py del árbol:
from parrot.tools.execution_plan import (          # execution_plan/__init__.py:26-40
    ExecutionPlanToolkit, PlanPlanner, PlanAuthoringError,
    RunRecord, RunningSummary, PlanFileStore, build_catalog,
)
from parrot.bots.flows.plan import (               # flows/plan/__init__.py:17,69
    ensure_tool_node_registered,
)
from parrot.bots.flows.core.checkpoint import (    # checkpoint/__init__.py:8-30
    CheckpointStore, DurableCheckpointStore, RedisCheckpointStore,
    FlowCheckpoint, FlowCheckpointer, FlowLockedError,
    FlowRecoveryService, get_checkpoint_store, get_recovery_service,
    CheckpointInputMetadata, CheckpointNotFoundError,
    CheckpointPersistenceError,
)
```

#### Key Attributes & Constants

- `ExecutionPlanToolkit._runs` → `Dict[str, RunRecord]` (toolkit.py:158) — el
  registro in-RAM que esta feature convierte en caché.
- `ExecutionPlanToolkit._run_contexts` → `Dict[str, FlowContext]` (toolkit.py:161)
  — de donde `plan_artifacts` lee; **no** se persiste hoy.
- `WorkingMemoryToolkit.DEFAULT_MAX_REHYDRATE_BYTES` → `2_000_000` (tool.py:272) —
  existe, pero sólo se consulta desde `_apply_raw_policy`, que está tras
  `is_enabled`: hoy es código muerto en el camino por defecto.
- `TaskMemoryConfig.max_rehydrate_bytes` → `2_000_000` (task_memory/config.py:131),
  con `resolve_rehydrate_bytes()` como techo duro (`:281`).
- `PlanMetadata.checkpoint` → `True` por defecto (plan/models.py:264) pero
  **ignorado**: `toolkit.py:219` fuerza `checkpoint=False` "regardless of what a
  plan file's `metadata` block says".
- `SyncCatalogWriteError` (internals.py) — adjuntar un backend convierte
  `put`/`put_generic`/`drop` síncronos en error. `PlanToolNode` ya usa la API
  awaited (`plan/node.py:535`), pero cualquier otro llamador síncrono del catálogo
  hay que auditarlo.
- `CatalogNotEnabledError` (internals.py) — la simétrica: API awaited sin backend.

### Does NOT Exist (Anti-Hallucination)

- ~~`PlanPlanner.replan()`~~ — **no existe**. `PlanPlanner.repair()` (planner.py:174)
  sí existe, pero repara un plan **estructuralmente inválido** desde un
  `ValidationReport` en tiempo de validación. No sabe nada de un `ExecutionManifest`
  ni de nodos que fallaron en ejecución. El replan de esta feature es un método
  hermano, no una reutilización.
- ~~`plan_repair` / `plan_resume` como tools~~ — no existen. Las tools del toolkit
  son exactamente cuatro: `plan_execute`, `plan_validate`, `plan_status`,
  `plan_artifacts`.
- ~~`WorkingMemoryCatalog.attach_backend()` / `.enable()` / `.set_backend()`~~ —
  **no existen**. El backend sólo se puede pasar en el constructor
  (internals.py:794), y exige un `TaskScope`. Adjuntarlo a una WorkingMemory ya
  construida requiere diseñar ese camino: es trabajo de esta feature, no algo que
  esté esperando a ser llamado.
- ~~`AgentsFlow.resume(node_factories=...)`~~ — no existe ese parámetro. El hook
  correcto es `flow_factory` (flow.py:1429), documentado como **required** para
  flujos con nodos personalizados. El finding F007 de FEAT-516 dice que resume "has
  no node_factories parameter", lo cual es literalmente cierto pero **no** implica
  que el caso esté bloqueado.
- ~~`ResultPolicy` como clase en `parrot.tools.working_memory`~~ — no existe. El
  diseño la propone como dataclass; lo implementado son parámetros y config. Existe
  `parrot/mcp/result_policy.py`, **sin relación**: es el cap de ~30K tokens del
  conector MCP (FEAT-477).
- ~~`describe_fn` por tool~~ — no existe en ningún punto del árbol. Las facets son
  declarativas en el plan (`FacetSpec`, plan/facets.py).
- ~~`HandleOnlyCodec`, `FilterLevel.AGGRESSIVE` como parte de este diseño~~ — el
  codec no existe; `FilterLevel` existe pero pertenece a FEAT-380 (compression).
- ~~`AgentsFlow.as_tool()`~~ — no existe; `as_tool()` es de `AbstractBot` y
  `AgentsFlow` no lo es (finding F005 de FEAT-453).

---

## Parallelism Assessment

- **Internal parallelism**: parcial y asimétrica. Dos piezas son verdaderamente
  independientes y pueden ir en paralelo desde el minuto uno: el fix del helper
  (`agent.py` + `manager.py` + doc) y el encendido del techo de rehidratación
  (constructor del toolkit + la WorkingMemory que recibe). Las otras dos son una
  cadena: el resolvedor de runs es prerrequisito del checkpointing, y el
  checkpointing es prerrequisito del replan —el delta se ejecuta como continuación
  de un run, así que necesita que "continuar un run" exista primero.
- **Cross-feature independence**: sin conflicto con las specs en vuelo. FEAT-580
  (sdd-research-lsp), FEAT-578 (sdd-spec-wiki-adr) y FEAT-572 (sdd-fix-ledger-lane)
  son todas de tooling SDD y no tocan `parrot/tools/` ni `parrot/bots/flows/`.
  Ficheros compartidos a vigilar: `parrot/bots/agent.py` y `parrot/tools/manager.py`
  son de alto tráfico en este repo — conviene que la tarea del helper aterrice
  pronto para no arrastrar un conflicto largo.
- **Recommended isolation**: `per-spec`.
- **Rationale**: aunque dos tareas podrían vivir en worktrees separados, las otras
  dos comparten `toolkit.py` de principio a fin y se pisarían constantemente. El
  ahorro de un worktree extra no compensa resolver conflictos sobre el fichero
  central de la feature. Un solo worktree, tareas secuenciales, con las dos
  independientes primero para que aterrice valor temprano.

---

## Open Questions

- [x] ¿Quién dispara el replan? — *Owner: Jesus Lara*: una tool separada; el agente
  decide. Preserva "cero tokens LLM durante la ejecución".
- [x] ¿Hasta dónde llega la reanudación? — *Owner: Jesus Lara*: cross-restart real,
  otro proceso recoge el `run_id`.
- [x] ¿Cómo se enciende el techo de rehidratación sin romper AC13? — *Owner: Jesus
  Lara*: sólo en contexto de plan; el default global de `WorkingMemoryToolkit` no
  se invierte.
- [x] ¿Qué pasa sin Redis? — *Owner: Jesus Lara*: se ejecuta sin checkpoint y el
  manifiesto lo declara como dato.
- [x] ¿Dónde vive el estado del run? — *Owner: Jesus Lara*: se deriva del
  checkpoint; nada de un segundo objeto persistido que pueda desincronizarse.
- [x] ¿Quién dispara la reanudación tras el reinicio? — *Owner: Jesus Lara*: el
  agente, con una tool. Nada se reanuda solo.
- [x] ¿Por qué mecanismo se enciende el techo? — *Owner: Jesus Lara*: adjuntando un
  backend de artefactos in-memory, asumiendo el versionado que trae consigo.
- [x] ¿Cómo se trata el cambio de conducta del helper? — *Owner: Jesus Lara*: se
  arregla sin flag; es la conducta que el código siempre dijo tener.
- [x] In-memory + cross-restart se contradicen, ¿cómo se resuelve? — *Owner: Jesus
  Lara*: durable si está configurado, in-memory si no, y el manifiesto declara el
  nivel de reanudación del run.
- [x] ¿Qué puede tocar el plan delta? — *Owner: Jesus Lara*: sólo nodos fallidos o
  bloqueados, mismo allowlist, nunca un nodo ok ni nodos nuevos.
- [ ] ¿Basta el checkpoint para reconstruir los `ArtifactRef` del manifiesto, o hay
  que persistir algo más? El checkpoint guarda `results` y `completion_order`, y
  `PlanToolNode` publica un `ArtifactRef` como resultado de nodo — sobre el papel
  encaja, pero hay que confirmarlo contra `ContextSnapshot` antes de comprometer
  D4. Si no bastara, la alternativa mínima es cachear el manifiesto final una vez
  al terminar. — *Owner: implementador, en la fase de spec*
- [ ] ¿De dónde sale el `TaskScope` que exige un catálogo con backend? Adjuntar un
  backend sin scope lanza `ValueError` (internals.py:824). ¿El toolkit sintetiza un
  scope por run, o lo hereda del agente? Afecta a cómo se atribuyen las escrituras
  del plan al leerlas de vuelta. — *Owner: implementador, en la fase de spec*
- [ ] ¿Cuál es el tope de rondas de replan por defecto, y es configurable por plan o
  por toolkit? El diseño dice "1–2 rondas". — *Owner: Jesus Lara*
- [ ] ¿`plan_repair` sobre un run expirado por TTL debe poder autorizar una
  re-ejecución completa, o negarse? Distinguir "expiró" de "no existió" es
  requisito; qué hacer después, no está decidido. — *Owner: Jesus Lara*
- [ ] Auditar qué llamadores síncronos del catálogo existen fuera de `PlanToolNode`,
  ya que adjuntar el backend los convierte en `SyncCatalogWriteError`. — *Owner:
  implementador, en la fase de spec*
