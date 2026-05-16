# API — User Agents (`/api/v1/user_agents`)

Documentación del handler `UserAgentHandler` para construir la interfaz de usuario que permite a un usuario autenticado crear, listar, editar y borrar sus propios bots privados.

> **Autenticación:** todas las rutas requieren la sesión del usuario (cookie de `navigator-session`). El handler usa los decoradores `@is_authenticated()` y `@user_session()`. El `user_id` se obtiene de la sesión — el cliente **no** lo envía en el body.
>
> **Aislamiento:** cada bot pertenece exclusivamente a `user_id`. Las consultas filtran siempre por `(user_id, chatbot_id)`; no existe acceso cruzado entre usuarios en v1.
>
> **Cifrado transparente:** los campos `mcp_config` y `tools_config` se almacenan cifrados (AES-GCM) en Postgres. La UI envía y recibe JSON plano; el handler se encarga del cifrado y de **redactar** las credenciales en las respuestas (ver §Redacción).

---

## Tabla de endpoints

| Método | URL | Acción |
|---|---|---|
| `PUT`    | `/api/v1/user_agents`                | Crear un bot nuevo (acepta `multipart/form-data` para subir documentos). |
| `GET`    | `/api/v1/user_agents`                | Listar todos los bots del usuario autenticado. |
| `GET`    | `/api/v1/user_agents/{chatbot_id}`   | Obtener un bot concreto. |
| `PATCH`  | `/api/v1/user_agents/{chatbot_id}`   | Editar parcialmente un bot. |
| `DELETE` | `/api/v1/user_agents/{chatbot_id}`   | Borrar el bot y sus documentos asociados en S3. |

---

## Esquema común — `UserBotConfig`

Este es el contrato JSON que comparten `PUT`, `PATCH` y las respuestas de `GET`.

```jsonc
{
  // === Identidad ===
  "name": "research-bot",                   // string, único por usuario (1-64 chars)
  "description": "Bot de investigación",    // string, opcional
  "avatar": "https://.../avatar.png",       // string (URL), opcional
  "enabled": true,                          // bool, default true

  // === Personalidad (PromptBuilder) ===
  "role":         "Research Assistant",
  "goal":         "Ayudar al usuario a investigar temas",
  "backstory":    "Soy un asistente especializado en...",
  "rationale":    "Mantengo un tono profesional...",
  "capabilities": "Puedo buscar, resumir y citar fuentes",

  // === Configuración del system prompt ===
  "prompt_config": {                        // ver §PromptBuilder más abajo
    "preset": "default",                    // "default" | "minimal" | "voice" | "agent" | "rag"
    "remove":    ["TOOLS_LAYER"],           // capas a eliminar (opcional)
    "add":       [                          // capas a añadir (opcional)
      { "name": "CUSTOM_LAYER", "content": "..." }
    ],
    "customize": {                          // overrides por capa (opcional)
      "BEHAVIOR_LAYER": { "tone": "casual" }
    }
  },
  "system_prompt_template": null,           // string, opcional (override total)
  "human_prompt_template":  null,           // string, opcional
  "pre_instructions":       [],             // array de strings

  // === LLM ===
  "llm":          "openai",                 // "openai" | "anthropic" | "google" | "groq" | "vertex" | ...
  "model_name":   "gpt-4o-mini",
  "temperature":  0.1,                      // 0-2
  "max_tokens":   1024,                     // > 0
  "top_k":        41,
  "top_p":        0.9,                      // 0-1
  "model_config": {},                       // dict libre del cliente LLM

  // === Vector store + documentos ===
  "use_vector":   true,
  "vector_config": {                        // StoreConfig serializado
    "vector_store":     "postgres",         // "postgres" | "faiss" | "arango" | ...
    "table":            "user_<user_id>_<chatbot_id>",
    "schema":           "public",
    "embedding_model":  { "model_name": "sentence-transformers/all-mpnet-base-v2",
                          "model_type": "huggingface" },
    "dimension":        768,
    "distance_strategy":"COSINE",
    "auto_create":      true
  },
  "embedding_model": { /* idem que vector_config.embedding_model */ },
  "context_search_limit":    10,
  "context_score_threshold": 0.7,
  "documents": [                            // SOLO LECTURA en GET; en PUT/PATCH se suben vía multipart
    {
      "name": "manual.pdf",
      "path": "s3://parrot-uploads/users/42/abc-uuid/manual.pdf",
      "url":  "https://parrot-uploads.s3.amazonaws.com/...?X-Amz-Signature=...",
      "size": 124533,
      "content_type": "application/pdf"
    }
  ],

  // === MCP servers (CIFRADO en BD; REDACTADO en GET) ===
  "mcp_config": [
    {
      "name":         "perplexity",
      "transport":    "http",               // "stdio" | "http" | "unix"
      "host":         "mcp.perplexity.ai",
      "port":         443,
      "auth_method":  "api_key",            // "none" | "api_key" | "bearer" | "oauth2_internal" | "oauth2_external"
      "api_key_header": "X-API-Key",
      "api_key":      "sk-prx-...",         // ⚠ secreto — en GET aparecerá como "***"
      "allowed_tools": ["search", "summarize"],
      "blocked_tools": []
    }
  ],

  // === Tools (CIFRADO en BD; REDACTADO en GET) ===
  "tools_config": [
    {
      "name": "DuckDuckGoSearchTool",
      "args": { "max_results": 5 }
    },
    {
      "name": "GitHubTool",
      "args": { "token": "ghp_xxxx" }       // ⚠ secreto — redactado en GET
    }
  ],
  "tools_enabled":  true,
  "operation_mode": "adaptive",             // "conversational" | "agentic" | "adaptive"

  // === Memoria ===
  "memory_type":               "redis",     // "memory" | "file" | "redis"
  "memory_config":             {},
  "max_context_turns":         5,
  "use_conversation_history":  true,

  // === Permisos y metadata ===
  "permissions": {},
  "language":    "es",
  "disclaimer":  null,

  // === Campos generados por el servidor (solo en respuestas) ===
  "chatbot_id":  "8e7d2c1a-...-uuid",
  "user_id":     42,
  "created_at":  "2026-05-16T12:34:56Z",
  "updated_at":  "2026-05-16T13:00:00Z"
}
```

