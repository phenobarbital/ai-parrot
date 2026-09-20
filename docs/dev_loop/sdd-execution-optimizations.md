# Propuestas para reducir el tiempo de ejecución de SDD

Fecha: 2026-09-21. Estado: análisis y propuestas, sin cambios de implementación.

> **Actualización 2026-09-21 (segunda pasada del profiler):** la §8 responde con mediciones a las preguntas abiertas de la §2, corrige la línea base y añade propuestas. Donde la §8 contradice una cifra anterior, prevalece la §8.

## 1. Diagnóstico

La prioridad es reducir las decisiones repetitivas del `sdd-worker`, el trabajo duplicado entre implementación y revisión, y los intentos que requieren recuperación. Antes de atribuir ahorro al polling o ampliar el paralelismo, hay que medir qué bloquea realmente la entrega.

La evaluación identifica candidatos razonables, pero **sus porcentajes no equivalen a tiempo recuperable**. Mezcla duraciones de llamadas, intervalos de agentes y un residual atribuido al modelo; además, el resumen numérico contiene una discrepancia. Conviene instrumentar y aplicar cambios pequeños antes de rediseñar el ejecutor.

Este documento utiliza tres niveles de evidencia:

- **Verificado localmente:** instrucciones actuales, implementación de `wait` y agregados de los JSONL MCP.
- **Aportado:** cifras de las cuatro corridas nativas y descripción del profiler. No se han auditado sus transcripts ni ejecutado el profiler.
- **Propuesto:** mejoras, objetivos experimentales y estimaciones condicionadas; no son ahorros demostrados.

## 2. Revisión de la evaluación

### 2.1 Agregados y representatividad

Se cuentan una sola vez las tablas repetidas en el mensaje original.

| Magnitud | Recalculado desde las cuatro filas |
|---|---:|
| Tiempo de pared | 19 h 19 min 02 s |
| Tiempo clasificado como activo | 11 h 01 min 49 s |
| Tiempo clasificado como idle | 8 h 17 min 11 s |
| Tiempo atribuido al modelo | 4 h 18 min 22 s |
| Modelo / activo | **39,0%**, frente al 36,2% del agregado aportado |
| Peso de FEAT-564 en el tiempo activo | 45,1% |
| Modelo / activo excluyendo FEAT-564 | 27,6% |

Hay también diferencias de segundos entre sumas de columnas, compatibles con redondeo o truncamiento. La diferencia entre 39,0% y 36,2% requiere reconciliar denominadores o reglas de atribución: no se explica por ese redondeo.

FEAT-564 influye fuertemente en el resultado. Cuatro features no permiten concluir que el tiempo escale «con el número de turnos, no con la feature»: dificultad, tamaño, fallos y dependencias pueden explicar simultáneamente más turnos y más duración. Conviene comparar por tarea aceptada, complejidad y número de ciclos de corrección, además de por feature.

### 2.2 Qué mide realmente el profiler

La unión de intervalos evita sumar dos veces trabajo concurrente, pero no demuestra causalidad ni identifica por sí sola el camino crítico. Si dos categorías coinciden, el resultado depende de cómo se les asigna el intervalo compartido. Esa regla debe quedar publicada.

Un hueco superior a 120 segundos sin herramientas no demuestra que el usuario estuviera ausente. Puede incluir generación larga, colas del proveedor, compactación, transporte o procesos sin instrumentar. Etiquetarlo como **intervalo sin atribución** hasta disponer de evidencia explícita de espera humana. Recalcular con umbrales de 60, 120 y 300 segundos ayuda a detectar sensibilidad, sin convertir ninguno en verdad de referencia.

Del mismo modo, «modelo del orquestador» calculado por diferencia es un **residual**, no una medición directa de inferencia. Para separarlo se necesitan eventos de inicio de solicitud, primer token y fin de respuesta, cuando el runtime los exponga. Los mensajes de assistant tampoco equivalen necesariamente a solicitudes al proveedor; hay que especificar qué significa `turn`.

La corrección del span de agentes en background es necesaria. También debe documentarse cómo se tratan hijos incompletos, reanudaciones, relojes y trabajo MCP que no aparece como span hijo del transcript.

### 2.3 `coder_wait`: espera no equivale a sobrecoste

La implementación actual usa `asyncio.wait_for(asyncio.shield(task), timeout=timeout_s)`: **retorna cuando termina el job o vence el plazo**, conservando el trabajo al vencer la espera. No duerme obligatoriamente hasta el siguiente tick.

Por tanto:

- `33 × 120 s = 66 min`, no 40 min. Unos 40 minutos pueden ser la suma observada de esperas parciales; el techo no permite deducir esa suma.
- El 6% de 11 h 01 min 49 s son unos 39,7 minutos, pero una parte puede solaparse enteramente con implementación útil.
- Los 33 turnos adicionales, usando la estimación aportada de 3,5 s, suponen unos **116 s** de modelo, antes de medir otros costes. No justifican prometer 40 minutos de ahorro.
- El prompt actual prescribe 90 s; el toolkit tiene un valor por defecto de 120 s. Hay que registrar versión y argumentos efectivos de las corridas.

