# Verificación del brainstorm SDD Decision Audit

Fecha: 2026-10-31. Base: `dev`, commit `50786d9bcc5187469c0083d6f12d9fc5a1636b2b`.
Documento revisado: `sdd/proposals/sdd-decision-audit.brainstorm.md`, 789 líneas,
SHA-256 `c13f9fdb99a3f9823b32b0c72f2758a52c73c9cd99ff5d1430a6234de82c4225`.

## Dictamen

**Mantener A como dirección, pero no convertir todavía sus contratos en una spec de implementación.**
La infraestructura ADR existe y es reutilizable. Sin embargo, el esfuerzo no es principalmente
wiring: faltan semántica comprobable, identidad de múltiples decisiones por spec, resolución de
alcance, ciclo de aprobación/sustitución y una lectura completa para el gate.
Hay también afirmaciones desactualizadas sobre FEAT-778 y el ledger.

Se distingue entre hechos comprobados en código, inferencias de diseño y decisiones atribuidas
al owner. Estas últimas constan en el documento; no se han verificado contra transcripciones
de las rondas de discovery ni se reinterpretan como nuevas aprobaciones del usuario.

## Hallazgos que deben resolverse antes de especificar

### F01 — Alta: target + polaridad no identifica una contradicción

Brainstorm: líneas 151–156, 447–454.

`forbids(importar httpx)` y `requires(usar aiohttp)` sobre el mismo archivo son compatibles,
pero la regla propuesta los clasifica como contradicción. Dos `requires` sobre ese archivo
pueden ser independientes, aunque la regla de `undeclared-supersedes` los marque.
El bloque estructurado no identifica la operación, propiedad u objeto que se prohíbe/exige.
Además, el juez usa `contradicts`, ausente del vocabulario de autoría enumerado.

**Corrección:** definir una proposición estructurada mínima (sujeto/alcance, predicado,
objeto/valor y polaridad), o limitar el bloqueo a conflictos declarados explícitamente entre
IDs. Tratar coincidencias estructurales como posibles conflictos consultivos. La coincidencia
de target/relación no constituye una prueba de conservatividad.

### F02 — Alta: el gate no puede evaluar un dossier truncado

Brainstorm: líneas 178–183, 444–454, 497–499.

`DecisionService.for_symbol()` empaqueta resultados con `limit=10` y `budget_tokens=3000`
(`decisions/service.py:193`, `:245`); `render.py:20` limita incluso el máximo solicitado a 50.
`pack_dossier()` puede omitir registros o acortar su texto (`render.py:115`).
Una contradicción en el undécimo registro puede quedar fuera. El brainstorm trata la
truncación del dossier como información para el autor, pero no define incompletitud bloqueante
para el gate. El radio también puede truncarse (`structural/service.py:443`).

**Corrección:** compartir inventario y filtros, no la salida presupuestada: evaluar todos los
registros aplicables antes de renderizar. Un límite, fallo de decodificación o snapshot
incompleto debe producir `incomplete`, nunca un resultado aprobable. Ya existe un inventario
con overflow explícito en `decisions/repository.py:63`.

### F03 — Alta: el filtro de aceptación elimina el seed recién ingerido

Brainstorm: líneas 157–168 frente a 444–446.

El productor promete `source_status="accepted"`; el gate exige además
`review_status="accepted"`. `DecisionRecord` tiene `review_status="unreviewed"`
por defecto (`models.py:185`) y `parse_adr()` no lo cambia (`parser.py:371`).
Así, un ADR con `status: accepted` no entraría en el gate sin otra acción de revisión.
El consumidor implementado por FEAT-778 admite estados de fuente aceptados salvo revisión
rechazada (`experts/knowledge/sources/adr.py:48`); no exige doble aceptación.

**Corrección:** definir un único predicado de autoridad para consumidor y gate, y especificar
qué evento humano lo establece, qué revisión queda registrada y qué modificaciones lo invalidan.
No equiparar automáticamente un texto editable `approved` con evidencia de aprobación humana.

### F04 — Alta: la ingestión existente es un documento → un registro

Brainstorm: líneas 151–163, 427–430, 464–469.

`parse_adr()` devuelve un único registro y exige la sección singular `Decision`
(`parser.py:252`, `:283`). Su ID canónico se deriva sólo del path
(`codec.py:104`). `refresh_decisions()` conserva un registro por source
(`ingest.py:277`). Agregar `about` y `targets` al frontmatter no implementa múltiples
decisiones dentro de una spec, ni su identidad estable.

