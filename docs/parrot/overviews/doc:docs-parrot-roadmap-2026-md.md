---
type: Wiki Overview
title: AI-Parrot · Roadmap McKinsey-Delta
id: doc:docs-parrot-roadmap-2026-md
tags:
- overview
timestamp: '2026-07-14T22:20:21+00:00'
summary: 'Cada feature usa el flujo SDD: `brainstorm → proposal → spec → tasks → worktree
  → PR a dev`. Los IDs `FEAT-A/B/...` son placeholders del documento McKinsey-delta;
  al iniciar `/sdd-spec` recibirán su `FEAT-NNN` real.'
---

# AI-Parrot · Roadmap McKinsey-Delta

> Roadmap consolidado a partir de `docs/parrot_delta_mckinsey.docx` (abril 2026), revisado contra el codebase actual (mayo 2026). Estructurado por las 16 recomendaciones McKinsey, con sprints, features SDD (FEAT-XXX) y milestones.

**Leyenda de estado**

| Símbolo | Significado |
|---|---|
| Ya realizado | Funcionalidad construida y operacional en el codebase. |
| Activación | Primitivas listas; falta capa de agregación / packaging / dashboards. |
| Brecha real | Hay que construir desde cero. |
| Config | Motor construido; falta autoría de YAML de dominio. |
| Externo | Fuera del scope del código de AI-Parrot. |

**Convención de FEATs**

Cada feature usa el flujo SDD: `brainstorm → proposal → spec → tasks → worktree → PR a dev`. Los IDs `FEAT-A/B/...` son placeholders del documento McKinsey-delta; al iniciar `/sdd-spec` recibirán su `FEAT-NNN` real.

---

## 1. Resumen ejecutivo

- **2 brechas técnicas reales** de las 16 recomendaciones McKinsey (no es un programa de 18 meses; es un sprint de fundación de 3-4 meses).
- **El trabajo predominante es activación**: la telemetría, los outcomes, los datasets y los prompts ya se capturan — falta la capa que los transforma en decisiones automatizadas.
- **Avance ya consolidado desde la redacción del delta (abril 2026):** FEAT-176 (Lifecycle Events System) está mergeado en `dev`, lo que destraba FEAT-177 (OTel) y compacta el #5 (Observability). FEAT-181 (agnostic prompt caching) está completado y aporta señales para el camino del #6 (Prompt Registry).
- **Tracks organizacionales** (#8, #11, #13, #14, #15) arrancan en paralelo y no bloquean ingeniería.

---

## 2. Categorización por brecha real

| Bucket | Items McKinsey | Esfuerzo |
|---|---|---|
| **Brecha real** | #3 (parcial post-FEAT-176), parte de #5 | 1-3 meses |
| **Activación** | #1, #2, #6, #10, #16 | 2-4 meses (paralelizable) |
| **Configuración** | #4 (motor 100% en prod) | 1-2 semanas |
| **Integración cross-cutting** | #9, #11 | 1-2 meses |
| **Frontend / UX** | #7, #12 | 3-6 meses (track largo) |
| **Externo** | #8, #13, #14, #15 | Paralelo |

---

## 3. Análisis por recomendación

### #1 · Agent Authority Framework — Activación
- **Estado**: Ya realizado en su mayoría. `parrot/auth/resolver.py` (PBAC + DefaultPermissionResolver + LRU), `permission.py`, `agent_guard.py`, `pbac.py`, `DecisionFlowNode` con `EscalationPolicy` y `ApprovalDecision`, `AbstractTool.execute()` con `can_execute()`.
- **Delta**: formalizar 3-tier model (T1 observe / T2 recommend / T3 autonomous) como atributo declarativo en YAML; estandarizar confidence-based escalation cross-cutting; empaquetar `GuardrailAgent` reusable.
- **FEAT propuesto**: **FEAT-C · Three-Tier Authority Model** (refactor cosmético sobre `_required_permissions` + nueva `GuardrailAgent` class).

### #2 · Medallion Data Architecture — Activación
- **Estado**: Ya realizado el Gold layer de facto. `DatasetManager` (AbstractToolkit) + 10 source types (`InMemory`, `QuerySlug`, `SQLQuery`, `TableSource`, `Airtable`, `Smartsheet`, `Iceberg`, `Mongo`, `DeltaTable`, `Composite`) + REST API + Redis caching + PBAC gateway.
- **Delta**: capas formales Bronze/Silver con schema enforcement; streaming validation (Apache Griffin o equivalente); quality scoring para outputs agente en `EpisodicMemory`; anomaly detection pre-RAG.
- **FEAT propuesto**: **FEAT-F · Medallion Bronze/Silver + Quality Scoring**.

### #3 · Pre-Deployment Agentic Testing — Brecha real (la única confirmada)
- **Estado**: Parcial. `BotConfigTestHandler`, `sdd-autopilot` pipeline, `PromptInjectionDetector`, `CommandSanitizer`, AgentsFlow tracing con retry/resume.
- **Delta**: shadow mode contra data productiva; red-team playbook sistemático; DAG chaos testing (inyección de fallos/latencia); rollback automático basado en error rate; regression test library con I/O contracts.
- **FEAT propuesto**: **FEAT-A · Shadow Mode + DAG Chaos Testing**. **Crítico — el único item McKinsey-Critical sin atender.**

### #4 · OntoGraph RAG — Configuración (motor 100% construido)
- **Estado**: Ya realizado y operacional. `OntologyRAGMixin`, `OntologyGraphStore` (ArangoDB tenant-isolated), `OntologyIntentResolver`, `TenantOntologyManager`, `OntologyCache` (Redis 24h TTL), `OntologyDefinition` con `TraversalPattern` (AQL + post_action), `concept_catalog/`, `entity_resolver.py`, `tool_dispatcher.py`. Config en `parrot/conf.py`: `ENABLE_ONTOLOGY_RAG`, `ONTOLOGY_BASE_FILE`, `ONTOLOGY_MAX_TRAVERSAL_DEPTH=4`.
- **Delta**: autoría de `base.ontology.yaml` retail (product, location, brand, contract, field_rep, planogram, inventory_unit, promotion); `domains/retail.ontology.yaml`; `clients/<brand>.ontology.yaml`; activar `ENABLE_ONTOLOGY_RAG=true`; smoke test.
- **FEAT propuesto**: **FEAT-B · Retail Ontology YAML Authoring** (1-2 sprints; no es código).

### #5 · Observability y Cost Tracking — Activación (avance reciente)
- **Estado**: Ya realizado a nivel de captura. `CompletionUsage` unificado (OpenAI/Groq/Claude/OpenRouter), `GenerationStats` (cost USD), `MetricAction` por nodo DAG, `SecurityEventLogger`, AgentsFlow tracing. **Avance: FEAT-176 (Lifecycle Events System) está mergeado en `dev` (mayo 2026)** — provee `EventEmitterMixin`, `Before/AfterClientCallEvent`, `Before/AfterToolCallEvent`, `OpenTelemetrySubscriber`, `WebhookSubscriber`. Esto absorbe ~60% del scope original.
- **Delta**: completar FEAT-177 (GenAI-SemConv subscriber + MetricsSubscriber + pricing/cost calculator + `setup_telemetry()` + OpenLIT + OTLP); pipeline a ClickHouse/BigQuery; dashboard cost attribution en nav-admin; regression detection automática; prompt drift sobre golden set.
- **FEAT propuesto**: **FEAT-D · Telemetry Aggregator + Cost Dashboard** (continuación de FEAT-177).

### #6 · Semantic Versioning de Prompts — Activación
- **Estado**: Ya realizado las primitivas. `PromptConfig` (YAML add/remove/customize), `PromptLayer` (priority + phase), `PromptBuilder`, two-phase rendering (configure_context + _build_prompt), `infographic_registry` como blueprint. **FEAT-181 (agnostic-prompt-caching-abstraction) mergeado** — añade `CacheableSegment`, `AgentContextLoader`, `build_segments()`, eventos de cache lifecycle.
- **Delta**: `PromptRegistry` centralizado con semver explícita + changelog + benchmark snapshots + dependency graph; canary release infra (5% traffic + auto-promote/rollback); golden datasets por prompt + regression CI sobre `qa-runner`; unit tests de prompt como artefacto SDD.
- **FEAT propuesto**: **FEAT-E · Prompt Registry with Semver + Canary**.

### #7 · No-Code Workflow Builder — Brecha real (frontend)
- **Estado**: Backend listo. YAML agent definitions, `AgentsFlow` DAG, `BotManager`, `AgentCrew` (sequential/parallel/flow/loop), `AutonomousOrchestrator` con triggers. Stack frontend planeado: nav-admin (SvelteKit 5 + Tailwind 4 + daisyUI + SvelteFlow).
- **Delta**: canvas drag-and-drop con SvelteFlow; agent catalog API con plain-language descriptions + permission requirements; NL→DAG generation; workflow sandbox pre-deploy.
- **FEAT propuesto**: **Track paralelo · Nav-admin No-Code Builder**.

### #8 · Consumer Transparency (NEXUS) — Externo
- **Estado**: AI-Parrot puede aportar `confidence` desde `DecisionFlowNode` y retention via `EpisodicMemory` si NEXUS lo integra.
- **Delta**: disclosure UX, consent flow, escalation policy, retention/privacy — owner: **equipo NEXUS + Legal**.

### #9 · Data Product Layer — Activación / Integración
- **Estado**: Ya realizado per-agent. `DatasetManager` + `DatasetInfo` (memory_usage_mb, null_count, row_count_estimate, cache_ttl, usage_do/dont) + `DatasetEntry` + `create_session_clone` + 10 sources + REST API.
- **Delta**: catálogo cross-agent / cross-tenant (Catalog Service); SLA dashboards (freshness/completeness/accuracy); consumption tracking agregado sobre AgentsFlow traces; quality scoring a nivel data product.
- **FEAT propuesto**: **FEAT-H · Cross-Agent Data Product Catalog**.

### #10 · Model Routing Optimizer — Activación
- **Estado**: Ya realizado el routing layer. `SUPPORTED_CLIENTS` factory (Google GenAI, Claude, OpenAI, Groq, OpenRouter, Ollama, vLLM, HuggingFace, Lambda Labs), `LLMConfig.resolve_llm_config` (priority chain), dual-mode LLM en `PandasAgent`, `CompletionUsage` como input de ranking.
- **Delta**: task taxonomy YAML (structured_extraction, semantic_reasoning, code_gen, classification, summarization, multi_hop); leaderboard cost-performance semanal; auto-routing en `LLMConfig.resolve`; tryout API (batch a N modelos); latency-aware degradation.
- **FEAT propuesto**: **FEAT-G · Intelligent Model Routing Optimizer** (depende de FEAT-D).

### #11 · Federated Operating Model — Activación organizacional
- **Estado**: Ya realizado la estructura técnica. Monorepo `packages/ai-parrot` + `ai-parrot-tools` + `ai-parrot-loaders` + `ai-parrot-pipelines` con `uv` workspaces; plugin system + `AgentRegistry` con `@register_agent`; pipeline `sdd-autopilot`; comandos `/sdd-*`; `CLAUDE.md` con worktree policy.
- **Delta**: RACI matrix documentada; SLA del production readiness review (5-day); agent community of practice charter; métricas de ownership por dominio.
- **FEAT propuesto**: **FEAT-I · Federated Operating Model Docs + RACI** (owner: Engineering Leadership).

### #12 · Developer SDK + Local Dev — Activación
- **Estado**: Ya realizado el SDK. AI-Parrot library con Pydantic v2; `uv` workspaces; `parrot/helpers/*` facades; `AgentRegistry` decorators; Ollama/vLLM disponibles; AgentsFlow tracing; comandos `/sdd-*` ya scaffold CLI.
- **Delta**: Docker Compose stack formal con deps + mock APIs + local Ollama; visual debugger UI con step-through DAG; `parrot scaffold` CLI unificado; agent cookbook centralizado.
- **FEAT propuesto**: **FEAT-K · DX Polish Bundle**.

### #13 · Adoption Program — Externo / Activación parcial
- **Estado**: Ya realizado la infra de feedback. `EpisodicMemoryStore.record_episode`, `ReflectionEngine`, `ImportanceScorer`, `RecallStrategy`, namespace dimensions (tenant/agent/user/session/room/crew), `recall_similar` por vector, multi-channel notification (Teams/Slack/Telegram/WhatsApp).
- **Delta**: playbooks por rol; A/B testing framework; thumbs up/down UX; KPI dashboard de adopción — **owner: Operations + Training**.

### #14 · Platform Roadmap Governance — Activación
- **Estado**: Ya realizado el roadmap interno. Pipeline SDD (`sdd/proposals`, `sdd/specs`, `sdd/tasks`), sync con Jira (`sdd-tojira` / `sdd-fromjira`), `FEAT-XXX` numbering, `sdd-autopilot` state.json.
- **Delta**: dashboard público / team-facing de roadmap; SLAs documentados (availability, latency SLO por task); Platform User Council; mapping de FEAT a KPI de negocio — **owner: Engineering Leadership**.

### #15 · IP Protection — Externo
- **Diferenciadores identificados en código** (no documentados como IP): ontology layered approach, OpenAPI auto-adapter, DAG-to-physical-dispatch, permission framework 2-layer, MCP/A2A nativos.
- **Delta**: IP counsel engagement, disclosure review gate, trade secret register, competitor differentiation maps — **owner: Legal + Engineering Leadership**.

### #16 · Continuous Learning Loop — Activación
- **Estado**: Ya realizado la captura. `EpisodicMemoryStore` (SUCCESS/FAILURE/PARTIAL outcomes, error_type, importance, reflection), `UnifiedMemoryManager` con `ContextAssembler` y token budget, `LongTermMemoryMixin` (episodic_auto_record, skill_auto_extract), `record_crew_workflow`, `CrossDomainRouter`.
- **Delta**: outcome linkage a KPIs de negocio (revenue, restock time, conversion); fine-tuning pipeline desde episodes (HF Transformers ya en stack); prompt performance dashboard temporal; monthly data flywheel report.
- **FEAT propuesto**: **FEAT-J · Fine-Tuning Pipeline desde Episodes**.

---

## 4. Plan de Sprints (3-6 meses)

Cadencia: sprints de 2 semanas con 2 worktrees paralelos. Cada sprint produce 1+ `FEAT-XXX` con brainstorm → spec → tasks.

### Sprint 1-2 (semanas 1-4) · Foundation Safety
**Objetivo:** cerrar la única brecha Critical y arrancar activaciones bloqueantes.

| Feature | Item McKinsey | Owner | Output |
|---|---|---|---|
| **FEAT-A** Shadow Mode + DAG Chaos Testing | #3 | Platform Eng | Brainstorm + spec + 2 worktrees paralelos |
| **FEAT-B** Retail Ontology YAML | #4 | Data Eng + Retail SME | `base.ontology.yaml` + `domains/retail.ontology.yaml` + 3-5 TraversalPatterns |
| **FEAT-C** Three-Tier Authority Model | #1 | Security | Spec con tier como atributo YAML + `GuardrailAgent` class |

### Sprint 3-4 (semanas 5-8) · Observability + Prompt Governance
**Objetivo:** activar telemetría sobre datos crudos ya capturados.

| Feature | Item McKinsey | Owner | Output |
|---|---|---|---|
| **FEAT-D** Telemetry Aggregator + Cost Dashboard (continuación FEAT-177) | #5 | Platform Eng + nav-admin | OTel + MetricsSubscriber + cost pipeline + dashboard |
| **FEAT-E** Prompt Registry + Semver + Canary | #6 | AI Eng | Extender `infographic_registry` → `PromptRegistry`; integración SDD |
| **FEAT-F** Medallion Bronze/Silver + Quality Scoring | #2 | Data Eng | Capas formales + streaming validation + `quality_score` en EpisodicMemory |

### Sprint 5-6 (semanas 9-12) · Routing Intelligence + Cross-Cutting
**Objetivo:** activar optimizer data-driven encima de la telemetría.

| Feature | Item McKinsey | Owner | Output / Depende |
|---|---|---|---|
| **FEAT-G** Intelligent Model Routing Optimizer | #10 | AI Eng | Task taxonomy + leaderboard + auto-routing. **Depende de FEAT-D** |
| **FEAT-H** Cross-Agent Data Product Catalog | #9 | Platform Eng | Catalog Service + REST discovery + SLA dashboards |
| **FEAT-I** Federated Operating Model Docs + RACI | #11 | Eng Leadership | RACI + SLA review 5-day + community of practice |

### Sprint 7-12 (meses 4-6) · Activation Layer + Long-Track

| Feature | Item McKinsey | Owner |
|---|---|---|
| **FEAT-J** Fine-Tuning Pipeline desde Episodes | #16 | AI Eng + Data Eng |
| **FEAT-K** DX Polish Bundle (Docker Compose + Visual Debugger + Scaffold CLI) | #12 | Platform Eng + DX |
| Track paralelo · **Nav-admin No-Code Builder** | #7 | Frontend |
| Track paralelo · **Org / Legal** | #8, #13, #14, #15 | NEXUS / Operations / Leadership / Legal |

---

## 5. Milestones

| ID | Hito | Fecha objetivo | Criterio de cierre |
|---|---|---|---|
| **M0** | FEAT-176 Lifecycle Events System en `dev` | Cumplido (mayo 2026) | Mergeado; destraba FEAT-177 |
| **M1** | Production Safety Gate | Fin Sprint 2 (semana 4) | FEAT-A shadow mode operacional contra data productiva con rollback automatizado |
| **M2** | Retail Ontology Live | Fin Sprint 2 (semana 4) | `ENABLE_ONTOLOGY_RAG=true` + smoke test pasando con `base.ontology.yaml` retail |
| **M3** | Authority Tiers Formalizados | Fin Sprint 2 (semana 4) | T1/T2/T3 declarables en YAML + `GuardrailAgent` reusable |
| **M4** | Cost Attribution Live | Fin Sprint 4 (semana 8) | Dashboard en nav-admin con cost por workflow / client / model |
| **M5** | Prompt Registry GA | Fin Sprint 4 (semana 8) | Semver + canary 5% + golden tests en CI |
| **M6** | Data Quality Layer | Fin Sprint 4 (semana 8) | Bronze/Silver + streaming validation + quality_score en EpisodicMemory |
| **M7** | Auto-Routing Live | Fin Sprint 6 (semana 12) | Leaderboard semanal alimenta `LLMConfig.resolve` automáticamente |
| **M8** | Cross-Agent Catalog | Fin Sprint 6 (semana 12) | Discovery API + SLA dashboards (freshness/completeness/accuracy) |
| **M9** | Federated Ops Charter | Fin Sprint 6 (semana 12) | RACI + SLA 5-day + community charter publicados |
| **M10** | Data Flywheel Activado | Fin mes 6 | Fine-tuning pipeline mensual + monthly report a stakeholders |
| **M11** | DX Stack Empaquetado | Fin mes 6 | Docker Compose + visual debugger + scaffold CLI + cookbook publicado |

---

## 6. Próximos pasos inmediatos

1. **Esta semana:** compartir este roadmap con leadership; alinear narrativa pública con el delta real (no estamos construyendo, estamos operacionalizando).
2. **Semana 1-2:** arrancar **FEAT-A**, **FEAT-B**, **FEAT-C** en paralelo vía `/sdd-brainstorm` o `/sdd-fromjira`.
3. **Semana 3:** revisar con owners externos (#8 NEXUS, #13 Operations, #14 Leadership, #15 Legal).
4. **Cadencia continua:** actualizar este roadmap cada 2 semanas según PRs mergeados a `dev` — es un documento vivo.
