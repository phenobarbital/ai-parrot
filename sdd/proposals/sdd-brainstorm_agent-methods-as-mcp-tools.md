---
feature_id: FEAT-XXX            # asignar al crear sdd/state/<FEAT-ID>/
title: Agent Methods as MCP Tools
stage: brainstorm
status: draft
owner: jesuslarag
created: 2026-08-30
depends_on:
  - navigator-auth OAuth 2.1 Authorization Server (S1)
  - HttpMCPServer Streamable HTTP conformance (S2, parcial)
related:
  - ai-parrot-integrations multi-agent mount
  - FEAT: HITL suspend/resume (SuspendedExecutionStore)
  - Handle-only execution design (claude_handle-only-execution-design.md)
next_stage: /sdd-proposal (bloqueado por S1)
---

# Agent Methods as MCP Tools

## 1. Problema

Un agente de ai-parrot (`AbstractBot`/`BasicAgent`) encapsula toolsets, KBs y flows
corporativos que hoy solo se consumen desde la API HTTP propia o desde otros agentes.
Se quiere que usuarios autorizados consuman ese trabajo desde Claude Web (y Claude
Code/Desktop/API) vía MCP, con identidad individual y PBAC determinista.

La exposición de tools sueltas vía MCP ya existe. Este feature cubre lo que falta:
**métodos decorados de un agente publicados como MCP tools**, autenticación OAuth 2.1
por usuario, y enforcement PBAC en el servidor MCP.

## 2. Qué NO es (non-goals)

- **No es Agents-as-Tool.** No envuelve un agente como tool de otro agente (eso ya
  existe con ese nombre). No exponer `ask`/`ask_stream` como MCP tool en v1.
- No reimplementa la exposición de `AbstractTool`/toolkits vía MCP (ya existe).
- No hay inferencia de schema desde la signature en v1 (D1).
- No hay memoria conversacional compartida entre llamadas MCP (D5).
- No soporta transporte SSE legacy ni stdio para Claude Web.
- No hay client_credentials (M2M): Claude Web exige authorization_code interactivo.
- No hay `static_headers` (beta, org-level) como camino primario: pierde identidad.

## 3. Codebase Contract

Anclas por grep, nunca líneas. Todo lo marcado ⚠️ VERIFY se confirmó en chats
anteriores pero no contra el árbol actual; validar antes del proposal.

| Ancla | Paquete/módulo esperado | Estado |
|---|---|---|
| `class MCPToolAdapter` | ai-parrot MCP server | existe ⚠️ VERIFY ruta |
| `class HttpMCPServer` (aiohttp, registra rutas en app existente) | ai-parrot MCP server | existe ⚠️ VERIFY Streamable HTTP: endpoint único, POST JSON-RPC, `Mcp-Session-Id` |
| `create_http_mcp_server` / `create_stdio_mcp_server` | ai-parrot MCP server | existe |
| `allowed_tools` / `blocked_tools` | filtros del server MCP | existe; reutilizar como capa previa al PBAC |
| `class AbstractBot`, `class BasicAgent` | `parrot.bots` | existe ⚠️ VERIFY módulo |
| `class AgentRegistry` (decorator-registered) | `parrot` | existe |
| `class ToolManager` (per-session) | `parrot.tools` | existe |
| `class EpisodicMemoryStore` | `parrot.memory` ⚠️ VERIFY | existe |
| `class AuditLedger`, `key_fingerprint` | `parrot` ⚠️ VERIFY | existe |
| Multi-agent mount en un server | `ai-parrot-integrations` ⚠️ VERIFY nombre de clase | existe; D2 lo extiende |
| navigator-auth PBAC (`enforcing: false`, glob/regex en `resources`) | `phenobarbital/navigator-auth` | existe |
| Google login → alta automática de cuenta | navigator-auth | casi listo (según owner) |

**Explícitamente NO existe hoy:**
- Decorador `@mcp_tool` ni registro de métodos exponibles por agente.
- Adaptador método→MCP tool (`AgentMethodAdapter`).
- OAuth 2.1 AS (DCR, PKCE, `/token`, refresh rotado) en navigator-auth.
- `resolve_principal(bearer)` que unifique OAuth access tokens y API keys.
- Enforcement PBAC dentro del server MCP (`tools/list` y `tools/call`).
- Tabla de activación manual de usuarios para MCP.

## 4. Hechos externos (Claude como cliente MCP) — verificados 2026-08

Fuente: claude.com/docs/connectors/building/authentication, support.claude.com,
guías de terceros con fecha 2026-07/08.

- **Auth:** custom connectors de claude.ai solo hablan OAuth 2.1
  (authorization_code + PKCE, bearer tokens). Soportan DCR (RFC 7591) y también
  client ID/secret estático por organización. No hay campo para API key por
  usuario. `static_headers` existe en beta pero es configuración de administrador.
