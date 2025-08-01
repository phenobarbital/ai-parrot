"""
AbstractDocumentTool - Base class for document generation tools.

This extends AbstractTool with common functionality for document generators like:
- PowerPoint, Word, Excel, PDF tools
- Standard document output management
- File path validation and generation
- Async file operations
- Template management
"""
from abc import abstractmethod
from typing import Any, Dict, Optional, Union, List
import re
from pathlib import Path
from datetime import datetime
import aiofiles
import aiofiles.os
import pandas as pd
from pydantic import BaseModel, Field, field_validator
from .abstract import AbstractTool


class DocumentGenerationArgs(BaseModel):
    """Base arguments schema for document generation tools."""

    content: str = Field(
        ...,
        description="Content to be converted to document (text, markdown, HTML, etc.)"
    )
    output_filename: Optional[str] = Field(
        None,
        description="Custom filename for the output document (without extension). If None, auto-generates with timestamp"
    )
    file_prefix: str = Field(
        "document",
        description="Prefix for auto-generated filenames"
    )
    output_dir: Optional[str] = Field(
        None,
        description="Custom output directory. If None, uses tool's default directory"
    )
    overwrite_existing: bool = Field(
        False,
        description="Whether to overwrite existing files with the same name"
    )

    @field_validator('output_filename')
    @classmethod
    def validate_filename(cls, v):
        if v is not None:
            # Remove invalid filename characters
            invalid_chars = r'[<>:"/\\|?*]'
            if re.search(invalid_chars, v):
                raise ValueError(f"Filename contains invalid characters: {invalid_chars}")
        return v

    @field_validator('file_prefix')
    @classmethod
    def validate_file_prefix(cls, v):
        # Clean file prefix
        return re.sub(r'[<>:"/\\|?*]', '_', v) if v else "document"


class DocumentMetadata(BaseModel):
    """Metadata for generated documents."""

    filename: str = Field(
        ...,
        description="Name of the generated document file"
    )
    file_path: str = Field(
        ...,
        description="Full path to the generated document file"
    )
    file_url: str = Field(
        ...,
        description="Public URL to access the generated document file"
    )
    relative_url: str = Field(
        ...,
        description="Relative URL to access the generated document file"
    )
    file_size: int = Field(
        ...,
        description="Size of the generated document file in bytes"
    )
    file_size_mb: float = Field(
        ...,
        description="Size of the generated document file in megabytes"
    )
    file_extension: str = Field(
        ...,
        description="File extension of the generated document"
    )
    created_at: str = Field(
        ...,
        description="Timestamp when the document was created"
    )
    content_length: int = Field(
        ...,
        description="Length of the document content in characters"
    )


