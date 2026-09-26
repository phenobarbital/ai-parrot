---
id: F005
query_id: Q006
type: read
intent: GCSFileManager — the existing Google-auth file manager pattern upstream
executed_at: 2026-09-25T22:52:30Z
duration_ms: 400
parent_id: null
depth: 0
---

# F005 — `GCSFileManager` is the upstream Google-credential manager; it uses `google.auth` + sync SDK in threads, not aiogoogle

## Summary

`navigator/utils/file/gcs.py` (upstream, navigator-api) implements the
contract for Cloud Storage with three credential modes (`json_credentials`
dict, `credentials` file path, `google.auth.default()`), `prefix` handling
(`_prefixed`/`_unprefixed`), `manager_name = "gcsfile"`, resumable-threshold
constants, `setup(app, route)` / `handle_file` delegating to
`FileServingExtension`, and a server-side `find_files` override. Every SDK call
is wrapped in `asyncio.to_thread`. It has **no** OAuth user-credential path
and **no** Redis session cache — those live only in `GoogleClient` (F002).

## Citations

- path: `.venv/lib/python3.12/site-packages/navigator/utils/file/gcs.py`
  lines: 45-48
  symbol: `GCSFileManager.manager_name`
  excerpt: |
    manager_name: str = "gcsfile"
    RESUMABLE_THRESHOLD: int = 5 * 1024 * 1024   # 5MB
    CHUNK_SIZE: int = 256 * 1024                  # 256KB

- path: `.venv/lib/python3.12/site-packages/navigator/utils/file/gcs.py`
  lines: 50-99
  symbol: `GCSFileManager.__init__`
  excerpt: |
    def __init__(self, bucket_name, prefix="", json_credentials=None, credentials=None, scopes=None, project=None, ...):
        if json_credentials: self._creds = service_account.Credentials.from_service_account_info(json_credentials)
        elif credentials:    self._creds = service_account.Credentials.from_service_account_file(credentials)
        else:                self._creds, self._project = google.auth.default(scopes=default_scopes)

- path: `.venv/lib/python3.12/site-packages/navigator/utils/file/gcs.py`
  lines: 120-149
  symbol: `_prefixed / _unprefixed / _make_metadata`
  excerpt: |
    def _prefixed(self, key: str) -> str: return self.prefix + key.lstrip("/")
    def _make_metadata(self, blob) -> FileMetadata: ... url=blob.public_url if blob.public_url else None

- path: `.venv/lib/python3.12/site-packages/navigator/utils/file/gcs.py`
  lines: 507-543
  symbol: `GCSFileManager.setup / handle_file`
  excerpt: |
    ext = FileServingExtension(manager=self, route=route if route.startswith("/") else "/" + route, manager_name=self.manager_name)
    return ext.setup(app)

- path: `.venv/lib/python3.12/site-packages/navigator/utils/file/gcs.py`
  lines: 466-501
  symbol: `GCSFileManager.find_files`
  excerpt: |
    async def find_files(self, keywords=None, extension=None, prefix=None):  # server-side prefix, in-memory keyword/extension

## Notes

`GCSFileManager` is registered upstream (`FileManagerFactory` key `"gcs"`,
F011) and lazily re-exported by the parrot shim (F010). A Drive manager cannot
reuse it (bucket/blob model, sync SDK), but it fixes two conventions the Drive
manager should follow: `manager_name` suffix `file`, and `prefix` semantics.
