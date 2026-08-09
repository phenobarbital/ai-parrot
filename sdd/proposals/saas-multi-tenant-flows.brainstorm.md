---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Brainstorm: Parrot Research Cloud — SaaS multi-tenant de Flows con BYOK

**Date**: 2026-08-09
**Author**: phenobarbital (diseño asistido)
**Status**: exploration
**Recommended Option**: Option C — Core tenancy primitives + satellite control-plane package

> FEAT-ID sin reservar todavía: este documento cubre un programa de ~14 features.
> Cada una reservará su propio `FEAT-<NNN>` vía `scripts/sdd/reserve_ids.py` al
> pasar por `/sdd-spec`.

---

## Problem Statement

Queremos vender **Flows de investigación pre-hechos** (`AgentCrew` + `AgentsFlow`) como
servicio SaaS. Cada ejecución debe devolver la **totalidad de la investigación**: el
contenido de cada tool ejecutada por agente, el resultado de cada agente, el executive
summary y una infografía generada con `InfographicToolkit`.

Tres modos comerciales:

| Modo | Runtime | Datos | Claves LLM |
|---|---|---|---|
| **shared** | servidor aiohttp compartido | schema-per-tenant en la DB Postgres compartida | BYOK |
| **enterprise** | servidor dedicado por tenant (Pulumi) | DB propia en el **mismo** servidor Postgres | BYOK |
| **enterprise-managed** | igual que enterprise | igual | **nuestras** claves → facturación por consumo |

Sin Redis per-tenant y sin servidor Postgres per-tenant en ningún modo.

Entrega: REST (`run_id` + dossier JSON + URLs firmadas), streaming SSE/WS, webhooks
salientes firmados y portal de tenant. AuthN: API keys por tenant (M2M) + navigator-auth
ABAC/PBAC (humanos). Facturación: por run, por tokens/coste LLM y suscripción por
tenant/seat.

**El framework ya tiene casi todas las piezas.** Lo que falta es la capa de tenancy, un
contrato de resultado estable y el plano de control comercial.

## Constraints & Requirements

- Un solo servidor Postgres para todo; aislamiento por **schema** (shared) o por
  **database** (enterprise). Nunca un servidor por cliente.
- Un solo Redis compartido. Nada de Redis per-tenant.
- BYOK es el modo por defecto; el modo con claves gestionadas debe ser **facturable**, lo
  que exige metering de tokens/coste de calidad contable.
- El dossier debe incluir el contenido real de cada tool call, no solo su metadato.
- Reutilizar navigator-auth (ABAC/PBAC), navrules, navigator-eventbus, OTEL+OpenLIT y el
  `PulumiToolkit` existentes; no construir paralelos.
- No contaminar el core OSS con lógica comercial.

---

## Estado real del codebase (verificado)

Hallazgos que condicionan cualquier opción:

1. **No existe frontera de tenant en HTTP.** No hay middleware de tenant ni cambio de
   schema por petición. `parrot/auth/permission.py:20` declara `UserSession.tenant_id`
   pero **nunca se construye** desde una request. El único precedente real de
   schema-per-tenant es `parrot_formdesigner/services/storage.py`
   (`PostgresFormStorage._resolve_schema` + `services/_identifiers.py:validate_identifier`),
   con el tenant sacado de `session[AUTH_SESSION_OBJECT]['programs'][0]`
   (`parrot_formdesigner/api/_utils.py:_get_request_tenant`).
2. **Agujeros de seguridad que bloquean cualquier venta multi-tenant.** Ninguna ruta
   `/api/v1/crew*` ni `/api/v1/crews*` lleva `@is_authenticated()`, y el `tenant` llega en
   el **body/query** (`handlers/crew/execution_history_handler.py:111`,
   `handlers/crew/execution_handler.py:590`) → lectura/replay cross-tenant. Fuera de auth
   además: `/bots/*/stream/{sse,ndjson,chunked,ws}` (`handlers/stream.py:383` se auto-añade
   al `exclude_list` de nav-auth), `/ws/userinfo`, `/v1/chat/completions/{session_id}`,
   `/v1/models`.
