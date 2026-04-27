"""FileManagerTool and FileManagerToolkit — tools for AI agents to interact with file systems.

Implementations live in parrot.interfaces.file:
- LocalFileManager / TempFileManager: always available (stdlib only)
- S3FileManager / GCSFileManager: lazy-loaded (require aioboto3 / google-cloud-storage)

Preferred API: ``FileManagerToolkit`` — each file operation is a separate, focused tool.
Legacy API: ``FileManagerTool`` — single tool with an ``operation`` dispatch field (deprecated).
"""
from typing import Literal, Optional, Dict, Any, Union, Set
from pathlib import Path
from io import BytesIO
import logging
from pydantic import Field
from .abstract import AbstractTool, AbstractToolArgsSchema, ToolResult
from .toolkit import AbstractToolkit
from parrot.conf import OUTPUT_DIR
from parrot.interfaces.file import FileManagerInterface
from navigator.utils.file import FileManagerFactory as _UpstreamFileManagerFactory


class FileManagerFactory:
    """Factory for creating file managers.

    Thin delegate over ``navigator.utils.file.FileManagerFactory``.
    Maps the historical parrot-side key ``"fs"`` to the upstream
    ``"local"`` key; forwards all other keys verbatim.
    """

    _PARROT_TO_UPSTREAM = {
        "fs": "local",
        "temp": "temp",
        "s3": "s3",
        "gcs": "gcs",
    }

    @staticmethod
    def create(
        manager_type: Literal["fs", "temp", "s3", "gcs"],
        **kwargs: Any,
    ) -> FileManagerInterface:
        """Create a file manager instance via the upstream factory.

        Args:
            manager_type: One of ``"fs"`` (local disk), ``"temp"``,
                ``"s3"``, ``"gcs"``.
            **kwargs: Forwarded to the upstream manager constructor.

        Returns:
            A FileManagerInterface instance.

        Raises:
            ValueError: If ``manager_type`` is not recognised.
        """
        try:
            upstream_key = FileManagerFactory._PARROT_TO_UPSTREAM[manager_type]
        except KeyError:
            raise ValueError(
                f"Unknown manager type: {manager_type}. "
                f"Available: {sorted(FileManagerFactory._PARROT_TO_UPSTREAM)}"
            )
        return _UpstreamFileManagerFactory.create(upstream_key, **kwargs)


class FileManagerToolArgs(AbstractToolArgsSchema):
    """Arguments schema for FileManagerTool.

    The operation field determines which file operation to perform.
    Each operation requires different additional fields.
    """

    operation: Literal[
        "list", "upload", "download", "copy", "delete",
        "exists", "get_url", "get_metadata", "create"
    ] = Field(
        ...,
        description=(
            "The file operation to perform. Options:\n"
            "- 'list': List files in a directory\n"
            "- 'upload': Upload a file to storage\n"
            "- 'download': Download a file from storage\n"
            "- 'copy': Copy a file within storage\n"
            "- 'delete': Delete a file from storage\n"
            "- 'exists': Check if a file exists\n"
            "- 'get_url': Get a URL to access a file\n"
            "- 'get_metadata': Get detailed file metadata\n"
            "- 'create': Create a new file with content"
        )
    )

    # Common fields
    path: Optional[Union[str, Path]] = Field(
        None,
        description="File or directory path. Used by most operations."
    )

    # List operation
    pattern: Optional[str] = Field(
        "*",
        description="Filename pattern for list operation (e.g., '*.txt', '*.pdf')"
    )

    # Upload operation
    source_path: Optional[str] = Field(
        None,
        description="Source file path for upload operation"
    )
    destination: Optional[str] = Field(
        None,
        description="Destination path or directory"
    )
    destination_name: Optional[str] = Field(
        None,
        description="Custom name for uploaded file (uses source name if not provided)"
    )

    # Copy operation
    source: Optional[str] = Field(
        None,
        description="Source file path for copy operation"
    )

    # Create operation
    content: Optional[str] = Field(
        None,
        description="Text content for create operation"
    )
    encoding: Optional[str] = Field(
        "utf-8",
        description="Text encoding for create operation"
    )

    # URL operation
    expiry_seconds: Optional[int] = Field(
        3600,
        description="URL expiry time in seconds (default: 3600 = 1 hour)"
    )


