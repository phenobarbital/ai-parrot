---
id: F024
query_id: Q024
type: read
intent: OverflowStore.generate_presigned_url + FileManager re-exports and upstream get_file_url/upload_file signatures
executed_at: 2026-09-24T23:21:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F024 — OverflowStore presigns via FileManagerInterface.get_file_url(path, expiry=3600); managers re-exported from navigator.utils.file

## Summary
`OverflowStore.generate_presigned_url(key, *, expires_in=604800)` caps the expiry at 604800 s (7 days) and calls `self._fm.get_file_url(key, expiry=effective_expiry)`. `parrot/interfaces/file/__init__.py` is a backward-compatibility shim. It eagerly re-exports `FileManagerInterface`, `FileMetadata`, `LocalFileManager` and `TempFileManager` from `navigator.utils.file`, and lazily loads `S3FileManager` and `GCSFileManager` through module `__getattr__`. Upstream (navigator-api 4.0.0 in the venv) the signatures are `get_file_url(self, path: str, expiry: int = 3600) -> str` and `upload_file(self, source: Union[BinaryIO, Path], destination: str) -> FileMetadata`. S3 returns a presigned URL; Local returns a `file://` URI.

## Citations
- path: `packages/ai-parrot/src/parrot/storage/overflow.py`
  lines: 20-20
  symbol: `OverflowStore`
  excerpt: |
    class OverflowStore:
- path: `packages/ai-parrot/src/parrot/storage/overflow.py`
  lines: 119-144
  symbol: `OverflowStore.generate_presigned_url`
  excerpt: |
    async def generate_presigned_url(self, key: str, *, expires_in: int = 604800) -> str:
        """... The expiry is silently capped at 604 800 seconds (7 days) ..."""
        effective_expiry = min(int(expires_in), 604_800)
        return await self._fm.get_file_url(key, expiry=effective_expiry)
- path: `packages/ai-parrot/src/parrot/interfaces/file/__init__.py`
  lines: 1-23
  symbol: `parrot.interfaces.file` (eager re-exports)
  excerpt: |
    """File manager interfaces — re-exported from navigator.utils.file.
    This module is a backward-compat shim. The single source of truth
    is navigator.utils.file (navigator-api >= 3.0.3). ..."""
    from navigator.utils.file import (
        FileManagerInterface, FileMetadata, LocalFileManager, TempFileManager,
    )
- path: `packages/ai-parrot/src/parrot/interfaces/file/__init__.py`
  lines: 34-47
  symbol: `_LAZY_MANAGERS`, `__getattr__`
  excerpt: |
    _LAZY_MANAGERS = {
        "S3FileManager": "navigator.utils.file.s3",
        "GCSFileManager": "navigator.utils.file.gcs",
    }
    def __getattr__(name: str):
        if name in _LAZY_MANAGERS:
            mod = importlib.import_module(_LAZY_MANAGERS[name])
- path: `packages/ai-parrot/src/parrot/interfaces/file/abstract.py`
  lines: 1-4
  symbol: `re-export FileManagerInterface`
  excerpt: |
    from navigator.utils.file.abstract import FileManagerInterface, FileMetadata
- path: `packages/ai-parrot/src/parrot/interfaces/file/s3.py`
  lines: 1-4
  symbol: `re-export S3FileManager`
  excerpt: |
    from navigator.utils.file.s3 import S3FileManager
- path: `.venv/lib/python3.12/site-packages/navigator/utils/file/abstract.py`
  lines: 67-92
  symbol: `FileManagerInterface.get_file_url`, `FileManagerInterface.upload_file`
  excerpt: |
    async def get_file_url(self, path: str, expiry: int = 3600) -> str:
    async def upload_file(self, source: Union[BinaryIO, Path], destination: str) -> FileMetadata:
- path: `.venv/lib/python3.12/site-packages/navigator/utils/file/abstract.py`
  lines: 245-247
  symbol: `FileManagerInterface.create_from_bytes`
  excerpt: |
    async def create_from_bytes(self, path: str, data: Union[bytes, BytesIO, StringIO]) -> bool:
- path: `.venv/lib/python3.12/site-packages/navigator/utils/file/s3.py`
  lines: 193-205
  symbol: `S3FileManager.get_file_url`
  excerpt: |
    async def get_file_url(self, path: str, expiry: int = 3600) -> str:
        """Generate a presigned URL for an S3 object."""
        key = self._prefixed(path)
        async with await self._s3_client() as s3:
            url = await s3.generate_presigned_url(
- path: `.venv/lib/python3.12/site-packages/navigator/utils/file/local.py`
  lines: 160-172
  symbol: `LocalFileManager.get_file_url`
  excerpt: |
    async def get_file_url(self, path: str, expiry: int = 3600) -> str:
        """Return a file:// URI for the resolved path."""
        return self._resolve_path(path).as_uri()

## Notes
- WRONG in the brainstorm: the parameter is `expiry`, not `expiry_seconds`.
- The OverflowStore docstring (L131-134) says Local/Temp managers may raise NotImplementedError. The installed navigator-api 4.0.0 `LocalFileManager` actually returns a `file://` URI, which Teams and Slack cannot render. Guard against non-http schemes.
- Upstream package: navigator-api 4.0.0 (`navigator.utils.file`). Presigned URLs are good for at most 7 days, so figure URLs sent into chat history will expire. Consider re-presigning when the answer is rendered, or a proxy endpoint.