El riesgo real es bloquear la atención a una entrega nativa, serializar solicitudes MCP o esperar a todo el chunk antes de aprovechar una tarea ya terminada. Medir `fin de tarea → observación → merge → siguiente tarea habilitada`. No aumentar el timeout indiscriminadamente: la documentación actual advierte de serialización del servidor y límites del cliente.

### 2.4 Telemetría MCP y recuperación

Los archivos locales FEAT-559, FEAT-560 y FEAT-563 reproducen los **22 intentos**, con **8.597,886 s acumulados**. Son otra cohorte: no se deben sumar al activo de FEAT-578/565/572/564 ni interpretar esa suma como tiempo de pared.

| Seat | Intentos | Segundos acumulados | Mediana, s | completed / salvaged / failed |
|---|---:|---:|---:|---|
| mistral | 6 | 2.205,085 | 355,432 | 4 / 2 / 0 |
| codex-spark | 1 | 1.801,191 | 1.801,191 | 0 / 0 / 1 |
| qwen | 5 | 1.716,222 | 329,162 | 4 / 1 / 0 |
| glm5 | 2 | 1.077,251 | 538,626 | 2 / 0 / 0 |
| minimax | 3 | 941,315 | 308,580 | 3 / 0 / 0 |
| glm | 5 | 856,822 | 175,004 | 1 / 2 / 2 |

`salvaged` no debe contarse automáticamente como tiempo sin entrega, ni `completed` como aceptación sin defectos. Hace falta enlazar cada intento con merge, revisión y correcciones. El intento fallido de codex-spark representa el 20,9% del tiempo acumulado de esta cohorte, pero una observación no demuestra inferioridad del modelo: hay que distinguir errores de infraestructura, contrato y capacidad.

La afirmación de que el 70–80% del tiempo de los coders nativos es generación queda pendiente de verificar. Aunque fuera correcta, los tests pueden tener un impacto mayor en integración y cierre que dentro del seat.

## 3. Optimizaciones priorizadas

| Orden | Cambio | Beneficio buscado | Esfuerzo / riesgo |
|---|---|---|---|
| P0 | Telemetría persistente y reconciliada | Evitar optimizar intervalos mal atribuidos | Medio / bajo |
| P1 | Automatizar transiciones mecánicas del worker | Menos turnos y relecturas | Medio / medio |
| P1 | Briefs completos y respuestas compactas | Menos exploración repetida y correcciones | Bajo–medio / bajo |
| P1 | Revisión incremental y cierre acotado | Reducir el bloque serial final | Medio / medio |
| P1 | Recuperación guiada por progreso y calidad | Evitar intentos largos improductivos | Medio / medio |
| P2 | Tests por evidencia reutilizable | Reducir validación redundante | Medio / medio |
| P2 | Eventos y planificación por tareas listas | Reducir espera de barreras y demoras de reacción | Alto / alto |

### 3.1 Automatizar el trabajo mecánico del orquestador

El coste de las llamadas de control puede ser pequeño y, aun así, la conversación necesaria para decidir cada llamada puede ser cara. Trasladar al kernel únicamente transiciones deterministas:

1. Normalizar la entrega y validar identidad, alcance, commits y estado.
2. Ejecutar los checks prescritos y devolver evidencia estructurada.
3. Preparar la nota de finalización y la actualización del índice a partir de esa evidencia.
4. Aplicar transiciones idempotentes; devolver excepciones concretas al worker.

El worker conserva decisiones semánticas: revisar defectos, resolver conflictos, evaluar evidencia insuficiente y gestionar bloqueos. El resultado puede incluir `state`, `evidence_refs`, `pending_actions` y `requires_decision`, sin pedir al modelo reconstruir el estado desde múltiples salidas.

Mantener los registros de revisión y feedback por entrega. Reducir llamadas o agrupar persistencia no autoriza a declarar una revisión que no ocurrió. Diseñar recuperación frente a fallos entre commit, índice y ledger; el worker sigue siendo dueño del estado SDD.

**Experimento:** automatizar una transición frecuente y comparar turnos de control por tarea aceptada, errores de estado y tiempo crítico. No rediseñar todo el engine para ahorrar el pequeño tiempo de ejecución de sus tools.

### 3.2 Mejorar los contratos de entrada y salida

Preparar cada brief con rutas y símbolos verificados, alcance permitido, criterios de aceptación, comandos de validación, dependencias ya resueltas y feedback relevante. La información ligada al código debe incluir revisión base o hash para detectar obsolescencia.

Entregar al worker un resumen estructurado con commits, tests ejecutados, resultado, limitaciones y enlaces a logs. Consultar logs completos solo cuando un resultado lo requiera. Mantener las convenciones obligatorias y permitir acceso a la evidencia original; compactar no significa eliminar contexto necesario.

