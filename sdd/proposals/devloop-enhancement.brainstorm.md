---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: DevLoop Enhancement — Feature-Mode Topology (SDD-style Feature Development Flow)

**Date**: 2026-07-26
**Author**: Jesus Lara (con Claude)
**Status**: exploration
**Recommended Option**: B

---

## Problem Statement

El flow `parrot.flows.dev_loop` fue diseñado para un proceso estricto y cerrado
de resolución de **bugs**: `BugIntake` extrae logs de CloudWatch/Elasticsearch,
el `ResearchNode` crea obligatoriamente un ticket Jira, y los acceptance
criteria vienen anclados a flowtasks o comandos shell. Para el desarrollo de
**nuevas funcionalidades core** (en ai-parrot u otras librerías) todo ese
boilerplate es innecesario y el flow no representa nuestro workflow SDD real
(`/sdd-brainstorm → /sdd-proposal → /sdd-spec → /sdd-task → implement →
/sdd-done`).

Hoy `WorkKind` ya admite `"new_feature"` (models.py:116), pero ese kind se
rutea **idéntico** a un bug sin intake: `enhancement` y `new_feature` toman el
mismo edge `IS_NOT_BUG → research` (definition.py:95), que exige Jira, log
excerpts y criterios ejecutables. No existe una topología orientada a features.

Se necesita un **feature-mode** del dev_loop, alineado con el patrón "Graph
Engineering" (fan-out → reduce → synthesize, judge panel, bounded feedback
loop) ya evaluado en FEAT-377:

1. **Intake documental**: el flow exige un brainstorm/proposal markdown, o un
   spec ya resuelto por el usuario — no un BugBrief con log sources.
2. **Planner**: el primer nodo genera (si faltan) spec + task index con
   `depends_on` (equivalente a `/sdd-spec` + `/sdd-task`) y dimensiona el pool
   de dev agents según el grafo de dependencias; el LLM/backend de cada agente
   viene de config.
3. **The diamond**: fan-out de N dev agents → merge de worktrees → nodo de
   **síntesis** que integra y reconcilia los resultados.
4. **QA con Judge Panel**: N jueces configurables (un cliente LLM por juez),
   decisión por mayoría, con adversarial review (`sdd-secondopinion`) como uno
   de los jueces.
5. **Feedback router**: un agente LLM que traduce los findings del panel en un
   dev-brief accionable y decide retry (acotado) / escalar / aceptar-con-notas,
   montado sobre el repair loop QA→Development de FEAT-377/G1.
6. **Feature handoff**: push + **PR obligatorio contra `dev`** (nunca merge
   directo), más un artefacto de documentación de lo realizado y actualización
   del wiki/knowledge-graph (`wikitoolkit` / GraphIndex) — un "sdd-done"
   automatizado que documenta y alimenta la memoria del repo.

Afectados: desarrolladores de ai-parrot y librerías satélite que hoy corren el
ciclo SDD a mano; operadores del dev_loop que solo pueden automatizar bugs.

## Constraints & Requirements

- **Feature regular sobre `dev`** (`type: feature`, `base_branch: dev`).
- **Variante dentro de `parrot/flows/dev_loop/`** — no un paquete nuevo: una
  segunda definition/topología en el mismo paquete, seleccionada por el
  IntentClassifier o por config/CLI (decisión de usuario, Ronda 1).
- **Depende de FEAT-377** — consume, no duplica: FEAT-A
  `dev-loop-qa-repair-loop` (edge QA→Development acotado, `_CEL_QA_RETRY`,
  `QaAttemptRecorded`, `DEV_LOOP_QA_MAX_RETRIES`), FEAT-B
  `dev-loop-graph-memory` (`DevLoopGraphMemory`) y FEAT-F
  `graphindex-ontology-completion`. Este feature NO implementa el retry edge
  ni el graph write-back genérico; los consume/extiende.
- **Jira opcional** en feature-mode: si el documento/config trae ticket se
  enlaza; si no, se omite (hoy `ResearchNode` crea issue incondicionalmente).
- **PR siempre, merge nunca**: el flow termina en draft-PR contra `dev`
  (reutilizando el patrón de `DeploymentHandoffNode`); el humano mergea.
  Sin gates intermedios (autónomo hasta PR).
- **Paridad declarativa/imperativa**: toda nueva topología debe existir en
  `definition.py` Y re-declararse con `add_edge` imperativo (constraint
  verificado: el scheduler de `from_definition` es AND-join; flow.py:301-307).
- **Event-sourced state**: todo estado nuevo (verdicts del panel, decisiones
  del feedback router) entra como action types + reducers sobre
  `DevLoopSessionState` (FEAT-322), nunca estado mutable.
- **Prompts de subagentes** deben aterrizar en `_subagent_data/` (el
  dispatcher solo lee de ahí vía `load_subagent_definition`), no solo en
  `.claude/agents/`.
- Async/await en todo; `uv` + venv; sin dependencias externas nuevas (gh CLI,
  aiohttp, click ya presentes).

---

## Options Explored

### Option A: Paquete hermano `parrot/flows/feature_dev/`

Un paquete nuevo con su propia definition, nodos y runner, importando la
infraestructura de dev_loop (dispatchers, `DevAgentPool`, `TaskScheduler`,
`SubWorktreeManager`, `code_review.py`) como librería compartida.

✅ **Pros:**
- Cero riesgo de regresión sobre el bug-loop en producción.
- Libertad total de topología y modelos (FeatureBrief sin herencia forzada).
- El paquete dev_loop no crece (ya tiene un dispatcher.py de 3053 líneas).