- **Endpoints requeridos:** `/.well-known/oauth-protected-resource` (RFC 9728),
  `/.well-known/oauth-authorization-server` (RFC 8414), `/register` (JSON),
  `/authorize`, `/token` (`application/x-www-form-urlencoded`; JSON-only ⇒ 415).
  Claude espera ≤10 s en discovery/registration/token, ≤30 s en refresh.
- **Refresh:** clientes públicos (DCR) exigen rotación de refresh token; el nuevo
  se devuelve en la misma respuesta que invalida el anterior.
- **Callback:** `https://claude.ai/api/mcp/auth_callback` (posible migración a
  `claude.com`; allowlistear ambos). Client name: `Claude`.
- **Transporte:** Streamable HTTP. SSE en deprecación / no soportado por la infra
  de conectores.
- **Red:** el servicio de conectores sale desde infraestructura de Anthropic incluso
  para Claude Desktop → la URL debe ser globalmente enrutable (no VPN). Hay rango
  de egreso publicado para allowlist.
- **Timeout tool call:** 300 s en Claude.ai/Desktop. Progress notifications no lo
  extienden (documentado para Claude Code; asumir igual en Web).
- **Tamaño de respuesta:** ~30.000 tokens por respuesta de custom connector.
- **Estado:** la revisión moderna del protocolo no ofrece estado de sesión HTTP;
  no depender de `Mcp-Session-Id` para nada durable.
- **`tools/list`:** Claude lee la superficie de tools en cada conexión. Soporte de
  `notifications/tools/list_changed` confirmado en Claude Code; no confirmado en
  Web (OQ4).

## 5. Decisiones

| ID | Decisión | Alternativa descartada | Razón |
|---|---|---|---|
| D1 | `@mcp_tool(name, args_schema, returns, scope)` con `args_schema` y `returns` Pydantic **obligatorios**; registro falla si faltan | Inferir schema desde signature | Predecibilidad; hueco futuro vía `schema_from_signature()` opt-in |
| D2 | Un mount único `MCPAgentMount(agents: list[AbstractBot])` que publica `/mcp/agents/{name}` por agente y, opcional, `/mcp` agregado con prefijo `{agent}__{tool}` | Solo per-agente / solo agregado | Misma machinery que el mount multi-agente de integrations; PBAC solo conoce el recurso canónico |
| D3 | Se exponen únicamente métodos decorados. `ask` no se expone | Agent-as-tool vía `ask` | LLM fuera del bucle por defecto; `question` como superficie de inyección queda fuera |
| D4 | OAuth 2.1 AS propio en navigator-auth; Google como upstream IdP; ai-parrot solo consume `resolve_principal(bearer)` | Keycloak/Auth0 | El gate de activación manual vive en `/authorize` sin sincronizar tablas |
| D5 | Working memory **stateless por call**; continuidad solo vía `thread_id` explícito en `args_schema`. `EpisodicMemoryStore` **por principal** para lo durable | Memoria continua por principal | Claude Web es dueño de la conversación; evitar contaminación entre chats; sin estado de sesión HTTP en el protocolo |
| D6 | Métodos que lancen flows/crews usan patrón handle: `start_*` → `job_id` durable; `*_status(job_id)`; `*_result(job_id)` proyectando manifiesto (nunca payloads) | Llamada bloqueante | Timeout 300 s; responsabilidad del método, no del adaptador |
| D7 | PBAC en dos puntos: `tools/list` filtrado por política del principal; `tools/call` re-verificado siempre. Recurso canónico `mcp:agent:{name}:tool:{tool}` | Solo 403 en `call` | Claude no debe ver tools que no puede usar; nunca confiar en la lista |
| D8 | `ResultPolicy` de tamaño en el adaptador: paginación obligatoria en listas, `exclude_none`, tope configurable por tool | Devolver `model_dump_json()` crudo | Límite ~30k tokens |
| D9 | `resolve_principal` acepta OAuth access token **y** API key (Claude Code/Desktop/API `mcp_servers`) sobre el mismo endpoint | Endpoints separados | Un solo `Principal`, un solo enforcement |
| D10 | Access token opaco (o JWT con `jti` revocable) ~1 h; refresh ~30 d rotado; `tenant_id` y scopes `mcp:agent:{name}` en el token; `key_fingerprint` al `AuditLedger` | JWT largo sin revocación | Revocación inmediata al desactivar usuario |
| D11 | Rollout con `enforcing: false` (shadow) hasta validar políticas; luego enforce | Enforce desde día 1 | Patrón ya usado en navigator-auth |

## 6. Diseño de alto nivel