El hash ADR actual acredita secciones del documento (`parser.py:334`), no que el código
cumpla la regla. Las citas de código son otra ruta. Un hash de código previo a implementación
tampoco certifica el cumplimiento de una decisión recién aprobada.

**Corrección:** parser específico del bloque, identidad `spec + entry-id`, unicidad,
semántica de edición/retirada, y evidencia separada de aprobación, aplicabilidad y cumplimiento.
Reutilizar modelos/repositorio; no presentar esto como una mera extensión de claves.

### F05 — Alta: resolución de targets y herencia de alcance no existen como se describen

Brainstorm: líneas 109–111, 178–183, 431–446, 553.

`StructuralService.lookup()` recibe nombres/qualnames y búsqueda léxica, no un resolver
genérico de IDs (`structural/service.py:182`). `blast_radius()` sí resuelve símbolos exactos
internamente (`:480`), pero no directorios. `DecisionService._resolve_symbol()` acepta el
prefijo `sym:` sin comprobar existencia (`decisions/service.py:171`).
`for_symbol()` recupera enlaces al símbolo y a su archivo; no a directorios ancestros
(`:218`). Expandir `dir:x` a símbolos y consultar cada símbolo no descubre por sí solo una
decisión cuyo único enlace sigue apuntando a `dir:x`.

**Corrección:** resolver explícito por tipo, expansión y herencia de alcance documentadas,
límites y política ante índice desactualizado. Diferenciar applicability de impact: un
dependiente en el blast radius no hereda automáticamente todas las restricciones del target.
Definir también cómo declarar archivos/símbolos futuros: exigir existencia antes de implementar
impide decisiones sobre componentes nuevos, salvo que v1 obligue a anclarlas a contenedores existentes.

### F06 — Alta: sustitución, exenciones y aprobación no tienen un ciclo cerrado

Brainstorm: líneas 395–398, 453–454, 463, 482–483.

Declarar `supersedes` produce un enlace, no una transición automática del estado anterior:
el parser guarda aliases en `DecisionLink` (`parser.py:355`); `_visible()` excluye por
`source_status`, no por existir un sucesor (`service.py:161`). Sin resolver identidad,
dirección y vigencia, la regla vieja puede seguir gobernando junto a la nueva.
Tampoco se especifican ciclos, bifurcaciones, sustituciones parciales o autorreferencias.

`resolved-by: <owner>: <reason>` es texto mutable dentro de una sección regenerada.
No se define cómo autenticarlo, conservarlo, asociarlo a un finding estable ni invalidarlo
cuando cambia el conflicto. El juez final sólo menciona `resolved-by`, aunque el flujo de
usuario también admite resolver con `supersedes`.

**Corrección:** grafo de sustituciones validado, estado efectivo y alcance explícitos;
exenciones estructuradas vinculadas a IDs/revisiones/digest y aprobación verificable según
el flujo del repositorio. Separar exenciones editables del informe generado.

### F07 — Alta: el digest propuesto no cubre los inputs ni garantiza idempotencia

Brainstorm: líneas 455–469, 479–487.

Hash del cuerpo completo de la spec más hashes de páginas consultadas es insuficiente:
escribir `Consequences` cambia el cuerpo que acaba de hashearse. Cambiar código fuente puede
cambiar `verify_freshness()` sin cambiar la página persistida (`evidence.py:226`). También
afectan el resultado nuevas decisiones, aristas estructurales, taxonomy, reglas y configuración.
El CAS existente protege una escritura individual (`repository.py:96`), no una lectura
consistente de todo el inventario ni la aprobación multirregistro.

**Corrección:** canonicalizar inputs excluyendo salida generada; incluir inventario relevante,
fuentes observadas, revisión estructural, taxonomy y versión de reglas. Definir snapshot/recheck
al aprobar y evitar que las decisiones de la propia spec se juzguen contra sí mismas tras ingerirse.
CI debe reconstruir un estado comparable desde fuentes versionadas, sin depender de la SQLite local.

### F08 — Media: las garantías de salida y el alcance de v1 se contradicen

Brainstorm: líneas 106–108, 184–187, 461–462 frente a 473–476, 494–496 y 770–789.

