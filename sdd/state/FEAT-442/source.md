---
kind: file
jira_key: null
file_path: sdd/proposals/saas-multi-tenant-flows.brainstorm.md
fetched_at: 2026-08-22T00:00:00Z
summary_oneline: Parrot Research Cloud - SaaS multi-tenant Flows (BYOK, 3 commercial modes, ~14-feature program, Option C core primitives + ai-parrot-saas satellite)
---

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
2. **Agujeros de seguridad que bloquean cualquier venta multi-tenant.** Los tres ficheros
   de handler con rutas de crew — `handlers/crew/{handler,execution_handler,execution_history_handler}.py`
   — **no llevan `@is_authenticated()`** (`special_nodes.py` y `tool_catalog.py` sí lo
   llevan). Y el `tenant` llega en el **body/query**, sin contraste contra la sesión:
   `execution_handler.py:590` sí exige tenant (400 si falta) pero no valida propiedad;
   `handler.py:412,512` y `execution_history_handler.py:144` **hacen default a `"global"`**
   → lectura/replay cross-tenant. Fuera de auth además:
   `/bots/*/stream/{sse,ndjson,chunked,ws}` (`handlers/stream.py:383` se auto-añade al
   `exclude_list` de nav-auth), `/ws/userinfo`, `/v1/chat/completions/{session_id}`,
   `/v1/models`.
3. **PBAC falla abierto.** `setup_pbac()` (`parrot/auth/pbac.py`) degrada a
   `(None, None, None)` ante cualquier error y los checks (`handlers/agent.py:135`) hacen
   `except → allow`. `RlsRegistry`, `DataPlanePolicyGuard` y `DatasetPolicyGuard` están
   implementados pero **nunca se instancian**.
4. **`AgentsFlow` no está a la altura de `AgentCrew`, y el fallo tiene dos sitios.**
   `AgentNode.execute()` (`core/node.py:310`) devuelve el envoltorio
   `{"response","output","execution_time","prompt"}`. El scheduler lo guarda tal cual y en
   **`flow.py:1734`** llama `ctx.mark_completed(nid, result=event.result)` **sin pasar
   `response=`** → `FlowContext.responses` queda permanentemente vacío. Después, en
   **`flow.py:841`**, `_aggregate_result()` pasa ese mismo dict como `response=` a
   `build_node_metadata()`, que solo introspecciona `AgentResponse`/`AIMessage`
   (`core/result.py:680`) → cae en la rama genérica y **`tool_calls`, `usage` y `model`
   salen vacíos** en todo run de `AgentsFlow`. La pérdida de `usage` es tan grave como la
   de contenido: es un agujero de facturación.
   Además `AgentsFlow` **no tiene `ExecutionMemory` en absoluto** (cero referencias en
   `flow.py`, frente a 60 en `crew.py`), lo que significa que la paridad de infografía no
   es "conectar un hook": `build_deterministic_tabs()` consume `execution_memory`, así que
   hay que construir ese plano primero. Tampoco llama a `_save_agent_result`, ni tiene
   execution wiki, ni campo `tenant` (`CrewDefinition.tenant` sí existe; `FlowDefinition` no).
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
  `qualified_table`) a `parrot/storage/identifiers.py` — en core, no en `parrot_saas`, para
  que el paquete SaaS no dependa de formdesigner; formdesigner pasa a importarlo de ahí.
- **Regla de naming — `client_slug` aleatorio, una sola para schema y base.** El slug se
  genera con un **CSPRNG en el alta del tenant**; no se deriva del nombre del cliente ni de
  su id, y no se recalcula nunca: es un dato almacenado, no una función. Esa es la
  propiedad que importa — un identificador derivado sigue siendo **enlazable** (quien lo vea
  puede confirmar una hipótesis probando candidatos), uno aleatorio no lo es sin la tabla de
  mapeo.
  - Formato: prefijo `t_` + alfabeto restringido a minúsculas y dígitos — Postgres pliega a
    minúsculas los identificadores sin comillar — dentro del límite de 63 caracteres de
    `NAMEDATALEN`. `t_` + ~26 caracteres base32 da entropía de sobra sin acercarse al límite.
  - El prefijo fijo garantiza además que nunca colisiona con el espacio reservado `pg_*`.
  - Unicidad por constraint en la tabla de tenants, con reintento ante colisión.
  - Se aplica con el **mismo generador** al schema en modo shared y al nombre de base en
    enterprise. Nunca se deriva de un valor de la request: sale siempre del registro `Tenant`.
  - Denylist (`public`, `navigator`, `pg_*`, `saas`) y validación de identificador se
    mantienen como defensa en profundidad, aunque un slug con prefijo no pueda infringirlas.
- **El mapeo `cliente ↔ client_slug` vive solo en el plano de control.** `saas.tenants`
  guarda `tenant_id`, `client_name` y `client_slug` (único). Un data plane conoce únicamente
  su propio slug y nunca necesita la tabla. Eso es lo que hace que el esfuerzo valga la pena:
  aunque un contenedor de tenant quede comprometido y liste `pg_database`, lo que ve no
  significa nada. **Corolario: esa tabla pasa a ser el activo sensible del plano de
  control**, porque es lo único que de-anonimiza todo lo demás.
- **Excepción, `PostgresResultStorage`**: su `_TABLE_RE = ^[a-z_][a-z0-9_]*$` **rechaza
  puntos**, así que no se le puede pasar `"t_x.crew_executions"` como colección. Dos
  salidas viables; se elige la segunda por ser menos invasiva:
  (i) añadirle un parámetro `schema` y cualificar DDL/DML internamente; o
  (ii) subclasarlo como `TenantPostgresResultStorage` con un LRU pequeño de conexiones
  `AsyncDB` por tenant, abiertas con `server_settings={'search_path': schema}` en el
  connect. Como usa un DSN dedicado propio (`CREW_RESULT_STORAGE_PG_DSN`) y escribe
  fire-and-forget, ahí no hay pool compartido que contaminar. La columna `tenant` se sigue
  poblando como contraste detectable.