No fragmentar por defecto cada tarea en más agentes: el coste de arranque, exploración y revisión puede superar el paralelismo. Dividir por contratos independientes; agrupar pasos pequeños y estrechamente relacionados solo si conserva aceptación verificable y propiedad clara de archivos.

**Experimento:** medir lecturas repetidas, tokens de entrada/salida cuando estén disponibles, tiempo hasta primera edición y correcciones por entrega. No usar menos tokens como sustituto de menos tiempo o mejor calidad.

### 3.3 Revisión incremental con evidencia de revisión base

Los 950–1150 segundos por revisión aportados equivalen a unos 16–19 minutos; reducirlos merece un experimento. Revisar contratos y cambios estabilizados durante la implementación puede adelantar descubrimientos y reducir el cierre serial.

- Cada revisión temprana queda ligada al diff y SHA revisados, criterios cubiertos y hallazgos.
- Cambios posteriores invalidan la parte afectada y sus dependencias.
- La revisión final cubre el delta pendiente y la integración global: interfaces, invariantes y riesgos que solo aparecen al unir tareas.
- Separar revisión semántica de checks mecánicos ya respaldados por evidencia válida.

Empezar con una revisión incremental acotada; añadir revisores solo si hay ámbitos independientes y capacidad disponible. Más agentes pueden aumentar colas, tokens y resultados duplicados. Mantener la independencia adversarial y evitar que una aprobación sobre un SHA anterior habilite el cierre de un diff distinto.

**Experimento:** comparar duración final y coste total de revisión, defectos confirmados, correcciones posteriores y cobertura de criterios. Una revisión final más corta no basta si se duplicó el trabajo previo.

### 3.4 Reducir intentos improductivos

La ruta por complejidad, la identidad efectiva del modelo y las suspensiones ya forman parte del flujo. Extender esas garantías en lugar de crear un ranking global a partir de 1–6 muestras por seat.

Definir señales de progreso: cambio válido en alcance, reducción de fallos y cumplimiento de criterios. Un contador de turnos aislado puede penalizar tareas complejas o premiar ediciones inútiles. Detectar bucles repetidos sin progreso y preparar diagnóstico antes de activar la recuperación existente.

Calibrar presupuestos por clase de tarea, incluyendo tiempo, turnos y correcciones. Distinguir lentitud legítima, herramienta bloqueada y error repetido. Conservar ramas y evidencia antes de recuperar; no iniciar otro escritor sobre una tarea cuyo agente anterior podría seguir activo. Suspender un modelo no prueba que terminó su proceso.

Optimizar **tiempo hasta tarea aceptada**, incluyendo intentos fallidos, recuperación, revisión y arreglos. Para consumo de recursos, medir además segundos de agentes acumulados por tarea aceptada; no confundir ambos indicadores.

### 3.5 Reducir tests redundantes sin reducir cobertura necesaria

El flujo actual ya selecciona tests por niveles `task`, `merge` y `feature`, limita suites dentro del coder y reutiliza ciertas escalaciones verdes por contenido. No proponerlo como una novedad.

Investigar las 226 ejecuciones: motivo, selección, revisión del código, duración de arranque/colección y si había cambios relevantes desde la anterior. Distinguir duplicados verdaderos de regresiones necesarias después de combinar ramas.

Para ampliar la reutilización, la identidad de la evidencia debe cubrir contenido relevante, tests, configuración, entorno y dependencias. El hash de un único archivo no basta para cualquier clase de validación. Mantener los checks posteriores al merge cuando cambia la composición integrada.

La documentación señala escalaciones core potencialmente muy amplias y una allowlist xdist vacía. Medir esas suites antes de cambiar umbrales. Habilitar paralelismo solo para distribuciones cuya equivalencia y aislamiento estén demostrados; no reducir cobertura para mejorar el cronómetro.

### 3.6 Eventos y planificación continua

Primero medir cuánto tiempo hay entre una entrega y su consumo. Si es significativo, explorar notificaciones MCP con recuperación de eventos y un fallback de espera acotada, siempre según lo que permita el host. No asumir que su soporte existe.

Después, evaluar liberar capacidad por tarea terminada en vez de esperar el chunk completo: despachar tareas listas cuando sus dependencias estén **aceptadas**, haya modelo elegible y el alcance no entre en conflicto. Priorizar tareas que desbloquean el camino crítico, sin eludir exclusividad, límites de concurrencia o clasificación compleja/desconocida.

Requiere planificación actualizada, merges serializados sobre la rama de integración, eventos idempotentes y evidencia de terminación antes de limpiar worktrees. Es una modificación de arquitectura; solo compensa si la barrera entre chunks representa demora material.

## 4. Medición necesaria

Persistir un registro compacto fuera de los worktrees efímeros. Mantener exportación antes del cleanup y eventos durante la ejecución para sobrevivir a fallos previos al cierre. El destino concreto debe seguir las convenciones existentes de ledger y telemetría.

