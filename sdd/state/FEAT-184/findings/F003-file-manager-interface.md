# F003 — FileManagerInterface

**Path**: `packages/ai-parrot/src/parrot/interfaces/file/__init__.py` (re-exports from `navigator.utils.file`)

Full method surface:
- `upload_file(source, destination)` → FileMetadata
- `download_file(source, destination: Path | BinaryIO)` → Path
- `create_file(path, content: bytes)` → bool
- `create_from_bytes(path, data)` → bool
- `create_from_text(path, text, encoding)` → bool
- `delete_file(path)` → bool
- `copy_file(source, destination)` → FileMetadata
- `rename_file(old, new)` → None
- `exists(path)` → bool
- `get_file_metadata(path)` → FileMetadata
- `get_file_url(path, expiry=3600)` → str
- `list_files(path='', pattern='*')` → list[FileMetadata]
- `find_files(keywords, extension, prefix)` → list[FileMetadata]
- `create_folder(name)` / `remove_folder(name)` / `rename_folder(old, new)`

FileMetadata: name, path, size, content_type, modified_at, url

`list_files` and `find_files` are the key methods for S3 browsing.
S3FileManager is lazily imported from `navigator.utils.file.s3`.
