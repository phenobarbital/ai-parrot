# SimpleMCPServer Configuration

The `SimpleMCPServer` can be configured via a YAML file. This document details the supported configuration options, including all authentication methods.

## Basic Structure

The configuration file must have a root key `MCPServer`.

```yaml
MCPServer:
  name: MyMCPServer
  host: 0.0.0.0
  port: 8081
  transport: sse  # Options: sse, http, stdio
  enable_ssl: false
  auth_method: none # See Authentication Methods below
  
  # Tool Configuration
  tools:
    - JiraToolkit:
        server_url: https://your-jira.atlassian.net
        username: user@example.com
        token: YOUR_API_TOKEN
```

## Authentication Methods

The `auth_method` field determines how clients authenticate with the server. Supported methods are:

### 1. No Authentication (`none`)

The default method. No authentication is required to access the server.

```yaml
MCPServer:
  auth_method: none
```

### 2. API Key (`api_key`)

Requires clients to send an API key in a header (default `X-API-Key`).

```yaml
MCPServer:
  auth_method: api_key
  api_key_header: X-API-Key
  # Note: The actual API key validation logic depends on the configured api_key_store.
  # For SimpleMCPServer, currently it might default to checking an environment variable or simple store.
```

### 3. Internal OAuth2 (`oauth2_internal`)

Uses an in-memory OAuth2 provider. Clients must obtain an access token via the OAuth flow.

**Features:**
- In-memory storage (tokens lost on restart)
- Dynamic client registration (optional)
- Static client registration (recommended)

```yaml
MCPServer:
  auth_method: oauth2_internal
  oauth_token_ttl: 3600
  oauth_allow_dynamic_registration: false
  
  # Register static clients (Recommended)
  oauth_static_clients:
    - client_name: 'integration-client'
      client_id: 'your-client-id'
      client_secret: 'your-client-secret'
      redirect_uris: ['http://localhost:8080/callback']
      scopes: ['mcp:access']
```

**Genering Credentials:**
You can use the `scripts/generate_mcp_client.py` script to generate a valid client ID and secret.

### 4. External OAuth2 (`oauth2_external`)

Validates tokens issued by an external provider (e.g., Keyloak, Azure AD, Auth0).

```yaml
MCPServer:
  auth_method: oauth2_external
  oauth2_issuer_url: https://auth.example.com/realms/master
  oauth2_client_id: my-mcp-service
  # oauth2_introspection_endpoint: ... (optional if discovery works)
```

### 5. Bearer Token (`bearer`)

Uses `navigator-auth` session validation. Expects a standard Bearer token in the `Authorization` header.

```yaml
MCPServer:
  auth_method: bearer
```

## Transport Configuration

- **SSE (Server-Sent Events)**:
  ```yaml
  transport: sse
  base_path: /mcp
  events_path: /events # Optional custom path
  ```

- **HTTP**:
  ```yaml
  transport: http
  ```

- **Stdio**:
  ```yaml
  transport: stdio
  # Host/port are ignored
  ```

## SSL Configuration

To enable SSL/TLS:

```yaml
MCPServer:
  enable_ssl: true
  ssl_cert: /path/to/cert.pem
  ssl_key: /path/to/key.pem
```