| Grupo | Campos o eventos propuestos |
|---|---|
| Identidad | feature, execution_id, job_id, task_id, attempt_uid, backend, modelo solicitado y resuelto |
| Versiones | commit del repositorio, hash de prompts/política, configuración del experimento |
| Tiempos | tarea lista, despacho, inicio/fin, entrega observada, merge, aceptación, revisión, fin de feature |
| Correlación | span_id, parent_span_id, toolUseId/ID de agente cuando existan |
| Calidad | terminal, resultado de gates, defectos confirmados, recuperación y commits correctivos |
| Tests | selección, motivo, revisión/contenido, entorno, duración, resultado y reutilización |
| Modelo | solicitudes, tokens y latencias observadas; valor desconocido explícito si faltan |

Para seats nativos, combinar registro de despacho/entrega con importación de transcripts cuando estén disponibles. No inventar tokens ni inferir éxito de la falta de errores. Registrar trabajo aún activo al terminar la ventana como incompleto.

Publicar separadamente:

- Tiempo de pared de extremo a extremo, con espera humana explícita desglosada.
- Tiempo automático, conservando un apartado de intervalos sin atribución.
- Segundos acumulados por recurso, que pueden exceder el tiempo de pared.
- Camino crítico derivado de dependencias y transiciones observadas.
- Demora de reacción y demora de cola; coste de corrección por tarea aceptada.

## 5. Ahorro potencial: escenarios, no predicciones

Sobre la base aportada de 11 h 01 min 49 s de tiempo activo:

| Escenario hipotético | Reducción del activo | Equivalente agregado |
|---|---:|---:|
| Reducir 25% del componente de orquestador, si su peso real es 36,2–39,0% | 9,1–9,8% | 60–65 min |
| Reducir 50% de la revisión final, si ocupa 11% exclusivo | 5,5% | 36 min |
| Reducir 50% de pytest, si ocupa 8,3% exclusivo | 4,15% | 27 min |

Estas cuentas suponen atribución correcta, reducción efectiva del componente y presencia en el camino crítico. No se pueden sumar sin corregir solapamientos y efectos de sustitución. Eliminar toda la espera observada de `coder_wait` no es un escenario válido de ahorro: el trabajo esperado sigue siendo necesario.

Como objetivo inicial de piloto, buscar **15% menos tiempo automático mediano en tareas/features comparables**, sin aumento observable de defectos, recuperaciones o evidencia faltante. Es un umbral experimental, no una previsión derivada de cuatro corridas.

## 6. Secuencia de validación

1. **Reconciliar la línea base.** Auditar reglas del profiler, resolver 36,2% frente a 39,0%, verificar intervalos compartidos y separar versiones/cohortes.
2. **Cerrar observabilidad.** Persistir eventos MCP y nativos; comprobar recuperación tras reinicio y limpieza sin perder atribución.
3. **Piloto de bajo riesgo.** Briefs acotados y una transición mecánica automatizada. Comparar con la política anterior en trabajo de complejidad semejante.
4. **Pilotos separados.** Revisión incremental, recuperación por progreso y reutilización de tests. Cambiar un factor cada vez para poder atribuir el efecto.
5. **Evaluar arquitectura.** Solo con evidencia de barreras costosas, introducir eventos y planificación continua.

Alternar control y variante entre ejecuciones comparables, registrando carga externa, tamaño, complejidad y versiones. No comparar una feature pequeña nueva con FEAT-564 como única referencia. Usar repeticiones sobre snapshots aislados cuando interese comparar la misma tarea sin contaminación por artefactos previos.

Informar tamaño de muestra, mediana, dispersión y casos individuales; estimar p90/p95 cuando haya muestra suficiente. Incluir fallos y abandonos para evitar sesgo de supervivencia. La ausencia de defectos en pocas tareas no demuestra equivalencia de calidad.

Cada cambio debe poder desactivarse mediante política/configuración. Revertir el piloto ante pérdida de evidencia, omisión de validaciones, doble escritor, incremento sostenido de recuperaciones o regresiones de corrección. La aprobación de tareas mantiene los mismos criterios funcionales.

## 7. Fuentes locales y alcance

- [Worker: ciclo de orquestación y cierre](../../.claude/agents/sdd-worker.md): espera, consolidación, feedback, revisión adversarial y estado SDD.
- [Contrato del coder](../../.claude/agents/sdd-coder.md): alcance, validación y entrega.
- [Documentación del orquestador](sdd-coder-orchestrator.md): routing, suspensiones, telemetría y selección de tests. Algunos ejemplos generales pueden diferir del prompt actualizado; verificar el contrato efectivo antes de implementar.
- [Espera del job](../../packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/jobs.py): retorno por finalización o timeout.
- [Toolkit](../../packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py): interfaz `coder_wait` y resumen por seat.
- [Resumen de seats](../../packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/summary.py) y [telemetría](../../packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/telemetry.py): agregación y proyección de intentos.
- Telemetría local: [FEAT-559](../../artifacts/logs/sdd-coder-usage/FEAT-559.jsonl), [FEAT-560](../../artifacts/logs/sdd-coder-usage/FEAT-560.jsonl), [FEAT-563](../../artifacts/logs/sdd-coder-usage/FEAT-563.jsonl). Su disponibilidad depende de conservar los artefactos locales.
- Evaluación suministrada por el usuario: fuente de las cifras nativas. El profiler citado mediante una ruta abreviada y los transcripts originales no se verificaron en esta revisión.