3. **PBAC falla abierto.** `setup_pbac()` (`parrot/auth/pbac.py`) degrada a
   `(None, None, None)` ante cualquier error y los checks (`handlers/agent.py:135`) hacen
   `except → allow`. `RlsRegistry`, `DataPlanePolicyGuard` y `DatasetPolicyGuard` están
   implementados pero **nunca se instancian**.
4. **`AgentsFlow` no está a la altura de `AgentCrew`.** En `bots/flows/flow/flow.py:836-850`,
   `_aggregate_result()` pasa a `build_node_metadata()` el **dict** que devuelve
   `AgentNode.execute()` (`core/node.py:310` → `{"response","output","execution_time","prompt"}`)
   en vez del `AgentResponse`. En `core/result.py:680` eso cae en la rama genérica →
   **`tool_calls` siempre vacío y `usage` siempre `None`** en runs de `AgentsFlow`. Tampoco
   tiene execution wiki, ni hook de infografía, ni llama a `_save_agent_result`, ni tiene
   campo `tenant` (`CrewDefinition.tenant` sí existe; `FlowDefinition` no).
5. **El contenido de las tools sí se captura hoy**, pero solo en la ruta crew:
   `ToolCall(id,name,arguments,result,error,execution_time)` (`parrot/models/basic.py:23`)
   sobre `AIMessage.tool_calls`, y las páginas `tool_result` del `ExecutionWikiRecorder`
   (`parrot/knowledge/wiki/execution.py`), que escribe en un **SQLite por crew** en
   `{cwd}/.parrot/crew_wiki/<slug>/wiki.db` — single-writer, no particionado por tenant.
6. **La base de metering existe y es buena.** `CostCalculator.cost_usd(...)` con tablas de
   precios por proveedor, `UsageRecord`, y el punto de extensión
   `observability/recorders/base.py:AbstractLogger.record(UsageRecord)`. **Pero**
   `UsageRecordingSubscriber` (`recorders/subscriber.py:~100`) descarta a propósito
   `user_id`/`session_id`/`agent_name` por contrato de PII y no hay `tenant_id`;
   `cumulative_cost_usd` es in-memory por proceso. No hay store durable, ni cuotas, ni
   rate limiter (el hook de `a2a/security.py:1444` siempre es `None`).
7. **BYOK tiene cimientos, sin dimensión tenant.** `parrot/security/credentials_utils.py`
   (AES-GCM con `key_id` para rotación), `parrot/security/vault_utils.py`
   (`store/retrieve/delete_vault_credential`, keyed por `(user_id, vault_name)`), y
   `parrot/auth/credentials.py` (`CredentialResolver`, `ResolvedCredential` con
   `key_fingerprint` solo para auditoría, `CredentialRequired`, `NeedsAuth`).
   `broker.py:276` ya tiene un `_VaultStaticKeyResolver` con `store_key()`. Inyectar la
   clave por instancia **ya es posible**: `LLMFactory.create(llm, ..., **kwargs)`
   (`clients/factory.py:179`) mezcla `kwargs` en `init_params` y `AbstractClient.__init__`
   lee `kwargs['api_key']`. Nadie lo usa.
8. **Pulumi no puede parametrizar por tenant hoy.** `PulumiToolkit` shell-ea al CLI y
   **descarta silenciosamente `config_values`** (no hay `pulumi config set`);
   `PulumiConfig.state_backend` se declara pero nunca se usa (no hay `pulumi login`); y
   **no existe ningún programa Pulumi** salvo el fixture de test
   (`packages/ai-parrot/tests/fixtures/pulumi_docker_project/`).
