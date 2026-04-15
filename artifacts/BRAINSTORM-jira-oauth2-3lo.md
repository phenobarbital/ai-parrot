# BRAINSTORM: Jira OAuth 2.0 (3LO) — Per-User Authentication

**Feature:** FEAT-XXX — Jira OAuth2 3LO Per-User Authentication  
**Author:** Jesus / Claude  
**Date:** 2026-04-09  
**Status:** Brainstorm  
**Scope:** `ai-parrot-tools` (JiraToolkit), `ai-parrot` (auth infra, AgenTalk, Telegram)

---

## 1. Problem Statement

### Current Situation
`JiraToolkit` authenticates using a single **system account** (basic_auth with API token or PAT). This means:

- **All operations** (create issue, assign, transition, comment) appear as the system account user
- The `reporter` field defaults to the system user — changing it requires "Modify Reporter" permission and `accountId` lookup
- **Audit trail is broken** — Jira's activity log shows the bot account, not the actual human user
- **Permission boundaries are invisible** — the system account may have broader access than individual users should
- In **AgenTalk** (web chat), each user gets their own `ToolManager`, but JiraToolkit shares the same static credentials
- In **Telegram** (autonomous bot), `JiraSpecialist` uses a single bot-level Jira connection

### Desired Outcome
When a user interacts with an AI-Parrot agent (via AgenTalk chat, Telegram, or any channel), Jira operations execute **in that user's name** using their own OAuth2 3LO authorization grant.

---

## 2. Background: Atlassian OAuth 2.0 (3LO)

### How 3LO Works

Atlassian's OAuth 2.0 implementation is a standard **Authorization Code Grant** (RFC 6749) with some specifics:

```
┌──────────┐                              ┌────────────────┐
│   User   │──1. Click "Connect Jira" ──▶│  AI-Parrot App │
│ (browser)│                              │  (our backend) │
└──────────┘                              └───────┬────────┘
     │                                            │
     │  2. Redirect to Atlassian                  │
     ▼                                            │
┌──────────────────────┐                          │
│ auth.atlassian.com   │                          │
│ Consent screen:      │                          │
│ "Allow AI-Parrot to  │                          │
│  access Jira on your │                          │
│  behalf?"            │                          │
└──────────┬───────────┘                          │
           │                                      │
           │ 3. User grants consent               │
           │    Redirect to callback_url           │
           │    with ?code=AUTH_CODE&state=...     │
           ▼                                      │
┌──────────────────────┐                          │
│ our-domain.com/      │                          │
│ api/auth/jira/       │  4. Exchange code ──────▶│
│ callback             │     for tokens           │
└──────────────────────┘                          │
                                                  │
                              5. POST https://auth.atlassian.com/oauth/token
                                 → { access_token, refresh_token, expires_in }
                                                  │
                              6. GET accessible-resources
                                 → cloud_id (site ID)
                                                  │
                              7. Store tokens in Redis
                                 key: jira:oauth:{user_id}
                                                  │
                              8. All API calls use:
                                 https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/...
                                 Authorization: Bearer {access_token}
```

### Key Atlassian-Specific Details

1. **Authorization URL:**
   ```
   https://auth.atlassian.com/authorize?
     audience=api.atlassian.com&
     client_id={CLIENT_ID}&
     scope=read:jira-work write:jira-work manage:jira-project manage:jira-configuration offline_access&
     redirect_uri={CALLBACK_URL}&
     state={STATE_VALUE}&
     response_type=code&
     prompt=consent
   ```

2. **Token Exchange:**
   ```
   POST https://auth.atlassian.com/oauth/token
   {
     "grant_type": "authorization_code",
     "client_id": "...",
     "client_secret": "...",
     "code": "AUTH_CODE",
     "redirect_uri": "..."
   }
   ```

3. **Accessible Resources (discover cloud_id):**
   ```
   GET https://api.atlassian.com/oauth/token/accessible-resources
   Authorization: Bearer {access_token}
   → [{ "id": "cloud-uuid", "name": "mysite", "url": "https://mysite.atlassian.net", ... }]
   ```

4. **API calls go through the gateway**, NOT direct to the site:
   ```
   Base URL: https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/
   ```

5. **Rotating Refresh Tokens:** Every time you use a refresh token, Atlassian returns a NEW refresh token. The old one is invalidated. You **must** persist the new one immediately or lose access.

6. **Token Lifetime:** Access tokens expire in ~3600 seconds (1 hour). Refresh tokens have a longer but finite life.

7. **Scopes are account-level:** The user grants access to their Atlassian account, not a specific site. But the `accessible-resources` endpoint tells you which sites the user has access to.

8. **User permissions still apply:** Even with `manage:jira-project` scope, if the user doesn't have "Administer Projects" permission in Jira, the API will return 403. Scopes define the ceiling; Jira permissions define the actual access.

---

## 3. Respondiendo la Pregunta: Deep Link — ¿Un Token por Acción o por Sesión?

### Respuesta: **Por sesión de larga duración, NO por acción.**

El flujo OAuth2 3LO produce un **token set** (access_token + refresh_token) que se almacena y reutiliza:

```
┌─────────────────────────────────────────────────────────────────┐
│                    CICLO DE VIDA DEL TOKEN                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Día 1: Usuario hace /connect_jira en Telegram                 │
│  ├── Bot genera deep link con state=tg:{user_id}:{nonce}       │
│  ├── Usuario abre link → consent screen → autoriza             │
│  ├── Callback recibe code, intercambia por tokens              │
│  ├── Redis: jira:oauth:tg_12345 = { access, refresh, ... }    │
│  └── Bot confirma: "✅ Jira conectado como jesus@empresa.com"  │
│                                                                 │
│  Día 1-N: Usuario usa Jira normalmente                         │
│  ├── Cada operación: get_valid_token(user_id)                  │
│  │   ├── access_token vigente? → usar directamente             │
│  │   └── expirado? → refresh automático (transparente)         │
│  │       ├── POST /oauth/token con refresh_token               │
│  │       ├── Recibir NUEVO access + NUEVO refresh              │
│  │       └── Guardar ambos en Redis                            │
│  └── El usuario NUNCA ve el flujo de refresh                   │
│                                                                 │
│  Día 30-90+: Sesión potencialmente indefinida                  │
│  ├── Mientras haya refresh tokens activos, se auto-renueva     │
│  ├── Si el refresh token expira (inactividad prolongada):      │
│  │   └── Bot: "Tu sesión de Jira expiró, /connect_jira"       │
│  └── Si el usuario revoca desde Atlassian:                     │
│      └── Bot detecta 401 → "Reconecta con /connect_jira"      │
│                                                                 │
│  Revocación explícita: /disconnect_jira                        │
│  └── Eliminar tokens de Redis                                  │
└─────────────────────────────────────────────────────────────────┘
```

### ¿Por qué NO un token por acción?

- OAuth2 3LO requiere **interacción del usuario en un browser** (consent screen). Sería intolerable pedir esto en cada operación.
- El refresh token es el mecanismo diseñado para mantener sesiones de larga duración.
- Es el mismo patrón que usa cualquier app que conecta con Google, GitHub, Slack, etc.: autorizas una vez, usas indefinidamente.

### Cuándo se requiere re-autenticación

| Escenario | Acción |
|-----------|--------|
| Access token expirado (cada ~1h) | Refresh automático, invisible al usuario |
| Refresh token expirado (inactividad prolongada) | Solicitar nuevo /connect_jira |
| Usuario revoca acceso en Atlassian settings | Detectar 401 → pedir reconexión |
| Admin desinstala la app de su site | Detectar 401 → notificar al usuario |
| Scopes cambian (app actualizada) | Solicitar re-consent con `prompt=consent` |

---

## 4. Arquitectura Propuesta

### 4.1 Componentes Nuevos

```
packages/
├── ai-parrot/src/parrot/
│   ├── auth/
│   │   ├── __init__.py
│   │   ├── base.py                    # AbstractOAuthProvider
│   │   ├── jira_oauth.py             # JiraOAuthManager
│   │   ├── token_store.py            # RedisTokenStore (genérico)
│   │   └── routes.py                 # aiohttp callback routes
│   └── ...
└── ai-parrot-tools/src/parrot_tools/
    └── jiratoolkit.py                 # Modificar: agregar auth_type="oauth2_3lo"
```

### 4.2 Modelo de Datos: TokenSet

```python
class JiraTokenSet(BaseModel):
    """Per-user Jira OAuth2 token set, stored in Redis."""
    
    # Tokens
    access_token: str
    refresh_token: str
    expires_at: float                   # epoch timestamp
    
    # Site info (from accessible-resources)
    cloud_id: str                       # UUID del site Jira
    site_url: str                       # https://mysite.atlassian.net
    
    # User info (from /myself)
    account_id: str                     # Atlassian accountId
    display_name: str                   # "Jesus Garcia"
    email: Optional[str] = None
    
    # Metadata
    scopes: list[str] = []
    granted_at: float = 0               # When user first authorized
    last_refreshed_at: float = 0        # Last successful refresh
    
    # Multi-site support (future)
    available_sites: list[dict] = []    # All sites from accessible-resources
    
    @property
    def is_expired(self) -> bool:
        """Check if access token is expired (with 60s safety margin)."""
        return time.time() >= (self.expires_at - 60)
    
    @property
    def api_base_url(self) -> str:
        """REST API base URL through Atlassian gateway."""
        return f"https://api.atlassian.com/ex/jira/{self.cloud_id}"
```

### 4.3 JiraOAuthManager

