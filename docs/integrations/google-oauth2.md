# Google OAuth 2.0 — AI-Parrot Integration

This guide documents the Google Drive file manager's authentication modes, scopes, and environment variable wiring.

The manager uses the existing `GoogleClient` infrastructure from `parrot.interfaces.google` with service-account, user, and cached modes, delegating to `aiogoogle` for token management.

## Authentication modes

### Service account

Service account credentials are loaded from `GOOGLE_CREDENTIALS_FILE` (default: `env/google/key.json`). The service account acts on behalf of the app and can access any Drive file the service account has access to, including shared drives.

```python
from parrot.interfaces.file import GoogleDriveFileManager

async with GoogleDriveFileManager(
    root_path="Reports",
    credentials="env/google/key.json",
) as gd:
    files = await gd.list_files()
```

**Shared drive membership**: Service accounts can access shared drives, but the shared drive's My Drive quota applies to the service account, not the organization. If you need to access a shared drive with organization-level quotas, use the `user` or `cached` mode with a user account.

### User (interactive login)

User credentials are obtained through an interactive OAuth2 flow. The signed-in user consents to the requested scopes, and a refresh token is stored for future use.

```python
from parrot.interfaces.file import GoogleDriveFileManager

async with GoogleDriveFileManager(
    root_path="My Drive",
    auth_mode="user",
    interactive_login_kwargs={"port": 5050},
) as gd:
    files = await gd.list_files()
```

The `interactive_login_kwargs` dict is passed to `GoogleClient.interactive_login()` and can include:

- `port` — local OAuth2 server port (default: 8080)
- `redirect_uri` — custom redirect URI (default: `http://localhost:8080/api/auth/google/callback`)

### Cached

Cached mode reuses a previously authenticated `GoogleClient` (e.g., from another tool or session). The client's token is used directly without re-authenticating.

```python
from parrot.interfaces.google import GoogleClient
from parrot.interfaces.file import GoogleDriveFileManager

# Get an authenticated client from elsewhere
client = await get_authenticated_client()

async with GoogleDriveFileManager(
    root_path="Reports",
    auth_mode="cached",
) as gd:
    gd.adopt_client(client)
    files = await gd.list_files()
```

**Redis history**: The `GoogleClient` class uses Redis to cache tokens with a 90-day TTL. Ensure `REDIS_HISTORY_URL` is configured (default: `redis://localhost:6379/4`) for token caching to work.

## Scopes

The manager uses the `DEFAULT_SCOPES["drive"]` set from `parrot.interfaces.google`:

```python
from parrot.interfaces.google import DEFAULT_SCOPES

print(DEFAULT_SCOPES["drive"])
# ['https://www.googleapis.com/auth/drive',
#  'https://www.googleapis.com/auth/drive.file',
#  'https://www.googleapis.com/auth/drive.metadata.readonly']
```

- `drive` — Full access to all files in the user's Drive (service account) or the signed-in user's Drive (user mode).
- `drive.file` — Access to files the user has opened or created (user mode only).
- `drive.metadata.readonly` — Read-only access to file metadata (used for search and listing).

You can override the default scopes by passing a custom `scopes` argument:

```python
async with GoogleDriveFileManager(
    root_path="Reports",
    auth_mode="user",
    scopes=["https://www.googleapis.com/auth/drive.readonly"],
) as gd:
    files = await gd.list_files()  # Only read access
```

## Environment variables

Configured in `parrot/conf.py`:

```python
GOOGLE_CREDENTIALS_FILE = Path(
    config.get("GOOGLE_CREDENTIALS_FILE", fallback=BASE_DIR.joinpath("env", "google", "key.json"))
)
```

**Required**:

- `GOOGLE_CREDENTIALS_FILE` — Path to the service account JSON key file (service account mode). If the value is `"env/google/key.json"`, the file is resolved relative to the project root.

**Optional** (for user/cached mode):

- `REDIS_HISTORY_URL` — Redis URL for token caching (default: `redis://localhost:6379/4`). Required for cached mode to work with token persistence.

## Bootstrapping the manager

In your application startup (e.g., `app.py`):

```python
from parrot.interfaces.file import GoogleDriveFileManager
from parrot.conf import GOOGLE_CREDENTIALS_FILE

async def on_startup(app):
    manager = GoogleDriveFileManager(
        root_path="Reports",
        credentials=GOOGLE_CREDENTIALS_FILE,
    )
    await manager.connect()
    app["gdrive_manager"] = manager
```

After this, any agent that needs Drive access can retrieve the manager from the app state and use it directly.

## Token lifecycle

| Layer       | Backing store                        | TTL              | Source of truth |
|-------------|--------------------------------------|------------------|-----------------|
| Hot cache   | Redis `oauth2:google:{channel}:{uid}`| 90 days (sliding)| no              |
| Persisted   | DocumentDB `user_credentials`        | none (until delete) | **yes**       |
| Refresh lock| Redis `lock:oauth2:google:refresh:...`| 10 s             | no              |

On `get_valid_token(channel, user_id)`:

1. Read Redis cache. If present and unexpired → return.
2. Fall back to the vault. On hit, refill the Redis cache and return.
3. If the token is expired and has a `refresh_token`, acquire the `lock:oauth2:google:refresh:...` Redis lock and POST `grant_type=refresh_token` to the token endpoint. On success, write the new token back to both layers and return; on 400/401 from Google, revoke both layers and return `None` (user must re-authorize).

## Revocation

Users can revoke consent from [Google Account settings](https://myaccount.google.com/permissions). The next `get_valid_token` call will get HTTP 400/401 on refresh and the manager will purge both vault and Redis. The toolkit then raises `AuthorizationRequired` on the next tool call, surfacing a fresh auth URL to the user.

To force a logout from the server side:

```python
await client.revoke("web", user_id)
```

## Troubleshooting

| Symptom                                            | Likely cause                                                                            |
|----------------------------------------------------|-----------------------------------------------------------------------------------------|
| `GOOGLE_CREDENTIALS_FILE` not found                | Service account key file path is incorrect or file does not exist.                      |
| `401 Unauthorized` on upload/download              | Token expired or revoked; user must re-authorize.                                       |
| `403 Forbidden` on shared drive access            | Service account does not have access to the shared drive; check IAM permissions.       |
| `REDIS_HISTORY_URL` not configured                 | Token caching disabled; cached mode will always re-authenticate.                        |
| `AuthorizationRequired` immediately                | Token missing from vault AND Redis — user must run the interactive login flow.          |
| Refresh fails repeatedly with 400                  | User changed their password or admin revoked the app — vault is purged automatically.  |

## See also

- Generic base: [`parrot.interfaces.google.GoogleClient`](../../packages/ai-parrot/src/parrot/interfaces/google.py)
- Drive client: [`parrot.interfaces.google.DriveClient`](../../packages/ai-parrot/src/parrot/interfaces/google.py)
- File manager: [`parrot.interfaces.file.GoogleDriveFileManager`](../../packages/ai-parrot/src/parrot/interfaces/file/gdrive.py)
- Toolkit: [`parrot_tools.google.GoogleDriveToolkit`](../../packages/ai-parrot-tools/src/parrot_tools/google/drive.py)
- Google API docs: [Drive v3 API](https://developers.google.com/drive/api/v3/reference)