### Campos mínimos para crear un bot (PUT)

```jsonc
{ "name": "mi-bot", "llm": "openai", "model_name": "gpt-4o-mini", "goal": "..." }
```

Todos los demás campos toman valores por defecto.

---

## `PUT /api/v1/user_agents` — Crear

### Variante 1 — JSON puro (sin documentos)

```http
PUT /api/v1/user_agents HTTP/1.1
Cookie: <sesión navigator>
Content-Type: application/json

{ /* UserBotConfig — name, llm y goal son obligatorios */ }
```

### Variante 2 — `multipart/form-data` (con documentos)

```http
PUT /api/v1/user_agents HTTP/1.1
Cookie: <sesión navigator>
Content-Type: multipart/form-data; boundary=----X

------X
Content-Disposition: form-data; name="config"
Content-Type: application/json

{ /* UserBotConfig */ }
------X
Content-Disposition: form-data; name="files[]"; filename="manual.pdf"
Content-Type: application/pdf

<binario>
------X--
```

- `config` es un campo de texto con el JSON completo.
- `files[]` puede repetirse para subir varios archivos.
- Cada archivo se sube a S3 vía `FileManager` y se anexa al array `documents`.
- Si `use_vector=true`, los archivos se ingieren en la colección vectorial declarada en `vector_config` (de forma asíncrona; el bot puede tardar unos segundos en estar listo para RAG sobre esos documentos).

### Respuesta — `201 Created`

```json
{
  "chatbot_id": "8e7d2c1a-...-uuid",
  "config": { /* UserBotConfig completo, con documents poblado y secretos redactados */ },
  "instance_ready": true
}
```

### Errores

| Status | Causa |
|---|---|
| `400` | JSON malformado, o archivo subido sin campo `config`. |
| `401` | Sesión inválida o ausente. |
| `409` | Ya existe un bot con ese `name` para este `user_id`. |
| `422` | Validación Pydantic fallida (p.ej. tool desconocido, `operation_mode` inválido, `temperature` fuera de rango). |
| `503` | Vault de cifrado no configurado (master keys faltan). |

Cuerpo de error estándar:
```json
{ "error": "ValidationError", "detail": "tool 'FooBar' is not registered" }
```

---

## `GET /api/v1/user_agents` — Listar

### Query params (opcionales)

| Param | Tipo | Default | Descripción |
|---|---|---|---|
| `enabled` | bool | `null` | Filtra por `enabled=true/false`. Si se omite, devuelve todos. |
| `q`       | str  | —       | Busca por substring sobre `name`/`description`. |
| `limit`   | int  | 50      | Máximo 200. |
| `offset`  | int  | 0       | Paginación. |

### Respuesta — `200 OK`