```python
class JiraOAuthManager:
    """
    Manages the complete OAuth 2.0 (3LO) lifecycle for Jira Cloud.
    
    Responsibilities:
    - Generate authorization URLs with proper state
    - Exchange authorization codes for token sets
    - Auto-refresh expired tokens (rotating refresh tokens)
    - Store/retrieve per-user tokens from Redis
    - Detect and handle revocation gracefully
    
    Thread-safe: Uses async Redis operations.
    State parameter: Encodes channel + user_id + nonce for CSRF protection.
    """
    
    AUTH_URL = "https://auth.atlassian.com/authorize"
    TOKEN_URL = "https://auth.atlassian.com/oauth/token"
    RESOURCES_URL = "https://api.atlassian.com/oauth/token/accessible-resources"
    
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        redis_client,                    # redis.asyncio
        scopes: list[str] | None = None,
        token_key_prefix: str = "jira:oauth:",
        nonce_key_prefix: str = "jira:nonce:",
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.redis = redis_client
        self.scopes = scopes or [
            "read:jira-work",
            "write:jira-work",
            "manage:jira-project",
            "offline_access",
        ]
        self.token_prefix = token_key_prefix
        self.nonce_prefix = nonce_key_prefix
    
    # ── Authorization URL ──
    
    async def create_authorization_url(
        self,
        channel: str,                   # "agentalk", "telegram", "teams"
        user_id: str,                    # channel-specific user ID
        extra_state: dict | None = None, # additional state data
    ) -> tuple[str, str]:
        """
        Generate authorization URL and state token.
        
        Returns:
            (authorization_url, state_token)
        
        State format: {channel}:{user_id}:{nonce}
        Nonce stored in Redis with 10min TTL to prevent replay.
        """
        nonce = secrets.token_urlsafe(32)
        state = f"{channel}:{user_id}:{nonce}"
        
        # Store nonce for verification (10 min TTL)
        nonce_data = {
            "channel": channel,
            "user_id": user_id,
            "created_at": time.time(),
            **(extra_state or {}),
        }
        await self.redis.set(
            f"{self.nonce_prefix}{nonce}",
            json.dumps(nonce_data),
            ex=600,  # 10 minutes
        )
        
        params = {
            "audience": "api.atlassian.com",
            "client_id": self.client_id,
            "scope": " ".join(self.scopes),
            "redirect_uri": self.redirect_uri,
            "state": state,
            "response_type": "code",
            "prompt": "consent",
        }
        url = f"{self.AUTH_URL}?{urlencode(params)}"
        return url, state
    
    # ── Code Exchange ──
    
    async def handle_callback(
        self, code: str, state: str
    ) -> JiraTokenSet:
        """
        Handle the OAuth callback: verify state, exchange code, 
        discover cloud_id, resolve user identity, store tokens.
        
        Raises:
            ValueError: Invalid/expired state (CSRF protection)
            httpx.HTTPStatusError: Atlassian API error
        """
        # 1. Parse and verify state
        channel, user_id, nonce = self._parse_state(state)
        nonce_key = f"{self.nonce_prefix}{nonce}"
        nonce_data = await self.redis.get(nonce_key)
        if not nonce_data:
            raise ValueError("Invalid or expired state — possible CSRF attack")
        await self.redis.delete(nonce_key)  # one-time use
        
        # 2. Exchange code for tokens
        async with httpx.AsyncClient(timeout=30) as client:
            token_resp = await client.post(self.TOKEN_URL, json={
                "grant_type": "authorization_code",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "code": code,
                "redirect_uri": self.redirect_uri,
            })
            token_resp.raise_for_status()
            token_data = token_resp.json()
            
            # 3. Discover accessible sites
            resources_resp = await client.get(
                self.RESOURCES_URL,
                headers={"Authorization": f"Bearer {token_data['access_token']}"},
            )
            resources_resp.raise_for_status()
            sites = resources_resp.json()
            
            if not sites:
                raise ValueError("No accessible Jira sites found for this user")
            
            # Use first site (TODO: multi-site selection UI)
            site = sites[0]
            
            # 4. Get user identity
            me_resp = await client.get(
                f"https://api.atlassian.com/ex/jira/{site['id']}/rest/api/3/myself",
                headers={"Authorization": f"Bearer {token_data['access_token']}"},
            )
            me_resp.raise_for_status()
            me = me_resp.json()
        
        # 5. Build and store token set
        token_set = JiraTokenSet(
            access_token=token_data["access_token"],
            refresh_token=token_data["refresh_token"],
            expires_at=time.time() + token_data.get("expires_in", 3600),
            cloud_id=site["id"],
            site_url=site.get("url", ""),
            account_id=me["accountId"],
            display_name=me.get("displayName", ""),
            email=me.get("emailAddress"),
            scopes=token_data.get("scope", "").split(),
            granted_at=time.time(),
            last_refreshed_at=time.time(),
            available_sites=sites,
        )
        
        # Build composite key: {prefix}{channel}:{user_id}
        storage_key = self._user_key(channel, user_id)
        await self._store_tokens(storage_key, token_set)
        
        return token_set
    
    # ── Token Retrieval (with auto-refresh) ──
    
    async def get_valid_token(
        self, channel: str, user_id: str
    ) -> JiraTokenSet | None:
        """
        Get a valid (non-expired) token set for a user.
        Auto-refreshes if expired. Returns None if user hasn't authorized.
        
        Raises:
            PermissionError: If refresh fails (token revoked)
        """
        key = self._user_key(channel, user_id)
        token_set = await self._load_tokens(key)
        if not token_set:
            return None
        
        if token_set.is_expired:
            try:
                token_set = await self._refresh_tokens(key, token_set)
            except httpx.HTTPStatusError as e:
                if e.response.status_code in (400, 401, 403):
                    # Token revoked or invalid — clean up
                    await self.revoke(channel, user_id)
                    raise PermissionError(
                        f"Jira authorization has been revoked for user {user_id}. "
                        "Please re-authorize with /connect_jira"
                    ) from e
                raise
        
        return token_set
    
    # ── Refresh (Rotating Tokens) ──
    
    async def _refresh_tokens(
        self, storage_key: str, token_set: JiraTokenSet
    ) -> JiraTokenSet:
        """
        Refresh using rotating refresh token.
        
        CRITICAL: Atlassian issues a NEW refresh token on every refresh.
        The old refresh token is INVALIDATED. We must atomically persist
        the new one or the user loses access permanently.
        """
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(self.TOKEN_URL, json={
                "grant_type": "refresh_token",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": token_set.refresh_token,
            })
            resp.raise_for_status()
            data = resp.json()
        
        # Update token set with new values
        token_set.access_token = data["access_token"]
        token_set.refresh_token = data["refresh_token"]  # NEW refresh token!
        token_set.expires_at = time.time() + data.get("expires_in", 3600)
        token_set.last_refreshed_at = time.time()
        
        # Persist immediately — if this fails, we lose the refresh token
        await self._store_tokens(storage_key, token_set)
        
        return token_set
    
    # ── Storage ──
    
    async def _store_tokens(self, key: str, tokens: JiraTokenSet):
        await self.redis.set(
            key, tokens.model_dump_json(),
            ex=90 * 86400,  # 90 days TTL
        )
    
    async def _load_tokens(self, key: str) -> JiraTokenSet | None:
        raw = await self.redis.get(key)
        if not raw:
            return None
        return JiraTokenSet.model_validate_json(raw)
    
    async def revoke(self, channel: str, user_id: str):
        """Remove stored tokens for a user."""
        await self.redis.delete(self._user_key(channel, user_id))
    
    async def is_connected(self, channel: str, user_id: str) -> bool:
        """Check if a user has valid stored tokens."""
        return await self.redis.exists(self._user_key(channel, user_id)) > 0
    
    # ── Helpers ──
    
    def _user_key(self, channel: str, user_id: str) -> str:
        return f"{self.token_prefix}{channel}:{user_id}"
    
    @staticmethod
    def _parse_state(state: str) -> tuple[str, str, str]:
        parts = state.split(":", 2)
        if len(parts) != 3:
            raise ValueError(f"Malformed state parameter: {state}")
        return parts[0], parts[1], parts[2]
```

