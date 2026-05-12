---
id: F004
query_id: Q004
type: read
intent: Read FileManagerInterface (abstract) to know what methods the mixin must call.
executed_at: 2026-05-12T00:00:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F004 — FileManagerInterface: nine abstract async methods, plus `create_from_bytes` helper

## Summary

`FileManagerInterface` defines 9 abstract methods that all backends must
implement plus 3 concrete helpers. The relevant methods for
`ReportPersistenceMixin` are `upload_file(source, destination) -> FileMetadata`,
`create_file(path, content: bytes) -> bool`, `create_from_bytes(path, data) -> bool`,
`exists`, `download_file`, `get_file_url`. The brainstorm references
`upload`/`download`/`exists`/`get_url` — the real method names are
`upload_file`/`download_file`/`exists`/`get_file_url`.

## Citations

- path: `.venv/lib/python3.11/site-packages/navigator/utils/file/abstract.py`
  lines: 36-165
  symbol: FileManagerInterface (abstract methods)
  excerpt: |
    class FileManagerInterface(ABC):
        @abstractmethod
        async def list_files(self, path: str = "", pattern: str = "*") -> List[FileMetadata]: ...
        @abstractmethod
        async def get_file_url(self, path: str, expiry: int = 3600) -> str: ...
        @abstractmethod
        async def upload_file(self, source: Union[BinaryIO, Path], destination: str) -> FileMetadata: ...
        @abstractmethod
        async def download_file(self, source: str, destination: Union[Path, BinaryIO]) -> Path: ...
        @abstractmethod
        async def copy_file(self, source: str, destination: str) -> FileMetadata: ...
        @abstractmethod
        async def delete_file(self, path: str) -> bool: ...
        @abstractmethod
        async def exists(self, path: str) -> bool: ...
        @abstractmethod
        async def get_file_metadata(self, path: str) -> FileMetadata: ...
        @abstractmethod
        async def create_file(self, path: str, content: bytes) -> bool: ...

- path: `.venv/lib/python3.11/site-packages/navigator/utils/file/abstract.py`
  lines: 15-34
  symbol: FileMetadata dataclass
  excerpt: |
    @dataclass
    class FileMetadata:
        name: str
        path: str
        size: int
        content_type: Optional[str]
        modified_at: Optional[datetime]
        url: Optional[str]

- path: `.venv/lib/python3.11/site-packages/navigator/utils/file/abstract.py`
  lines: 230-263
  symbol: concrete helpers create_from_text / create_from_bytes
  excerpt: |
    async def create_from_text(self, path, text, encoding="utf-8") -> bool: ...
    async def create_from_bytes(self, path, data: Union[bytes, BytesIO, StringIO]) -> bool:
        # accepts bytes | BytesIO | StringIO; calls create_file under the hood

## Notes

- `upload_file` accepts either a `Path` or a `BinaryIO`. For the mixin's
  in-memory `bytes` payload, prefer `create_file(path, content)` or
  `create_from_bytes(path, BytesIO(content))`.
- Return shape: `FileMetadata.path` becomes the value to embed in `ReportRef.uri`
  (or build `s3://{bucket}/{key}` from `manager.bucket_name + path`).