```json
{
  "total": 3,
  "limit": 50,
  "offset": 0,
  "items": [
    {
      "chatbot_id": "8e7d2c1a-...",
      "name": "research-bot",
      "description": "Bot de investigación",
      "llm": "openai",
      "model_name": "gpt-4o-mini",
      "enabled": true,
      "tools_count": 3,
      "documents_count": 2,
      "use_vector": true,
      "created_at": "2026-05-10T12:00:00Z",
      "updated_at": "2026-05-15T08:30:00Z"
    }
  ]
}
```

> El listado devuelve una vista **resumida** (no las configuraciones completas) para evitar tráfico innecesario y exposición innecesaria de configuraciones. Para los detalles completos llama a `GET /{chatbot_id}`.

---

## `GET /api/v1/user_agents/{chatbot_id}` — Detalle

### Respuesta — `200 OK`

Devuelve el `UserBotConfig` completo con dos transformaciones:

1. **Redacción de credenciales** dentro de `mcp_config` y `tools_config` — ver §Redacción.
2. **URLs pre-firmadas** en `documents[*].url`, regeneradas en cada respuesta (expiración por defecto 1 h).

```json
{
  "chatbot_id": "8e7d2c1a-...",
  "user_id": 42,
  "name": "research-bot",
  /* ... UserBotConfig completo ... */
  "mcp_config": [
    {
      "name": "perplexity",
      "transport": "http",
      "host": "mcp.perplexity.ai",
      "auth_method": "api_key",
      "api_key": "***"            // ⬅ redactado
    }
  ],
  "tools_config": [
    { "name": "GitHubTool", "args": { "token": "***" } }
  ]
}
```

### Errores

| Status | Causa |
|---|---|
| `401` | Sesión inválida. |
| `404` | `chatbot_id` no existe **para este usuario** (mismo código que "no existe en absoluto"). |

---

## `PATCH /api/v1/user_agents/{chatbot_id}` — Editar

Edición parcial: cualquier subconjunto de los campos de `UserBotConfig` es válido. Los campos no enviados quedan intactos.

### Reglas de merge

- **Campos planos** (`name`, `model_name`, `temperature`, ...): se sobrescriben con el valor enviado.
- **`prompt_config`, `vector_config`, `model_config`, `memory_config`, `permissions`**: merge a primer nivel (los sub-campos no enviados se preservan).
- **`mcp_config` / `tools_config`** (cifrados):
  - El servidor **descifra** el blob existente, hace **deep merge por `name`** con el patch, y vuelve a cifrar.
  - Para **mantener** una credencial sin reenviarla, envía la entrada sin esa clave (o con el valor literal `"***"` — se ignora).
  - Para **borrar** una credencial concreta, envía la clave con valor `null`.
  - Para **eliminar** una entrada entera de la lista, usa `{ "name": "X", "_delete": true }`.
- **`documents`**: no se modifica directamente vía JSON. Para añadir archivos, envía `multipart/form-data` con `files[]`; para quitarlos, envía `{ "remove_documents": ["s3://.../manual.pdf"] }`.

### Ejemplo

```http
PATCH /api/v1/user_agents/8e7d2c1a-...-uuid HTTP/1.1
Cookie: <sesión>
Content-Type: application/json

{
  "temperature": 0.4,
  "tools_config": [
    { "name": "DuckDuckGoSearchTool", "args": { "max_results": 10 } },
    { "name": "GitHubTool", "_delete": true }
  ]
}
```

### Respuesta — `200 OK`

```json
{
  "chatbot_id": "8e7d2c1a-...",
  "config": { /* UserBotConfig actualizado y redactado */ },
  "instance_invalidated": true
}
```

`instance_invalidated: true` indica que la instancia en sesión se descartó: la próxima vez que el usuario hable con el bot vía `/api/v1/agents/chat/{chatbot_id}` se reconstruirá desde la base de datos con la nueva configuración.

### Errores

Mismos códigos que `PUT`, más `404` si el bot no existe.

---

## `DELETE /api/v1/user_agents/{chatbot_id}` — Borrar

Borra la fila de `navigator.users_bots`, elimina la instancia cacheada en la sesión y **best-effort** borra los archivos de S3 listados en `documents`.

### Respuesta — `200 OK`

```json
{
  "deleted": true,
  "chatbot_id": "8e7d2c1a-...",
  "documents_deleted": 2,
  "documents_failed": 0
}
```

Si la fila se borró pero la limpieza de S3 falló parcialmente:
```json
{
  "deleted": true,
  "chatbot_id": "8e7d2c1a-...",
  "documents_deleted": 1,
  "documents_failed": 1,
  "warnings": ["s3://.../manual.pdf: AccessDenied"]
}
```

### Errores