No se han cambiado prompts, routing, código ni políticas. Las propuestas necesitan especificación y validación antes de su adopción.

## 8. Segunda pasada del profiler: respuestas, correcciones y propuestas adicionales

Nivel de evidencia: **verificado sobre los transcripts locales** de las cuatro corridas (FEAT-578, FEAT-565, FEAT-572, FEAT-564). Scripts y salidas crudas en `artifacts/logs/sdd-worker-profiling/` (`profile_sdd_worker.py`, `analyze_orchestrator.py`, `first-pass-20260921.txt`, `second-pass-20260921.txt`); el directorio está bajo `.gitignore`, así que la reproducibilidad depende de conservarlo junto con `~/.claude/projects/`. Siguen siendo cuatro features: lo que sigue describe esta cohorte, no una ley.

### 8.1 Respuestas a las preguntas abiertas de la §2

**36,2% frente a 39,0% (§2.1).** Era un defecto del agregado, no redondeo. La fila del modelo se calculaba como `activo − Σ(unión por categoría)`, y eso resta dos veces el solape entre categorías (un pytest que corre mientras vive un agente en background). El solape medido es de 1.148 s. Con `activo − unión(todas las tools)` el residual es **15.504 s = 39,0%**, que coincide con la suma por filas. Corregido en el script; las filas por categoría se solapan entre sí y no suman 100%.

**Qué es un `turn` (§2.2).** Las filas `assistant` del transcript son *bloques de contenido*, no solicitudes: una solicitud con `thinking` + `tool_use` produce dos filas con el mismo `requestId`. Agrupando por `requestId`:

| Feature | Filas assistant | Solicitudes reales | Latencia mediana | p90 | Contexto mediano (tokens) | Contexto máx. |
|---|---:|---:|---:|---:|---:|---:|
| FEAT-578 | 707 | 419 | 6,5 s | 18,7 s | 160 k | 359 k |
| FEAT-565 | 551 | 305 | 4,1 s | 9,6 s | 247 k | 408 k |
| FEAT-572 | 655 | 348 | 3,3 s | 10,7 s | 306 k | 513 k |
| FEAT-564 | 2.201 | 1.155 | 4,2 s | 16,9 s | 525 k | 966 k |

Las cifras de «turnos» de la primera pasada estaban infladas ~1,85×. La latencia se mide de forma directa como *evento previo → último bloque de la solicitud*; su suma (16.531 s) es coherente con el residual (15.504 s), de modo que el residual **sí es, en lo esencial, latencia de solicitudes del orquestador** y no tiempo misterioso. No separa primer token de generación: el transcript no lo expone.

**Qué son los huecos «idle» (§2.2).** La objeción era correcta y cambia la línea base. Clasificando cada hueco por el evento que lo termina:

| Umbral | Total | Termina en prompt del usuario | Termina en notificación de tarea en background | Sin clasificar (`attachment`) |
|---|---:|---:|---:|---:|
| 60 s | 8,50 h | 297 min (11) | 136 min (18) | 68 min (5) |
| 120 s | 8,29 h | 297 min (11) | 133 min (16) | 68 min (5) |
| 300 s | 7,59 h | 289 min (8) | 109 min (7) | 58 min (3) |

El resultado es poco sensible al umbral, pero **solo ~5 h son espera humana demostrable**. Los 133 min restantes son trabajo de máquina que el profiler no veía, porque un `Bash` con `run_in_background` y una llamada MCP enviada a background devuelven su `tool_result` al instante:

- FEAT-578: cinco corridas de tests en background **muertas por timeout (exit 124)** de ~590 s cada una (47,8 min): selección merge-tier, suite completa con xdist y tres intentos sucesivos de la misma suite de `ai-parrot-integrations`.
- FEAT-572: una selección merge-tier de **1.985 s** que terminó con exit 1.
- FEAT-564: `coder_prepare_native` colgado **1.667 s** hasta fallar; más dos suites en background (165 s y 286 s, exit 0).
- FEAT-565: siete `coder_wait` de ~145 s enviados a background.

Consecuencias: el tiempo activo real es ≥ 13,2 h (no 11,0 h) y **los tests pesan ~18% del activo corregido** (3.289 s en primer plano + ~5.300 s en background), no 8,3%. Esto confirma la cautela del final de la §2.4: dentro del seat los tests son marginales, en integración y cierre no.

**70–80% de generación en coders nativos (§2.4).** Verificado con n = 15: residual 72,4%, tools 27,6%, pytest 7,0% del span. Para `code-reviewer` (n = 4): residual 67,5%, pytest 15,0%. «Residual» con la misma salvedad de arriba.