- `TenantProvisioner.provision()` es idempotente: `CREATE SCHEMA IF NOT EXISTS`, rol por
  tenant con `GRANT USAGE` solo sobre su schema y `REVOKE ALL ON SCHEMA public`, migraciones
  versionadas en `<schema>.schema_migrations`, y seed de entitlements. Un console script
  `saas-migrate --all-tenants` itera el registro de tenants.

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

- a. Añadir `unwrap_node_response(value)` a `core/result.py` y llamarlo en **los dos**
  sitios: `flow.py:1734` (`mark_completed(..., response=env["response"], result=env["output"])`)
  y `flow.py:841` (`build_node_metadata(response=<desenvuelto>)`). Un solo helper cubre
  también `CrewAgentNode` y cualquier nodo custom que devuelva el mismo envoltorio. Esto
  restaura `tool_calls`, `model` **y** `usage`, y rellena `FlowContext.responses`.
  **Es el arreglo de mayor valor unitario de todo el plan.**
- b. Dar a `AgentsFlow` una `ExecutionMemory` (misma construcción que `crew.py:232`),
  poblada con un `NodeResult` en cada completación. Es **prerrequisito** de (d) y de la
  persistencia por agente, no un extra.
- c. Añadir `tenant`, `generate_infographic`, `result_agent_name`, `enable_execution_wiki`
  y `execution_wiki_path` al ctor, espejando `AgentCrew`; y `tenant` a `FlowMetadata` para
  que `from_definition` lo recoja.
- d. Extraer `AgentCrew._finalize_infographic` + `build_deterministic_tabs` a un
  `InfographicMixin` en `bots/flows/core/`, compartido por crew y flow, y **dejar de
  tragarse las excepciones en silencio** — que se registren en `dossier.errors`.
- e. Llamar a `_save_result`/`_save_agent_result` (heredados pero nunca invocados),
  estampando `tenant=`.
- f. **No** añadir `SynthesisMixin` a `AgentsFlow`: su docstring dice que la omisión es
  deliberada. El executive summary lo genera el `FlowRunner` del SaaS sobre el `FlowResult`,
  usando el `summary_agent` declarado en el manifiesto del flow o un `ResultAgent` por
  defecto. Mantiene mínima la superficie de cambio en el core.

### 3. Catálogo y entitlements

Bundles versionados en `catalog/flows/<slug>/<semver>/`: `manifest.yaml` (nombre, versión,
descripción, engine, tools requeridas, proveedores requeridos, JSON-Schema de inputs, hints
de precio) + `definition.json` (`CrewDefinition` o `FlowDefinition`). `FlowCatalog` los
carga y publica; el catálogo es global y los **entitlements son por tenant**:
`tenant_entitlements(tenant_id, flow_slug, version_spec, max_runs_month, enabled)`.

La **puerta de admisión** antes de cada run evalúa entitlement + cuota + modo con un
`navrules.RuleSet` — declarativo, y por fin le da a `navrules` un consumidor real.

**Definiciones propias: prohibidas en shared — decidido.** No es una recomendación
revisable: en modo shared el catálogo es la **única** superficie de ejecución. El allowlist
de tools sale siempre del manifiesto del flow publicado, nunca de input del tenant, de modo
que la admisión no tiene que validar definiciones arbitrarias en el camino caliente.
`POST /api/v1/saas/flows` queda hard-gated a `tenant.mode != "shared"` y devuelve 403 con un
motivo legible que apunta al upgrade a enterprise; la comprobación vive en la admisión, no
solo en el handler, para que no exista una segunda vía de entrada.

**Definiciones propias en enterprise:** validadas contra un allowlist de tools derivado del
plan; agentes resueltos vía `AgentRegistry` y tools vía `ToolManager` filtrado por
PBAC/`ExecutionPolicy`.

> Lo que esta decisión **no** resuelve: un flow *del catálogo* también puede llevar tools que
> ejecutan código (pandas agent, sandbox tool). En shared esas siguen teniendo que ir al
> executor docker/qworker. La restricción cierra la superficie de definiciones arbitrarias,
> no el riesgo de vecinos ruidosos (pregunta abierta "vecinos ruidosos en modo shared").

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

**Papel de OTEL y OpenLIT, y qué es la fuente de verdad.** La pila de observabilidad ya
existe y se arranca sola: `ensure_observability_bootstrapped()` lee `ObservabilityConfig`
del entorno en la primera construcción de bot o cliente, y `OBSERVABILITY_OPENLIT=true`
escala `usage_backend` a `otel`, instalando OpenLIT **después** del `TracerProvider` global
para que sus spans aniden como hijos. En modo SaaS se activa con `usage_backend=otel` y
exportador OTLP.

La distinción importa y hay que dejarla escrita: **OpenLIT y los spans GenAI son
observabilidad — diagnóstico, latencias, dashboards — y no son la fuente de verdad de la
factura.** Lo facturable sale de `usage_events`, escrito por `TenantUsageRecorder` desde
`AfterClientCallEvent`, que es un camino durable y transaccional. Un exportador OTLP puede
perder spans bajo presión sin que eso sea un fallo; una factura no puede. Se cruzan como
control (`gen_ai.client.cost.total` frente a la suma de `usage_events`), y una discrepancia
sostenida es una alerta operativa, no un ajuste de facturación.

`capture_prompts`/`capture_completions` quedan en `false` en SaaS: es el único punto por el
que un prompt con una clave pegada podría acabar en un span.

`TenantUsageRecorder(AbstractLogger)` registrado extendiendo `build_recorders_from_config`.
Encola en un `asyncio.Queue` y un flusher de fondo escribe INSERTs multi-fila cada 1 s o
200 filas, honrando el contrato "MUST be cheap and non-blocking" del docstring de
`AbstractLogger` y espejando el patrón del `AuditSubscriber` de navigator-eventbus.

