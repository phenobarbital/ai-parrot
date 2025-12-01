from typing import Optional, Dict, Any, Literal
from pathlib import Path
from datetime import datetime
from pydantic import BaseModel, Field, field_validator
from .abstract import AbstractTool


class FileManagementArgs(BaseModel):
    """Arguments for file management operations."""
    operation: Literal["create", "edit", "delete", "retrieve"] = Field(
        description="Operation to perform: create, edit, delete, or retrieve"
    )
    filename: str = Field(
        description="Target filename or path"
    )
    content: Optional[str] = Field(
        default=None,
        description="Content for create/edit operations"
    )
    edit_mode: Optional[Literal["replace", "append", "prepend"]] = Field(
        default="replace",
        description="Edit mode: replace (overwrite), append (add to end), prepend (add to beginning)"
    )
    extension: Optional[str] = Field(
        default="txt",
        description="File extension for create operation"
    )
    output_dir: Optional[str] = Field(
        default=None,
        description="Output directory (relative or absolute)"
    )
    retrieve_metadata: Optional[bool] = Field(
        default=False,
        description="For retrieve: return metadata only (no content)"
    )
    max_lines: Optional[int] = Field(
        default=None,
        description="For retrieve: limit number of lines to return"
    )

    @field_validator("operation")
    @classmethod
    def validate_operation(cls, v):
        """Validate operation type."""
        valid_ops = ["create", "edit", "delete", "retrieve"]
        if v not in valid_ops:
            raise ValueError(f"Operation must be one of {valid_ops}")
        return v

    @field_validator("content")
    @classmethod
    def validate_content(cls, v, info):
        """Ensure content is provided for create/edit operations."""
        operation = info.data.get("operation")
        if operation in ["create", "edit"] and not v:
            raise ValueError(f"Content is required for {operation} operation")
        return v