class FileManagerTool(AbstractTool):
    """Tool for AI agents to interact with file systems.

    .. deprecated::
        ``FileManagerTool`` uses a multi-operation dispatch pattern (an ``operation``
        field that routes to one of nine sub-operations).  This flat schema confuses
        LLMs because every call must include the ``operation`` key and the parameters
        vary by operation.  Prefer :class:`FileManagerToolkit` instead — it exposes
        each operation as a separate, focused tool with a minimal, unambiguous schema.

    Provides secure file operations across different storage backends:
    - 'fs': Local filesystem
    - 'temp': Temporary storage (auto-cleanup)
    - 's3': AWS S3 buckets
    - 'gcs': Google Cloud Storage

    Usage Pattern:
    The LLM must specify an 'operation' field to route to the correct action.
    Each operation has specific required and optional fields.

    Examples:
        List files: {"operation": "list", "path": "documents", "pattern": "*.pdf"}
        Upload: {"operation": "upload", "source_path": "/tmp/file.txt", "destination": "uploads"}
        Download: {"operation": "download", "path": "reports/summary.pdf", "destination": "/tmp/summary.pdf"}
        Get URL: {"operation": "get_url", "path": "shared/file.zip", "expiry_seconds": 7200}
        Create: {"operation": "create", "path": "output.txt", "content": "Hello, World!"}
    """

    name: str = "file_manager"
    description: str = "Manage files across different storage backends (local, S3, GCS, temp)"
    args_schema: type[AbstractToolArgsSchema] = FileManagerToolArgs

    def __init__(
        self,
        manager_type: Literal["fs", "temp", "s3", "gcs"] = "fs",
        default_output_dir: str = None,
        allowed_operations: Optional[set] = None,
        max_file_size: int = 100 * 1024 * 1024,  # 100MB
        auto_create_dirs: bool = True,
        **manager_kwargs
    ):
        """Initialize file manager tool.

        Args:
            manager_type: Type of file manager ("fs", "temp", "s3", "gcs").
            default_output_dir: Default directory for file operations.
            allowed_operations: Set of allowed operations (None = all allowed).
            max_file_size: Maximum file size in bytes.
            auto_create_dirs: Automatically create directories.
            **manager_kwargs: Additional arguments for the specific manager.
        """
        super().__init__()

        self.manager_type = manager_type
        self.default_output_dir = default_output_dir or str(OUTPUT_DIR)
        self.max_file_size = max_file_size
        self.auto_create_dirs = auto_create_dirs
        self.logger = logging.getLogger('ai_parrot.tools.FileManager')

        self.allowed_operations = allowed_operations or {
            "list", "upload", "download", "copy", "delete",
            "exists", "get_url", "get_metadata", "create"
        }

        self.manager = self._create_manager(manager_type, **manager_kwargs)

        self.description = (
            f"Manage files in {manager_type} storage. "
            f"Default output directory: {self.default_output_dir}. "
            f"Allowed operations: {', '.join(sorted(self.allowed_operations))}. "
            f"Max file size: {max_file_size / (1024*1024):.1f}MB"
        )

        self.logger.info(
            f"FileManagerTool initialized with {manager_type} manager, "
            f"output dir: {self.default_output_dir}"
        )

    def _create_manager(
        self,
        manager_type: str,
        **kwargs
    ) -> FileManagerInterface:
        """Create file manager with type-specific defaults."""
        if manager_type == "fs":
            return FileManagerFactory.create(
                manager_type,
                base_path=kwargs.get('base_path', Path.cwd()),
                sandboxed=kwargs.get('sandboxed', True),
                **{k: v for k, v in kwargs.items() if k not in ['base_path', 'sandboxed']}
            )
        elif manager_type == "temp":
            return FileManagerFactory.create(
                manager_type,
                cleanup_on_exit=kwargs.get('cleanup_on_exit', True),
                **{k: v for k, v in kwargs.items() if k != 'cleanup_on_exit'}
            )
        else:  # s3 or gcs
            return FileManagerFactory.create(manager_type, **kwargs)

    def _check_operation(self, operation: str):
        """Check if operation is allowed."""
        if operation not in self.allowed_operations:
            raise PermissionError(
                f"Operation '{operation}' not allowed. "
                f"Allowed: {self.allowed_operations}"
            )

    def _check_file_size(self, size: int):
        """Check if file size is within limits."""
        if size > self.max_file_size:
            raise ValueError(
                f"File size ({size} bytes) exceeds maximum "
                f"allowed size ({self.max_file_size} bytes)"
            )

    def _resolve_output_path(self, path: Optional[str] = None) -> str:
        """Resolve path relative to default output directory."""
        if path is None:
            return self.default_output_dir

        if Path(path).is_absolute() or path.startswith(self.default_output_dir):
            return path

        return str(Path(self.default_output_dir) / path)

    async def _execute(self, **kwargs) -> ToolResult:
        """Execute file operation based on the operation field."""
        args = FileManagerToolArgs(**kwargs)
        operation = args.operation

        self.logger.info(f"Executing operation: {operation}")
        self._check_operation(operation)

        try:
            if operation == "list":
                result = await self._list_files(args)
            elif operation == "upload":
                result = await self._upload_file(args)
            elif operation == "download":
                result = await self._download_file(args)
            elif operation == "copy":
                result = await self._copy_file(args)
            elif operation == "delete":
                result = await self._delete_file(args)
            elif operation == "exists":
                result = await self._exists(args)
            elif operation == "get_url":
                result = await self._get_file_url(args)
            elif operation == "get_metadata":
                result = await self._get_file_metadata(args)
            elif operation == "create":
                result = await self._create_file(args)
            else:
                return ToolResult(
                    success=False,
                    result=None,
                    error=f"Unknown operation: {operation}"
                )

            return ToolResult(
                success=True,
                result=result,
                metadata={
                    "operation": operation,
                    "manager_type": self.manager_type
                }
            )

        except Exception as e:
            self.logger.error(f"Operation {operation} failed: {str(e)}", exc_info=True)
            return ToolResult(
                success=False,
                error=str(e),
                metadata={
                    "operation": operation,
                    "manager_type": self.manager_type
                }
            )

    async def _list_files(self, args: FileManagerToolArgs) -> Dict[str, Any]:
        """List files in a directory."""
        path = self._resolve_output_path(args.path) if args.path else ""
        pattern = args.pattern or "*"

        self.logger.info(f"Listing files in '{path}' with pattern '{pattern}'")
        files = await self.manager.list_files(path, pattern)

        return {
            "files": [
                {
                    "name": f.name,
                    "path": f.path,
                    "size": f.size,
                    "content_type": f.content_type,
                    "modified_at": f.modified_at.isoformat() if f.modified_at else None,
                    "url": f.url
                }
                for f in files
            ],
            "count": len(files),
            "directory": path,
            "pattern": pattern
        }

    async def _upload_file(self, args: FileManagerToolArgs) -> Dict[str, Any]:
        """Upload a file to storage."""
        if not args.source_path:
            raise ValueError("source_path is required for upload operation")

        source = Path(args.source_path)
        if not source.exists():
            raise FileNotFoundError(f"Source file not found: {args.source_path}")

        file_size = source.stat().st_size
        self._check_file_size(file_size)

        dest = args.destination_name or source.name
        if args.destination:
            dest = str(Path(args.destination) / dest)
        dest = self._resolve_output_path(dest)

        self.logger.info(f"Uploading '{args.source_path}' to '{dest}'")
        metadata = await self.manager.upload_file(source, dest)

        return {
            "uploaded": True,
            "name": metadata.name,
            "path": metadata.path,
            "size": metadata.size,
            "content_type": metadata.content_type,
            "url": metadata.url
        }

    async def _download_file(self, args: FileManagerToolArgs) -> Dict[str, Any]:
        """Download a file from storage."""
        if not args.path:
            raise ValueError("path is required for download operation")

        if args.destination is None:
            destination = self._resolve_output_path(Path(args.path).name)
        else:
            destination = args.destination

        dest_path = Path(destination)
        self.logger.info(f"Downloading '{args.path}' to '{destination}'")
        result = await self.manager.download_file(args.path, dest_path)

        return {
            "downloaded": True,
            "source": args.path,
            "destination": str(result),
            "size": dest_path.stat().st_size if dest_path.exists() else 0
        }

    async def _copy_file(self, args: FileManagerToolArgs) -> Dict[str, Any]:
        """Copy a file within storage."""
        if not args.source:
            raise ValueError("source is required for copy operation")
        if not args.destination:
            raise ValueError("destination is required for copy operation")

        self.logger.info(f"Copying '{args.source}' to '{args.destination}'")
        metadata = await self.manager.copy_file(args.source, args.destination)

        return {
            "copied": True,
            "source": args.source,
            "destination": args.destination,
            "name": metadata.name,
            "size": metadata.size,
            "url": metadata.url
        }

    async def _delete_file(self, args: FileManagerToolArgs) -> Dict[str, Any]:
        """Delete a file from storage."""
        if not args.path:
            raise ValueError("path is required for delete operation")

        self.logger.info(f"Deleting file '{args.path}'")
        deleted = await self.manager.delete_file(args.path)

        return {
            "deleted": deleted,
            "path": args.path
        }

    async def _exists(self, args: FileManagerToolArgs) -> Dict[str, Any]:
        """Check if a file exists."""
        if not args.path:
            raise ValueError("path is required for exists operation")

        exists = await self.manager.exists(args.path)
        return {
            "exists": exists,
            "path": args.path
        }

    async def _get_file_url(self, args: FileManagerToolArgs) -> Dict[str, Any]:
        """Get a URL to access the file."""
        if not args.path:
            raise ValueError("path is required for get_url operation")

        expiry = args.expiry_seconds or 3600
        url = await self.manager.get_file_url(args.path, expiry)

        return {
            "url": url,
            "path": args.path,
            "expiry_seconds": expiry
        }

    async def _get_file_metadata(self, args: FileManagerToolArgs) -> Dict[str, Any]:
        """Get detailed metadata about a file."""
        if not args.path:
            raise ValueError("path is required for get_metadata operation")

        metadata = await self.manager.get_file_metadata(args.path)

        return {
            "name": metadata.name,
            "path": metadata.path,
            "size": metadata.size,
            "content_type": metadata.content_type,
            "modified_at": metadata.modified_at.isoformat() if metadata.modified_at else None,
            "url": metadata.url
        }

    async def _create_file(self, args: FileManagerToolArgs) -> Dict[str, Any]:
        """Create a new file with content."""
        if not args.path:
            raise ValueError("path is required for create operation")
        if not args.content:
            raise ValueError("content is required for create operation")

        encoding = args.encoding or 'utf-8'
        content_bytes = args.content.encode(encoding)
        self._check_file_size(len(content_bytes))

        dest = self._resolve_output_path(args.path)
        self.logger.info(f"Creating file '{dest}' ({len(content_bytes)} bytes)")

        # Upstream create_from_bytes returns bool; fetch metadata explicitly.
        await self.manager.create_from_bytes(dest, BytesIO(content_bytes))
        metadata = await self.manager.get_file_metadata(dest)

        return {
            "created": True,
            "name": metadata.name,
            "path": metadata.path,
            "size": metadata.size,
            "content_type": metadata.content_type,
            "url": metadata.url,
        }