❌ **Cons:**
- Duplica el andamiaje transversal: runner, session_state (el `NodeId` Literal
  y los reducers están acoplados al paquete), FlowEventPublisher, CLI,
  factories — o fuerza a extraer una capa común primero (refactor grande).
- Dos lugares donde mantener el mismo patrón de nodos; deriva garantizada.
- El usuario decidió explícitamente en contra (Ronda 1).

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| (ninguna nueva) | — | Reutiliza dispatchers/pool/worktree de dev_loop |

🔗 **Existing Code to Reuse:**
- `parrot/flows/dev_loop/agent_pool.py`, `task_scheduler.py`, `worktree_manager.py` — importados cross-package
- `parrot/flows/dev_loop/code_review.py` — panel de jueces

---

### Option B: Variante feature-mode dentro de `parrot/flows/dev_loop/` ⭐

Extender el paquete existente con una **tercera topología** (junto a la
inicial y la de revisión), siguiendo el precedente exacto de
`build_dev_loop_definition(revision=True)` + `build_dev_loop_revision_flow()`
(runner.py:101): un `mode: Literal["bug","feature"]` en la definition, nodos
nuevos registrados en el mismo registry, factories ampliadas, y selección de
ruta vía `IntentClassifierNode` (nuevo kind ruteable) o CLI
(`parrot devloop run --brief feature.yaml` donde el brief es un
`FeatureBrief`).

Topología feature-mode:

```
intent_classifier ─(kind=="feature")→ planner → development → synthesis → qa ─(passed)→ feature_handoff → close
                                                     ↑                     │
                                                     └──(feedback_router: retry ≤ N)──┘
                                                                            │
                                        (escalate / attempts ≥ N)→ failure_handler
```

- **`PlannerNode`** (variante de `ResearchNode`): recibe `FeatureBrief`
  (document_path + doc_kind ∈ {brainstorm, proposal, spec}), despacha un
  subagente `sdd-planner` que —si falta— genera spec + task index
  (`/sdd-spec` + `/sdd-task`), crea el worktree, y devuelve
  `PlannerOutput` (spec_path, task index, worktree, branch, jira opcional,
  **pool sizing sugerido** derivado de las waves de `TaskScheduler`).
  Jira: solo si `FeatureBrief.jira_issue_key` viene poblado.
- **Development**: el `DevelopmentNode` actual sin cambios — FEAT-323 ya
  implementa el fan-out (waves Kahn) y el merge (`merge_sequential`).
- **`SynthesisNode`** (nuevo): el "reduce → synthesize" explícito del diamond.
  Tras el merge, despacha un agente que reconcilia interfaces entre los
  outputs de los workers, corre la suite de integración y produce un
  `SynthesisReport` (resumen integrado + inconsistencias resueltas). Es el
  "owner del merge point" a nivel semántico, no solo git.
- **QA + Judge Panel**: `QANode` actual (determinista + code review +
  adversarial FEAT-375 ya cableado) más un nuevo
  `JudgePanelReviewDispatcher` en `code_review.py` que generaliza
  `ParallelPerspectiveReviewDispatcher`: N jueces desde
  `JudgePanelConfig.judges: List[JudgeSpec{backend, model}]` (default 3:
  claude-code + codex/`sdd-secondopinion` + gemini, vía los 7 backends de
  `build_dispatcher`), decisión por **mayoría**; empate/disenso fuerte →
  escala.
- **`FeedbackRouterNode`** (nuevo): consume el repair loop de FEAT-377/G1.
  Un agente LLM lee el `QAReport` + verdicts del panel y emite
  `FeedbackDecision ∈ {retry, escalate, accept_with_notes}` con un dev-brief
  accionable; `retry` re-entra a development con el brief inyectado
  (≤ `DEV_LOOP_QA_MAX_RETRIES`); el stop rule corta siempre.
- **`FeatureHandoffNode`** (extiende el patrón de `DeploymentHandoffNode`):
  push + draft-PR contra `dev` (gh CLI / REST fallback ya existentes), genera
  `docs/migration/feat-<id>-<slug>.md` (convención existente) con el resumen
  de lo implementado, ejecuta `wikitoolkit upsert --changed` en el worktree
  (mismo comando del git post-commit hook) y publica el run outcome vía
  `DevLoopGraphMemory.publish_run_outcome()` (FEAT-B). Jira transition solo
  si hay ticket. **Nunca mergea.**

✅ **Pros:**
- Máxima reutilización: runner, session_state, CLI, FlowEventPublisher,
  dispatchers, pool, gates — todo se comparte; solo se agregan nodos y edges.
- Precedente probado: la topología de revisión ya demuestra el patrón
  "segunda definition + mismas factories + edges imperativos".
- El bug-loop no se toca: feature-mode es aditivo (nuevos node types en el
  registry, nuevo kind en el classifier).
- Un solo CLI (`parrot devloop`) para bugs y features.

❌ **Cons:**
- El paquete crece (ya es grande); modelos bug-céntricos (`WorkBrief` exige
  `acceptance_criteria` min_length=1 y `log_sources`) conviven con
  `FeatureBrief` — hay que mantener la separación limpia.
- Acopla el timing a FEAT-377 (A, B, F deben aterrizar antes o en paralelo
  coordinado — tocan `definition.py`/`flow.py`/`models.py`).
- `NodeId` Literal, `_GATE_TTL_CONF_ATTR`, factories: varios puntos de
  extensión dispersos que hay que tocar consistentemente (mitigado por el
  parity test).