9. **`ArtifactStore`** (`parrot/storage/artifacts.py:27`) está keyed por
   `(user_id, agent_id, session_id)` sobre `ConversationBackend` + `OverflowStore` (S3),
   con URL pública firmada HMAC (`/api/v1/artifacts/public/{signature}/{artifact_id_html}`,
   excluida de auth). Sin dimensión tenant.
10. **`navrules`** está en el workspace con **cero imports** fuera de su paquete. Es el
    consumidor natural para entitlements/cuotas declarativas.

---

## Options Explored

### Option A: Todo dentro de `ai-parrot-server`

Añadir tenancy, catálogo, entitlements y facturación como handlers y servicios más dentro
del paquete de servidor existente.

✅ **Pros:**
- Cero fricción de packaging; el `app.py` actual ya monta todo desde ahí.
- Camino más corto a una demo.

❌ **Contras:**
- Mezcla lógica comercial (precios, facturación, entitlements) con infraestructura OSS.
- Una instancia enterprise en casa del cliente acabaría llevando el código del plano de
  control, incluidas las tablas de facturación cross-tenant.
- Imposible versionar/vender el plano de control por separado.

### Option B: Servicio SaaS separado que consume ai-parrot como librería

Un repositorio/servicio nuevo e independiente que importa `ai-parrot` y expone su propia
API, dejando el monorepo intacto.

✅ **Pros:**
- Separación comercial total y limpia.
- Ciclo de release independiente.

❌ **Contras:**
- Los arreglos imprescindibles (paridad de `AgentsFlow`, contenido de tools, tenant en las
  definiciones) **son del core** — desde fuera solo se pueden parchear con monkey-patching.
- Duplicaría el ensamblado del app aiohttp, la auth y el registro de rutas.
- Los agujeros de seguridad del servidor compartido seguirían abiertos.

### Option C: Primitivas de tenancy en el core + paquete satélite de plano de control ⭐

Dos movimientos complementarios:

- Al **core** (`packages/ai-parrot`) van solo primitivas genéricas y reutilizables:
  `parrot/tenancy/` (contexto + ContextVar + validación de identificadores),
  `parrot/models/dossier.py`, `parrot/auth/llm_credentials.py`, y las correcciones de
  paridad de `AgentsFlow`. Todo esto es valor de framework, útil aunque no vendiéramos nada.
- Un paquete satélite nuevo **`packages/ai-parrot-saas`** (namespace `parrot.saas.*` vía
  PEP 420, como `ai-parrot-embeddings`) con el plano de control comercial: registro de
  tenants, API keys, catálogo, entitlements, facturación, provisioning y los handlers SaaS.
  Extras `[controlplane]` / `[dataplane]` para que una instancia enterprise instale solo lo
  que le toca.

✅ **Pros:**
- Los arreglos del core se hacen donde viven, sin parches.
- La lógica comercial queda separable, versionable y vendible aparte.
- Sigue el patrón de satélites que el monorepo ya usa y entiende.
- Una instancia enterprise no lleva las tablas de facturación cross-tenant.

❌ **Contras:**
- Un paquete más que mantener y publicar.
- Obliga a disciplina para no colar lógica de producto en el core.

**Recomendación: Option C.**

---

## Diseño recomendado

### 1. Frontera de tenant

`parrot/tenancy/context.py`:

```python
@dataclass(frozen=True, slots=True)
class TenantContext:
    tenant_id: str          # slug validado ^[a-z][a-z0-9_]{2,30}$
    schema: str             # shared: == tenant_id | enterprise: "public"
    mode: Literal["shared", "enterprise", "enterprise_managed"]
    plan: str
    entitlements: frozenset[str]
    principal: str          # user_id humano o "apikey:<key_id>"

current_tenant: ContextVar[TenantContext | None]
```

**Middleware** `parrot.saas.middleware.tenant_middleware`, registrado **después** de
`AuthHandler().setup(app)` en `app.py` (para que la sesión exista) y antes de los
handlers. Dos caminos de autenticación conviviendo:

- **API key M2M**: `Authorization: Bearer pk_live_<key_id>.<secret>`. Búsqueda por
  `key_id`, verificación del `secret` con Argon2id, de ahí salen tenant y scopes. Estas
  rutas se añaden al `exclude_list` de nav-auth y **las validamos nosotros, fail-closed**.
- **Sesión navigator-auth**: `resolve_tenant(session)` canónico en core, generalizando la
  heurística de formdesigner — primero un claim explícito `tenant_id`, luego
  `organizations`/`programs[0]`, y si no hay nada → **403**. Nada de `'global'` por defecto
  en modo SaaS.

El contexto se deposita en `request['tenant']`, en `current_tenant` y en el
`PermissionContext` de `parrot/auth/context.py:_pctx_var` (con `tenant_id` poblado), de
modo que el runtime de flows, los clientes LLM y los recorders lo ven sin pasar parámetros.

**Aplicación del schema — decisión: nombres cualificados, no `search_path`.**
`PostgresResultStorage` (`bots/flows/core/storage/backends/postgres.py:52`) mantiene una
**única conexión de larga vida** y hace `CREATE TABLE IF NOT EXISTS <table>` sin
cualificar: mutar `search_path` sobre una conexión compartida entre tenants concurrentes
es un riesgo cross-tenant real. En su lugar:

- Promover `parrot_formdesigner/services/_identifiers.py` (`validate_identifier`,
  `qualified_table`) a `parrot/tenancy/identifiers.py` y usarlo en ambos sitios.
- `PostgresResultStorage.__init__` acepta `schema: str | None`; DDL y DML se cualifican
  `"<schema>"."<table>"`. Denylist de slugs: `public`, `navigator`, `pg_*`, `parrot_saas`.
- `TenantProvisioner.create_schema()` hace `CREATE SCHEMA IF NOT EXISTS` y ejecuta el
  bootstrap DDL idempotente existente por colección más las tablas SaaS.

**PBAC tenant-aware:** consolidar las tres copias de `_build_eval_context()`
(`handlers/agent.py:415`, `handlers/chat.py:47`, `handlers/bots.py:57`) en
`parrot.auth.eval_context.build_eval_context(request)`, que inyecta
`userinfo['tenant_id']`; las políticas YAML pasan a usar `conditions.resource.tenant_id`.
`setup_pbac` pasa a **fail-closed** cuando `PARROT_SAAS_MODE=true`.

### 2. El dossier

`parrot/models/dossier.py` (pydantic v2), contrato versionado y estable:

```
ResearchDossier
  dossier_version: Literal["1.0"]
  run_id, tenant_id, flow_ref ("slug@semver" | custom id), engine ("crew"|"flow")
  method, status, started_at, finished_at, total_time, query
  agents: list[AgentSection]
  executive_summary: ExecutiveSummary(text, model, usage)
  infographic: InfographicRef | None (artifact_id, html_url, template, theme)
  usage: RunUsage(by_model[], input_tokens, output_tokens, cost_usd|None, billable)
  errors: dict[str,str], metadata: dict

AgentSection: node_id, agent_name, provider, model, status, execution_time,
              prompt, output, usage, tool_runs: list[ToolRun]
ToolRun:      call_id, tool_name, arguments, result_inline|None, result_ref|None,
              result_bytes, truncated, error, execution_time
```

`DossierBuilder.from_flow_result(result, *, execution_memory=None, tenant, run_id)`
ensambla desde `FlowResult.nodes[].tool_calls` (contenido real de cada tool), los
`NodeResult` de `execution_memory`, `FlowResult.summary` y `FlowResult.infographic`.

**Almacenamiento — ambos, por tamaño.** El esqueleto del dossier (metadatos por agente,
summary, refs) va como JSONB en `<schema>.flow_runs`. Los cuerpos de resultado de tool que
superen el umbral (32 KiB por defecto) se descargan a object storage reutilizando el
`OverflowStore` que ya usa `ArtifactStore` (`maybe_offload`/`resolve`), dejando
`result_ref`. Por debajo del umbral, inline. Así la fila de run sigue siendo consultable y
el dossier completo sigue siendo reconstruible.