class TextFileTool(AbstractTool):
    """Comprehensive file management tool supporting CRUD operations."""

    name = "TextFileTool"
    description = (
        "Manages text files with create, edit, delete, and retrieve operations. "
        "Supports various edit modes and metadata retrieval."
    )
    args_schema = FileManagementArgs

    def _default_output_dir(self) -> Path:
        """Default output directory for text files."""
        return self.static_dir / "documents" / "text"

    def _resolve_file_path(
        self,
        filename: str,
        output_dir: Optional[str] = None,
        must_exist: bool = False
    ) -> Path:
        """
        Resolve the full file path.

        Args:
            filename: Filename or relative path
            output_dir: Optional output directory
            must_exist: If True, raises error if file doesn't exist

        Returns:
            Resolved Path object
        """
        # Determine target directory
        if output_dir:
            target_dir = Path(output_dir)
            if not target_dir.is_absolute():
                target_dir = self.output_dir / target_dir
        else:
            target_dir = self.output_dir

        # Resolve file path
        file_path = target_dir / filename

        # Check existence if required
        if must_exist and not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        return file_path

    async def _create_file(
        self,
        content: str,
        filename: str,
        extension: str = "txt",
        output_dir: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Create a new file with specified content.

        Args:
            content: Text content to write
            filename: Target filename
            extension: File extension
            output_dir: Output directory

        Returns:
            Dictionary with file information
        """
        # Generate filename if needed
        if not filename or filename == "auto":
            ext = extension if extension.startswith('.') else f".{extension}"
            filename = self.generate_filename("text_output", ext)

        # Resolve path
        file_path = self._resolve_file_path(filename, output_dir)

        # Ensure directory exists
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # Validate output path
        file_path = self.validate_output_path(file_path)

        # Check if file already exists
        if file_path.exists():
            raise FileExistsError(
                f"File already exists: {file_path}. Use 'edit' operation to modify."
            )

        # Write content
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)

        # Generate URL
        file_url = self.to_static_url(file_path)

        return {
            "operation": "create",
            "success": True,
            "filename": filename,
            "file_path": str(file_path),
            "file_url": file_url,
            "content_length": len(content),
            "lines": len(content.splitlines()),
            "created_at": datetime.now().isoformat()
        }

    async def _edit_file(
        self,
        content: str,
        filename: str,
        edit_mode: str = "replace",
        output_dir: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Edit an existing file.

        Args:
            content: New content
            filename: Target filename
            edit_mode: Edit mode (replace, append, prepend)
            output_dir: Output directory

        Returns:
            Dictionary with operation results
        """
        # Resolve path (must exist)
        file_path = self._resolve_file_path(
            filename,
            output_dir,
            must_exist=True
        )

        # Get original size
        original_size = file_path.stat().st_size

        # Perform edit based on mode
        if edit_mode == "replace":
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            new_content = content

        elif edit_mode == "append":
            with open(file_path, 'a', encoding='utf-8') as f:
                f.write(content)
            with open(file_path, 'r', encoding='utf-8') as f:
                new_content = f.read()

        elif edit_mode == "prepend":
            with open(file_path, 'r', encoding='utf-8') as f:
                existing = f.read()
            new_content = content + existing
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(new_content)

        # Generate URL
        file_url = self.to_static_url(file_path)

        return {
            "operation": "edit",
            "success": True,
            "edit_mode": edit_mode,
            "filename": filename,
            "file_path": str(file_path),
            "file_url": file_url,
            "original_size": original_size,
            "new_size": len(new_content),
            "content_length": len(new_content),
            "lines": len(new_content.splitlines()),
            "modified_at": datetime.now().isoformat()
        }

    async def _delete_file(
        self,
        filename: str,
        output_dir: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Delete a file.

        Args:
            filename: Target filename
            output_dir: Output directory

        Returns:
            Dictionary with operation results
        """
        # Resolve path (must exist)
        file_path = self._resolve_file_path(
            filename,
            output_dir,
            must_exist=True
        )

        # Get metadata before deletion
        file_size = file_path.stat().st_size
        file_modified = datetime.fromtimestamp(
            file_path.stat().st_mtime
        ).isoformat()

        # Delete the file
        file_path.unlink()

        return {
            "operation": "delete",
            "success": True,
            "filename": filename,
            "file_path": str(file_path),
            "deleted_size": file_size,
            "last_modified": file_modified,
            "deleted_at": datetime.now().isoformat()
        }

    async def _retrieve_file(
        self,
        filename: str,
        output_dir: Optional[str] = None,
        retrieve_metadata: bool = False,
        max_lines: Optional[int] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Retrieve file content or metadata.

        Args:
            filename: Target filename
            output_dir: Output directory
            retrieve_metadata: If True, return only metadata
            max_lines: Maximum number of lines to return

        Returns:
            Dictionary with file content/metadata
        """
        # Resolve path (must exist)
        file_path = self._resolve_file_path(
            filename,
            output_dir,
            must_exist=True
        )

        # Get file stats
        stats = file_path.stat()
        metadata = {
            "filename": filename,
            "file_path": str(file_path),
            "file_url": self.to_static_url(file_path),
            "size_bytes": stats.st_size,
            "created_at": datetime.fromtimestamp(stats.st_ctime).isoformat(),
            "modified_at": datetime.fromtimestamp(stats.st_mtime).isoformat(),
        }

        # If metadata only, return early
        if retrieve_metadata:
            return {
                "operation": "retrieve",
                "success": True,
                "metadata_only": True,
                **metadata
            }

        # Read content
        with open(file_path, 'r', encoding='utf-8') as f:
            if max_lines:
                lines = []
                for i, line in enumerate(f, 1):
                    if i > max_lines:
                        break
                    lines.append(line)
                content = ''.join(lines)
                truncated = True
            else:
                content = f.read()
                truncated = False

        return {
            "operation": "retrieve",
            "success": True,
            "content": content,
            "content_length": len(content),
            "lines": len(content.splitlines()),
            "truncated": truncated,
            **metadata
        }

    async def _execute(
        self,
        operation: str,
        filename: str,
        content: Optional[str] = None,
        edit_mode: str = "replace",
        extension: str = "txt",
        output_dir: Optional[str] = None,
        retrieve_metadata: bool = False,
        max_lines: Optional[int] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Execute the specified file operation.

        Args:
            operation: Operation type (create, edit, delete, retrieve)
            filename: Target filename
            content: Content for create/edit
            edit_mode: Edit mode for edit operation
            extension: File extension for create
            output_dir: Output directory
            retrieve_metadata: Metadata only for retrieve
            max_lines: Line limit for retrieve

        Returns:
            Dictionary with operation results
        """
        try:
            if operation == "create":
                return await self._create_file(
                    content=content,
                    filename=filename,
                    extension=extension,
                    output_dir=output_dir,
                    **kwargs
                )

            elif operation == "edit":
                return await self._edit_file(
                    content=content,
                    filename=filename,
                    edit_mode=edit_mode,
                    output_dir=output_dir,
                    **kwargs
                )

            elif operation == "delete":
                return await self._delete_file(
                    filename=filename,
                    output_dir=output_dir,
                    **kwargs
                )

            elif operation == "retrieve":
                return await self._retrieve_file(
                    filename=filename,
                    output_dir=output_dir,
                    retrieve_metadata=retrieve_metadata,
                    max_lines=max_lines,
                    **kwargs
                )

            else:
                raise ValueError(f"Unknown operation: {operation}")

        except Exception as e:
            return {
                "operation": operation,
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__,
                "timestamp": datetime.now().isoformat()
            }