“Non-zero iff contradiction” contradice los errores bloqueantes de targets/taxonomy.
CI y propagación a tareas se describen como parte de la funcionalidad y luego quedan como
preguntas abiertas. El texto cuenta dos secciones nuevas aunque enumera tres.

**Corrección:** matriz de resultados separando error/incompleto, contradicción no resuelta y
advisory. Resolver CI, `/sdd-task`, lifecycle del informe y fuente de aprobación antes de
estimar tareas. Incluir `.agents/skills/sdd-spec` y `sdd-task` en el impacto multiplataforma;
el cuadro actual enumera principalmente comandos Claude y workflows Antigravity.

### F09 — Media: FEAT-778 ya está implementado y no satisface todo el dossier prometido

Brainstorm: líneas 60–63, 221–223, 499–502, 737–739.

El índice `sdd/tasks/index/domain-experts.json` tiene **22/22 tareas `done`**.
Existen `experts/knowledge/resolver.py:28` y `experts/knowledge/sources/adr.py:16`.
La fuente ADR hace una consulta léxica `why(description)` y emite título/decisión; no recupera
por taxonomy ni devuelve rationale, consecuencias, alternativas descartadas o cadena de
sustituciones. `DecisionHit` tampoco incluye todos esos campos (`decisions/models.py:224`).

**Corrección:** eliminar “esperar a FEAT-778”; evaluar un contrato compartido real. El dossier
rico exige cargar registros completos/extender proyecciones. Reutilizar `ADRSource` sin cambios
no cumple la recuperación estricta por dominio que aquí se propone.

### F10 — Media: compatibilidad sólo en una dirección

Brainstorm: líneas 207–210, 565–566.

Los modelos usan `extra="forbid"`, `schema_version: Literal[1]` y relaciones Literal cerradas
(`models.py:57`, `:140`, `:175`). El lector nuevo puede aceptar registros viejos con defaults;
un lector viejo rechazará campos o relaciones nuevos aunque se mantenga `schema_version=1`.
`about` también exige persistencia autoritativa: `DecisionLink` no admite esa relación hoy,
y las aristas proyectadas son una caché, no autoridad (`ingest.py:380`).

**Corrección:** declarar matriz de compatibilidad y despliegue/migración. No usar
`supported_by` para representar indistintamente evidencia y target normativo. Persistir
`about` y targets con significado propio y reconstruir las aristas desde esos registros.

## Matriz de claims restantes

| Claim del brainstorm | Resultado | Evidencia / precisión necesaria |
|---|---|---|
| FEAT-578 implementó registros, evidencia, CAS, freshness y dejó fuera compliance automático | Confirmado | `sdd/specs/sdd-spec-wiki-adr.spec.md:43`, `:51`, `:357`; modelos, repositorio y servicio inspeccionados. |
| Lecturas ordinarias sin LLM | Confirmado dentro del contrato actual | Test offline ejecutado; no significa que toda operación de `DecisionService` sea offline: `generate()` es opt-in. |
| Sólo TID251 verifica mecánicamente reglas arquitectónicas | Refutado | `test_abstract_client_memoryless.py:73`, `:95`; `test_history_ownership.py:169`. Ambos tienen controles ejecutables. No equivalen a una auditoría completa. |
| No hay directorios ADR por defecto | Confirmado | No existen `docs/adr`, `docs/adrs`, `docs/decisions`. |
| Plano local vacío | Confirmado además por consulta | `wiki_decision_why(namespace="local", include_history=true)` devuelve `empty`, sin diagnósticos ni truncación. Ausencia de directorios por sí sola no lo demostraría: `refresh_decisions(paths=...)` permite otras fuentes y retiene desaparecidas. |
| Falta consumo explícito en los cuatro archivos SDD citados | Confirmado para esos archivos | Sin referencias a `wiki_decision_why`/`wiki_decisions_for_symbol` en los comandos/agentes citados; también se revisaron skills locales spec/task. No prueba que ningún agente pueda invocar esas herramientas. |
| No hay filtro taxonomy/tags en DecisionRecord | Confirmado | `models.py:172`; APIs `for_symbol`/`why`. |
| Una pregunta sobre memoria no puede contestarse hoy | Exagerado | `why()` acepta lenguaje natural sin símbolos (`service.py:276`); puede devolver coincidencias léxicas. Lo ausente es recuperación por dominio explícito con cobertura garantizada. |
| Seed “zero-code” | Parcial | El glob está implementado (`models.py:67`); leer `about`, targets, reglas y aprobación requiere cambios. Sólo descubrir los Markdown estándar es zero-code. |
| Parser sólo lee id/title/status/supersedes | Confirmado | `parser.py:132`. Una lista YAML multilínea da diagnóstico; una clave desconocida con valor inline puede ignorarse sin ese error. No afirmar que cualquier `targets:` falla igual. |
| PyYAML existe vía navconfig | Dependencia disponible, explicación imprecisa | Es dependencia directa de core: `packages/ai-parrot/pyproject.toml:58`. |
| RelationType.ABOUT existe; faltan CONSTRAINS/FORBIDS/REQUIRES | Confirmado | `knowledge/okf/ontology.py`. No implica que DecisionLink acepte ABOUT. |
| navrules y backend Rust están disponibles en workspace | Confirmado como implementación | `packages/navrules`, `ruleset.py:20`; backend opcional/condicionado. “Large rule sets stay cheap” necesita benchmark. |
| Issue 36a652416160 sigue abierto | Refutado | Ledger: cerrado el 2026-10-18 por FEAT-700; inventario esperado centralizado en `_tool_surface.py`. Un nuevo tool aún requiere actualizar ese inventario. |
| Issue b084239103d7 sigue abierto | Confirmado | Ledger: `open`, `feature_gap`; la ausencia de extracción documental sigue pendiente. |
| No hay pasos CI de check_task_graph/check_e2e_closeout | Confirmado para nombres exactos | Búsqueda en `.github/workflows` sin coincidencias; no demuestra ausencia de toda validación SDD en CI. |
| Auditoría manual de 2026-09-20 | Archivo y fecha confirmados | `plan-then-execute-design-drift.findings.md:7`. “Única”, “sesión completa” y “ya obsoleta” no están demostrados por fecha/existencia. |
| Opciones B/C no pueden ser consumers o requieren segunda autoridad | No demostrado | Es una elección de integración: un evaluador podría recibir una proyección de DecisionRecord. A reduce integración, pero no tiene exclusividad lógica sobre consumer/producer. |