📊 **Effort:** High (M-L; ~4 capacidades separables)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| (ninguna nueva) | — | gh CLI + aiohttp (PR), click (CLI), redis ya presentes |
| `wikitoolkit` (interno) | Actualización del wiki en handoff | Shell-out a `wikitoolkit upsert --changed`; no hay `build_wiki()` reutilizable |

🔗 **Existing Code to Reuse:**
- `parrot/flows/dev_loop/definition.py` + `flow.py` — patrón de segunda topología (revision)
- `parrot/flows/dev_loop/nodes/research.py` — base del PlannerNode (dispatch sdd-research → sdd-planner)
- `parrot/flows/dev_loop/nodes/development.py` + `agent_pool.py` + `task_scheduler.py` + `worktree_manager.py` — el diamond fan-out/merge ya existe (FEAT-323)
- `parrot/flows/dev_loop/code_review.py` — `ParallelPerspectiveReviewDispatcher._run_judge` es el precedente del panel
- `parrot/flows/dev_loop/nodes/deployment_handoff.py` — push + gh pr create --draft --base dev
- `parrot/flows/dev_loop/agent_builder.py` — `build_dispatcher()` para "un LLM por juez/agente vía config"
- FEAT-377/FEAT-B `graph_memory.py::DevLoopGraphMemory` (propuesto) — write-back al grafo

---

### Option C: AgentCrew literal (`parrot/bots/flows/crew/`)

Implementar el flow como `CrewDefinition` + `AgentCrew.run_flow()` con
`task_flow()` declarando el DAG planner → devs → merge → qa → handoff.

✅ **Pros:**
- API declarativa simple y familiar (`AgentCrew.from_definition`).
- Independiente de dev_loop; demo rápida.

❌ **Cons:**
- `run_flow()` no tiene routing condicional con OR-join/skip-propagation ni
  loops acotados nativos — el ciclo QA→feedback→development y el branch
  escalate/accept no se expresan; habría que reimplementarlos ad-hoc.
- Pierde toda la infraestructura dev_loop: session state event-sourced,
  gates HITL, dispatchers CLI (Claude Code/Codex/Gemini), sub-worktrees,
  streaming de eventos.
- Los "dev agents" serían Agents in-process con tools, no code-agents CLI
  operando en worktrees — un modelo de ejecución distinto al validado.

📊 **Effort:** Medium (pero con techo funcional bajo)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| (ninguna nueva) | — | — |

🔗 **Existing Code to Reuse:**
- `parrot/bots/flows/crew/crew.py` — AgentCrew
- `parrot/bots/flows/core/` — primitivas DAG

---

### Option D (unconventional): Orquestación en la capa de comandos (sin Python nuevo)

No tocar `parrot/flows/`: componer el pipeline como un agente Claude Code
autónomo (`sdd-autopilot` ampliado) que encadena `/sdd-spec → /sdd-task →`
sub-sesiones paralelas de `sdd-worker` en sub-worktrees → `codex exec review`
+ panel de CLIs como jueces → `gh pr create` + `wikitoolkit upsert`, todo
gobernado por prompts en `.claude/agents/`.

✅ **Pros:**
- Cero código Python; iterable editando markdown; disponible mañana.
- `sdd-autopilot.md` ya hace push + `gh pr create` (línea 419).

❌ **Cons:**
- Sin contrato tipado, sin session state, sin telemetría Redis, sin HITL
  gates, sin retry acotado verificable — exactamente lo que dev_loop aporta.
- No invocable como servicio/producto (el objetivo es que ai-parrot ofrezca
  este flow como capacidad de la librería, no como tooling del repo).
- Paralelismo y merge dependen del juicio del LLM, no de Kahn/TaskScheduler.

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| Claude Code / codex / gemini CLIs | Agentes y jueces | Ya instalados |

🔗 **Existing Code to Reuse:**
- `.claude/agents/sdd-autopilot.md`, `.claude/commands/sdd-*.md`

---

## Recommendation

**Option B** — variante feature-mode dentro de `parrot/flows/dev_loop/`
(decisión confirmada por el usuario en la Ronda 1 de discovery).

Razones:
- El costo marginal es el menor de las opciones "serias": el diamond
  (fan-out/reduce) **ya existe** (FEAT-323), el adversarial review **ya está
  cableado** en QANode (FEAT-375), el PR node **ya existe**
  (DeploymentHandoffNode), y el repair loop + graph memory llegan por
  FEAT-377. Lo genuinamente nuevo son 4 piezas: FeatureBrief/PlannerNode,
  SynthesisNode, JudgePanelReviewDispatcher + FeedbackRouterNode, y
  FeatureHandoffNode (docs + wiki).
- El precedente `revision=True` demuestra que el paquete soporta múltiples
  topologías con las mismas factories sin regresión.
- Option A paga un refactor de extracción sin beneficio funcional; Option C
  no puede expresar el feedback loop; Option D no es producto.

Trade-off aceptado: acoplamiento temporal a FEAT-377 (secuenciar E→F→A→B
antes de los nodos que los consumen) y crecimiento del paquete dev_loop.

---

## Feature Description

### User-Facing Behavior