**Demora de reacción (§2.3).** De *fin del coder nativo* a la primera salida del orquestador: mediana 3 s, máx. 55 s. De *fin del coder* al siguiente `coder_merge`: mediana 3 s, pero 4 de 12 entregas esperaron 240–1.657 s. En el caso de 1.657 s (FEAT-565) el orquestador estuvo 691 s dentro de `coder_wait` y 436 s sin atribución mientras la entrega nativa ya estaba lista: es exactamente el riesgo descrito en la §2.3. Salvedad: el emparejamiento es «siguiente merge», no por `task_id`; en FEAT-572 los retrasos de ~395 s coinciden con el despacho del siguiente coder antes de consolidar, que puede ser pipelining legítimo.

### 8.2 Hallazgos nuevos

**a) El residual del orquestador no está en el plano de control.** Atribuyendo la latencia de cada solicitud a la primera acción que emite:

| Siguiente acción | Solicitudes | % del tiempo de modelo | s/solicitud | Tokens de salida/solicitud |
|---|---:|---:|---:|---:|
| Bash (otros: grep, ls, python inline…) | 589 | 26,4% | 7,4 | 694 |
| Edit | 218 | 11,7% | 8,9 | 997 |
| Bash git | 299 | 11,2% | 6,2 | 520 |
| Solo texto / fin de turno | 180 | 10,0% | 9,2 | 146 |
| Read | 269 | 8,6% | 5,3 | 460 |
| Bash pytest | 226 | 8,6% | 6,3 | 581 |
| Write | 35 | 8,2% | 38,5 | 5.216 |
| Todas las `coder_*` juntas | 209 | 6,3% | 5,0 | 330–990 |

Decidir las llamadas MCP es barato. Lo caro es el trabajo manual del propio orquestador: inspección por shell, git, ediciones y relecturas. Esto respalda la §3.1 y acota su objetivo: no son las tools de control, es todo lo que rodea a la consolidación.

**b) FEAT-564 no fue una corrida de orquestación.** No se observa ningún intento MCP, hay un único `coder_merge`, y el orquestador hizo él mismo 91 ediciones de código fuente y 67 de tests, con 145 ejecuciones de pytest (79 repeticiones exactas; ×20 sobre el mismo directorio). Es el camino de reserva «implementar uno mismo», ejecutado en el contexto más caro del sistema (mediana 525 k tokens, máximo 966 k) y en serie. Como pesa el 45% de la línea base, el «39%» describe sobre todo ese modo; sin FEAT-564 el residual es 27,6% (la cifra de la §2.1). En las otras tres el orquestador edita casi solo estado SDD (46 de 71 ediciones).

**c) La línea base está contaminada por un defecto ya corregido.** En FEAT-572 y FEAT-578, 25 de 34 intentos MCP fallaron en 0 s con `CoderFailure: seat '<x>' … is not eligible for unknown task` (issue `e01c03baf493`, fix integrado en `dev` durante FEAT-572): el plan asignaba seats que el despacho rechazaba. Cada rechazo costó replanificación: `coder_plan` se llamó 35 veces (8–12 por feature) con ~9 KB por respuesta, el 11,5% de todo el payload devuelto al orquestador. Estas corridas no sirven como control de un experimento; hace falta una línea base posterior al fix.

**d) El contexto es un problema de coste más que de tiempo.** 1.369 de 2.227 solicitudes corrieron con más de 250 k tokens de contexto. La latencia mediana apenas cambia entre 100–150 k (3,7 s) y >250 k (4,3 s); la media sube de 5,1 a 7,7 s. La caché absorbe el tiempo, no la factura.

**e) Qué llena el contexto del orquestador** (caracteres de `tool_result`): Read 33,9%, Bash otros 19,1%, pytest 13,3%, `coder_plan` 11,5%, git 6,1%.

**f) Coste de consolidación observado:** ~50 solicitudes del orquestador por tarea integrada (FEAT-565: 51; FEAT-572: 50), con mediana de 14–34 entre merges consecutivos.

**g) Repetición de tests:** 116 de las 226 ejecuciones de pytest del orquestador repiten exactamente un objetivo ya ejecutado en la misma sesión. Son bucles corregir-reintentar, no validación nueva.

### 8.3 Propuestas adicionales y ajustes de prioridad

| Orden | Cambio | Evidencia (§8) | Esfuerzo / riesgo |
|---|---|---|---|
| P0 | Presupuesto y fallo rápido para suites en background | 8.1: 81 min en corridas que acabaron en timeout o error | Bajo / bajo |
| P0 | Reserva acotada: no implementar en el contexto del orquestador | 8.2 b: 45% de la línea base | Bajo–medio / medio |
| P0 | Profiler: tareas en background, solicitudes reales, huecos clasificados | 8.1 | Bajo / bajo |
| P1 | Paridad de admisión plan ↔ despacho y `coder_plan` incremental | 8.2 c | Medio / bajo |
| P1 | Plazo por operación en las llamadas MCP de control | 8.1: `coder_prepare_native` 1.667 s | Bajo / bajo |
| P1 | Consolidar al recibir la entrega, no al volver de la espera | 8.1: 4/12 entregas, hasta 1.657 s | Medio / medio |
| P2 | Higiene del bucle de tests del orquestador | 8.2 g | Bajo / bajo |
| P2 | Higiene de contexto (coste) | 8.2 d, e | Medio / bajo |