| Status | Causa |
|---|---|
| `401` | Sesión inválida. |
| `404` | `chatbot_id` no existe para este usuario. |

---

## Redacción de credenciales

Para no filtrar secretos al cliente, el servidor **enmascara** las siguientes claves en cualquier nivel anidado dentro de `mcp_config` y `tools_config`:

```
api_key, client_secret, oauth2_client_secret, password, token, secret
```

El valor original sigue almacenado y cifrado en Postgres; en la respuesta se sustituye por el string literal `"***"`.

Implicación para la UI:
- Si el usuario edita un bot, **no** vuelvas a enviar los campos enmascarados a menos que el usuario los cambie. El backend conserva los originales.
- Si el usuario quiere borrar un secreto explícitamente, envía la clave con `null`.
- Si el usuario rota un secreto, envía la nueva versión en plano; el backend la cifra al guardar.

---

## PromptBuilder — qué pasar en `prompt_config`

El bot usa `PromptBuilder` (`parrot/bots/prompts/builder.py`). Capas disponibles:

| Capa | Cuándo se resuelve | Editable por el usuario |
|---|---|---|
| `IDENTITY_LAYER` | configure (estática) | sí (vía `role`/`goal`/`backstory`/`rationale`) |
| `PRE_INSTRUCTIONS_LAYER` | configure | sí (vía `pre_instructions[]`) |
| `SECURITY_LAYER` | configure | no (gestionada por la plataforma) |
| `KNOWLEDGE_LAYER` | request (RAG) | indirectamente (depende de `vector_config` y `documents`) |
| `USER_SESSION_LAYER` | request | no |
| `TOOLS_LAYER` | request | indirectamente (depende de `tools_config`) |
| `OUTPUT_LAYER` | request | sí (vía `prompt_config.customize.OUTPUT_LAYER`) |
| `BEHAVIOR_LAYER` | configure | sí (vía `prompt_config.customize.BEHAVIOR_LAYER`) |

Presets aceptados en `prompt_config.preset`:

- `"default"` — stack completo (recomendado).
- `"minimal"` — solo `IDENTITY` + `SECURITY` + `USER_SESSION` (chat ligero).
- `"voice"` — optimizado para canal de voz.
- `"agent"` — añade `STRICT_GROUNDING_LAYER` (uso intensivo de tools).
- `"rag"` — añade `RAG_GROUNDING_LAYER` y elimina `TOOLS_LAYER` (RAG puro).

---

## Cómo hablar con un user-bot (no es este handler, pero la UI lo necesita)

Una vez creado un bot vía `PUT /api/v1/user_agents`, el cliente lo usa exactamente igual que un agente del sistema:

```http
POST /api/v1/agents/chat/{chatbot_id} HTTP/1.1
Cookie: <sesión>
Content-Type: application/json

{ "query": "Resume el documento manual.pdf" }
```

El handler `AgentTalk` resuelve primero el `chatbot_id` contra la caché en sesión del usuario y, si no está, contra `navigator.users_bots`. Si tampoco existe ahí, hace fallback a los bots del sistema. Para la UI esto es transparente — el mismo botón de "chat" sirve para ambos tipos de bot.

> Alternativamente, `POST /api/v1/chat/{chatbot_id}` es una versión simplificada (sin negociación de salida HTML/markdown, sin invocación de métodos personalizados) — útil para clientes ligeros.

---

## Resumen para una UI

Pantallas mínimas:

1. **Listado** — `GET /api/v1/user_agents`, tabla con `name`, `llm`, `enabled`, `tools_count`, `documents_count`, fechas + acciones (chat / editar / borrar).
2. **Wizard de creación** — `PUT /api/v1/user_agents` en 5 pasos:
   1. Identidad: `name`, `description`, `role`, `goal`.
   2. LLM: `llm`, `model_name`, `temperature`, `max_tokens`.
   3. Prompt: preset + textareas para `pre_instructions` y customización por capa.
   4. Conocimiento: toggle `use_vector` + uploader de archivos (`multipart files[]`).
   5. Tools / MCP: pickers que listan los nombres válidos de `ToolkitRegistry` y formularios para añadir MCP servers con `MCPServerConfig`.
3. **Editor** — `GET` para precargar, `PATCH` para guardar cambios parciales; muestra `"***"` para credenciales y permite reescribirlas u opcionalmente borrarlas (`null`).
4. **Chat** — `POST /api/v1/agents/chat/{chatbot_id}` (mismo widget que para bots del sistema).
5. **Borrado** — `DELETE` con confirmación (avisa de la pérdida de documentos S3).