1. El usuario escribe (o ya tiene) un `*.brainstorm.md`, `*.proposal.md` o
   `*.spec.md` y crea un brief YAML mínimo:

   ```yaml
   kind: feature
   document_path: sdd/proposals/mi-feature.brainstorm.md
   document_kind: proposal        # brainstorm | proposal | spec
   jira_issue_key: null           # opcional
   dev_agents:                    # opcional; default 1 claude-code
     - {agent: claude-code, model: claude-sonnet-4-6, count: 2}
     - {agent: codex, model: gpt-5.5, count: 1}
   judge_panel:                   # opcional; default panel de 3
     judges:
       - {agent: claude-code, model: claude-sonnet-4-6}
       - {agent: codex, model: gpt-5.5}        # adversarial (sdd-secondopinion)
       - {agent: gemini, model: auto}
     decision: majority
   ```

2. `parrot devloop run --brief feature.yaml` (mismo CLI; el classifier rutea
   por `kind`). El usuario observa el progreso por los streams Redis
   existentes (`flow:{run_id}:flow`) / consola devloop.
3. El flow corre autónomo: planifica, desarrolla en paralelo, sintetiza,
   pasa el panel de QA, itera con feedback acotado si falla.
4. Al terminar, el usuario recibe: un **draft PR contra `dev`** (nunca
   merge), un artefacto `docs/migration/feat-<id>-<slug>.md` dentro del PR,
   el wiki del repo actualizado, y el run registrado en el knowledge graph.
   Si hay ticket Jira, queda transicionado y comentado con el PR.
5. Si el panel escala (disenso, o agotados los retries), el run abre el gate
   correspondiente / rutea a `failure_handler` con el estado completo para
   intervención humana.

### Internal Behavior

1. **Intake** (`IntentClassifierNode` extendido): valida `FeatureBrief`
   (document_path existe y es legible; doc_kind coherente), lo publica en
   `shared["feature_brief"]` y retorna kind para el edge condicional
   `_CEL_IS_FEATURE`.
2. **Planner** (`PlannerNode`, node id `planner`): despacha subagente
   `sdd-planner` (prompt nuevo en `_subagent_data/`) con el documento como
   contexto + graph context de `DevLoopGraphMemory.build_research_context()`
   (FEAT-B). El subagente: genera spec si doc_kind ≠ spec (`/sdd-spec`),
   genera task index (`/sdd-task`), crea worktree
   (`git worktree add -b feat-<id>-<slug> ... HEAD` desde `dev`), y emite
   `PlannerOutput`. El nodo deriva `DevAgentPoolConfig` efectivo: config del
   brief si existe; si no, dimensiona por el ancho de la primera wave de
   `TaskScheduler.from_worktree()` (cap `development_pool_max`).
3. **Development**: `DevelopmentNode` actual — waves topológicas,
   sub-worktrees en modo `isolated`, `merge_sequential()` como merge point,
   `aggregate_outputs()`.
4. **Synthesis** (`SynthesisNode`): despacha un agente (claude-code, cwd =
   worktree integrado) que revisa consistencia inter-worker (interfaces,
   imports, duplicaciones), ejecuta `pytest` de integración y commitea
   ajustes de reconciliación. Output `SynthesisReport{consistent: bool,
   adjustments: [...], summary}`. Si la reconciliación falla → edge on_error
   a failure_handler.
5. **QA**: `QANode` con `codereview_dispatcher =
   JudgePanelReviewDispatcher(judges=[...], decision="majority")`. Cada juez
   corre su review independiente (mismo brief neutral); el panel:
   `passed = mayoría`; findings agregados con `source=<judge>`; el path
   advisory existente (triage CONFIRM/REJECT/ESCALATE + gate
   `review_escalation`) se conserva usando `sdd-secondopinion` como juez
   adversarial. Verdicts individuales se registran como actions
   (`JudgeVerdictRecorded`) en session state.
6. **Feedback router** (`FeedbackRouterNode`): en QA-fail, un dispatch LLM
   corto (subagente `sdd-feedback`, read-only) recibe QAReport + verdicts y
   emite `FeedbackDecision`:
   - `retry` → edge condicional a `development` con dev-brief inyectado
     (usa el mecanismo de feedback-injection del repair loop FEAT-A;
     respeta `qa_attempts < DEV_LOOP_QA_MAX_RETRIES`),
   - `escalate` → failure_handler (con las notas del panel),
   - `accept_with_notes` → continúa a feature_handoff con las notas
     anexadas al PR body (solo permitido si los fallos son no-bloqueantes:
     findings minor/nit y criterios manuales no-blocking).
7. **Feature handoff** (`FeatureHandoffNode`): push branch → draft PR
   `--base dev` (gh/REST, retry-once, patrón DeploymentHandoffNode) →
   genera `docs/migration/feat-<id>-<slug>.md` (qué se implementó, decisiones,
   findings aceptados, cómo probar) y lo commitea/pushea a la rama del PR →
   `wikitoolkit upsert --changed` (subprocess en el worktree; degrade
   silencioso si wikitoolkit no está instalado/inicializado) →
   `DevLoopGraphMemory.publish_run_outcome()` (un commit auditado
   RUN/CLAIM/PRODUCED; no-op si FEAT-B no está configurado) → Jira transition
   + comment **solo si** hay ticket. Retorna `{status, pr_url, pr_number,
   docs_path, wiki_updated}`.
8. **Close**: `DevLoopCloseNode` actual (tolera ausencia de Jira:
   `closed_without_ticket`).

Paridad: los nuevos nodos/edges se agregan a `build_dev_loop_definition`
(nuevo parámetro de modo), a las factories (`dev_loop.planner`,
`dev_loop.synthesis`, `dev_loop.feedback_router`, `dev_loop.feature_handoff`)
y al wiring imperativo de un `build_dev_loop_feature_flow()` (precedente:
`build_dev_loop_revision_flow`, runner.py:101). `NodeId` Literal y
reducers de session_state se extienden con los nuevos ids/actions.