El `ExecutionWikiRecorder` deja de ser el sistema de registro: se conserva como
herramienta de recuperación para el agente, con `execution_wiki_path` por tenant, y se
**desactiva en modo shared** (SQLite single-writer sobre un slug de crew compartido entre
tenants es una colisión garantizada).

**Paridad de `AgentsFlow` (obligatorio; sin esto el modo `flow` no se puede vender):**

- a. `_aggregate_result()`: desenvolver `resp["response"]` antes de `build_node_metadata()`
  → restaura `tool_calls` **y** `usage`.
- b. Añadir `tenant` a `FlowDefinition`/`FlowMetadata` y a `AgentsFlow.__init__`.
- c. Llamar a `_save_agent_result()` desde la ruta de nodo completado.
- d. Extraer `AgentCrew._finalize_infographic` + `build_deterministic_tabs` a un
  `parrot/bots/flows/core/infographic.py` compartido por crew y flow, y **dejar de tragarse
  las excepciones en silencio** — que se registren en `dossier.errors`.
- e. Usar `synthesize_results` como `on_complete` por defecto cuando `generate_summary=True`.

### 3. Catálogo y entitlements

Bundles versionados en `catalog/flows/<slug>/<semver>/`: `manifest.yaml` (nombre, versión,
descripción, engine, tools requeridas, proveedores requeridos, JSON-Schema de inputs, hints
de precio) + `definition.json` (`CrewDefinition` o `FlowDefinition`). `FlowCatalog` los
carga y publica; el catálogo es global y los **entitlements son por tenant**:
`tenant_entitlements(tenant_id, flow_slug, version_spec, max_runs_month, enabled)`.

La **puerta de admisión** antes de cada run evalúa entitlement + cuota + modo con un
`navrules.RuleSet` — declarativo, y por fin le da a `navrules` un consumidor real.

**Definiciones propias (enterprise):** `POST /api/v1/saas/flows`, validadas contra un
allowlist de tools derivado del plan; agentes resueltos vía `AgentRegistry` y tools vía
`ToolManager` filtrado por PBAC/`ExecutionPolicy`. **Solo se aceptan en modos
`enterprise*`.** En modo shared solo corren flows del catálogo: ejecutar tools arbitrarias
definidas por el cliente en el servidor compartido no es un radio de impacto aceptable.

### 4. BYOK

`parrot/auth/llm_credentials.py` → `TenantLLMCredentialResolver(CredentialResolver)`, sobre
el patrón de `_VaultStaticKeyResolver`:

- Vault namespaced sin cambiar el esquema de la colección:
  `vault_name = f"llm_{tenant}_{provider}"` con `user_id = f"tenant:{slug}"` como principal
  sintético. Se añade `tenant` al `_ctx` de `_encrypted_field.seal()`.
- **Punto de inyección:** `LLMFactory.create(..., api_key=...)` al construir el crew/flow
  del run, nunca global. El `RunService` construye vía `from_definition` y resuelve la clave
  de cada agente desde el vault del tenant.
- Cadena de fallback: clave del tenant → (modo managed) pool de claves de plataforma →
  `CredentialRequired` con cuerpo con forma `NeedsAuth` (402/409).
- No se filtra: solo `key_fingerprint` en auditoría; prohibido persistir `api_key` dentro de
  `AgentDefinition.config` (se sustituye por una referencia).
- Validación en el alta: sonda barata tipo `models.list` por proveedor antes de aceptar.

### 5. Metering y facturación

Tablas en un schema de **plano de control** (`parrot_saas`), no per-tenant, para poder
agregar cross-tenant: `usage_events` (append-only: run_id, tenant_id, provider, model,
tokens in/out/cached, cost_usd, billable, mode, ts), `run_records`, `tenant_quota`,
`tenant_subscription`, `invoice_lines`.