# ---------------------------------------------------------------------------
# FileManagerToolkit — preferred API (one tool per operation)
# ---------------------------------------------------------------------------

#: Maps allowed_operations keys → method names used in exclude_tools filtering.
_OP_TO_METHOD: Dict[str, str] = {
    "list": "list_files",
    "upload": "upload_file",
    "download": "download_file",
    "copy": "copy_file",
    "delete": "delete_file",
    "exists": "file_exists",
    "get_url": "get_file_url",
    "get_metadata": "get_file_metadata",
    "create": "create_file",
}
_ALL_OPS: frozenset = frozenset(_OP_TO_METHOD)


class FileManagerToolkit(AbstractToolkit):
    """Toolkit for AI agents to interact with file systems — preferred API.

    Exposes each file operation as a separate, focused tool with a minimal
    schema.  LLMs no longer need to know about an ``operation`` dispatch field;
    they simply call the right tool directly.

    Tool names (with ``tool_prefix="fs"``):
      - ``fs_list_files``      — list files in a directory
      - ``fs_upload_file``     — upload a local file to storage
      - ``fs_download_file``   — download a file from storage
      - ``fs_copy_file``       — copy a file within storage
      - ``fs_delete_file``     — delete a file from storage
      - ``fs_file_exists``     — check whether a file exists
      - ``fs_get_file_url``    — get a URL to access a file
      - ``fs_get_file_metadata`` — fetch detailed file metadata
      - ``fs_create_file``     — create a new file with text content

    Supported backends:
      - ``"fs"``   — local filesystem (sandboxed by default)
      - ``"temp"`` — temporary storage (auto-cleaned on exit)
      - ``"s3"``   — AWS S3 (requires aioboto3)
      - ``"gcs"``  — Google Cloud Storage (requires google-cloud-storage)

    Example::

        toolkit = FileManagerToolkit(manager_type="fs")
        tools = toolkit.get_tools()   # returns 9 AbstractTool instances
        result = await toolkit.list_files(path="docs", pattern="*.md")
    """

    #: Namespace prefix applied to every auto-generated tool name.
    tool_prefix: Optional[str] = "fs"

    def __init__(
        self,
        manager_type: Literal["fs", "temp", "s3", "gcs"] = "fs",
        default_output_dir: Optional[str] = None,
        allowed_operations: Optional[Set[str]] = None,
        max_file_size: int = 100 * 1024 * 1024,  # 100 MB
        auto_create_dirs: bool = True,
        **manager_kwargs: Any,
    ) -> None:
        """Initialise the file manager toolkit.

        Args:
            manager_type: Storage backend — one of ``"fs"``, ``"temp"``,
                ``"s3"``, ``"gcs"``.
            default_output_dir: Default directory for resolving relative paths.
                Defaults to ``parrot.conf.OUTPUT_DIR``.
            allowed_operations: Restrict which operations are exposed as tools.
                Pass a subset of ``{"list", "upload", "download", "copy",
                "delete", "exists", "get_url", "get_metadata", "create"}``.
                ``None`` means all operations are allowed (default).
            max_file_size: Maximum file size in bytes (default 100 MB).
                Enforced on ``create_file`` and ``upload_file``.
            auto_create_dirs: Automatically create parent directories when
                writing files (default ``True``).
            **manager_kwargs: Extra keyword arguments forwarded to the
                backend manager constructor (e.g. ``base_path``, ``bucket``).
        """
        # Compute exclude_tools BEFORE super().__init__ so that
        # _generate_tools() sees the instance-level override.
        if allowed_operations is not None:
            self.exclude_tools = tuple(
                method
                for op, method in _OP_TO_METHOD.items()
                if op not in allowed_operations
            )

        super().__init__()

        self.manager_type = manager_type
        self.default_output_dir = default_output_dir or str(OUTPUT_DIR)
        self.max_file_size = max_file_size
        self.auto_create_dirs = auto_create_dirs
        self.allowed_operations: Set[str] = (
            allowed_operations if allowed_operations is not None else set(_ALL_OPS)
        )

        self.manager: FileManagerInterface = self._create_manager(
            manager_type, **manager_kwargs
        )

        self.logger.info(
            "FileManagerToolkit initialised — backend=%s output_dir=%s ops=%s",
            manager_type,
            self.default_output_dir,
            sorted(self.allowed_operations),
        )

    # ── Private helpers ─────────────────────────────────────────────────────

    def _create_manager(
        self,
        manager_type: str,
        **kwargs: Any,
    ) -> FileManagerInterface:
        """Create the underlying file manager, applying type-specific defaults.

        Args:
            manager_type: Backend type key.
            **kwargs: Forwarded to the factory.

        Returns:
            A ``FileManagerInterface`` instance.
        """
        if manager_type == "fs":
            return FileManagerFactory.create(
                manager_type,
                base_path=kwargs.get("base_path", Path.cwd()),
                sandboxed=kwargs.get("sandboxed", True),
                **{k: v for k, v in kwargs.items() if k not in ("base_path", "sandboxed")},
            )
        elif manager_type == "temp":
            return FileManagerFactory.create(
                manager_type,
                cleanup_on_exit=kwargs.get("cleanup_on_exit", True),
                **{k: v for k, v in kwargs.items() if k != "cleanup_on_exit"},
            )
        else:  # s3 or gcs
            return FileManagerFactory.create(manager_type, **kwargs)

    def _check_file_size(self, size: int) -> None:
        """Raise ``ValueError`` when *size* exceeds ``max_file_size``.

        Args:
            size: File size in bytes to check.

        Raises:
            ValueError: If *size* is larger than ``self.max_file_size``.
        """
        if size > self.max_file_size:
            raise ValueError(
                f"File size ({size} bytes) exceeds maximum allowed size "
                f"({self.max_file_size} bytes)"
            )

    def _resolve_output_path(self, path: Optional[str] = None) -> str:
        """Resolve *path* relative to the default output directory.

        Args:
            path: Relative or absolute path string.  ``None`` returns the
                default output directory itself.

        Returns:
            Absolute path string.
        """
        if path is None:
            return self.default_output_dir
        if Path(path).is_absolute() or path.startswith(self.default_output_dir):
            return path
        return str(Path(self.default_output_dir) / path)

    # ── Public tools (9) ────────────────────────────────────────────────────

    async def list_files(
        self,
        path: str = "",
        pattern: str = "*",
    ) -> Dict[str, Any]:
        """List files in a directory on the configured storage backend.

        Returns a dictionary with keys ``files`` (list of file info dicts),
        ``count`` (int), ``directory`` (str), and ``pattern`` (str).

        Args:
            path: Directory path to list.  Defaults to the root of the
                configured storage.
            pattern: Glob pattern to filter filenames (e.g. ``"*.pdf"``).
                Defaults to ``"*"`` (all files).

        Returns:
            Dict containing ``files``, ``count``, ``directory``, ``pattern``.
        """
        resolved = self._resolve_output_path(path) if path else ""
        self.logger.info("Listing files in '%s' with pattern '%s'", resolved, pattern)
        files = await self.manager.list_files(resolved, pattern)
        return {
            "files": [
                {
                    "name": f.name,
                    "path": f.path,
                    "size": f.size,
                    "content_type": f.content_type,
                    "modified_at": f.modified_at.isoformat() if f.modified_at else None,
                    "url": f.url,
                }
                for f in files
            ],
            "count": len(files),
            "directory": resolved,
            "pattern": pattern,
        }

    async def upload_file(
        self,
        source_path: str,
        destination: Optional[str] = None,
        destination_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Upload a local file to the configured storage backend.

        Checks that the file exists and that its size does not exceed the
        configured ``max_file_size`` limit before uploading.

        Args:
            source_path: Absolute or relative path to the local file to upload.
            destination: Destination directory on the backend.  Defaults to the
                toolkit's ``default_output_dir``.
            destination_name: Custom name for the uploaded file.  Defaults to
                the source filename.

        Returns:
            Dict with keys ``uploaded``, ``name``, ``path``, ``size``,
            ``content_type``, and ``url``.

        Raises:
            ValueError: If ``source_path`` is missing or the file is too large.
            FileNotFoundError: If the source file does not exist on disk.
        """
        source = Path(source_path)
        if not source.exists():
            raise FileNotFoundError(f"Source file not found: {source_path}")

        file_size = source.stat().st_size
        self._check_file_size(file_size)

        dest = destination_name or source.name
        if destination:
            dest = str(Path(destination) / dest)
        dest = self._resolve_output_path(dest)

        self.logger.info("Uploading '%s' to '%s'", source_path, dest)
        metadata = await self.manager.upload_file(source, dest)
        return {
            "uploaded": True,
            "name": metadata.name,
            "path": metadata.path,
            "size": metadata.size,
            "content_type": metadata.content_type,
            "url": metadata.url,
        }

    async def download_file(
        self,
        path: str,
        destination: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Download a file from the storage backend to the local filesystem.

        Args:
            path: Path of the file on the storage backend.
            destination: Local path where the file will be saved.  Defaults to
                the toolkit's ``default_output_dir`` using the source filename.

        Returns:
            Dict with keys ``downloaded``, ``source``, ``destination``, and
            ``size`` (bytes saved on disk).

        Raises:
            ValueError: If ``path`` is empty.
        """
        if not path:
            raise ValueError("path is required for download_file")

        if destination is None:
            destination = self._resolve_output_path(Path(path).name)

        dest_path = Path(destination)
        self.logger.info("Downloading '%s' to '%s'", path, destination)
        result = await self.manager.download_file(path, dest_path)
        return {
            "downloaded": True,
            "source": path,
            "destination": str(result),
            "size": dest_path.stat().st_size if dest_path.exists() else 0,
        }

    async def copy_file(
        self,
        source: str,
        destination: str,
    ) -> Dict[str, Any]:
        """Copy a file within the configured storage backend.

        Args:
            source: Source path of the file to copy.
            destination: Destination path for the copied file.

        Returns:
            Dict with keys ``copied``, ``source``, ``destination``, ``name``,
            ``size``, and ``url``.

        Raises:
            ValueError: If either ``source`` or ``destination`` is empty.
        """
        if not source:
            raise ValueError("source is required for copy_file")
        if not destination:
            raise ValueError("destination is required for copy_file")

        self.logger.info("Copying '%s' to '%s'", source, destination)
        metadata = await self.manager.copy_file(source, destination)
        return {
            "copied": True,
            "source": source,
            "destination": destination,
            "name": metadata.name,
            "size": metadata.size,
            "url": metadata.url,
        }

    async def delete_file(
        self,
        path: str,
    ) -> Dict[str, Any]:
        """Delete a file from the configured storage backend.

        Args:
            path: Path of the file to delete on the storage backend.

        Returns:
            Dict with keys ``deleted`` (bool) and ``path`` (str).

        Raises:
            ValueError: If ``path`` is empty.
        """
        if not path:
            raise ValueError("path is required for delete_file")

        self.logger.info("Deleting file '%s'", path)
        deleted = await self.manager.delete_file(path)
        return {
            "deleted": deleted,
            "path": path,
        }

    async def file_exists(
        self,
        path: str,
    ) -> Dict[str, Any]:
        """Check whether a file exists on the configured storage backend.

        Args:
            path: Path of the file to check.

        Returns:
            Dict with keys ``exists`` (bool) and ``path`` (str).

        Raises:
            ValueError: If ``path`` is empty.
        """
        if not path:
            raise ValueError("path is required for file_exists")

        exists = await self.manager.exists(path)
        return {
            "exists": exists,
            "path": path,
        }

    async def get_file_url(
        self,
        path: str,
        expiry_seconds: int = 3600,
    ) -> Dict[str, Any]:
        """Get a URL to access a file on the configured storage backend.

        For cloud backends (S3, GCS) this generates a pre-signed URL valid for
        ``expiry_seconds``.  For local backends it typically returns the file
        path or a static URL.

        Args:
            path: Path of the file on the storage backend.
            expiry_seconds: URL validity duration in seconds (default 3 600 = 1 hour).

        Returns:
            Dict with keys ``url`` (str), ``path`` (str), and
            ``expiry_seconds`` (int).

        Raises:
            ValueError: If ``path`` is empty.
        """
        if not path:
            raise ValueError("path is required for get_file_url")

        url = await self.manager.get_file_url(path, expiry_seconds)
        return {
            "url": url,
            "path": path,
            "expiry_seconds": expiry_seconds,
        }

    async def get_file_metadata(
        self,
        path: str,
    ) -> Dict[str, Any]:
        """Retrieve detailed metadata for a file on the storage backend.

        Args:
            path: Path of the file whose metadata should be fetched.

        Returns:
            Dict with keys ``name``, ``path``, ``size``, ``content_type``,
            ``modified_at`` (ISO-8601 string or ``None``), and ``url``.

        Raises:
            ValueError: If ``path`` is empty.
        """
        if not path:
            raise ValueError("path is required for get_file_metadata")

        metadata = await self.manager.get_file_metadata(path)
        return {
            "name": metadata.name,
            "path": metadata.path,
            "size": metadata.size,
            "content_type": metadata.content_type,
            "modified_at": metadata.modified_at.isoformat() if metadata.modified_at else None,
            "url": metadata.url,
        }

    async def create_file(
        self,
        path: str,
        content: str,
        encoding: str = "utf-8",
    ) -> Dict[str, Any]:
        """Create a new text file on the configured storage backend.

        Encodes *content* using *encoding*, checks the resulting byte length
        against ``max_file_size``, then writes the file and returns metadata.

        Args:
            path: Destination path for the new file (relative to
                ``default_output_dir`` unless absolute).
            content: Text content to write to the file.
            encoding: Character encoding for the content (default ``"utf-8"``).

        Returns:
            Dict with keys ``created`` (``True``), ``name``, ``path``,
            ``size``, ``content_type``, and ``url``.

        Raises:
            ValueError: If ``path`` or ``content`` is empty, or if the encoded
                content exceeds ``max_file_size``.
        """
        if not path:
            raise ValueError("path is required for create_file")
        if not content:
            raise ValueError("content is required for create_file")

        content_bytes = content.encode(encoding)
        self._check_file_size(len(content_bytes))

        dest = self._resolve_output_path(path)
        self.logger.info("Creating file '%s' (%d bytes)", dest, len(content_bytes))

        # Upstream create_from_bytes returns bool; fetch metadata explicitly.
        await self.manager.create_from_bytes(dest, BytesIO(content_bytes))
        metadata = await self.manager.get_file_metadata(dest)

        return {
            "created": True,
            "name": metadata.name,
            "path": metadata.path,
            "size": metadata.size,
            "content_type": metadata.content_type,
            "url": metadata.url,
        }