### Edge Cases & Error Handling

- **Documento inexistente/ilegible** → el classifier falla la validación
  (ValueError) antes de gastar dispatch; run `failed` limpio.
- **Spec ya resuelto** (`document_kind: spec`): el planner salta `/sdd-spec`
  y va directo a `/sdd-task` (o valida un index existente).
- **Task index sin depends_on / una sola task** → pool degrada a
  single-agent (comportamiento actual de `TaskScheduler.from_index_file` →
  `None` / wave única).
- **Ciclo de dependencias** → `TaskScheduler` raises ValueError → planner
  reporta y el run falla con diagnóstico (no dispatch de devs).
- **Juez caído/infra error** → el panel degrada como hoy (`_resolve_side` →
  nit advisory) y decide con los jueces restantes; si cae la mayoría del
  panel → escalate (fail-closed).
- **Empate del panel** (N par o abstenciones) → escalate, nunca pase por
  default.
- **Retries agotados** (`qa_attempts ≥ DEV_LOOP_QA_MAX_RETRIES`) → stop rule
  de FEAT-A rutea a failure_handler; el feedback router no puede overridear.
- **`wikitoolkit` no inicializado / `gh` ausente** → wiki update se omite
  con warning (no bloquea el PR); PR cae a REST con `GITHUB_TOKEN`; si ambos
  fallan → `status: blocked` (patrón `_mark_blocked` sin Jira).
- **Sin Jira**: todos los pasos Jira son no-ops; `close` retorna
  `closed_without_ticket` (ya soportado).
- **Feature-mode sin FEAT-A desplegado** → el edge retry no existe; el
  feedback router solo puede escalate/accept (degradación documentada).

---

## Capabilities

### New Capabilities
- `dev-loop-feature-mode`: FeatureBrief + PlannerNode + topología
  feature (definition/flow/factories/session-state/CLI) + SynthesisNode.
- `dev-loop-judge-panel`: `JudgePanelReviewDispatcher` (N jueces por config,
  decisión por mayoría, adversarial integrado) en `code_review.py`.
- `dev-loop-feedback-router`: FeedbackRouterNode + FeedbackDecision sobre el
  repair loop de FEAT-A.
- `dev-loop-feature-handoff`: FeatureHandoffNode — PR forzado + artefacto de
  documentación + wiki/graph update.

### Modified Capabilities
- `dev-loop-orchestration` (FEAT-129/132): definition/flow/factories ganan la
  tercera topología; `IntentClassifierNode` gana el kind/route de feature.
- `dev-loop-code-review` (FEAT-270/375): factory registra `"judge-panel"`.
- `dev-loop-session-state` (FEAT-322): nuevos NodeIds + actions
  (`JudgeVerdictRecorded`, `FeedbackDecisionRecorded`, `DocsArtifactLinked`).

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/flows/dev_loop/definition.py` | modifies | Parámetro de modo + nodos/edges feature (junto al edge retry de FEAT-A — coordinar) |
| `parrot/flows/dev_loop/flow.py` / `runner.py` | extends | `build_dev_loop_feature_flow()` (precedente: revision, runner.py:101); `DevLoopRunner.run()` acepta FeatureBrief |
| `parrot/flows/dev_loop/models.py` | extends | `FeatureBrief`, `PlannerOutput`, `JudgeSpec`, `JudgePanelConfig`, `SynthesisReport`, `FeedbackDecision` |
| `parrot/flows/dev_loop/nodes/` | extends | `planner.py`, `synthesis.py`, `feedback_router.py`, `feature_handoff.py` (4 nodos nuevos) |
| `parrot/flows/dev_loop/code_review.py` | extends | `JudgePanelReviewDispatcher` registrado como `"judge-panel"` |
| `parrot/flows/dev_loop/session_state.py` | modifies | `NodeId` +4, nuevas actions + reducers |
| `parrot/flows/dev_loop/_subagent_data/` | extends | `sdd-planner.md`, `sdd-feedback.md` (+ espejo en `.claude/agents/`) |
| `parrot/flows/dev_loop/factories.py` | modifies | +4 factories |
| `parrot/cli/devloop/` | extends | brief loader detecta FeatureBrief por `kind`; wizard opcional |
| `parrot/conf.py` | extends | `DEV_LOOP_JUDGE_PANEL` (json/env), `DEV_LOOP_DOCS_ARTIFACT_DIR` (default `docs/migration`), `DEV_LOOP_WIKI_UPDATE` (bool) |
| FEAT-377 (A, B, F) | depends on | Retry edge + `DevLoopGraphMemory` + ontología RUN/CLAIM deben aterrizar antes |
| Bug-loop existente | none | Aditivo; parity test protege la topología actual |

Sin breaking changes: `WorkBrief`/bug path intactos; `FeatureBrief` es un
modelo nuevo discriminado por `kind`.

---

## Code Context

### User-Provided Code

(El usuario no aportó código; aportó la referencia conceptual
"Graph Engineering with Claude Code" — movez.substack.com/p/graph-engineering-with-claude-14 —
ya evaluada en `sdd/proposals/graph-engineering-devloop.proposal.md` y
FEAT-377.)

### Verified Codebase References

#### Classes & Signatures
```python
# From packages/ai-parrot/src/parrot/flows/dev_loop/definition.py:61
def build_dev_loop_definition(*, revision: bool = False) -> FlowDefinition: ...
# Node-id constants :36-44 (intent_classifier, bug_intake, research, development,
# qa, deployment_handoff, failure_handler, close, revision_handoff)
# CEL predicates :47-50 (_CEL_IS_BUG, _CEL_IS_NOT_BUG, _CEL_QA_PASSED, _CEL_QA_FAILED)