### 4.4 Callback HTTP Routes

```python
# parrot/auth/routes.py

async def jira_oauth_callback(request: web.Request) -> web.Response:
    """
    GET /api/auth/jira/callback?code=...&state=...
    
    Called by Atlassian after user grants consent.
    Exchanges code, stores tokens, shows success page.
    """
    code = request.query.get("code")
    state = request.query.get("state")
    error = request.query.get("error")
    
    if error:
        return web.Response(
            text=_render_error_page(error, request.query.get("error_description")),
            content_type="text/html",
        )
    
    if not code or not state:
        return web.Response(text="Missing code or state", status=400)
    
    oauth_mgr: JiraOAuthManager = request.app["jira_oauth_manager"]
    
    try:
        token_set = await oauth_mgr.handle_callback(code, state)
    except ValueError as e:
        return web.Response(
            text=_render_error_page("invalid_state", str(e)),
            content_type="text/html",
        )
    except httpx.HTTPStatusError as e:
        return web.Response(
            text=_render_error_page("token_exchange_failed", str(e)),
            content_type="text/html",
        )
    
    # Parse channel from state to customize success page
    channel, user_id, _ = JiraOAuthManager._parse_state(state)
    
    # Notify the channel (e.g., send Telegram message)
    notifier = request.app.get("oauth_notifier")
    if notifier:
        await notifier.notify_success(channel, user_id, token_set)
    
    return web.Response(
        text=_render_success_page(token_set.display_name, token_set.site_url),
        content_type="text/html",
    )


def setup_oauth_routes(app: web.Application):
    """Mount OAuth callback routes on the aiohttp app."""
    app.router.add_get("/api/auth/jira/callback", jira_oauth_callback)
    
    # Exclude from auth middleware
    from navigator_auth.conf import exclude_list
    exclude_list.append("/api/auth/jira/callback")
```

### 4.5 JiraToolkit — Modo `oauth2_3lo`

```python
# Modificaciones a JiraToolkit

class JiraToolkit(AbstractToolkit):
    
    def __init__(
        self,
        # ... existing params ...
        oauth_manager: Optional[JiraOAuthManager] = None,
        oauth_channel: Optional[str] = None,
        oauth_user_id: Optional[str] = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._oauth_manager = oauth_manager
        self._oauth_channel = oauth_channel
        self._oauth_user_id = oauth_user_id
        
        # Lazy client — only init for non-oauth modes
        if self.auth_type != "oauth2_3lo":
            self._set_jira_client()
        else:
            self.jira = None  # Will be set per-request
    
    async def _ensure_oauth_client(self) -> JIRA:
        """
        Get or refresh the JIRA client for OAuth2 3LO mode.
        Called before every Jira operation.
        """
        if self.auth_type != "oauth2_3lo":
            return self.jira
        
        if not self._oauth_manager:
            raise ValueError("oauth2_3lo requires JiraOAuthManager")
        
        token_set = await self._oauth_manager.get_valid_token(
            self._oauth_channel, self._oauth_user_id
        )
        
        if not token_set:
            raise PermissionError(
                "Jira no está conectado. Usa /connect_jira para autorizar."
            )
        
        # Recreate client if token changed
        # (pycontribs/jira doesn't support changing auth after init)
        self.jira = JIRA(
            server=token_set.api_base_url,
            options={
                "headers": {
                    "Authorization": f"Bearer {token_set.access_token}",
                    "Accept": "application/json",
                },
                "verify": True,  # Atlassian gateway uses valid certs
            },
        )
        return self.jira
    
    # Every tool method needs to call _ensure_oauth_client() first:
    
    async def jira_get_issue(self, issue: str, ...) -> dict:
        await self._ensure_oauth_client()
        # ... existing logic ...
    
    async def jira_search_issues(self, jql: str, ...) -> dict:
        await self._ensure_oauth_client()
        # ... existing logic ...
```

