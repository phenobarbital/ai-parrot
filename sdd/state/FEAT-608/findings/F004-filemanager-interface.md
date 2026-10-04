---
id: F004
query_id: Q005
type: read
intent: FileManagerInterface abstract contract in navigator-api 4.0.0
executed_at: 2026-09-25T22:52:30Z
duration_ms: 300
parent_id: null
depth: 0
---

# F004 — The contract: 9 abstract async methods + 4 optional folder/rename hooks + `find_files` default

## Summary

`navigator.utils.file.abstract` (navigator-api 4.0.0, installed in `.venv`)
defines `FileMetadata` (dataclass: name, path, size, content_type,
modified_at, url) and `FileManagerInterface` with nine abstract coroutines
(`list_files`, `get_file_url`, `upload_file`, `download_file`, `copy_file`,
`delete_file`, `exists`, `get_file_metadata`, `create_file`), four
non-abstract folder/rename hooks that raise `NotImplementedError`, and
concrete helpers `create_from_text`, `create_from_bytes`, `find_files`
(in-memory filter over `list_files`). Same contract FEAT-603 implemented.

## Citations

- path: `.venv/lib/python3.12/site-packages/navigator/utils/file/abstract.py`
  lines: 15-33
  symbol: `FileMetadata`
  excerpt: |
    @dataclass
    class FileMetadata:
        name: str; path: str; size: int; content_type: Optional[str]; modified_at: Optional[datetime]; url: Optional[str]

- path: `.venv/lib/python3.12/site-packages/navigator/utils/file/abstract.py`
  lines: 36-164
  symbol: `FileManagerInterface`
  excerpt: |
    async def list_files(self, path: str = "", pattern: str = "*") -> List[FileMetadata]
    async def get_file_url(self, path: str, expiry: int = 3600) -> str
    async def upload_file(self, source: Union[BinaryIO, Path], destination: str) -> FileMetadata
    async def download_file(self, source: str, destination: Union[Path, BinaryIO]) -> Path
    async def copy_file(self, source: str, destination: str) -> FileMetadata
    async def delete_file(self, path: str) -> bool
    async def exists(self, path: str) -> bool
    async def get_file_metadata(self, path: str) -> FileMetadata     # raises FileNotFoundError
    async def create_file(self, path: str, content: bytes) -> bool

- path: `.venv/lib/python3.12/site-packages/navigator/utils/file/abstract.py`
  lines: 170-224
  symbol: `create_folder / remove_folder / rename_folder / rename_file`
  excerpt: |
    async def create_folder(self, folder_name: str) -> None: raise NotImplementedError(...)

- path: `.venv/lib/python3.12/site-packages/navigator/utils/file/abstract.py`
  lines: 265-296
  symbol: `FileManagerInterface.find_files`
  excerpt: |
    async def find_files(self, keywords=None, extension=None, prefix=None) -> List[FileMetadata]:
        files = await self.list_files(path=prefix or "")   # in-memory default; managers may override server-side