# From packages/ai-parrot/src/parrot/flows/dev_loop/flow.py:189
def build_dev_loop_flow(*, dispatcher, jira_toolkit, log_toolkits, redis_url,
    name="dev-loop", publish_flow_events=True, lifecycle_events=True,
    development_dispatcher=None, development_profile=None,
    development_pool_config=None, development_dispatcher_builder=None,
    development_pool_max=4, git_toolkit=None, repos=None,
    codereview_dispatcher=None, require_deployment_approval=False) -> AgentsFlow: ...
# ⚠ Ejecuta en modo explicit-edge: from_definition tiene AND-join; edges se
#   re-declaran imperativamente (flow.py:301-307, :332-360). Paridad obligatoria.

# From packages/ai-parrot/src/parrot/flows/dev_loop/runner.py:101
def build_dev_loop_revision_flow(*, dispatcher, jira_toolkit, git_toolkit,
    redis_url, codereview_dispatcher=None, name="dev-loop-revision",
    publish_flow_events=True) -> AgentsFlow: ...
# ← PRECEDENTE para build_dev_loop_feature_flow (segunda topología, mismas factories)

# From packages/ai-parrot/src/parrot/flows/dev_loop/runner.py:156,522
class DevLoopRunner:
    async def run(self, brief: WorkBrief, *, run_id=None, initial_task="",
                  extra_shared=None) -> FlowResult: ...  # :522

# From packages/ai-parrot/src/parrot/flows/dev_loop/models.py
WorkKind = Literal["bug", "enhancement", "new_feature"]        # :116
class WorkBrief(BaseModel):                                     # :138
    kind: WorkKind = "bug"                                      # :151
    acceptance_criteria: List[AcceptanceCriterion]              # :180 (min_length=1)
    dev_agents: Optional[List[DevAgentSpec]]                    # :200
    dev_isolation: Optional[Literal["shared", "isolated"]]      # :210
DevAgentBackend = Literal["claude-code","codex","gemini","nvidia","grok","zai","moonshot"]  # :372
class DevAgentSpec(BaseModel):   # :377 — agent, model="", count=1
class DevAgentPoolConfig(BaseModel):  # :396 — agents (min 1), isolation_mode="shared"
class ResearchOutput(BaseModel):  # :312 — jira_issue_key, spec_path, feat_id,
                                  # branch_name, worktree_path, repo_path, log_excerpts
class DevelopmentOutput(BaseModel):  # :452
class QAReport(BaseModel):  # :487 — passed, criterion_results, lint_passed,
                            # notes, code_review_passed, code_review_findings
class CodeReviewVerdict(BaseModel):  # :757 — passed, findings, summary, files_modified
class AdversarialFinding(CodeReviewFinding):  # :793 — source, disposition
                            # Optional[Literal["confirm","reject","escalate"]]
class ClaudeCodeDispatchProfile(BaseModel):  # :519
    subagent: Optional[Literal["sdd-research","sdd-worker","sdd-qa","sdd-codereview"]]  # :527
    # ⚠ nuevos subagentes (sdd-planner, sdd-feedback) requieren ampliar este Literal

# From packages/ai-parrot/src/parrot/flows/dev_loop/nodes/intent_classifier.py:33
class IntentClassifierNode(DevLoopNode):
    def __init__(self, *, redis_url: str, name: str = "intent_classifier"): ...  # :48
    # NO clasifica con LLM: valida y propaga brief.kind (:62,:111,:142)

# From packages/ai-parrot/src/parrot/flows/dev_loop/nodes/research.py:119
class ResearchNode(DevLoopNode):
    # execute :162-295 — crea Jira SIEMPRE (issuetype por kind, :85-89
    # {"bug":"Bug","enhancement":"Story","new_feature":"New Feature"});
    # /sdd-spec, /sdd-task y worktree viven en el PROMPT del subagente
    # (_subagent_data/sdd-research.md:38-44), no en Python.

# From packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py:88
class QANode(DevLoopNode):
    # execute :113-249 — deterministic QA (sdd-qa, plan mode :280-285) +
    # code review pluggable + adversarial triage FEAT-375 YA CABLEADO
    # (:168-186, advisory→_run_finding_triage :393, gate review_escalation :513-524)

# From packages/ai-parrot/src/parrot/flows/dev_loop/nodes/deployment_handoff.py:46
class DeploymentHandoffNode(DevLoopNode):
    def __init__(self, *, jira_toolkit, git_toolkit=None, gh_cli_path=None,
        target_repo=None, base_branch="dev", name="deployment_handoff",
        require_deployment_approval=False): ...  # :71
    # execute :100 — _push_branch :283 → draft PR :117-119
    # (gh pr create --draft --base dev :325 / REST :354, retry-once :144-162)