class AbstractDocumentTool(AbstractTool):
    """
    Abstract base class for document generation tools.

    This class provides common functionality for tools that generate documents
    like PowerPoint presentations, Word documents, Excel spreadsheets, PDFs, etc.

    Features:
    - Standardized document output management
    - File path validation and generation
    - Async file operations with aiofiles
    - Template management support
    - Duplicate file handling
    - Comprehensive metadata generation
    """

    # Document-specific configuration
    document_type: str = "document"  # Override in subclasses (e.g., "presentation", "spreadsheet")
    default_extension: str = "txt"   # Override in subclasses (e.g., "pptx", "docx", "xlsx")
    supported_extensions: List[str] = []  # Override in subclasses

    def __init__(
        self,
        templates_dir: Optional[Path] = None,
        output_dir: Optional[Union[str, Path]] = None,
        default_template_name: Optional[str] = None,
        max_file_size_mb: float = 100.0,
        overwrite_existing: bool = False,
        **kwargs
    ):
        """
        Initialize the AbstractDocumentTool.

        Args:
            templates_dir: Directory containing document templates
            default_template_name: Default template file name
            max_file_size_mb: Maximum allowed file size in MB
            **kwargs: Additional arguments for AbstractTool
        """
        # Set output_dir in kwargs if provided, so AbstractTool can use it
        if output_dir:
            kwargs['output_dir'] = Path(output_dir).resolve()

        super().__init__(**kwargs)

        self.overwrite_existing = overwrite_existing

        # Template management
        self.templates_dir = templates_dir
        self.default_template_name = default_template_name
        self.max_file_size_mb = max_file_size_mb

        # Initialize templates directory if provided
        if self.templates_dir:
            self.templates_dir = Path(self.templates_dir)
            if not self.templates_dir.exists():
                self.templates_dir.mkdir(parents=True, exist_ok=True)
                self.logger.info(
                    f"Created templates directory: {self.templates_dir}"
                )

        # If output_dir was provided, ensure it exists
        if output_dir and not self.output_dir.exists():
            self.output_dir.mkdir(parents=True, exist_ok=True)
            self.logger.info(
                f"Created output directory: {self.output_dir}"
            )

    def _default_output_dir(self) -> Path:
        """Get the default output directory for this document type."""
        return self.static_dir / "documents" / self.document_type

    async def _ensure_output_directory(self, custom_dir: Optional[str] = None) -> Path:
        """
        Ensure output directory exists and return the path.

        Args:
            custom_dir: Custom output directory path

        Returns:
            Path object for the output directory
        """
        if custom_dir:
            output_dir = Path(custom_dir).resolve()
        else:
            output_dir = self.output_dir

        # Create directory if it doesn't exist
        if not await aiofiles.os.path.exists(output_dir):
            await aiofiles.os.makedirs(output_dir, exist_ok=True)
            self.logger.info(f"Created output directory: {output_dir}")

        return output_dir

    def _generate_document_filename(
        self,
        output_filename: Optional[str],
        file_prefix: str,
        extension: Optional[str] = None
    ) -> str:
        """
        Generate a filename for the document.

        Args:
            output_filename: User-provided filename (without extension)
            file_prefix: Prefix for auto-generated names
            extension: File extension (without dot)

        Returns:
            Complete filename with extension
        """
        # Use default extension if not provided
        if not extension:
            extension = self.default_extension

        # Ensure extension doesn't have a leading dot
        extension = extension.lstrip('.')

        if output_filename:
            # Use provided filename
            if not output_filename.endswith(f'.{extension}'):
                filename = f"{output_filename}.{extension}"
            else:
                filename = output_filename
        else:
            # Generate filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{file_prefix}_{timestamp}.{extension}"

        return filename

    async def _check_file_exists(
        self,
        file_path: Path,
        overwrite_existing: bool
    ) -> None:
        """
        Check if file exists and handle according to overwrite setting.

        Args:
            file_path: Path to the file
            overwrite_existing: Whether to overwrite existing files

        Raises:
            FileExistsError: If file exists and overwrite is False
        """
        if await aiofiles.os.path.exists(file_path):
            if not overwrite_existing:
                self.logger.warning(
                    f"File already exists: {file_path}"
                )
                raise FileExistsError(
                    f"File already exists: {file_path.name}. "
                    f"Set overwrite_existing=True to overwrite."
                )
            else:
                self.logger.info(
                    f"Will overwrite existing file: {file_path}"
                )

    async def _save_document_content(
        self,
        content: Union[bytes, str],
        file_path: Path,
        encoding: Optional[str] = None
    ) -> None:
        """
        Save document content to file using aiofiles.

        Args:
            content: Content to save (bytes or string)
            file_path: Path where to save the file
            encoding: Text encoding (only used for string content)
        """
        try:
            if isinstance(content, bytes):
                # Binary content (e.g., Excel, PowerPoint files)
                async with aiofiles.open(file_path, 'wb') as f:
                    await f.write(content)
            else:
                # Text content (e.g., HTML, markdown, plain text)
                encoding = encoding or 'utf-8'
                async with aiofiles.open(file_path, 'w', encoding=encoding) as f:
                    await f.write(content)

            self.logger.info(
                f"Document saved successfully: {file_path}"
            )

        except Exception as e:
            self.logger.error(
                f"Error saving document to {file_path}: {e}"
            )
            raise

    async def _get_file_size(self, file_path: Path) -> int:
        """
        Get file size in bytes.

        Args:
            file_path: Path to the file

        Returns:
            File size in bytes
        """
        try:
            stat = await aiofiles.os.stat(file_path)
            return stat.st_size
        except Exception as e:
            self.logger.error(f"Error getting file size for {file_path}: {e}")
            return 0

    async def _validate_file_size(self, file_path: Path) -> None:
        """
        Validate that file size is within limits.

        Args:
            file_path: Path to the file

        Raises:
            ValueError: If file is too large
        """
        file_size = await self._get_file_size(file_path)
        file_size_mb = file_size / (1024 * 1024)

        if file_size_mb > self.max_file_size_mb:
            raise ValueError(
                f"Generated file is too large: {file_size_mb:.2f}MB "
                f"(max allowed: {self.max_file_size_mb}MB)"
            )

    async def _generate_document_metadata(
        self,
        file_path: Path,
        content_length: int
    ) -> DocumentMetadata:
        """
        Generate metadata for the created document.

        Args:
            file_path: Path to the generated file
            content_length: Length of original content

        Returns:
            DocumentMetadata object
        """
        file_size = await self._get_file_size(file_path)
        file_url = self.to_static_url(file_path)

        return DocumentMetadata(
            filename=file_path.name,
            file_path=str(file_path),
            file_url=file_url,
            relative_url=self.relative_url(file_url),
            file_size=file_size,
            file_size_mb=round(file_size / (1024 * 1024), 2),
            file_extension=file_path.suffix.lstrip('.'),
            created_at=datetime.now().isoformat(),
            content_length=content_length
        )

    def _get_template_path(
        self,
        template_name: Optional[str]
    ) -> Optional[Path]:
        """
        Get the full path to a template file.

        Args:
            template_name: Name of the template file

        Returns:
            Path to template file or None if not found
        """
        if not template_name or not self.templates_dir:
            return None

        template_path = self.templates_dir / template_name

        if template_path.exists():
            return template_path
        else:
            self.logger.warning(f"Template not found: {template_path}")
            return None

    def _list_available_templates(
        self,
        extensions: Optional[List[str]] = None
    ) -> List[str]:
        """
        List available template files.

        Args:
            extensions: File extensions to filter by (e.g., ['.pptx', '.potx'])

        Returns:
            List of template filenames
        """
        if not self.templates_dir or not self.templates_dir.exists():
            return []

        templates = []
        extensions = extensions or self.supported_extensions or [f'.{self.default_extension}']

        for ext in extensions:
            ext = ext if ext.startswith('.') else f'.{ext}'
            templates.extend([
                f.name for f in self.templates_dir.glob(f'*{ext}')
                if f.is_file()
            ])

        return sorted(templates)

    async def _create_document_safely(
        self,
        content: str,
        output_filename: Optional[str] = None,
        file_prefix: str = "document",
        output_dir: Optional[str] = None,
        overwrite_existing: bool = False,
        extension: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Safely create a document with all error handling and validation.

        This method provides a complete workflow for document creation:
        1. Validate input
        2. Ensure output directory exists
        3. Generate filename
        4. Check for file conflicts
        5. Create the document content
        6. Save the file
        7. Validate file size
        8. Generate metadata

        Args:
            content: Content to convert to document
            output_filename: Custom filename (without extension)
            file_prefix: Prefix for auto-generated filenames
            output_dir: Custom output directory
            overwrite_existing: Whether to overwrite existing files
            extension: File extension override
            **kwargs: Additional arguments for document creation

        Returns:
            Dictionary with document metadata and status
        """
        try:
            # 1. Validate input
            if isinstance(content, pd.DataFrame):
                if content.empty:
                    raise ValueError("DataFrame content cannot be empty")
            elif isinstance(content, str):
                if not content.strip():
                    raise ValueError("Content cannot be empty")
            elif not content:
                raise ValueError("Content cannot be empty")

            # 2. Ensure output directory exists
            output_directory = await self._ensure_output_directory(output_dir)

            # 3. Generate filename
            filename = self._generate_document_filename(
                output_filename, file_prefix, extension
            )
            file_path = output_directory / filename
            # 4. Check for file conflicts
            await self._check_file_exists(file_path, overwrite_existing)
            # 5. Create document content (implemented by subclasses)
            document_content = await self._generate_document_content(content, **kwargs)
            # 6. Save the file
            await self._save_document_content(document_content, file_path)
            # 7. Validate file size
            await self._validate_file_size(file_path)
            # 8. Generate metadata
            metadata = await self._generate_document_metadata(file_path, len(content))
            self.logger.info(f"Document created successfully: {filename}")

            return {
                "status": "success",
                "message": f"{self.document_type.title()} created successfully",
                "metadata": metadata.model_dump(),
                **metadata.model_dump()  # For backward compatibility
            }

        except Exception as e:
            self.logger.error(f"Error creating {self.document_type}: {e}")
            return {
                "status": "error",
                "error": str(e),
                "message": f"Failed to create {self.document_type}: {str(e)}"
            }

    @abstractmethod
    async def _generate_document_content(self, content: str, **kwargs) -> Union[bytes, str]:
        """
        Generate the actual document content.

        This method must be implemented by subclasses to create the specific
        document format (PowerPoint, Word, Excel, etc.).

        Args:
            content: Input content to convert
            **kwargs: Additional arguments specific to the document type

        Returns:
            Document content as bytes (for binary formats) or string (for text formats)
        """
        pass

    # Utility methods for subclasses

    def get_supported_extensions(self) -> List[str]:
        """Get list of supported file extensions for this document type."""
        return self.supported_extensions or [self.default_extension]

    def get_available_templates(self) -> List[str]:
        """Get list of available template files."""
        return self._list_available_templates()

    async def template_exists(self, template_name: str) -> bool:
        """Check if a template file exists."""
        template_path = self._get_template_path(template_name)
        return template_path is not None and await aiofiles.os.path.exists(template_path)

    def get_document_info(self) -> Dict[str, Any]:
        """Get information about this document tool."""
        return {
            "document_type": self.document_type,
            "default_extension": self.default_extension,
            "supported_extensions": self.get_supported_extensions(),
            "templates_dir": str(self.templates_dir) if self.templates_dir else None,
            "available_templates": self.get_available_templates(),
            "output_dir": str(self.output_dir),
            "max_file_size_mb": self.max_file_size_mb
        }

    def _get_current_date(self) -> str:
        """Get current date in YYYY-MM-DD format."""
        return datetime.now().strftime('%Y-%m-%d')

    def _get_current_timestamp(self) -> str:
        """Get current timestamp in ISO format."""
        return datetime.now().isoformat()