## Referencia externa: open-ontologies

Se contrastó con el [README oficial](https://github.com/fabio-rovai/open-ontologies#readme).
Confirma Rust/MIT, lifecycle, certificados TSV, checker Lean independiente y digest de assertions.
Sin embargo, la conservatividad se evalúa bajo una tabla de reglas; la fuente distingue pruebas,
mediciones y resultados no certificados. No justifica “conservativity and satisfiability are
solved problems” sin delimitar fragmento y garantías. El software instalado puede operar offline;
el coste es aprovisionar/versionar herramientas. Proyectar relaciones SDD a RDF no les confiere
automáticamente semántica lógica. Mantener C como exploración opcional es razonable, pero sus
ventajas deben formularse con esos límites. No se ejecutó ni certificó el motor externo.

## Decisiones recomendadas tras la verificación

1. Mantener A, seed versionado y lectura sin LLM. Separar inventario completo de la presentación presupuestada.
2. Mantener los dos ejes dominio/estructura, con semántica de alcance explícita y fuente autoritativa única.
3. Elegir entre proposiciones estructuradas verificables y conflictos explícitos; no bloquear por polaridad de targets genéricos.
4. Resolver aprobación, sustitución, exenciones e identidad antes de diseñar el parser/servicio.
5. Usar FEAT-778 ya implementado como referencia concreta; no asumir equivalencia entre su ADRSource y el dossier requerido.
6. Mantener certificados/drift/backfill fuera de v1. Describir v1 como consistencia de declaraciones, sin prometer demostrar cumplimiento del código.

## Validación y límites

- Lectura completa del brainstorm y contraste focalizado de fuentes; wiki consultada antes del código.
- Consulta del plano ADR local y de ambos issues del ledger, sin sincronizar ni ingerir decisiones.
- Pruebas existentes ejecutadas: `test_namespace_and_offline.py`, `test_abstract_client_memoryless.py`, `test_history_ownership.py`.
- Resultado: **41 passed, 8 warnings**, 3.18 s. Log: `artifacts/logs/sdd_decision_audit_review_pytest.log`.
- Las pruebas corroboran el comportamiento existente; el gate propuesto aún no existe y no se probó.
- No se ha revalidado exhaustivamente cada firma auxiliar, cada tarea histórica ni el estado de ramas remotas.
- No se modificó el brainstorm ni código de implementación.