**Cómo llega el `tenant_id` — captura en construcción del evento, no lectura en el
recorder.** Se añaden `current_tenant_id`/`current_run_id` a
`parrot/observability/context.py` (junto a los tres que ya existen) y campos
`tenant_id`/`run_id` a `AfterClientCallEvent`, `ClientRoundEvent` y
`ClientCallFailedEvent`, poblados en `clients/base.py` **en las mismas líneas que ya leen
los otros ContextVars** (`_emit_before_call:482`, `_emit_round_event:561`,
`_emit_after_call:609`); y a `UsageRecord`, poblado en `UsageRecordingSubscriber`.

> Se descartó la alternativa de que el recorder leyera el ContextVar por su cuenta. El
> propio código ya documenta por qué, tres veces, con este comentario literal en
> `clients/base.py:479`, `:558` y `:606`:
> *"FEAT-228: read here (construction time, bot's task context) not at emit time —
> `_emit_*` dispatches fire-and-forget via `emit_nowait` so the ContextVar must be captured
> before the event leaves the calling coroutine."*
> Para cuando corre la corutina del recorder, el contexto puede pertenecer a otra tarea.

**Enmienda del contrato de observabilidad — aprobada, y es entregable de la feature.**
`packages/ai-parrot/src/parrot/observability/README.md` documenta hoy un contrato de PII que
esta feature toca, así que la enmienda es criterio de aceptación de S7, no un apéndice. Debe
decir, explicando el porqué para que un revisor futuro no la revierta con razón:

- `tenant_id` y `run_id` son identificadores de **organización y de correlación**, no de
  usuario final. Permitidos en spans y en `UsageRecord`.
- **Prohibidos como etiquetas de métrica.** La whitelist de labels de
  `observability/subscribers/metrics.py` no se toca: añadirlos dispararía la cardinalidad y
  `run_id` es directamente ilimitado.
- `user_id`/`session_id` mantienen su trato actual — solo spans, descartados del
  `UsageRecord`.

`cumulative_cost_usd` es un total global de proceso y carece de sentido multi-tenant: se
conserva por compatibilidad pero `TenantUsageRecorder` lo ignora y calcula el acumulado por
run desde `run_meters`.

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

Backend: **`CompositeBackend(RedisStreamsBackend, RedisPubSubBackend)`** sobre el Redis
compartido. Streams (durable, consumer groups, dedup, retention) para lo que no se puede
perder — `saas.run.completed`, `saas.usage.recorded`, `saas.billing.*` y la entrada del
dispatcher de webhooks. Pub/Sub para el tráfico alto y desechable de UI
(`saas.run.node.*`, `saas.run.progress`), para que un cliente SSE lento no engorde un
stream. Prefijo de canal `parrot:saas:`, distinto del `parrot:events:` que ya usa
`orchestrator.py:245`, para poder separar políticas de retención.

`saas.usage.recorded` se emite **agregado (~1/s por run), no por llamada LLM**. Los payloads
llevan metadatos y referencias — nunca cuerpos de dossier ni contenido de tools. El
`tenant_id` viaja **en el payload, no en el topic** (el registro de TOPICS se mantiene
limpio), pero se usa `stream_key_fn` para shardear streams por tenant de cara a retención.

`GET /api/v1/saas/runs/{run_id}/events` (SSE/WS): autentica por el middleware SaaS,
**verifica en `run_meters` que el `run_id` pertenece al tenant — nunca se confía en el
path**, y se suscribe a `saas.run.*` con `filter_fn`. Al conectar drena primero el Redis
Stream de ese run desde `0-0` para que un cliente que reconecta no pierda eventos, y luego
pasa a vivo. Heartbeat cada 15 s. Reutiliza los helpers de framing SSE de
`handlers/stream.py` pero **no `StreamHandler`** — ese se auto-excluye de nav-auth.

`WebhookDispatcher`: consumer group durable sobre el stream de `saas.run.completed|failed`,
para que un reinicio no pierda entregas.
- Firma HMAC-SHA256 `X-Parrot-Signature: t=<ts>,v1=<hex>` sobre `f"{ts}.{body}"` (esquema
  Stripe), más `X-Parrot-Event-Id` y `X-Parrot-Delivery-Attempt`; ventana de replay 5 min;
  secreto por endpoint cifrado con `encrypt_credential`; dos secretos activos durante
  rotación.
- Reintentos: 8 intentos con backoff exponencial y jitter (1 s → ~6 h), solo en
  5xx/timeout/429; el resto de 4xx son terminales.
- **Guardia SSRF**: la URL la controla el tenant. Resolver DNS y rechazar RFC1918,
  link-local y direcciones de metadatos; exigir https en producción.
- Agotados los intentos → `saas.webhook.dead` + DLQ (`navigator.evb_dlq` ya existe) y
  `POST /api/v1/saas/webhooks/{id}/redeliver`.

La misma implementación de firma HMAC sirve para los webhooks salientes y para el
phone-home del data plane — una implementación, dos usos.

### 7. Provisioning enterprise

**Split control plane / data plane.** El plano de control compartido es dueño del registro
de tenants, las API keys, el catálogo, los entitlements y la facturación. Las instancias
enterprise son planos de datos que **llaman a casa**: se autentican con una credencial de
instancia y empujan `usage_events` + `run_records` a `POST /api/v1/saas/ingest`, y bajan
entitlements/catálogo periódicamente. La facturación no puede depender de la máquina del
cliente, y la máquina del cliente debe seguir funcionando si el control plane cae (cola
local + replay).

Trabajo Pulumi necesario:

1. **Arreglar `config_values`** en `parrot_tools/pulumi/executor.py`: un
   `pulumi config set-all --stack <s> --plaintext k=v ... --secret k=v ...` antes de
   `preview`/`up`. `toolkit.py:124,184` ya lo pasan hacia abajo; solo falta el executor. Con
   un parámetro `secret_keys: set[str]` para que passwords de DB y tokens de enrolamiento
   queden cifrados en el stack config y no en claro.
2. **Honrar `state_backend`**: `_ensure_login()` con `pulumi login <backend>` antes de
   cualquier comando. **Backend S3** (`s3://.../<env>`) con la passphrase desde el vault —
   evita depender de Pulumi Cloud y reutiliza las credenciales AWS que ya trae
   `BaseExecutorConfig`. `PULUMI_CONFIG_PASSPHRASE` ya está cableado.
3. **Escribir el programa**: uno solo, parametrizado, en
   `packages/ai-parrot-saas/src/parrot_saas/provisioning/pulumi_programs/enterprise_flows/`,
   en Pulumi **Python** (no YAML, para reutilizar config pydantic), stack por tenant
   (`enterprise-<slug>`). Recursos: servicio **ECS Fargate** + task def, ALB + ACM +
   Route53, security groups, log group, Secrets Manager, y `postgresql.Database` + rol
   **sobre la instancia RDS compartida**. Sin Redis. Outputs:
   `{endpointUrl, serviceArn, dbName, taskRoleArn}`.
   *Fargate y no EKS*: no hay manifiestos k8s ni Helm en el repo y `KubernetesToolkit` solo
   hace `k8s_apply_manifest`; levantar EKS para un proceso aiohttp de larga vida es mucho
   más trabajo sin beneficio proporcional.

   **Endurecimiento del aislamiento lógico — criterio de aceptación de S11, no prosa.**
   Al haberse decidido cluster compartido, esto es lo único que separa a un tenant de otro,
   así que el programa debe emitirlo y el test negativo debe comprobarlo:
   - `REVOKE CONNECT ON DATABASE <db> FROM PUBLIC` en **cada** base provisionada. Es el
     default que muerde: sin esto, cualquier rol capaz de autenticarse contra el cluster
     puede conectarse a la base recién creada, porque las bases nuevas heredan el `CONNECT`
     de `PUBLIC` desde `template1`.
   - Rol por base, con `CONNECT` revocado en las demás.
   - Reglas `pg_hba` por (rol, base, CIDR de origen).
   - Rol de provisioning con `CREATEDB`, **separado del rol de aplicación**, y ningún DSN de
     superusuario en ningún data plane.
   - `ALTER ROLE ... CONNECTION LIMIT n` y `ALTER ROLE ... SET statement_timeout` por
     tenant: baratos, y acotan al vecino ruidoso en el propio motor.
   - **Nombre de base = `client_slug`**, según la regla de naming de §2 (slug aleatorio de
     CSPRNG, jamás la razón social ni nada derivado de ella). El motivo vive aquí:
     `pg_database` es un catálogo compartido legible por cualquier rol autenticado, así que
     todo tenant puede **listar los nombres de todas las bases** aunque no pueda conectarse
     a ellas. Con nombres de cliente, eso filtra la cartera comercial a cualquier cliente.
   - **El slug debe llegar a todo lo que nombra recursos**, no solo a la base. Si el stack de
     Pulumi, los tags de AWS, los log groups o los nombres de recursos siguen llevando la
     razón social, el nombre reaparece en el bucket de estado y en la consola cloud y la
     opacidad no sirve de nada. El `enterprise-<slug>` del punto 3 es ese mismo `client_slug`.
     *Excepción deliberada*: el **hostname de cara al cliente sí puede ser legible** — el
     cliente espera su propio dominio y solo él lo ve. La opacidad protege frente a *otros*
     tenants y frente a los catálogos compartidos, no frente al dueño del dato.
   - **Prohibido `COMMENT ON DATABASE` con el nombre del cliente.** Es el atajo que alguien
     añadirá con buena intención para facilitar la operación, y **deshace la decisión
     entera**: los comentarios de objetos compartidos son legibles con `shobj_description()`
     por cualquier rol autenticado.
   - **Coste operativo, y cómo se paga**: con nombres aleatorios, quien esté de guardia
     mirando `pg_stat_activity` o un log de queries lentas ya no sabe de quién es lo que ve.
     Se compensa con una vía de resolución `slug → cliente` en el plano de control, y con
     `tenant_id` presente en logs y trazas de la aplicación — la correlación se hace en la
     capa que ya lo tiene, sin bajar el nombre del cliente a la capa de datos.
   - **Fijar y documentar la versión del servidor**: dos defaults dependen de ella — el
     `CREATE` de `PUBLIC` sobre el esquema `public` (retirado en PG 15) y el agujero
     histórico de `CREATEROLE`, que permitía a ese rol concederse pertenencia a otros roles
     no-superusuario (endurecido en PG 16).

   **Lo que el aislamiento lógico no cubre**, a documentar para no sobrevenderlo:
   - **El PITR es de cluster completo.** Restaurar un tenant a un punto en el tiempo exige
     dumps lógicos por base; hay que decidir el SLA de recuperación por tenant **antes** de
     venderlo.
   - **Recursos compartidos** (`max_connections`, WAL, autovacuum): acotados por los límites
     por rol de arriba, no eliminados.
4. **`StackManager`** (`provisioning/stack.py`): envoltorio fino y **no agéntico** que llama
   a `PulumiExecutor` directamente. Un LLM no debe conducir `pulumi up` en provisioning —
   `PulumiToolkit` existe para uso agéntico, el plano de control no pasa por ahí. Nombrado
   determinista de stacks, ensamblado de config desde el registro `Tenant`,
   `up`/`destroy`/`refresh`, parseo de outputs a `saas.tenant_stacks`, y lock en Redis que
   serializa operaciones por tenant. Corre en el `BackgroundQueue`/`JobManager` existente,
   nunca en un handler HTTP — `pulumi up` tarda minutos. La aprobación humana usa el sistema
   de grants acotados existente (`tool:pulumi_apply` es literalmente el ejemplo canónico en
   `parrot/auth/grants.py:53`).