`TenantUsageRecorder(AbstractLogger)` registrado extendiendo `build_recorders_from_config`.
`UsageRecordingSubscriber` desecha la identidad por contrato de PII — **no peleamos contra
eso**: el recorder lee `tenant_id`/`run_id` de los ContextVars (`current_tenant`,
`current_run_id`) que fija el `RunService`. Si `current_tenant` está vacío se escribe
`tenant_id='unattributed'` con una métrica WARN; **nunca se descarta un evento**.

> Riesgo a validar con test antes de comprometerse: `AfterClientCallEvent` se emite desde
> código que lee ContextVars **en construcción**. Si el ContextVar no propaga hasta el
> recorder, el plan B es añadir `tenant_id` al dataclass del evento (ya lleva
> `user_id`/`session_id`, así que no rompe su contrato) y a un subtipo de `UsageRecord`.

Cuotas: **admisión previa al run** (navrules) + **corte en caliente** con un `BudgetGuard`
suscrito a `AfterClientCallEvent` que acumula coste por run y cancela la tarea al superar
`run_budget_usd` (emite `saas.run.budget_exceeded`). Corte duro en shared, solo aviso en
enterprise BYOK. Las tres unidades de facturación: por run (`run_records`), por
tokens/coste (`usage_events`, autoritativo en managed) y suscripción
(`tenant_subscription`).

### 6. Eventbus

Reservar el namespace **`saas.*`** en `navigator-eventbus/TOPICS.md` (fila nueva; es el
proceso de gobernanza de ese repo):
`saas.run.{queued,started,node_started,node_completed,tool_completed,summary_ready,infographic_ready,completed,failed,budget_exceeded}`,
`saas.tenant.{provisioned,suspended}`, `saas.usage.recorded`, `saas.webhook.{delivered,failed}`.

Backend: **`RedisStreamsBackend`** (durable, consumer groups, dedup, retention) sobre el
Redis compartido — necesario para que un SSE que reconecta pueda reproducir y para que los
webhooks sean at-least-once. El `tenant_id` viaja **en el payload, no en el topic** (el
registro de TOPICS se mantiene limpio), pero se usa `stream_key_fn` para shardear streams
por tenant de cara a retención y escala.

`GET /api/v1/saas/runs/{run_id}/stream` (SSE/WS) se suscribe a `saas.run.*` con `filter_fn`
sobre `run_id` + `tenant_id`. Reutiliza la forma de `handlers/stream.py` pero
**autenticado** — no se replica su truco de `exclude_list`.

`WebhookDispatcher` suscrito a `saas.run.completed|failed`: HMAC-SHA256
`X-Parrot-Signature: t=<ts>,v1=<hex>` sobre `f"{ts}.{body}"`, 5 reintentos con backoff
exponencial, fallos al DLQ del bus (`navigator.evb_dlq` ya existe) + `saas.webhook.failed`.

### 7. Provisioning enterprise

**Split control plane / data plane.** El plano de control compartido es dueño del registro
de tenants, las API keys, el catálogo, los entitlements y la facturación. Las instancias
enterprise son planos de datos que **llaman a casa**: se autentican con una credencial de
instancia y empujan `usage_events` + `run_records` a `POST /api/v1/saas/ingest`, y bajan
entitlements/catálogo periódicamente. La facturación no puede depender de la máquina del
cliente, y la máquina del cliente debe seguir funcionando si el control plane cae (cola
local + replay).

Trabajo Pulumi necesario:

1. **Arreglar `config_values`** en `parrot_tools/pulumi/executor.py`: emitir
   `pulumi config set --stack <s> [--secret] k v` antes de `preview`/`up`. Hoy se descarta
   en silencio — es un bug real, no una limitación de diseño.
2. **Honrar `state_backend`**: `pulumi login <backend>` (bucket S3/GCS) para estado durable
   y compartido.
