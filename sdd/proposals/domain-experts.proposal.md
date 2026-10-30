# Domain Experts en ai-parrot — SDD Proposal (brainstorm)

Oct 30, 2026 · @Jesus Lara

## Resumen

Se propone introducir en ai-parrot el concepto de **Domain Expert**: un agente declarativo compuesto por una identidad (`persona.md`), una knowledge base propia en dos tiers, un conjunto de reglas de gobierno y acceso obligatorio al LLM Wiki (OKF) y al bookstore. Un expert es inerte hasta que un stage de un Flow SDD lo nombra como lead o support; la delegación siempre la hace el conductor del Flow, nunca otro expert.

El patrón se toma de los *domain experts* de AWS AI-DLC (11 agentes de dominio, knowledge en dos tiers, orden de carga determinista, binding a stages) y se adapta a lo que ai-parrot ya tiene: PromptBuilder por capas, AgentRegistry/AgentCrew, LLM Wiki OKF, GraphIndex, soporte ADR y gates de sesión AHP. Los primeros consumidores son `sdd-proposal` y `sdd-spec`, que delegan en experts la validación, la escritura y la review de documentos SDD y ADR.

Este documento es un brainstorm para abrir el research; las decisiones quedan abiertas en la sección de preguntas.

## Contexto y motivación

ai-parrot ya tiene las primitivas; falta el contrato que las convierte en un expert reutilizable.

| Primitiva existente | Estado | Qué aporta al expert |
| --- | --- | --- |
| PromptBuilder por capas (`identity`, …) | En producción | Capa donde encaja `persona.md` |
| Loader de knowledge (KB) | Funcional, sin optimizar | Base del `KnowledgeResolver`; hoy carga sin presupuesto ni orden declarado |
| LLM Wiki (bundles OKF) + bookstore | En producción | Conocimiento documental del expert; acceso obligatorio |
| GraphIndex (L0 tree-sitter, L1 wiki, L2 retrieval) | Diseño v1 cerrado | Retrieval de KBs grandes y trazabilidad código ↔ conocimiento |
| Soporte ADR | Existe | Fuente de verdad para el expert y artefacto que puede producir |
| `sdd-proposal` / `sdd-spec` | Existen | Primeros consumidores: delegan validación, escritura y review |
| AgentRegistry / AgentCrew | En producción | Registro y despacho de experts |
| Gates de sesión AHP (TTL fail-closed/fail-open) | Implementado con smoke tests | Approval gates de cada stage |
| OTEL por agente, modelo y tool | En producción | Observabilidad por expert sin cambios |

Lo que falta: una forma declarativa de definir un expert (identidad + knowledge + reglas + toolkits), un orden de carga determinista y presupuestado, y el binding entre experts y stages de un Flow SDD. Sin eso, cada agente de dominio (contratos, legal, trading) se construye a mano y no comparte contrato.

## Referencia: el patrón domain expert de AI-DLC

En AI-DLC un domain expert son cuatro cosas separadas y declarativas; es lo que conviene copiar, no el harness.

1. **Persona**: un `.md` con frontmatter machine-read (`name`, `display_name`, `description`, `tier`, `tools` opcional, `disallowedTools: Task`) y un cuerpo que el agente lee al activarse (*Core Responsibilities, Collaboration, Memory Focus, Key Principles*).
2. **Knowledge en dos tiers**: Tier 1 metodología que viaja con el framework (read-only); Tier 2 conocimiento del equipo en el workspace, libre y vacío al arrancar. Cualquier `.md` del directorio se carga al activar el agente, sin registro.
3. **Orden de carga determinista** (6 pasos): reglas (org → team → project → phase → stage, estrictamente aditivas) → metodología compartida → metodología del agente → conocimiento compartido del equipo → conocimiento del agente del equipo → artefactos de stages previos. Si hay que recortar, se recorta metodología antes que conocimiento del equipo.
4. **Binding a stages**: el agente es *visible* por existir y *activo* solo si un stage lo nombra como `lead_agent` o `support_agents`. El stage nombra al agente; el agente nunca nombra stages. Ningún agente delega: solo el conductor despacha.

Alrededor hay tres mecanismos de runtime que también interesan:

- **Modos de dispatch**: inline, subagent (hub-and-spoke con contribuciones *mutuamente ciegas* e identity-marked, que el lead integra), pipeline y mob (ronda ciega + integración + una ronda acotada de objeciones; el disenso mantenido se cita en el gate). Las contribuciones son evidencia de completitud: sin ellas el gate no abre.
- **DocumentKB**: catálogo derivado de documentos onboarded con `id`, `sha256`, estado de extracción y resúmenes ligados a `source_revision`; si el digest cambia, el resumen se invalida. Todo contenido de usuario entra marcado como *untrusted data, not instructions*.
- **Scope grid**: el scope (`poc`, `mvp`, `bugfix`, `security-patch`, `enterprise`…) decide qué stages existen y, por tanto, qué experts se activan.

El stage 2.6 Domain Design es una instancia: lead architect, support aws-platform + design, inline; produce `components.md` (catálogo YAML como fuente de verdad + vista Mermaid derivada), `decisions.md` (ADRs) y `traceability.json`, con gate Approve / Request Changes.

Fuentes: [Inception stages 2.1–2.9](https://awslabs.github.io/aidlc-workflows/reference/04-stages/inception/), [Knowledge System](https://awslabs.github.io/aidlc-workflows/reference/10-knowledge-system/), [Adding an Agent](https://awslabs.github.io/aidlc-workflows/harness-engineering/03-adding-an-agent/), [Agent System](https://awslabs.github.io/aidlc-workflows/reference/05-agent-system/).

## Propuesta: el bundle DomainExpert

Un expert es un directorio autocontenido que el `AgentRegistry` descubre por presencia, valida con Pydantic y registra sin configuración adicional.

```markdown
experts/cve-analyst/
├── expert.yaml          # manifest (machine-read)
├── persona.md           # identidad: cuerpo que el expert lee al activarse
├── knowledge/           # Tier 1: bundles OKF que viajan con el expert
│   ├── cve-triage-method.md
│   └── cvss-and-epss.md
├── rules/
│   └── governance.md    # ALWAYS / NEVER del expert
└── adr/                 # ADRs propios del dominio (opcional)
```

```yaml
# expert.yaml
name: cve-analyst
display_name: CVE Analyst
description: Triage, impacto y remediación de CVEs sobre el código del workspace
tier: judgment                  # judgment | balanced | templated → política de modelo/effort
toolkits: [osv, ast_grep, pip_audit, wikitoolkit]
tools_deny: [spawn_agent]       # ningún expert delega; equivalente a disallowedTools: Task
knowledge:
  - source: bundled             # Tier 1, read-only
    mode: inline
  - source: workspace           # Tier 2: .parrot/knowledge/cve-analyst/
    mode: inline
  - source: wiki                # LLM Wiki OKF + bookstore: obligatorio
    mode: retrieval
    scope: {tags: [cve, advisory, security]}
  - source: graphindex          # grafo L0 del repo
    mode: retrieval
  - source: adr                 # ADRs del workspace como fuente de verdad
    mode: inline
    filter: {status: [accepted]}
capabilities: [validate, write, review]   # lo que sdd-proposal / sdd-spec pueden delegar
produces: [vulnerability-report, remediation-plan, adr]
```

Invariantes del manifest:

- `name` debe coincidir con el nombre del directorio; nombres duplicados fallan en carga.
- `knowledge` siempre incluye `source: wiki`; un manifest sin wiki es inválido.
- `tools_deny` siempre incluye `spawn_agent`; la delegación pertenece al conductor del Flow.
- `tier` se proyecta a una política de modelo y effort; el manifest nunca nombra un modelo concreto.
- Un expert registrado pero no nombrado por ningún stage es visible e inerte.

## Identidad: persona.md como capa identity

`persona.md` se inyecta como la capa `identity` del PromptBuilder cuando el expert se activa; sustituye a la identidad genérica del agente conductor en modo inline y es la identidad completa del subagente en modo despachado.

Estructura fija del cuerpo, para que el resolver pueda validarla y recortarla por secciones:

| Sección | Contenido | Recortable |
| --- | --- | --- |
| Core Responsibilities | Qué hace y qué no hace el expert | No |
| Collaboration | De quién recibe, con quién trabaja, a quién entrega | No |
| Memory Focus | Qué temas de memoria consulta y actualiza | Sí |
| Key Principles | Guías de comportamiento del dominio | Parcial |

Solo el frontmatter de `expert.yaml` es machine-read; `persona.md` es prosa para el propio expert. Un cambio de persona no exige cambio de código ni de registro.

## Knowledge: tiers, loader y wiki obligatoria

El loader actual se sustituye por un `KnowledgeResolver` puro: dado `(expert, stage, workspace)` devuelve un `KnowledgeContext` ordenado y presupuestado, reproducible sin LLM.

**Orden de carga** (adaptado del de 6 pasos de AI-DLC):

1. Reglas de gobierno resueltas (org → team → project → phase → stage; ver sección siguiente).
2. Tier 1 compartido: metodología que viaja con ai-parrot (p. ej. plantillas SDD, formato ADR).
3. Tier 1 del expert: `experts/<slug>/knowledge/`.
4. Tier 2 compartido del workspace: `.parrot/knowledge/shared/`.
5. Tier 2 del expert: `.parrot/knowledge/<slug>/`.
6. ADRs aceptados que el expert declara consumir.
7. Artefactos de stages previos que el stage actual nombra como inputs.
8. Retrieval bajo demanda: wiki OKF + bookstore y GraphIndex, según `scope`.

**Dos modos por fuente.** AI-DLC carga todos los `.md` al contexto porque es un harness sin runtime. ai-parrot tiene runtime y presupuesto de tokens: cada fuente declara `mode: inline` (persona, reglas, resúmenes, ADRs) o `mode: retrieval` (feeds grandes, grafo de código). Para retrieval, el resolver inyecta solo el índice o resumen y deja la consulta a las policies L2 de GraphIndex y al wikitoolkit.

**Presupuesto y recorte.** Cada capa tiene cuota; al recortar, el orden es metodología Tier 1 antes que conocimiento Tier 2, y nunca reglas ni persona. Encaja con el budgeting BPE de la compactación per-turn.

**Wiki OKF + bookstore como acceso obligatorio.** Todo expert tiene el `wikitoolkit` en su toolkit y un `scope` de la wiki. Es la vía para incorporarle conocimiento documental sin tocar el bundle: onboardear un documento al bookstore, taggearlo, y el expert lo ve en su siguiente activación. Del DocumentKB de AI-DLC se copia el contrato, no la implementación: cada documento con `id` y `sha256`, resúmenes ligados a `source_revision` e invalidados si cambia el digest, y contenido de usuario envuelto como datos no confiables.

```yaml
# KnowledgeContext (salida del resolver, serializable y testeable)
expert: cve-analyst
stage: cve-triage
budget_tokens: 24000
layers:
  - {layer: rules,        source: org/governance.md,          revision: 3f1a…, tokens: 420}
  - {layer: tier1_shared, source: sdd/templates.md,            revision: 9b02…, tokens: 1800}
  - {layer: tier1_expert, source: cve-triage-method.md,        revision: c7d4…, tokens: 2100}
  - {layer: tier2_expert, source: .parrot/knowledge/cve-analyst/sla-policy.md, revision: 11ae…, tokens: 600}
  - {layer: adr,          source: ADR-0007-dependency-policy.md, revision: 52c9…, tokens: 350}
  - {layer: retrieval,    source: wiki, scope: {tags: [cve]},   handle: wikitoolkit}
trimmed: []
```

## Reglas de gobierno

Un expert carga una cadena de reglas estrictamente aditiva: una capa más amplia nunca se anula, solo se añade. Esto es lo que hace que un expert se comporte igual en `sdd-proposal`, en `sdd-spec` y en un Flow de construcción.

| Capa | Dónde vive | Ejemplo |
| --- | --- | --- |
| org | `.parrot/memory/org.md` | NEVER proponer dependencias con licencia AGPL |
| team | `.parrot/memory/team.md` | ALWAYS incluir sección de riesgos en un proposal |
| project | `.parrot/memory/project.md` | ALWAYS referenciar el ADR que justifica un cambio de contrato |
| expert | `experts/<slug>/rules/governance.md` | ALWAYS citar CVE id y CVSS al reportar una vulnerabilidad |
| phase / stage | frontmatter del stage | NEVER recomendar orden de implementación en Domain Design |

Formato: dos secciones, *Mandated* (`ALWAYS …`) y *Forbidden* (`NEVER …`), sin prosa libre, para que el resolver las pueda contar, deduplicar y verificar en tests. Las reglas nunca se recortan por presupuesto.

Las reglas descubiertas durante un stage (el equivalente al *Practices Discovery* de AI-DLC) se promueven a `team.md` / `project.md` solo tras un gate humano, nunca de forma automática.

## ADR: consumidor y productor

El expert trata los ADRs aceptados del workspace como fuente de verdad y puede recibir delegada la construcción de nuevos ADRs. Son dos contratos distintos.

**Como consumidor.** La fuente `adr` del manifest carga en modo inline los ADRs con `status: accepted` que cumplan el filtro del expert (por tag de dominio o por componente). Un expert que proponga algo contrario a un ADR aceptado debe citarlo y marcar la propuesta como *supersede*, nunca ignorarlo. Esto convierte a los ADRs en la regla de gobierno con más peso después de org/team/project.

**Como productor.** `sdd-proposal` o `sdd-spec` pueden delegar en un expert con `capabilities: [write]` la redacción de un ADR a partir de una decisión tomada en un stage. El expert produce el ADR con la plantilla del soporte ADR existente (contexto, decisión, alternativas rechazadas, consecuencias, trazabilidad al requisito o story) y lo entrega como artefacto del stage, pendiente de gate. Un ADR producido por un expert nace siempre en `status: proposed`; solo el gate humano lo acepta.

| Operación | Quién la pide | Quién la hace | Resultado |
| --- | --- | --- | --- |
| Cargar ADRs aceptados | KnowledgeResolver | Fuente `adr` del manifest | Capa `adr` del KnowledgeContext |
| Detectar conflicto con un ADR | Expert durante validate/review | Expert | Hallazgo citado en la contribución |
| Redactar ADR nuevo | sdd-proposal / sdd-spec / stage | Expert con `write` | `ADR-NNNN.md` en `proposed` |
| Aceptar o rechazar | Gate del stage | Humano | `status` actualizado; el expert lo verá en la siguiente activación |

## Integración con sdd-proposal y sdd-spec

Los dos flujos SDD existentes se convierten en los primeros conductores de experts: cada uno puede delegar tres operaciones, declaradas en `capabilities` del manifest.

| Capability | sdd-proposal (research) | sdd-spec (construcción de specs) |
| --- | --- | --- |
| `validate` | Contrastar hipótesis y hallazgos del research contra el conocimiento y las reglas del dominio; devolver hallazgos con cita | Verificar que la spec respeta ADRs, contratos y reglas; devolver lista de incumplimientos |
| `write` | Redactar la sección del proposal que cae en su dominio (p. ej. análisis de riesgos de seguridad) | Redactar secciones de la spec, catálogos de componentes y ADRs derivados |
| `review` | Revisión ciega del proposal completo; contribución identity-marked | Revisión ciega de la spec; una ronda acotada de objeciones |

Protocolo de delegación, común a ambos:

1. El conductor resuelve el `KnowledgeContext` del expert para ese stage y le pasa rutas a los artefactos, no sus cuerpos.
2. El expert escribe su contribución en `contributions/<slug>.md` con marcador de identidad; nunca edita el artefacto del lead.
3. Varios experts en el mismo stage son mutuamente ciegos: reciben el borrador del lead y los inputs, no las contribuciones de sus hermanos.
4. El lead integra; los desacuerdos de juicio van al humano en el gate, los de conocimiento tienen una ronda de objeción.
5. El gate no abre si falta alguna contribución esperada.

Un expert no decide si participa: lo decide el stage del flow (o el scope). `sdd-proposal` con scope `security-patch` nombra a `cve-analyst` como support en research; con scope `mvp` no lo nombra.

## Flows, stages, scope grid y dispatch

Un Flow SDD es un grafo de stages compilado en carga; cada stage nombra su lead, sus supports, el modo de despacho, sus inputs, sus artefactos con esquema y su gate. El compilador falla si un stage nombra un expert inexistente o un artefacto sin esquema.

```yaml
# flows/security-patch/stages/cve-triage.yaml
name: cve-triage
phase: inception
condition: always
lead: cve-analyst
support: [developer]
mode: subagent                   # inline | subagent | pipeline | mob
inputs:
  - codekb/<repo>/*              # reutiliza reverse-engineering si existe
  - wiki:{tags:[cve, advisory]}
outputs:
  vulnerability-report: {schema: VulnerabilityReport}   # YAML fuente de verdad + vista derivada
  traceability: {schema: Traceability}                  # CVE → símbolo afectado → unidad de fix
gate: approve_or_request_changes # sobre gates AHP, TTL fail-closed
```

**Scope grid.** El scope decide qué stages existen y, por tanto, qué experts se activan. Nada más.

| Scope | Stages de inception | Experts activados |
| --- | --- | --- |
| poc | requirements (mínimo), walking skeleton | product, developer |
| mvp | requirements, user stories, domain design, units, contracts, delivery planning | product, architect, developer, quality |
| security-patch | reverse engineering (brownfield), cve-triage, remediation plan | cve-analyst, developer, quality |
| bugfix | reverse engineering (brownfield), requirements (mínimo) | developer |

**Modos de dispatch**, implementados sobre AgentCrew:

- *inline*: la persona del lead se inyecta en el agente conductor; nada se despacha.
- *subagent* (hub-and-spoke): el lead escribe un borrador; cada support lo recibe sin ver a sus hermanos; escribe `contributions/<slug>.md`; el lead integra.
- *pipeline*: cadena; cada eslabón recibe la ruta del artefacto anterior, no su cuerpo.
- *mob*: ronda ciega + integración + una ronda acotada de objeciones; el disenso mantenido se cita en el gate.

Invariante que no se relaja: ningún expert despacha a otro. Toda delegación sale del conductor del Flow, que es lo que mantiene el grafo de ejecución predecible, auditable y legible en las métricas OTEL por agente.

&#91;embedded content: ciclo de un stage · conductor, resolver, expert, contribución, gate\]

El conductor resuelve el contexto, activa al expert y recoge su contribución; solo el gate humano devuelve el control al siguiente stage.

## Casos de uso de referencia

**`cve-analyst` con scope `security-patch`.** Es el primer expert real porque ejercita todas las piezas: knowledge en dos tiers, retrieval de feeds grandes, grafo de código, ADRs y un artefacto con esquema.

| Pieza | Contenido |
| --- | --- |
| Tier 1 (bundle) | Método de triage, CVSS/EPSS, patrones de remediación por ecosistema (pip, npm, cargo) |
| Tier 2 (workspace) | SLAs por severidad, paquetes vetados, excepciones aprobadas |
| Wiki + bookstore | Feeds OSV/NVD/KEV onboardeados y taggeados; advisories del proveedor |
| GraphIndex | Grafo L0 del repo: paquete → símbolo que lo usa → módulo |
| ADRs | Política de dependencias, decisiones de pinning |
| Toolkits | `osv`, `pip_audit`/`grype`, `ast_grep` para localizar y proponer el parche, `wikitoolkit` |
| Artefactos | `vulnerability-report.md`, `remediation-plan.md`, `traceability.json` (CVE → símbolo → unidad de fix → verificación) |

La cadena CVE → paquete → símbolo afectado → fix → verificación es lo que GraphIndex permite y ningún scanner da por sí solo. Un advisory es un vector obvio de prompt injection: entra siempre envuelto como datos no confiables.

**Scope `mvp` / `poc`.** Aquí los experts son los genéricos (product, architect, developer, quality) y lo que se replica es el scope grid más el stage Domain Design tal cual: un `ComponentCatalogue` en Pydantic (componentes con `behaviour`, `responsibilities`, `depends_on`, `entities` con `identifier` y `references`) que se serializa a YAML como fuente de verdad y renderiza una vista Mermaid; más el log de ADRs y la trazabilidad `US/FR → componente`. Es el tipo de salida estructurada para la que ya existe `parrot.outputs`.

**Experts de dominio ya existentes.** Los agentes de contratos y legales que corren sobre ai-parrot son instancias de este patrón construidas a mano; migrarlos al bundle es la prueba de que el contrato generaliza.

## Preguntas abiertas para el research

- [ ] **Ubicación del bundle.** ¿`experts/` dentro del paquete ai-parrot (Tier 1 instalable vía pip) y `.parrot/experts/` en el workspace para experts propios del proyecto? ¿O un único namespace con prioridad workspace > paquete?
- [ ] **Relación con AgentRegistry.** ¿Un expert es un `Agent` con un `ExpertProfile` adjunto, o una subclase `DomainExpert`? Afecta a cómo lo ve AgentCrew y a la serialización del estado AHP.
- [ ] **Capa `identity` del PromptBuilder.** ¿`persona.md` sustituye la identidad del conductor en modo inline o se apila sobre ella? ¿Qué pasa con dos experts inline en el mismo turno?
- [ ] **Presupuesto del KnowledgeContext.** ¿Cuota fija por capa, proporcional al `tier`, o derivada del modelo activo? ¿Cómo se reporta el recorte (`trimmed`) al humano?
- [ ] **Wiki como fuente obligatoria.** ¿Qué `scope` mínimo exige el validador? ¿Un expert sin documentos taggeados en la wiki debe fallar en carga o solo avisar?
- [ ] **ADR en modo inline.** ¿Cuántos ADRs aceptados caben antes de pasar a retrieval? ¿Filtro por tag, por componente o por ambos?
- [ ] **Reglas promovidas.** ¿Dónde se persiste la promoción a `team.md` / `project.md` y cómo se audita quién la aprobó?
- [ ] **Contribuciones como evidencia.** ¿Se almacenan en el workspace (ficheros) o en el memory backend con el turno? Influye en la compactación per-turn.
- [ ] **Scope grid declarativo.** ¿Tabla YAML compilada con el flow o política en código? ¿Puede el humano sobrescribir el scope en un gate?
- [ ] **Tier → modelo.** ¿La proyección de `tier` vive en navconfig o en el manifest del Flow? ¿Cómo se registra en OTEL qué tier corrió cada stage?
- [ ] **Identidad del expert en memoria.** ¿Un expert tiene memoria propia entre activaciones (Memory Focus) o solo lee la memoria del workspace?
- [ ] **Migración.** ¿Qué agentes existentes (contratos, legal, trading) se migran primero y qué rompe en su API pública?

## Alternativas consideradas

| Alternativa | Por qué se descarta (o se pospone) |
| --- | --- |
| Copiar AI-DLC como harness de ficheros Markdown leídos por el LLM | AI-DLC no tiene runtime; carga todo el knowledge al contexto y gobierna con convenciones de ficheros. ai-parrot tiene runtime, presupuesto de tokens y gates AHP: el contrato se puede verificar en código y testear sin LLM. |
| Experts como simples system prompts por agente | Pierde el orden de carga determinista, el presupuesto por capa y la trazabilidad de qué revisión de cada fuente entró en el contexto. |
| Permitir que un expert despache a otros experts | Rompe la predictibilidad del grafo de ejecución y la atribución OTEL; es la regla que AI-DLC más defiende (`disallowedTools: Task`). Se mantiene la prohibición. |
| Knowledge solo por retrieval (RAG puro) | Persona, reglas y ADRs deben estar siempre presentes; un retrieval que no los devuelva cambia el comportamiento del expert entre turnos. Se mantiene el modo dual inline/retrieval. |
| Un `.md` por expert con todo dentro | Impide validar el manifest, versionar knowledge por separado y reutilizar reglas. El bundle en directorio mantiene cada parte editable por separado. |

## Fases propuestas y fuera de alcance

1. **Manifest + loader + resolver.** `expert.yaml` en Pydantic, descubrimiento en AgentRegistry, `persona.md` como capa `identity`, `KnowledgeResolver` con orden y presupuesto, solo modo inline. Tests deterministas sin LLM sobre el `KnowledgeContext`. Reemplaza el loader de KB actual.
2. **Reglas, ADR y wiki.** Cadena aditiva de reglas, fuente `adr` (consumo) y capability `write` para ADR (producción), `wikitoolkit` obligatorio con `scope`, contrato de digest/revisión sobre el bookstore.
3. **Delegación desde sdd-proposal y sdd-spec.** Capabilities `validate` / `write` / `review`, protocolo de contribuciones ciegas e identity-marked, gate que exige las contribuciones.
4. **Flows y dispatch.** Spec de stage, compilador a grafo, scope grid, modos subagent / pipeline / mob sobre AgentCrew, gates sobre AHP.
5. **Primeros experts.** `cve-analyst` con scope `security-patch`; después el grid `mvp` / `poc` con Domain Design y `ComponentCatalogue`; migración de los agentes de contratos y legal al bundle.

Fuera de alcance de este research:

- Infraestructura de ingesta de feeds CVE (OSV/NVD/KEV) más allá de onboardearlos al bookstore.
- UI de administración de experts en el admin de ai-parrot.
- Multi-equipo / workshop mode de AI-DLC.
- Proyección de `tier` a proveedores concretos de modelo; se asume política en navconfig.