```
Claude Web ──OAuth 2.1 (PKCE)──▶ navigator-auth AS ──▶ Google IdP
     │                              │  gate: tabla mcp_access (activación manual)
     │  bearer                      ▼
     ▼                         access token (tenant, scopes, jti)
HttpMCPServer (Streamable HTTP)
     │  resolve_principal(bearer) → Principal
     ▼
MCPAgentMount
  ├─ /mcp/agents/{name}   ← AgentMethodAdapter(agent)  [@mcp_tool methods]
  └─ /mcp                 ← agregado, prefijo {agent}__{tool} → recurso canónico
     │
     ▼
PBAC (navigator-auth): filtra tools/list · verifica tools/call
     │
     ▼
método del agente (Principal en contextvar, ToolManager por tenant/sesión)
  └─ si long-running → job durable (Redis/Postgres) + handle
```

Contratos nuevos (Pydantic-only, siempre importables):
- `parrot.interfaces.mcp`: `MCPToolSpec`, `MCPAgentManifest`, `Principal`,
  `ResultPolicy`, `JobHandle`.
- Implementación detrás de extra `ai-parrot[mcp-server]` con `__getattr__` lazy,
  mismo patrón que `faiss _try_create_faiss_store`.

## 7. Spike gates

| ID | Pregunta empírica | Bloquea | Estado |
|---|---|---|---|
| S1 | ¿Un AS mínimo (PRM + RFC 8414 + DCR + PKCE + `/token` form-urlencoded + refresh rotado) conecta desde claude.ai sin "Disconnected"? Probar DCR **y** client estático | proposal | pendiente |
| S2 | ¿`HttpMCPServer` pasa MCP Inspector como Streamable HTTP? | spec | parcial (owner) |
| S3 | Timeout/tamaño | — | cerrado por documentación (§4) |
| S4 | ¿claude.ai honra `list_changed`? | — | no bloqueante: `tools/list` es por principal en cada conexión; cambios mid-session los cubre D7 |

## 8. Open questions

1. **OQ1 — Propagación del `Principal` al método.** ¿`contextvars` seteado por el
   adaptador, o inyección explícita como primer parámetro (`principal: Principal`)
   detectada por el decorador? Explícito es más testeable; contextvar no ensucia la
   firma pública del agente.
2. **OQ2 — Binding tenant → `ToolManager`.** ¿`ToolManager` por `(tenant_id,
   principal)` o por `(tenant_id)` con credenciales por principal? Cruza con el
   `SandboxPool` keyed por `(tenant_id, template)`.
3. **OQ3 — DCR vs cliente estático por organización.** ¿Default DCR con opción
   estática, o solo estática (T-ROC, Epson) y DCR desactivado? DCR abre registro a
   cualquier cliente; el gate real sigue siendo `/authorize`.
4. **OQ4 — `list_changed` en claude.ai.** Confirmar en S1 (observar si reconecta o
   refresca al cambiar la lista).
5. **OQ5 — Anotaciones MCP.** ¿`readOnlyHint`/`destructiveHint`/`idempotentHint`
   derivadas del `scope` del decorador (`*:read` ⇒ readOnly) o declaradas aparte?
6. **OQ6 — Ubicación del decorador.** ¿`parrot.interfaces.mcp.mcp_tool` (importable
   sin extras) o en el paquete de implementación? Debe ser lo primero para que los
   agentes declaren sin arrastrar deps.
7. **OQ7 — Métodos `@mcp_tool` fuera de MCP.** ¿El mismo registro alimenta también
   la API HTTP propia / A2A (`AgentCard.skills`)? Si sí, el decorador es
   transporte-agnóstico y el spec debe nombrarlo así.
8. **OQ8 — Job store para D6.** ¿Reutilizar `SuspendedExecutionStore` (HITL) o
   store nuevo? Semántica tombstone/TTL ya resuelta ahí.

## 9. Criterios de aceptación (borrador)

- Un `BasicAgent` con dos métodos `@mcp_tool` aparece en Claude Web como conector
  con exactamente esas dos tools, tras login Google + activación manual.
- Un usuario no activado obtiene `access_denied` en `/authorize` y nunca token.
- Desactivar un usuario revoca acceso en ≤ TTL del access token; `tools/call`
  posterior falla con error limpio.
- `tools/list` de dos principales con políticas distintas devuelve listas distintas.
- Un método long-running devuelve `job_id` en < 5 s y su resultado vía `*_result`.
- Respuesta de cualquier tool ≤ tope de `ResultPolicy`; listas paginadas.
- Cada `tools/call` deja entrada en `AuditLedger` con principal, tool, hash de args,
  duración.
- Mismo endpoint acepta API key (Claude Code) y OAuth token (Claude Web).
- Las interfaces de `parrot.interfaces.mcp` importan sin el extra instalado.

## 10. Revision history

| Fecha | Cambio |
|---|---|
| 2026-08-30 | v0.1 — brainstorm inicial; D1–D11; S3 cerrado por documentación; S4 desbloqueado |