3. **Escribir el programa**: `packages/ai-parrot-saas/pulumi/tenant-dataplane/` en Pulumi
   **Python** (no YAML, para reutilizar config pydantic): contenedor de la app del tenant,
   **base de datos** en el servidor Postgres existente vía el provider `postgresql`
   (`CREATE DATABASE`, rol, grants), inyección de secretos, DNS/ruta, y outputs
   `{endpoint, database, instance_id, instance_token}`.
4. `TenantProvisioner` orquesta: plan → aprobación humana → apply → registrar outputs →
   health check → tenant `active`. Usa el sistema de grants acotados existente
   (`tool:pulumi_apply` es literalmente el ejemplo canónico en `parrot/auth/grants.py:53`).

---

## Ficheros críticos

**Core (`packages/ai-parrot/src/parrot/`)**
- `tenancy/{__init__,context,identifiers,resolver}.py` — nuevo
- `models/dossier.py` — nuevo
- `auth/llm_credentials.py` — nuevo; `auth/eval_context.py` — nuevo (consolida 3 copias)
- `bots/flows/flow/flow.py` — fix `_aggregate_result` (~línea 836) + tenant + persistencia
- `bots/flows/core/infographic.py` — nuevo (extraído de `crew/crew.py:559` y
  `crew/result_infographic.py:121`)
- `bots/flows/core/storage/backends/postgres.py` — parámetro `schema`
- `bots/flows/flow/definition.py` — campo `tenant`
- `security/vault_utils.py` — dimensión tenant

**SaaS (`packages/ai-parrot-saas/src/parrot/saas/`)** — paquete nuevo completo

**Server (`packages/ai-parrot-server/src/parrot/`)**
- `handlers/crew/{handler,execution_handler,execution_history_handler}.py` —
  `@is_authenticated()` y tenant desde el contexto, no desde el body
- `handlers/stream.py:383` — quitar la auto-exclusión de auth
- `manager/manager.py:1673` — registro de rutas SaaS

**Root**: `app.py` — orden `setup_pbac()` → `BotManager.setup()` → `AuthHandler.setup()` →
`tenant_middleware` (el comentario en `app.py:336` ya avisa de que el orden actual está mal)

**navigator-eventbus**: `TOPICS.md` — fila del namespace `saas.*`

---

## Plan de features

**Fase 0 — Prerrequisitos de seguridad (bloquean todo lo demás)**
- `S0 saas-auth-hardening` — `@is_authenticated()` en todo `/api/v1/crew*`; dejar de derivar
  tenant del body; autenticar `/bots/*/stream/*`, `/ws/userinfo`, `/v1/chat/completions`;
  `setup_pbac` fail-closed bajo `PARROT_SAAS_MODE`; consolidar los tres
  `_build_eval_context()`.

**Fase 1 — Fundación de tenancy**
- `S1 tenant-context-and-middleware` [dep: S0]
- `S2 tenant-schema-provisioning` [dep: S1]

**Fase 2 — Contrato de resultado**
- `S3 agentsflow-parity` [independiente — puede ir en paralelo desde el día 1]
- `S4 research-dossier` [dep: S2, S3]

**Fase 3 — Plano comercial**
- `S5 flow-catalog-and-entitlements` [dep: S1]
- `S6 byok-llm-credentials` [dep: S1]
- `S7 usage-metering-store` [dep: S1]

**Fase 4 — Entrega**
- `S8 run-service-and-api` [dep: S4, S5, S6, S7]
- `S9 run-streaming-and-webhooks` (+ PR de TOPICS.md en navigator-eventbus) [dep: S8]

**Fase 5 — Enterprise**
- `S10 pulumi-config-and-state` [independiente]
- `S11 tenant-dataplane-provisioning` [dep: S10, S1]
- `S12 control-plane-ingest` [dep: S7, S11]