**Alternativa más limpia — Interceptor pattern:**

En vez de modificar cada método, usar un wrapper en `AbstractToolkit` que intercepte antes de ejecutar:

```python
class JiraToolkit(AbstractToolkit):
    
    async def _pre_execute(self, tool_name: str, **kwargs):
        """Called by AbstractToolkit before any tool execution."""
        if self.auth_type == "oauth2_3lo":
            await self._ensure_oauth_client()
    
    # Si AbstractToolkit no soporta _pre_execute, usar __getattr__ 
    # o decorar tools en get_tools()
```

---

## 5. Integración: Dos Modos de Entrega al Usuario

### 5.1 Opción A — Deep Link (Recomendada para Telegram)

```
┌──────────────────────────────────────────────────────────────┐
│ DEEP LINK FLOW                                               │
│                                                              │
│ User: /connect_jira                                          │
│                                                              │
│ Bot:  "Para conectar tu cuenta de Jira, abre este enlace:   │
│        🔗 https://our-app.com/auth/jira?                     │
│           state=telegram:12345:abc123def456                  │
│                                                              │
│        El enlace expira en 10 minutos."                      │
│                                                              │
│ [User opens link in browser]                                 │
│ → Atlassian consent screen                                   │
│ → User clicks "Accept"                                       │
│ → Redirect to our callback                                   │
│ → Callback stores tokens, sends success page                 │
│ → Callback notifies Telegram bot via API                     │
│                                                              │
│ Bot:  "✅ Jira conectado como Jesus Garcia                   │
│        (jesus@empresa.com) en empresa.atlassian.net          │
│        Todas las operaciones se harán en tu nombre.          │
│        Para desconectar: /disconnect_jira"                   │
│                                                              │
│ [From now on, ALL Jira operations use user's token]          │
│ [Token refreshes automatically every ~1 hour]                │
│ [Re-auth only needed if refresh token expires or is revoked] │
└──────────────────────────────────────────────────────────────┘
```

**Ventajas:**
- Funciona en TODOS los clientes de Telegram (desktop, mobile, web)
- No requiere Telegram Mini App setup
- Flujo estándar OAuth — el usuario lo reconoce
- El `state` parameter vincula la sesión Telegram con el callback

**Desventajas:**
- El usuario sale de Telegram momentáneamente
- Requiere que nuestro servidor sea accesible públicamente (HTTPS)

**Seguridad del state parameter:**

```python
# State structure: channel:user_id:nonce
# Nonce: random token, stored in Redis with 10min TTL
# Prevents:
#   - CSRF: nonce is verified on callback
#   - Replay: nonce deleted after use
#   - Guessing: 32 bytes of randomness
state = f"telegram:{telegram_user_id}:{secrets.token_urlsafe(32)}"
```

### 5.2 Opción B — Telegram Mini App (WebView)

```
┌──────────────────────────────────────────────────────────────┐
│ MINI APP FLOW                                                │
│                                                              │
│ User: /connect_jira                                          │
│                                                              │
│ Bot sends InlineKeyboardButton with web_app:                 │
│   { "text": "🔗 Connect Jira",                              │
│     "web_app": {                                             │
│       "url": "https://our-app.com/tma/jira-connect"         │
│     }                                                        │
│   }                                                          │
│                                                              │
│ [Mini App opens inside Telegram]                             │
│ ├── Shows branded "Connect to Jira" page                     │
│ ├── Validates initData (Telegram auth)                       │
│ ├── User clicks "Authorize" button                           │
│ ├── window.open() → Atlassian consent screen                 │
│ │   (problem: some clients block popups)                     │
│ │   Alternative: redirect within WebView                     │
│ │   (problem: consent screen may not render well)            │
│ ├── After consent, callback receives code                    │
│ ├── Mini App polls or uses WebSocket for status              │
│ └── Shows "✅ Connected!" and closes                         │
│                                                              │
│ Bot: "✅ Jira connected as Jesus Garcia"                     │
└──────────────────────────────────────────────────────────────┘
```

**Ventajas:**
- Experiencia "in-app" — el usuario no sale de Telegram
- Podemos mostrar UI rica (selección de site, confirmación)
- Podemos validar la identidad del usuario via `initData`

**Desventajas:**
- Más complejo de implementar (frontend Mini App + initData validation)
- Problemas con popups/redirects dentro del WebView
- Algunos clientes de Telegram tienen restricciones con WebView
- Requiere hosting de assets frontend
- El flujo OAuth con redirects dentro de un WebView puede romperse

### 5.3 Recomendación: Deep Link + Mini App Progresivo