**P0 — Suites en background con presupuesto.** Ninguna suite debería lanzarse sin una duración esperada. Reglas candidatas: registrar la duración de cada selección `merge`/`feature` y usarla como presupuesto de la siguiente; ante exit 124, **no reintentar la misma selección** (en FEAT-578 se hizo tres veces seguidas, ~30 min): reducir el alcance, particionar o escalar al usuario; propagar el motivo del fallo en lugar de un código desnudo. Enlaza con la §3.5: la escalación amplia es donde está el tiempo, no el test por tarea. Medir primero cuánto tarda hoy cada nivel en frío.

**P0 — Reserva acotada.** Cuando el camino MCP no está disponible, el worker hoy puede implementar las tareas él mismo. Hacerlo en su propio contexto es la opción más lenta y cara observada. Alternativa a probar: que la reserva sea despachar seats nativos `sdd-coder` tarea a tarea (contexto fresco, mismo contrato de entrega), y que la autoimplementación requiera una condición explícita y un tope (p. ej. número de ediciones de código fuente por el orquestador) que obligue a detenerse e informar. El indicador es directo: ediciones de código fuente hechas por el orquestador por feature; en tres de cuatro corridas fue ≤ 5.

**P0 — Profiler.** Emparejar cada lanzamiento en background con su `task-notification` para tratarlo como intervalo ocupado; contar solicitudes por `requestId`; clasificar cada hueco por su evento final y reportar «espera humana», «espera de máquina no instrumentada» y «sin clasificar» por separado; publicar la regla de solape. Convertirlo en script versionado cuando se estabilice (hoy vive en un directorio ignorado). Esto concreta la P0 de la §3 y el paso 1 de la §6.

**P1 — Paridad plan ↔ despacho.** Un fallo de 0 s no es un fallo del modelo: es un error de contrato que el plan debió impedir. Invariante comprobable: todo seat asignado por `coder_plan` supera la admisión de despacho para esa tarea. Además, clasificar estos rechazos aparte en la telemetría para que no cuenten como intentos ni disparen suspensiones, y permitir que `coder_plan` devuelva solo lo que cambió respecto al plan anterior (o un resumen compacto), dado su peso en el contexto. Verificar primero si el fix de `e01c03baf493` ya cubre el invariante.

**P1 — Plazos en las llamadas de control.** El envoltorio del toolkit ya mide `elapsed_ms`; falta un plazo por operación. `coder_prepare_native` tiene una mediana de pocos segundos y un caso de 1.667 s: un plazo del orden de decenas de segundos con error estructurado habría devuelto 27 minutos. Requiere que la operación sea idempotente o limpie su sub-worktree parcial.

**P1 — Consolidar por entrega.** Da la medición que pedía la §2.3 y un primer paso más barato que la §3.6: mientras haya seats nativos vivos, preferir esperas MCP cortas o consolidar primero los hand-backs nativos pendientes antes de volver a `coder_wait`. No exige eventos nuevos ni planificador continuo. Medir con emparejamiento por `task_id` antes de decidir.

**P2 — Bucle de tests.** Para los bucles corregir-reintentar: `--lf`/`-x` sobre el objetivo que falla y, si el bucle supera N iteraciones, tratarlo como una tarea de corrección para un seat en lugar de seguir en el orquestador. No afecta a la cobertura de los niveles `merge`/`feature`.

**P2 — Contexto.** Como la latencia casi no escala con el contexto, clasificarlo como optimización de coste: lecturas por diff o por rango en lugar de archivos completos durante la revisión, salida de pytest resumida por defecto con el log completo en archivo, respuestas MCP compactas (§3.2). No esperar ahorro de tiempo apreciable de aquí.

**Ajustes a la §3.** La §3.1 gana un indicador concreto (*solicitudes del orquestador por tarea integrada*, hoy ~50) y un alcance más preciso: git y estado SDD, no las tools `coder_*`. La §3.5 sube de prioridad para los niveles amplios y baja para el nivel de tarea. La §3.6 puede esperar al resultado de «consolidar por entrega».

### 8.4 Escenarios de la §5, revisados

Los tres escenarios de la §5 usaban una base de 11 h 01 min que subestima el activo y una atribución que ahora se sabe mezclada. Con la base corregida (≥ 13,2 h):

| Escenario hipotético | Base medida | Equivalente |
|---|---|---:|
| Eliminar las corridas en background que acabaron en timeout/error | 5 × ~590 s + 1.985 s | ~81 min |
| Evitar el cuelgue de `coder_prepare_native` con un plazo | 1.667 s | ~27 min |
| Evitar las 116 repeticiones exactas de pytest (mediana ~9 s) | 116 × ~9 s, más la solicitud asociada (~6 s) | ~29 min |
| Reducir 25% las solicitudes del orquestador en corridas de orquestación real (sin FEAT-564) | residual 6.010 s en tres features | ~25 min |