**Enrolamiento y degradación:** el provisioning escribe un `enrollmentToken` de un solo uso
en el stack config → env del contenedor. Al arrancar, el data plane hace `POST
/api/v1/saas/internal/enroll` y recibe `{tenant_id, api_key, plan, entitlements,
catalog_sync_url}`. Después baja deltas de catálogo/entitlements cada 60 s y empuja uso
batcheado cada 60 s con clave de idempotencia. **Si el control plane no responde, el data
plane sigue sirviendo** con los últimos entitlements conocidos durante
`SAAS_OFFLINE_GRACE` (72 h), bufferizando uso localmente, y solo entonces rechaza runs
nuevos. Nunca se tumba a un cliente enterprise porque nuestro control plane parpadee.

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
- `S3a agentsflow-result-fidelity` — solo `unwrap_node_response()` y los dos sitios de
  llamada. **El arreglo de mayor valor unitario del plan y el más barato**; independiente,
  puede ir en paralelo desde el día 1.
- `S3b agentsflow-parity` — `ExecutionMemory`, args de ctor, `InfographicMixin`,
  persistencia por agente [dep: S3a]
- `S4 research-dossier` [dep: S2, S3b]

**Fase 3 — Plano comercial**
- `S5 flow-catalog-and-entitlements` [dep: S1] — incluye el gate de
  `POST /api/v1/saas/flows` a `mode != shared`
- `S6 byok-llm-credentials` [dep: S1]
- `S7 usage-metering-store` [dep: S1] — **incluye la enmienda de
  `observability/README.md` como criterio de aceptación**

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
- `S15 custom-definitions-sandbox` — **enterprise-only, fuera del camino crítico**
  [dep: S5, S11]. Validación estática de definiciones, `ExecutionPolicy` enrutada al
  executor docker/qworker, PBAC por tool. Al quedar prohibidas las definiciones propias en
  shared, esta feature **ya no bloquea nada del modo compartido** y puede llegar cuando haya
  demanda enterprise real.

---

## Verificación

- **S0**: test de integración que golpea cada ruta antes-abierta sin credenciales y espera
  401/403; test que envía `tenant` en el body y verifica que se ignora.
- **S1/S2**: dos tenants, mismo flow, misma tabla — el tenant A no ve filas de B. Test de
  inyección con slugs maliciosos (`../`, `public`, `pg_catalog`).
- **S3a**: regresión que corre el mismo grafo como `AgentCrew` y como `AgentsFlow` y afirma
  que `FlowResult.nodes[].tool_calls`, `.usage` y `.model` son **no vacíos e iguales** en
  ambos, y que `FlowContext.responses` está poblado. Este test hoy falla en los tres campos.
- **S4**: `ResearchDossier` round-trip, incluyendo un tool result >32 KiB que debe salir por
  `result_ref` y resolverse de vuelta.
- **S5**: un tenant en modo shared **no puede registrar ni ejecutar** una definición fuera
  del catálogo — `POST /api/v1/saas/flows` devuelve 403, y un intento de run con una
  definición inline es rechazado en la admisión, no solo en el handler.
- **S6**: test de fuga — correr un flow con una clave BYOK conocida y hacer grep del log
  completo, de los spans OTEL y de las filas de DB buscando el secreto; debe aparecer solo
  el fingerprint.
- **S7**: un run con N llamadas LLM debe producir N `usage_events` con el `tenant_id`
  correcto y un `cost_usd` que cuadre con `CostCalculator`. Test específico de
  **concurrencia**: dos runs de tenants distintos solapados en el tiempo no deben mezclar
  atribución (es exactamente el fallo que evita capturar el ContextVar en construcción).
  Y un test de que `RunUsage` del dossier cuadra con el store de metering — ojo, sin S3a ese
  contraste siempre discrepa, porque el `usage` del lado AgentsFlow viene vacío.
- **S8/S9**: end-to-end contra el servidor real — `POST /api/v1/saas/runs` de un flow del
  catálogo, seguir el SSE hasta `saas.run.completed`, `GET` del dossier, abrir la URL
  firmada de la infografía, y comprobar la entrega del webhook con firma HMAC válida.
- **S10/S11**: `pulumi preview` contra el programa del data-plane con `config_values`
  distintos por tenant, verificando que **llegan** al stack (hoy no llegan).
- **S11 — test negativo de aislamiento**, el que sostiene la decisión de cluster compartido:
  el rol del tenant A **no puede conectarse** a la base del tenant B, y `PUBLIC` no tiene
  `CONNECT` sobre ninguna base provisionada. Sin este test, el aislamiento descansa en que
  nadie se equivoque escribiendo un `GRANT`.
- **S11 — opacidad del naming**: dos tenants provisionados no comparten `client_slug`; **dos
  altas con el mismo nombre de cliente producen slugs distintos** (es lo que demuestra que el
  slug no se deriva); y ni el nombre de base, ni el de schema, ni el del stack, ni el del log
  group contienen la razón social.

Global: `pytest` en cada paquete tocado tras cualquier cambio de lógica, y un smoke de dos
tenants concurrentes ejecutando el mismo flow del catálogo con claves BYOK distintas.

---

## Feature Description

### User-Facing Behavior

El cliente obtiene un **tenant** y una o más **API keys**. Con ellas lanza un flow del
catálogo (`POST /api/v1/saas/runs`) y recibe un `run_id` inmediato. Puede seguir la ejecución
en vivo por SSE/WS, recibir un webhook firmado al terminar, y descargar el **dossier
completo** — contenido de cada tool por agente, resultado de cada agente, executive summary e
infografía — vía REST y URLs firmadas. Los humanos del tenant entran por navigator-auth
(ABAC/PBAC) al portal; las máquinas por API key.