**Fase 1:** Implementar Deep Link (simple, robusto, universal)  
**Fase 2:** Agregar Mini App como upgrade opcional para UX mejorada  

El Deep Link es el **MVP** correcto porque:
1. Cero dependencias frontend
2. Funciona en todos los clientes
3. El flujo OAuth está probado y es estándar
4. Podemos pasar a Mini App sin cambiar el backend

---

## 6. Integración con AgenTalk (Web Chat)

AgenTalk es más simple porque el usuario ya está en un browser:

```
┌──────────────────────────────────────────────────────────────┐
│ AGENTALK FLOW                                                │
│                                                              │
│ 1. User opens AgenTalk session                               │
│    → Session creates ToolManager for user                    │
│    → Check Redis: has user authorized Jira?                  │
│                                                              │
│ 2a. YES → Create JiraToolkit(auth_type="oauth2_3lo",         │
│           oauth_manager=mgr, channel="agentalk",             │
│           user_id=session_user_id)                           │
│       → Register tools in user's ToolManager                 │
│       → User can immediately use Jira tools                  │
│                                                              │
│ 2b. NO → Register JiraConnectTool in ToolManager             │
│       → When LLM tries to use Jira:                          │
│         "Para usar Jira, necesitas autorizar el acceso.      │
│          [🔗 Conectar Jira](authorization_url)"              │
│       → User clicks link → opens in new tab                  │
│       → Consent → callback → popup/tab closes               │
│       → WebSocket notification to chat session               │
│       → Chat: "✅ Jira conectado! Repitiendo tu solicitud.." │
│       → Replace JiraConnectTool with full JiraToolkit         │
│       → Re-execute the original request                      │
│                                                              │
│ 3. Hot-swap: When tokens arrive mid-session                  │
│    → Remove placeholder tool                                 │
│    → Create JiraToolkit with oauth2_3lo                      │
│    → Register in existing ToolManager                        │
│    → Sync to LLM client                                      │
└──────────────────────────────────────────────────────────────┘
```

### JiraConnectTool (Placeholder)

```python
class JiraConnectTool(AbstractTool):
    """
    Placeholder tool that generates the OAuth authorization URL.
    Registered when a user hasn't connected Jira yet.
    Replaced with full JiraToolkit after successful authorization.
    """
    name = "jira_connect"
    description = (
        "Connect your Jira account. Call this when the user wants to "
        "interact with Jira but hasn't authorized yet."
    )
    
    async def execute(self, **kwargs) -> ToolResult:
        url, _ = await self.oauth_manager.create_authorization_url(
            channel="agentalk",
            user_id=self.user_id,
        )
        return ToolResult(
            success=True,
            result=(
                f"Para usar Jira, necesitas autorizar el acceso.\n\n"
                f"👉 [Conectar Jira]({url})\n\n"
                f"El enlace expira en 10 minutos."
            ),
        )
```

---

## 7. Integración con Telegram

### 7.1 Comandos del Bot

```python
# En TelegramAgentWrapper o JiraSpecialist

@router.message(Command("connect_jira"))
async def cmd_connect_jira(message: Message):
    """Generate and send OAuth authorization URL."""
    user_id = str(message.from_user.id)
    
    # Check if already connected
    if await oauth_manager.is_connected("telegram", user_id):
        token_set = await oauth_manager.get_valid_token("telegram", user_id)
        await message.answer(
            f"✅ Ya estás conectado a Jira como **{token_set.display_name}**\n"
            f"Site: {token_set.site_url}\n\n"
            f"Para desconectar: /disconnect\\_jira",
            parse_mode="Markdown",
        )
        return
    
    url, state = await oauth_manager.create_authorization_url(
        channel="telegram",
        user_id=user_id,
        extra_state={"chat_id": str(message.chat.id)},
    )
    
    await message.answer(
        "🔗 **Conectar tu cuenta de Jira**\n\n"
        "Abre este enlace para autorizar el acceso:\n"
        f"👉 [Autorizar en Jira]({url})\n\n"
        "⏱ El enlace expira en 10 minutos.\n"
        "ℹ️ Las operaciones se harán en tu nombre.",
        parse_mode="Markdown",
    )


@router.message(Command("disconnect_jira"))
async def cmd_disconnect_jira(message: Message):
    """Revoke Jira authorization."""
    user_id = str(message.from_user.id)
    await oauth_manager.revoke("telegram", user_id)
    await message.answer("❌ Jira desconectado. Usa /connect\\_jira para reconectar.")


@router.message(Command("jira_status"))
async def cmd_jira_status(message: Message):
    """Check Jira connection status."""
    user_id = str(message.from_user.id)
    try:
        token_set = await oauth_manager.get_valid_token("telegram", user_id)
        if token_set:
            await message.answer(
                f"✅ **Jira conectado**\n"
                f"Usuario: {token_set.display_name}\n"
                f"Site: {token_set.site_url}\n"
                f"Autorizado: {datetime.fromtimestamp(token_set.granted_at).strftime('%Y-%m-%d')}\n"
                f"Último refresh: {datetime.fromtimestamp(token_set.last_refreshed_at).strftime('%Y-%m-%d %H:%M')}",
                parse_mode="Markdown",
            )
        else:
            await message.answer("❌ Jira no conectado. Usa /connect\\_jira")
    except PermissionError:
        await message.answer(
            "⚠️ Tu autorización de Jira ha expirado.\n"
            "Usa /connect\\_jira para reconectar."
        )
```