**Fase 6 — Claves gestionadas y facturación**
- `S13 managed-key-pool-and-rating` [dep: S6, S7, S12]
- `S14 tenant-portal` (SvelteKit, fuera del scope backend) [dep: S8, S9]

---

## Verificación

- **S0**: test de integración que golpea cada ruta antes-abierta sin credenciales y espera
  401/403; test que envía `tenant` en el body y verifica que se ignora.
- **S1/S2**: dos tenants, mismo flow, misma tabla — el tenant A no ve filas de B. Test de
  inyección con slugs maliciosos (`../`, `public`, `pg_catalog`).
- **S3**: regresión que corre el mismo grafo como `AgentCrew` y como `AgentsFlow` y afirma
  que `FlowResult.nodes[].tool_calls` y `.usage` son **no vacíos e iguales** en ambos. Este
  test hoy falla.
- **S4**: `ResearchDossier` round-trip, incluyendo un tool result >32 KiB que debe salir por
  `result_ref` y resolverse de vuelta.
- **S6**: test de fuga — correr un flow con una clave BYOK conocida y hacer grep del log
  completo, de los spans OTEL y de las filas de DB buscando el secreto; debe aparecer solo
  el fingerprint.
- **S7**: **validar primero la propagación del ContextVar** (test aislado antes de escribir
  el recorder); luego, un run con N llamadas LLM debe producir N `usage_events` con el
  `tenant_id` correcto y un `cost_usd` que cuadre con `CostCalculator`.
- **S8/S9**: end-to-end contra el servidor real — `POST /api/v1/saas/runs` de un flow del
  catálogo, seguir el SSE hasta `saas.run.completed`, `GET` del dossier, abrir la URL
  firmada de la infografía, y comprobar la entrega del webhook con firma HMAC válida.
- **S10/S11**: `pulumi preview` contra el programa del data-plane con `config_values`
  distintos por tenant, verificando que **llegan** al stack (hoy no llegan).

Global: `pytest` en cada paquete tocado tras cualquier cambio de lógica, y un smoke de dos
tenants concurrentes ejecutando el mismo flow del catálogo con claves BYOK distintas.

---

## Open Questions

1. **Propagación del ContextVar hasta el usage recorder** — condiciona todo el diseño de
   metering. Probarlo en S7 antes de escribir código encima.
2. **`ArtifactStore` sin tenant y con URL pública firmada no autenticada** — las infografías
   del tenant A no pueden ser adivinables por B. Hay que meter el tenant en la clave del
   artefacto y en el payload de la firma, y poner TTL corto.
3. **`PostgresResultStorage` usa `CREW_RESULT_STORAGE_PG_DSN`**, una conexión distinta de
   `app['database']`. Dos rutas de conexión que hay que reconciliar (o documentar
   explícitamente que el storage de resultados vive aparte).
4. **Frescura de las tablas de precios** (avisan a los 90 días): facturar claves gestionadas
   con precios rancios es riesgo de ingresos. Necesita un proceso de refresco.
5. **Límite de escala del schema-per-tenant**: Postgres se degrada con miles de schemas
   (bloat de catálogo, coste de `pg_dump`). Bien para cientos; hay que marcar la ruta de
   migración (tablas particionadas por tenant + RLS — `RlsRegistry` ya existe sin usar)
   antes de pasar de ~1–2k tenants.
6. **Decisión de producto a confirmar**: en modo shared se prohíben las definiciones de flow
   propias del cliente. Si comercialmente hace falta permitirlas, el coste es un sandbox de
   ejecución real (`parrot/tools/executors/{docker,k8s}.py` ya existen y serían la base), y
   eso es una feature en sí misma.

---

## Next Steps

1. `/sdd-spec saas-auth-hardening` — es el bloqueante duro; nada de lo demás es vendible
   hasta que esté cerrado.
2. `/sdd-spec agentsflow-parity` en paralelo (no depende de nada).
3. Validar el riesgo nº 1 (ContextVar) con un test aislado antes de especificar S7.