En modo shared solo ejecuta flows del catálogo. En enterprise puede además registrar sus
propias definiciones. Aporta sus claves LLM (BYOK), salvo en el modo enterprise-managed,
donde las ponemos nosotros y se le factura el consumo.

Desarrollo completo en §1–§7 de "Diseño recomendado".

### Internal Behavior

Una petición atraviesa: `tenant_middleware` (resuelve principal → `TenantContext`, lo deposita
en `request`, en un ContextVar y en `_pctx_var`) → **admisión** (entitlement + cuota +
presencia de clave BYOK, evaluada con `navrules`) → `RunService`, que construye el crew/flow
desde la definición del catálogo inyectando la clave del tenant en `LLMFactory.create()` →
ejecución → `DossierBuilder` ensambla el `ResearchDossier` desde el `FlowResult` → persistencia
en el schema del tenant con offload a object storage por encima del umbral → emisión de
eventos `saas.*` que alimentan SSE y webhooks → `TenantUsageRecorder` escribe `usage_events`
en el plano de control.

### Edge Cases & Error Handling

- **Sin clave BYOK válida**: 402 con cuerpo con forma `NeedsAuth`. Nunca se cae al pool de
  plataforma en modo shared — eso sería cargarnos un coste silenciosamente.
- **Cuota o presupuesto agotado**: rechazo en admisión (402/429 con `reason` legible), o corte
  en caliente vía `BudgetGuard` si se supera durante el run. El corte deja un `FlowResult`
  parcial que se persiste con `status=budget_exceeded`, no se descarta.
- **Fallo de un nodo**: `FlowResult` ya modela `partial`/`failed` y `errors` por nodo; el
  dossier los propaga en `errors` en vez de perderlos.
- **Infografía fallida**: hoy `AgentCrew._finalize_infographic` se traga toda excepción y deja
  `infographic=None`. El diseño exige registrarla en `dossier.errors` (§2.d).
- **Tool result gigante**: por encima de `SAAS_TOOL_MAX_BYTES` se trunca marcando
  `truncated=True` y guardando el sha256 del cuerpo completo.
- **Control plane caído** (enterprise): el data plane sigue sirviendo con los últimos
  entitlements durante `SAAS_OFFLINE_GRACE` (72 h), bufferizando uso, y solo entonces rechaza
  runs nuevos.
- **Webhook a URL del tenant**: guardia SSRF obligatoria (§6).

---

## Capabilities

### New Capabilities

- `saas-auth-hardening`: cerrar las rutas de crew sin autenticar y dejar de derivar el tenant
  del body. **Prerrequisito duro de todo lo demás.**
- `tenant-context-and-middleware`: `TenantContext`, resolución de tenant, API keys de tenant.
- `tenant-schema-provisioning`: `client_slug` aleatorio, `CREATE SCHEMA`, migraciones,
  nombres cualificados.
- `agentsflow-result-fidelity`: `unwrap_node_response()` en los dos sitios de llamada.
- `agentsflow-parity`: `ExecutionMemory`, args de ctor, `InfographicMixin`, persistencia.
- `research-dossier`: modelo, builder, store, redacción, umbral inline/offload.
- `flow-catalog-and-entitlements`: bundles versionados, `FlowCatalog`, gate de shared.
- `byok-llm-credentials`: vault por tenant, resolver, inyección, validación en alta.
- `usage-metering-store`: `usage_events`, `TenantUsageRecorder`, `BudgetGuard`, enmienda del
  contrato de PII de observabilidad.
- `run-service-and-api`, `run-streaming-and-webhooks`, `pulumi-config-and-state`,
  `tenant-dataplane-provisioning`, `control-plane-ingest`, `managed-key-pool-and-rating`,
  `custom-definitions-sandbox`, `tenant-portal`.

Correspondencia y dependencias en "Plan de features".

### Modified Capabilities

- `granular-permission-system` / `botmanager-pbac-permissions`: el `EvalContext` pasa a llevar
  `tenant`, y `setup_pbac` deja de fallar abierto bajo `PARROT_SAAS_MODE`.
- `formregistry-multi-tenancy`: `_identifiers.py` se promueve al core y formdesigner pasa a
  importarlo de ahí.

---

## Impact & Integration

| Componente afectado | Tipo de impacto | Notas |
|---|---|---|
| `packages/ai-parrot-saas` | nuevo | Plano de control; extras `[control]`/`[dataplane]` |
| `parrot/bots/flows/flow/flow.py` | modifica | Fidelidad del resultado + tenant + persistencia |
| `parrot/bots/flows/core/result.py` | extiende | `unwrap_node_response()` |
| `parrot/bots/flows/core/storage/backends/postgres.py` | modifica | Schema por tenant |
| `parrot/observability/{context,recorders}` + `clients/base.py` | extiende | `tenant_id`/`run_id`; **enmienda el contrato de PII documentado** |
| `parrot/auth/{pbac,eval_context}` | modifica | Fail-closed + `tenant` en contexto |
| `parrot_tools/pulumi/executor.py` | corrige | `config_values` y `pulumi login` |
| `handlers/crew/*`, `handlers/stream.py`, `app.py` | modifica | **Cambio de seguridad**: rutas hoy abiertas se cierran |
| `parrot_formdesigner/services/_identifiers.py` | mueve | Al core, import redirigido |
| `navigator-eventbus/TOPICS.md` | extiende | Namespace `saas.*` |

**Breaking changes**: cerrar `/api/v1/crew*` y `/bots/*/stream/*` rompe a cualquier consumidor
que hoy dependa de que estén abiertos. Es intencionado y es el prerrequisito de la venta.

**Nuevas dependencias**: Argon2 (hash de API keys), provider `postgresql` de Pulumi. Sin Redis
ni Postgres adicionales.

---

## Code Context

### User-Provided Code

Ninguno. Los requisitos se dieron en prosa; todas las referencias de abajo salen de
investigación sobre el repo.