### 7.2 Notificador post-callback

```python
class TelegramOAuthNotifier:
    """
    Notifies the user in Telegram after successful OAuth callback.
    Uses the Telegram Bot API to send a message.
    """
    
    def __init__(self, bot: Bot):
        self.bot = bot
    
    async def notify_success(
        self, channel: str, user_id: str, token_set: JiraTokenSet
    ):
        if channel != "telegram":
            return
        
        # Retrieve chat_id from nonce data (stored during create_authorization_url)
        # Or use user_id directly if it's a private chat
        try:
            await self.bot.send_message(
                chat_id=int(user_id),
                text=(
                    f"✅ **Jira conectado exitosamente**\n\n"
                    f"Usuario: {token_set.display_name}\n"
                    f"Email: {token_set.email}\n"
                    f"Site: {token_set.site_url}\n\n"
                    f"Todas las operaciones de Jira se harán en tu nombre."
                ),
                parse_mode="Markdown",
            )
        except Exception as e:
            logging.warning(f"Could not notify Telegram user {user_id}: {e}")
```

### 7.3 JiraSpecialist con OAuth

```python
# Modificación a JiraSpecialist.agent_tools()

class JiraSpecialist(BasicAgent):
    
    def agent_tools(self):
        """Return Jira tools — OAuth2 if user connected, system account as fallback."""
        
        # Check if current user has OAuth2 token
        # user_id is injected via conversation context
        user_id = getattr(self, '_current_user_id', None)
        channel = getattr(self, '_current_channel', 'telegram')
        
        if user_id and self._oauth_manager:
            # Try OAuth2 per-user mode
            self.jira_toolkit = JiraToolkit(
                server_url="oauth2_3lo",  # Placeholder — real URL comes from token
                auth_type="oauth2_3lo",
                oauth_manager=self._oauth_manager,
                oauth_channel=channel,
                oauth_user_id=user_id,
                default_project=config.get("JIRA_PROJECT"),
            )
        else:
            # Fallback to system account
            self.jira_toolkit = JiraToolkit(
                server_url=config.get("JIRA_INSTANCE"),
                auth_type="basic_auth",
                username=config.get("JIRA_USERNAME"),
                password=config.get("JIRA_API_TOKEN"),
                default_project=config.get("JIRA_PROJECT"),
            )
        
        if hasattr(self, 'tool_manager') and self.tool_manager:
            self.jira_toolkit.set_tool_manager(self.tool_manager)
        
        return self.jira_toolkit.get_tools()
```

---

## 8. Consideraciones de Seguridad

### 8.1 CSRF Protection
- El `state` parameter contiene un nonce criptográfico almacenado en Redis con TTL de 10 min
- El nonce se elimina después de un solo uso
- Si el state no coincide, se rechaza el callback

### 8.2 Token Storage
- Tokens en Redis con TTL de 90 días
- Redis debe tener `requirepass` configurado y TLS en producción
- Keys: `jira:oauth:{channel}:{user_id}` — namespace por canal evita colisiones

### 8.3 Secret Management
- `JIRA_OAUTH2_CLIENT_ID` y `JIRA_OAUTH2_CLIENT_SECRET` en environment variables (navconfig)
- Nunca en logs, responses, o system prompts

### 8.4 Rotating Refresh Token Race Condition
Si dos requests concurrentes intentan refresh simultáneamente:
- Request A refreshes → gets new refresh_token_B
- Request B refreshes with old refresh_token_A → Atlassian REJECTS (already rotated)

**Solución:** Redis lock durante refresh:
```python
async def _refresh_tokens(self, key, token_set):
    lock_key = f"lock:{key}"
    async with self.redis.lock(lock_key, timeout=10):
        # Re-read from Redis in case another process already refreshed
        fresh = await self._load_tokens(key)
        if fresh and not fresh.is_expired:
            return fresh  # Already refreshed by another process
        
        # Proceed with refresh
        ...
```

### 8.5 Scope Minimization
Solo solicitar los scopes necesarios:
- `read:jira-work` — leer issues, proyectos, boards
- `write:jira-work` — crear/editar issues, transiciones, comentarios
- `manage:jira-project` — gestión de proyectos (si es necesario)
- `offline_access` — REQUERIDO para obtener refresh tokens

NO solicitar `manage:jira-configuration` a menos que sea necesario.

---

## 9. Configuración Requerida

### 9.1 Atlassian Developer Console

1. Ir a https://developer.atlassian.com/console/myapps/
2. Crear nueva app → "OAuth 2.0 integration"
3. En Authorization → OAuth 2.0 (3LO):
   - Callback URL: `https://{DOMAIN}/api/auth/jira/callback`
4. En Permissions → Jira API:
   - Agregar scopes: `read:jira-work`, `write:jira-work`, `manage:jira-project`
5. En Settings:
   - Copiar Client ID y Client Secret

### 9.2 Environment Variables