# From packages/ai-parrot/src/parrot/flows/dev_loop/code_review.py
class AbstractCodeReviewDispatcher(ABC):   # :59 — advisory=False :74, review() :80
class CodeReviewDispatcherFactory:         # :133 — register :139, create :148
# Registrados: "claude-code" :159, "codex" :180, "gemini" :200,
#              "codex-adversarial" :220 (advisory), "parallel" :292 (advisory)
class ParallelPerspectiveReviewDispatcher: # :293
    # ctor: primary, adversary, judge_dispatcher=None, judge_enabled=False (:312-325)
    # _merge_verdicts :357/:411, _run_judge :460 (juez ÚNICO, perfil Claude-shaped
    # :500-506 — el seam exacto a generalizar para el panel N-jueces)

# From packages/ai-parrot/src/parrot/flows/dev_loop/agent_builder.py:98
def build_dispatcher(spec: DevAgentSpec, *, redis_url, max_concurrent,
    stream_ttl_seconds, config_getter=...) -> Tuple[DevLoopCodeDispatcher, BaseModel]: ...
# 7 backends con modelo default por env (:136-201) — la palanca "un LLM por juez"

# From packages/ai-parrot/src/parrot/flows/dev_loop/task_scheduler.py:43
class TaskScheduler:
    @classmethod def from_worktree(cls, worktree_path, feature_slug): ...  # :111
    def next_wave(self) -> List[TaskRef]: ...   # :166  (Kahn; ciclo → ValueError :128)

# From packages/ai-parrot/src/parrot/flows/dev_loop/worktree_manager.py:75
class SubWorktreeManager:
    def merge_sequential(self, *, resolver=None) -> MergeReport: ...  # :181
    # ← el merge point del diamond (FEAT-323); refresh_all :264, cleanup :297

# From packages/ai-parrot/src/parrot/flows/dev_loop/agent_pool.py:89
class DevAgentPool:
    async def run_wave(self, tasks, *, research, run_id, cwd_for) -> WaveResult: ...  # :237
def aggregate_outputs(results, incomplete) -> DevelopmentOutput: ...  # :340

# From packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py
NodeId = Literal[...]        # :139 — SOLO los 9 ids actuales; ampliar para nuevos nodos
GateKind = Literal["manual_criterion","deployment_approval","revision_approval",
                   "plan_approval","review_escalation"]   # :166
class SessionHost:           # :724 — open_gate :862, wait_gate :932, resolve_gate :817
def reduce(...): ...         # :560 — todo estado nuevo = action + reducer (FEAT-322)

# From packages/ai-parrot/src/parrot/knowledge/wiki/ (wikitoolkit)
# CLI entry: pyproject.toml:115 → parrot.knowledge.wiki.cli:main; click group :596
# build command cli.py:634 (pipeline INLINE — sin build_wiki() reutilizable)
# git post-commit hook ya ejecuta: `wikitoolkit upsert --changed --quiet`
#   (wiki/claude_code/assets.py:167-175) ← mismo comando para el handoff
class LLMWikiToolkit:  # wiki/toolkit.py:46 — ingest_source :140, search :844

# From packages/ai-parrot/src/parrot/knowledge/graphindex/publish.py:37
class GraphPublisher:
    async def publish(self, update: GraphUpdate) -> CommitReceipt: ...  # :90
# builder.py:56 GraphIndexBuilder.build(sources, ctx) :137