### Verified Codebase References

#### Classes & Signatures

```python
# From parrot/bots/flows/core/node.py:310 — el envoltorio que rompe la fidelidad
return {"response": response, "output": output,
        "execution_time": end_time - start_time, "prompt": prompt}

# From parrot/bots/flows/core/result.py:619
def build_node_metadata(node_id, agent, response, output,
                        execution_time, status, error=None) -> NodeExecutionInfo: ...

# From parrot/models/basic.py:23 — el contenido real de cada tool
class ToolCall(BaseModel):
    id: str; name: str; arguments: Dict[str, Any]
    result: Optional[Any] = None; error: Optional[str] = None
    execution_time: Optional[float] = None

# From parrot/auth/broker.py:297 — patrón BYOK a extender
async def store_key(self, user_id: str, api_key: str) -> None: ...

# From parrot/storage/artifacts.py:177 — lanza ValueError si el artefacto es inline
async def get_public_url(self, user_id, agent_id, session_id, artifact_id,
                         *, format="html") -> str: ...
```

#### Verified Imports

```python
from parrot.models.basic import ToolCall, CompletionUsage      # parrot/models/basic.py:23,48
from parrot.bots.flows.core.result import build_node_metadata  # core/result.py:619
from parrot.auth.credentials import CredentialResolver, ResolvedCredential, NeedsAuth
from parrot.security.vault_utils import store_vault_credential, retrieve_vault_credential
from parrot.observability.cost.calculator import CostCalculator
from navigator_eventbus import EventBus, EventEnvelope, CompositeBackend
```

#### Key Attributes & Constants

- `PostgresResultStorage._TABLE_RE` → `^[a-z_][a-z0-9_]*$` — **rechaza puntos**
  (`core/storage/backends/postgres.py:19`)
- `PARROT_SCHEMA` → constante estática (`parrot/conf.py:103`)
- `CREW_RESULT_STORAGE` → por defecto `documentdb`, **no** postgres (`parrot/conf.py:309`)
- `FlowResult.infographic` → `Optional[InfographicRenderResult]` (`core/result.py`)
- ContextVars leídos **en construcción del evento**, no al emitir
  (`clients/base.py:479`, `:558`, `:606`)

### Does NOT Exist (Anti-Hallucination)

- ~~Cualquier programa Pulumi~~ — solo existe el fixture de test
  `packages/ai-parrot/tests/fixtures/pulumi_docker_project/`
- ~~`pulumi config set` en el executor~~ — `config_values` se acepta y se **descarta**
- ~~Uso de `PulumiConfig.state_backend`~~ — declarado, nunca leído; no hay `pulumi login`
- ~~Clase `RateLimiter`~~ — `a2a/security.py:1444` es un hook que siempre vale `None`
- ~~Store durable de uso~~ — `cumulative_cost_usd` es in-memory por proceso
- ~~`tenant_id` en `UsageRecord` o en `AfterClientCallEvent`~~ — no existen hoy
- ~~Resolver de credenciales LLM~~ — no hay ninguno para proveedores LLM
- ~~Middleware de tenant / construcción de `UserSession` desde HTTP~~ — `UserSession.tenant_id`
  está declarado en `parrot/auth/permission.py:20` pero **nunca se construye** desde request
- ~~Instanciación de `RlsRegistry`, `DataPlanePolicyGuard`, `DatasetPolicyGuard`~~ —
  implementados, cero construcciones en `src/`
- ~~Consumidores de `navrules`~~ — cero imports fuera de su propio paquete
- ~~`ExecutionMemory` en `AgentsFlow`~~ — cero referencias en `flow.py` (60 en `crew.py`)
- ~~Endpoint HTTP genérico para ejecutar un `AgentsFlow`~~ — solo existe la superficie de
  checkpoints
- ~~`tenant` en `FlowDefinition`~~ — existe en `CrewDefinition`, no en `FlowDefinition`

---

## Parallelism Assessment

- **Internal parallelism**: alto. `S3a`/`S3b` (fidelidad y paridad de `AgentsFlow`) tocan solo
  `parrot/bots/flows/` y no dependen de la tenencia, así que van en paralelo desde el día 1.
  `S10` (Pulumi) es independiente de todo. `S5`/`S6`/`S7` son disjuntos entre sí una vez está
  `S1`.
- **Cross-feature independence**: el riesgo de colisión está en tres ficheros compartidos —
  `app.py` (orden de middleware), `handlers/crew/*` (los toca `S0`) y `clients/base.py` (lo
  toca `S7`). `S0` debe cerrar antes de que nadie más entre en `handlers/crew/*`.
- **Recommended isolation**: per-spec.
- **Rationale**: el grueso del trabajo vive en un paquete nuevo (`ai-parrot-saas`) que nadie
  más toca, y los cambios en core son quirúrgicos y localizados. Un worktree por feature evita
  el único choque real, que es el de los tres ficheros compartidos.

---

## Decisiones cerradas

- **Definiciones de flow propias del cliente: prohibidas en modo shared.** El catálogo es la
  única superficie de ejecución en shared; las definiciones propias son exclusivas de
  enterprise. Saca a `S15 custom-definitions-sandbox` del camino crítico.
- **Enmienda del contrato de PII de observabilidad: aprobada.** `tenant_id`/`run_id` entran
  en spans y `UsageRecord`, nunca en etiquetas de métrica, y
  `observability/README.md` se actualiza como parte de S7.
