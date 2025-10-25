from typing import Literal, Optional, Dict, Any, List, Union
from pathlib import Path
from io import BytesIO, StringIO
import logging
from pydantic import Field
from ..abstract import AbstractTool, AbstractToolArgsSchema, ToolResult
from .abstract import FileManagerInterface
from .local import LocalFileManager
from .tmp import TempFileManager
from .s3 import S3FileManager
from .gcs import GCSFileManager


class FileManagerFactory:
    """Factory for creating file managers"""

    @staticmethod
    def create(
        manager_type: Literal["fs", "temp", "s3", "gcs"],
        **kwargs
    ) -> FileManagerInterface:
        """Create a file manager instance"""
        managers = {
            "fs": LocalFileManager,
            "temp": TempFileManager,
            "s3": S3FileManager,
            "gcs": GCSFileManager,
        }

        if manager_type not in managers:
            raise ValueError(
                f"Unknown manager type: {manager_type}. "
                f"Available: {list(managers.keys())}"
            )

        return managers[manager_type](**kwargs)


class FileManagerToolArgs(AbstractToolArgsSchema):
    """
    Arguments schema for FileManagerTool.

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
    """
    Tool for AI agents to interact with file systems.

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
        default_output_dir: str = "./outputs",
        allowed_operations: Optional[set] = None,
        max_file_size: int = 100 * 1024 * 1024,  # 100MB
        auto_create_dirs: bool = True,
        **manager_kwargs
    ):
        """
        Initialize file manager tool.

        Args:
            manager_type: Type of file manager ("fs", "temp", "s3", "gcs")
            default_output_dir: Default directory for file operations
            allowed_operations: Set of allowed operations (None = all allowed)
            max_file_size: Maximum file size in bytes
            auto_create_dirs: Automatically create directories
            **manager_kwargs: Additional arguments for the specific manager
        """
        super().__init__()

        self.manager_type = manager_type
        self.default_output_dir = default_output_dir
        self.max_file_size = max_file_size
        self.auto_create_dirs = auto_create_dirs
        self.logger = logging.getLogger('ai_parrot.tools.FileManager')

        # Default to all operations if not specified
        self.allowed_operations = allowed_operations or {
            "list", "upload", "download", "copy", "delete",
            "exists", "get_url", "get_metadata", "create"
        }

        # Create the appropriate file manager
        self.manager = self._create_manager(manager_type, **manager_kwargs)

        # Update description with specific manager type
        self.description = (
            f"Manage files in {manager_type} storage. "
            f"Default output directory: {default_output_dir}. "
            f"Allowed operations: {', '.join(sorted(self.allowed_operations))}. "
            f"Max file size: {max_file_size / (1024*1024):.1f}MB"
        )

        self.logger.info(
            f"FileManagerTool initialized with {manager_type} manager, "
            f"output dir: {default_output_dir}"
        )

    def _create_manager(
        self,
        manager_type: str,
        **kwargs
    ) -> FileManagerInterface:
        """Create file manager with type-specific defaults"""
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
        """Check if operation is allowed"""
        if operation not in self.allowed_operations:
            raise PermissionError(
                f"Operation '{operation}' not allowed. "
                f"Allowed: {self.allowed_operations}"
            )

    def _check_file_size(self, size: int):
        """Check if file size is within limits"""
        if size > self.max_file_size:
            raise ValueError(
                f"File size ({size} bytes) exceeds maximum "
                f"allowed size ({self.max_file_size} bytes)"
            )

    def _resolve_output_path(self, path: Optional[str] = None) -> str:
        """Resolve path relative to default output directory"""
        if path is None:
            return self.default_output_dir

        if Path(path).is_absolute() or path.startswith(self.default_output_dir):
            return path

        return str(Path(self.default_output_dir) / path)

    async def _execute(self, **kwargs) -> ToolResult:
        """
        Execute file operation based on the operation field.

        This is the main router method that dispatches to specific operations.
        The LLM must provide an 'operation' field to determine which action to perform.

        Args:
            **kwargs: Arguments matching FileManagerToolArgs schema

        Returns:
            ToolResult with operation results
        """
        # Validate and extract operation
        args = FileManagerToolArgs(**kwargs)
        operation = args.operation

        self.logger.info(f"Executing operation: {operation}")

        # Check if operation is allowed
        self._check_operation(operation)

        try:
            # Route to appropriate operation
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
        """List files in a directory"""
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
        """Upload a file to storage"""
        if not args.source_path:
            raise ValueError("source_path is required for upload operation")

        source = Path(args.source_path)

        if not source.exists():
            raise FileNotFoundError(f"Source file not found: {args.source_path}")

        # Check file size
        file_size = source.stat().st_size
        self._check_file_size(file_size)

        # Determine destination
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
        """Download a file from storage"""
        if not args.path:
            raise ValueError("path is required for download operation")

        # Default destination in output dir
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
        """Copy a file within storage"""
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
        """Delete a file from storage"""
        if not args.path:
            raise ValueError("path is required for delete operation")

        self.logger.info(f"Deleting file '{args.path}'")

        deleted = await self.manager.delete_file(args.path)

        return {
            "deleted": deleted,
            "path": args.path
        }

    async def _exists(self, args: FileManagerToolArgs) -> Dict[str, Any]:
        """Check if a file exists"""
        if not args.path:
            raise ValueError("path is required for exists operation")

        exists = await self.manager.exists(args.path)

        return {
            "exists": exists,
            "path": args.path
        }

    async def _get_file_url(self, args: FileManagerToolArgs) -> Dict[str, Any]:
        """Get a URL to access the file"""
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
        """Get detailed metadata about a file"""
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
        """Create a new file with content"""
        if not args.path:
            raise ValueError("path is required for create operation")
        if not args.content:
            raise ValueError("content is required for create operation")

        # Convert string to bytes
        encoding = args.encoding or 'utf-8'
        content_bytes = args.content.encode(encoding)

        # Check size
        self._check_file_size(len(content_bytes))

        dest = self._resolve_output_path(args.path)

        self.logger.info(f"Creating file '{dest}' ({len(content_bytes)} bytes)")

        # Use create_from_bytes
        metadata = await self.manager.create_from_bytes(
            dest,
            BytesIO(content_bytes)
        )

        return {
            "created": True,
            "name": metadata.name,
            "path": metadata.path,
            "size": metadata.size,
            "content_type": metadata.content_type,
            "url": metadata.url
        }