# FEAT-377 spec (sdd/specs/graphindex-as-engineering-devloop.spec.md) PROPONE
# (aún NO implementado):
#   _CEL_QA_RETRY, QaAttemptRecorded, QAReport.attempt, DEV_LOOP_QA_MAX_RETRIES=2,
#   DevAgentSpec.escalation_model, should_fan_out(),
#   graph_memory.py::DevLoopGraphMemory{from_config, build_research_context,
#   publish_run_outcome, ground_findings}, DEV_LOOP_GRAPH_MEMORY_PATH
```

#### Verified Imports
```python
# Confirmados en el codebase:
from parrot.flows.dev_loop.models import WorkBrief, DevAgentSpec, DevAgentPoolConfig
from parrot.flows.dev_loop.flow import build_dev_loop_flow
from parrot.flows.dev_loop.runner import DevLoopRunner, build_dev_loop_revision_flow
from parrot.flows.dev_loop.code_review import CodeReviewDispatcherFactory
from parrot.flows.dev_loop.agent_builder import build_dispatcher
from parrot.flows.dev_loop.nodes.base import register_dev_loop_node, DevLoopNode
from parrot.knowledge.graphindex.publish import GraphPublisher
# Import path es parrot.flows.dev_loop (packages/ai-parrot/src/…, PEP 420 host).
```

#### Key Attributes & Constants
- `conf.DEV_LOOP_CODEREVIEW_AGENT` → `"claude-code"|"codex"|"gemini"|"codex-adversarial"|"parallel"` (parrot/conf.py:928-934)
- `conf.DEV_LOOP_CODEREVIEW_JUDGE` → bool, default False (conf.py:995-999)
- `conf.DEV_LOOP_ADVERSARIAL_MODEL` → `gpt-5.5` (conf.py:986-988)
- Selección del review backend vive en `examples/dev_loop/server.py:598-688`, NO en `build_dev_loop_flow`
- `_ISSUE_TYPE_BY_KIND = {"bug":"Bug","enhancement":"Story","new_feature":"New Feature"}` (research.py:85-89)
- `docs/migration/feat-<id>-<slug>.md` — convención manual existente (6 archivos), sin automatización

### Does NOT Exist (Anti-Hallucination)
- ~~Feature-mode / `feature_mode` / `build_dev_loop_definition(mode=...)`~~ — solo existe `revision: bool`; `enhancement`/`new_feature` rutean idéntico a research.
- ~~Clasificación LLM en IntentClassifierNode~~ — solo valida y propaga `kind`.
- ~~Edge `qa → development` / `_CEL_QA_RETRY` / `qa_attempts` / `DEV_LOOP_QA_MAX_RETRIES`~~ — propuestos por FEAT-377, no implementados.
- ~~`graph_memory.py` / `DevLoopGraphMemory` / acoplamiento dev_loop↔GraphIndex~~ — cero hits Python/prompt (claim C2 de FEAT-377, re-verificado).
- ~~Panel N-jueces / `judges: List[...]`~~ — solo `judge_dispatcher` único opcional, default off, perfil hardcoded Claude (code_review.py:500-506).
- ~~`build_wiki()` reutilizable~~ — el pipeline de `wikitoolkit build` está inline en el click command (wiki/cli.py:634); `LLMWikiToolkit.rebuild_index` solo regenera `index.md`.
- ~~Generación de docs / PR en `/sdd-done`~~ — sdd-done pushea y mergea a base local; nunca abre PR ni escribe documentación.
- ~~PR creation fuera de `deployment_handoff.py`~~ — `revision_handoff` tiene prohibido crear PRs (revision_handoff.py:10).
- ~~`docs/features/`~~ — no existe; la convención es `docs/migration/`.
- ~~`sdd-secondopinion` en `ClaudeCodeDispatchProfile.subagent`~~ — es Codex-only (models.py:527 vs :557,:884).
- ~~`gate_ttl_for("review_escalation")`~~ — KeyError; ese TTL se lee directo de conf (qa.py:473).
- ~~Persistencia/resume cross-process de SessionHost~~ — in-memory por run; checkpoint/resume es FEAT-D (futuro).

---

## Parallelism Assessment

- **Internal parallelism**: parcial. `dev-loop-judge-panel` (code_review.py +
  conf) es independiente y podría ir en worktree propio. Las otras tres
  capacidades comparten `definition.py`, `flow.py`, `models.py`,
  `session_state.py`, `factories.py` — alta contención.
- **Cross-feature independence**: **conflicto directo con FEAT-377** (FEAT-A
  toca definition/flow/models/session_state; FEAT-B crea graph_memory.py).
  Secuenciar: FEAT-377 E→F→A→B primero, este feature después (o coordinar en
  la misma cola de worktrees).
- **Recommended isolation**: `per-spec` — un worktree, tasks secuenciales.
  (Alternativa: extraer `dev-loop-judge-panel` como spec hermano
  paralelizable.)
- **Rationale**: la topología, los modelos y el session state forman un núcleo
  acoplado con parity test compartido; paralelizar dentro del feature
  produciría merges dolorosos en los mismos archivos.

---

## Open Questions

- [x] ¿Tipo/base? — *Owner: Jesus*: feature / dev.
- [x] ¿Paquete nuevo o variante dev_loop? — *Owner: Jesus*: variante dentro de `parrot/flows/dev_loop/`.
- [x] ¿Relación con FEAT-377? — *Owner: Jesus*: este feature depende de FEAT-377 (A, B, F); consume el repair loop y DevLoopGraphMemory.
- [x] ¿Quién descompone en tasks si solo llega brainstorm/proposal? — *Owner: Jesus*: el PlannerNode genera spec + task index (equivalente /sdd-spec + /sdd-task).
- [x] ¿Composición del panel QA? — *Owner: Jesus*: N jueces por config (default 3, un LLM por juez vía dispatchers), mayoría; adversarial = sdd-secondopinion como juez; empate/disenso → escala.
- [x] ¿Semántica del feedback agent? — *Owner: Jesus*: router LLM sobre el repair loop G1 — retry (≤ DEV_LOOP_QA_MAX_RETRIES) / escalate / accept_with_notes; stop rule inviolable.
- [x] ¿Gate humano antes del PR? — *Owner: Jesus*: no — autónomo hasta el draft-PR; el humano solo revisa/mergea.
- [x] ¿Selección de modo y Jira? — *Owner: Jesus*: IntentClassifier rutea el kind feature (también forzable por CLI/config); Jira opcional.
- [ ] ¿Nuevo `kind` literal (`"feature"`) en un FeatureBrief discriminado, o re-rutear el `"new_feature"` existente de WorkBrief? Re-rutear cambia el comportamiento de briefs new_feature actuales (hoy van a research+Jira). — *Owner: Jesus*
- [ ] ¿Panel default exacto (backends/modelos de los 3 jueces) y regla ante N par? Propuesta: claude-sonnet + codex/gpt-5.5 (adversarial) + gemini/auto; empate → escalate. — *Owner: Jesus*
- [ ] ¿`SynthesisNode` como nodo separado (dispatch extra) o como fase final del DevelopmentNode tras `merge_sequential()`? Nodo separado da telemetría/gates propios; fase interna ahorra un dispatch. — *Owner: Jesus*
- [ ] ¿El artefacto de documentación va a `docs/migration/` (convención actual) o se estrena `docs/features/`? ¿Se ingesta también como página wiki (`LLMWikiToolkit.create_page`)? — *Owner: Jesus*
- [ ] Wiki update en el worktree del PR vs en dev post-merge: actualizar el wiki desde la rama del PR documenta código aún no mergeado a dev. ¿Aceptable (el PR lo trae consigo) o diferir el `wikitoolkit upsert` al merge? — *Owner: Jesus*
- [ ] ¿`accept_with_notes` requiere quórum del panel o basta que los fallos sean minor/nit + manual no-blocking? — *Owner: Jesus*