```env
# Jira OAuth2 3LO
JIRA_OAUTH2_CLIENT_ID=your-client-id-here
JIRA_OAUTH2_CLIENT_SECRET=your-client-secret-here
JIRA_OAUTH2_REDIRECT_URI=https://your-domain.com/api/auth/jira/callback
JIRA_OAUTH2_SCOPES=read:jira-work write:jira-work manage:jira-project offline_access

# Redis (existing)
REDIS_URL=redis://localhost:6379
```

---

## 10. Impacto en Componentes Existentes

| Componente | Impacto | Cambios |
|------------|---------|---------|
| `JiraToolkit` | ALTO | Nuevo auth_type, lazy client init, _ensure_oauth_client() |
| `JiraSpecialist` | MEDIO | Detección de OAuth vs fallback system account |
| `ToolManager` | BAJO | Sin cambios — ya soporta hot-swap de tools |
| `AbstractToolkit` | BAJO | Opcional: agregar `_pre_execute()` hook |
| `AutonomousOrchestrator` | BAJO | Montar routes de OAuth callback |
| `TelegramAgentWrapper` | MEDIO | Nuevos comandos /connect_jira, /disconnect_jira |
| `AgenTalk/WebSocket` | MEDIO | JiraConnectTool placeholder, hot-swap post-auth |
| Redis | BAJO | Nuevas keys jira:oauth:* y jira:nonce:* |

---

## 11. Plan de Tareas (Propuesto)

```
TASK-01: JiraTokenSet model + RedisTokenStore (genérico)
TASK-02: JiraOAuthManager (core: auth URL, code exchange, refresh, storage)
TASK-03: OAuth callback HTTP routes + success/error pages
TASK-04: JiraToolkit — auth_type="oauth2_3lo" + _ensure_oauth_client()
TASK-05: JiraConnectTool (placeholder para cuando no hay auth)
TASK-06: Telegram commands (/connect_jira, /disconnect_jira, /jira_status)
TASK-07: TelegramOAuthNotifier (post-callback message)
TASK-08: AgenTalk integration (session setup, hot-swap, WebSocket notification)
TASK-09: JiraSpecialist — OAuth vs fallback logic
TASK-10: Race condition handling (Redis lock for rotating refresh)
TASK-11: Tests (unit: OAuth manager, integration: full flow)
TASK-12: Documentation + Atlassian Developer Console setup guide
```

---

## 12. Preguntas Abiertas

1. **Multi-site:** Si un usuario tiene acceso a múltiples Jira sites, ¿auto-seleccionar el primero o mostrar selector?

2. **Fallback policy:** ¿Qué hacer si OAuth falla? ¿Caer al system account (riesgo de confusión de identidad) o bloquear la operación?

3. **AbstractOAuthProvider:** ¿Generalizar esto para otros servicios (GitHub, GitLab, Confluence) desde el inicio, o solo Jira por ahora y refactorizar después?

4. **Token encryption at rest:** ¿Cifrar los tokens en Redis con una key de aplicación, o confiar en Redis ACLs + TLS?

5. **Admin override:** ¿Permitir a un admin "impersonar" las credenciales de un usuario para debugging?

---

## 13. Referencia Rápida — Diagrama Completo

```
                    ┌─────────────────────────────────────────┐
                    │           ATLASSIAN CLOUD                │
                    │  auth.atlassian.com (consent, tokens)   │
                    │  api.atlassian.com  (Jira REST API)     │
                    └──────────┬──────────────────────────────┘
                               │
                    ┌──────────▼──────────────────────────────┐
                    │           AI-PARROT BACKEND              │
                    │                                          │
                    │  ┌─────────────────────────────┐        │
                    │  │   JiraOAuthManager           │        │
                    │  │   - create_authorization_url │        │
                    │  │   - handle_callback          │        │
                    │  │   - get_valid_token          │        │
                    │  │   - auto-refresh             │        │
                    │  └──────────┬──────────────────┘        │
                    │             │                             │
                    │  ┌──────────▼──────────────────┐        │
                    │  │   Redis                      │        │
                    │  │   jira:oauth:tg:12345 = {}   │        │
                    │  │   jira:oauth:web:abc = {}    │        │
                    │  │   jira:nonce:xyz = {}         │        │
                    │  └──────────────────────────────┘        │
                    │                                          │
                    │  ┌──────────────────────────────┐        │
                    │  │   /api/auth/jira/callback    │        │
                    │  │   (aiohttp route)            │        │
                    │  └──────────────────────────────┘        │
                    │                                          │
                    │  ┌──────────────────────────────┐        │
                    │  │   JiraToolkit                 │        │
                    │  │   auth_type="oauth2_3lo"      │        │
                    │  │   → per-user JIRA client      │        │
                    │  └──────────────────────────────┘        │
                    └──────────────────────────────────────────┘
                               │
              ┌────────────────┼─────────────────┐
              │                │                  │
    ┌─────────▼───┐  ┌────────▼────────┐  ┌─────▼──────────┐
    │  Telegram   │  │   AgenTalk      │  │   MS Teams     │
    │  Bot        │  │   WebSocket     │  │   (future)     │
    │             │  │                  │  │                │
    │ /connect    │  │ JiraConnectTool  │  │                │
    │ deep link   │  │ → inline link   │  │                │
    │ /disconnect │  │ → hot-swap      │  │                │
    └─────────────┘  └─────────────────┘  └────────────────┘
```