Las dos primeras filas son tiempo que no produjo nada y no compiten con la calidad; por eso pasan a P0. Siguen siendo sumas sobre cuatro corridas, no predicciones, y las tres primeras dependen de incidentes que pueden no repetirse con la misma frecuencia.

### 8.5 El 26% de «Bash de inspección»: qué es y qué lo abarata

Desglose de las 589 llamadas (verificado sobre los mismos transcripts):

| Categoría | n | % |
|---|---:|---:|
| Leer archivos del worktree o logs (`cat`, `sed -n`, `tail`) | 194 | 32,9% |
| Buscar (`grep`, `find`, `ls`, `wc`, `ps`) | 184 | 31,2% |
| Sin efecto útil (`echo "waiting"`, `true`, `python -c "uuid4()"`) | 71 | 12,1% |
| Python inline (consultas al índice JSON, comprobaciones) | 60 | 10,2% |
| Leer tarea / spec / índice SDD | 43 | 7,3% |
| Espera activa (`sleep`, `until kill -0`) | 19 | 3,2% |
| Operaciones de archivo (`mv`, `mkdir`, `jq` sobre el índice) | 17 | 2,9% |

**El coste es el viaje de ida y vuelta, no la ejecución.** Cada inspección cuesta ~7,4 s de solicitud al modelo más ~3,8 s de ejecución. Paralelizar los comandos dentro de una tool no ahorra nada apreciable: son operaciones de milisegundos. Lo que ahorra es **colapsar cadenas**: el 68% de las llamadas de solo lectura (Bash de inspección + Read + git status/log/diff) ocurre en cadenas de tres o más consecutivas (140 cadenas, mediana 4), donde cada paso depende del anterior y por eso el modelo no las emite en paralelo.

**Hay un suelo de ~3,6 s por llamada Bash que no es del comando.** `true` y `echo waiting` tardan lo mismo que un `grep`. Distribución de ejecución: Bash p25 3,3 s / mediana 3,8 s; Read mediana 1,9 s; Edit 0,1 s. La diferencia son los hooks `PreToolUse`. Cronometrados sobre una entrada trivial: `wikitoolkit claude-hook` **2,05 s**; `parrot_tools.tool_optimizations.hooks` 0,06 s; `dangerous-actions-blocker.sh` 0,05 s; `rtk hook` 0,003 s. `-X importtime` muestra la causa: el CLI de `wikitoolkit` importa en el arranque `parrot.knowledge.wiki.decisions.cli → parrot.clients.base` (1,31 s: pandas, `pythonrepl`, `parrot.memory`, `documentdb`) para un hook que solo consulta SQLite. Sobre las 1.573 llamadas Bash + Read del orquestador en estas cuatro corridas son **~54 min**, sin contar los sub-agentes, que heredan los hooks. El hook emite además líneas de depuración de navconfig por stdout.

Propuestas, por orden de relación beneficio/esfuerzo:

1. **P0 — Importación perezosa en el CLI de `wikitoolkit`** (registrar el subcomando `decisions` sin importar su módulo hasta que se invoque) y silenciar stdout en modo hook. Objetivo: hook < 0,3 s. No cambia comportamiento y beneficia a toda sesión del repositorio, no solo a SDD.
2. **P1 — Eliminar las llamadas sin efecto** desde el prompt del worker: no narrar con `echo`, y que `coder_begin_execution` entregue el identificador en lugar de generarlo con `python -c uuid4`. 71 llamadas × ~11 s ≈ 13 min.
3. **P1 — Operaciones de lectura con propósito en el toolkit MCP**, no una tool genérica de inspección (que sería Bash con otro nombre). Candidatas, cada una sustituyendo una cadena observada:
   - `coder_task_context(task_id)`: tarea, entrada del índice, estado de dependencias y archivos declarados.
   - `coder_delivery_report(task_id)`: rama, commits, `diff --stat`, archivos fuera de alcance, estado del sub-worktree y evidencia de lint/tests. Es la «entrega normalizada» de la §3.1 y absorbe buena parte de las 299 llamadas git.
   - `coder_bg_status(handle)`: vivo/terminado, código de salida y cola acotada del log; sustituye los `ps | grep`, `tail`, `wc -l` y las esperas activas.
4. Salida **acotada y estructurada** en las tres: Read ya es el 33,9% del payload del contexto (§8.2 e); una tool que devuelva archivos enteros empeora el problema que pretende resolver.

Cota superior del punto 3: si cada cadena de ≥ 3 se redujera a una llamada, se evitarían ~650 viajes (~11 s cada uno), unas 2 h sobre 13,2 h. Una parte de esas cadenas es exploración genuina cuyo siguiente paso depende del resultado, así que la expectativa razonable es una fracción; medirlo con el indicador de la §8.3 (*solicitudes por tarea integrada*).