- **Aislamiento lógico sobre el Postgres compartido, no instancias dedicadas.** Enterprise
  va a ser poco frecuente al principio; el coste de una instancia por tenant no está
  justificado todavía. Todos los tenants enterprise comparten cluster, con base de datos
  propia y aislamiento impuesto por roles y `pg_hba`.

  La contrapartida hay que asumirla con los ojos abiertos: **lo único que separa a un tenant
  de otro es la corrección de esa configuración**. Por eso el endurecimiento de §7 deja de
  ser buena práctica y pasa a ser criterio de aceptación verificable de S11, con un test
  negativo que lo demuestre.

  **Naming**: schemas y bases se nombran con un `client_slug` **aleatorio** (CSPRNG), unido
  al cliente por una relación `cliente ↔ client_slug` que solo existe en el plano de control.
  Regla completa en §2; el slug se propaga también a stacks, tags y log groups.

  **Disparadores para revisar la decisión** — para que no caduque en silencio: un cliente
  regulado que exija instancia dedicada por contrato; un tenant cuyo consumo degrade de
  forma medible al resto; o el punto en que el volumen enterprise haga que el coste deje de
  ser el factor dominante. La vía de escape es barata y no toca el diseño: mover un tenant a
  instancia dedicada es **cambiar el DSN que recibe su data plane**. Eso es justamente lo
  que hace defendible empezar por lo compartido.

## Open Questions

> Convención consumida por `/sdd-spec`: `[ ]` sin resolver, `[x]` resuelta con la respuesta
> tras el último `:`. Las resueltas se desarrollan en "Decisiones cerradas".

- [ ] `ArtifactStore` no tiene dimensión de tenant y su URL firmada no está autenticada:
  partición `(user_id, agent_id, session_id)`, firma sigv4 de hasta 7 días, autorización solo
  por firma. Hay que meter el tenant en la clave y en el payload de la firma, y acortar el
  TTL. Además `get_public_url()` lanza `ValueError` para artefactos inline, así que el dossier
  y la infografía deben escribirse con offload forzado si queremos URL firmada siempre.
  — *Owner: Platform Eng*
- [ ] `PostgresResultStorage` usa `CREW_RESULT_STORAGE_PG_DSN`, una conexión distinta de
  `app['database']`, y se traga todos los errores de `save()` en un `logger.warning`. En un
  producto facturable, un registro de ejecución perdido en silencio es un ticket de soporte.
  ¿Hacemos que la escritura del dossier sea la autoritativa y transaccional con el estado del
  run, dejando `crew_executions` como telemetría best-effort? — *Owner: Platform Eng*
- [ ] `CREW_RESULT_STORAGE` por defecto es `documentdb`, no postgres (`conf.py:309`). Toda la
  historia de schema-per-tenant asume postgres: hay que confirmar que el despliegue compartido
  fija `CREW_RESULT_STORAGE=postgres`, o los datos de todos los tenants acaban en una colección
  DocumentDB compartida distinguida solo por un campo `tenant`. — *Owner: Platform Eng*
- [ ] Vecinos ruidosos en modo shared: un solo proceso aiohttp sirviendo los flows de todos los
  tenants. Hay caps de concurrencia por tenant, pero no aislamiento de CPU/memoria: una tool de
  pandas o de código puede bloquear el event loop. En shared, todo lo que ejecute código
  debería ir al executor docker/qworker. — *Owner: Platform Eng*
- [ ] Frescura de las tablas de precios (avisan a los 90 días): facturar claves gestionadas con
  precios rancios es riesgo de ingresos. Necesita un proceso de refresco y reconciliación
  mensual contra la factura real del proveedor. — *Owner: Platform Eng + Finance*
- [ ] Límite de escala del schema-per-tenant: Postgres se degrada con miles de schemas (bloat
  de catálogo, coste de `pg_dump`). Bien para cientos; hay que marcar la ruta de migración
  (tablas particionadas por tenant + RLS, con `RlsRegistry` que ya existe sin usar) antes de
  pasar de ~1–2k tenants. — *Owner: Platform Eng*
- [ ] SLA de recuperación por tenant: el PITR es de cluster completo, así que restaurar un
  tenant a un punto en el tiempo exige dumps lógicos por base. Hay que fijar el SLA antes de
  venderlo. — *Owner: Platform Eng*

Resueltas:

- [x] ¿El tercer modo (claves LLM nuestras) entra desde v1 o se pospone? — *Owner: phenobarbital*:
  desde v1. El punto de captura de uso es el mismo en los tres modos, así que diseñarlo después
  obligaría a un retrofit.
- [x] ¿Se permiten definiciones de flow propias del cliente en modo shared? — *Owner: phenobarbital*:
  no. El catálogo es la única superficie de ejecución en shared; las definiciones propias son
  exclusivas de enterprise.
- [x] ¿Se puede enmendar el contrato de PII de observabilidad para añadir `tenant_id`/`run_id`?
  — *Owner: phenobarbital*: sí, documentándolo en `observability/README.md` como criterio de
  aceptación de la feature de metering.
- [x] ¿Instancias Postgres dedicadas por tenant enterprise, o cluster compartido? — *Owner: phenobarbital*:
  cluster compartido con aislamiento lógico. Enterprise será poco frecuente al principio y el
  coste de instancias dedicadas no está justificado; con disparadores de revisión definidos.
- [x] ¿Cómo se nombran schemas y bases de datos? — *Owner: phenobarbital*: con un `client_slug`
  aleatorio de CSPRNG, unido al cliente por una relación `cliente ↔ client_slug` que solo existe
  en el plano de control.

---

## Next Steps

1. `/sdd-spec saas-auth-hardening` (S0) — es el bloqueante duro; nada de lo demás es
   vendible hasta que esté cerrado.
2. `/sdd-spec agentsflow-result-fidelity` (S3a) en paralelo — no depende de nada, es un
   helper más dos líneas de llamada, y desbloquea a la vez el dossier y la facturación.
3. Al especificar S7, incluir la enmienda de `observability/README.md` como criterio de
   aceptación (decisión ya cerrada, no un pendiente).
4. Al especificar S5, incluir el gate de shared y su test de rechazo.

**Camino crítico: S0 → S3a/S3b → S1/S2 → S4 → S8.** Todo lo demás cuelga de esa espina.
