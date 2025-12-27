"""
Shared Response Parser for Integration Wrappers.

Provides a unified way to parse AIMessage responses into structured content
for rendering in different platforms (Telegram, MS Teams, etc.).
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional, Union
import mimetypes

try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False


@dataclass
class ParsedResponse:
    """Structured response content extracted from AIMessage."""
    
    # Main text content
    text: str = ""
    
    # File attachments
    images: List[Path] = field(default_factory=list)
    documents: List[Path] = field(default_factory=list)
    media: List[Path] = field(default_factory=list)  # Videos, audio
    
    # Code content
    code: Optional[str] = None
    code_language: Optional[str] = None
    
    # Tabular data
    table_data: Optional[Any] = None  # pandas DataFrame if available
    table_markdown: Optional[str] = None  # Pre-rendered markdown table
    
    # Flags
    is_markdown: bool = True
    has_structured_output: bool = False
    
    @property
    def has_attachments(self) -> bool:
        """Check if there are any file attachments."""
        return bool(self.images or self.documents or self.media)
    
    @property
    def has_table(self) -> bool:
        """Check if there is table data to render."""
        return self.table_data is not None or self.table_markdown is not None
    
    @property
    def has_code(self) -> bool:
        """Check if there is code to render."""
        return bool(self.code)


def _classify_file(file_path: Path) -> str:
    """Classify file type based on extension and MIME type."""
    if not file_path.exists():
        return "unknown"
    
    mime_type, _ = mimetypes.guess_type(str(file_path))
    ext = file_path.suffix.lower()
    
    image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.svg'}
    video_extensions = {'.mp4', '.avi', '.mov', '.wmv', '.flv', '.webm', '.mkv'}
    audio_extensions = {'.mp3', '.wav', '.ogg', '.m4a', '.flac', '.aac'}
    
    if mime_type:
        if mime_type.startswith('image/'):
            return "image"
        elif mime_type.startswith('video/'):
            return "video"
        elif mime_type.startswith('audio/'):
            return "audio"
    
    if ext in image_extensions:
        return "image"
    elif ext in video_extensions:
        return "video"
    elif ext in audio_extensions:
        return "audio"
    
    return "document"


def _dataframe_to_markdown(df: Any, max_rows: int = 50) -> str:
    """Convert a pandas DataFrame to markdown table format."""
    if not HAS_PANDAS:
        return str(df)
    
    if not isinstance(df, pd.DataFrame):
        return str(df)
    
    # Limit rows if DataFrame is large
    if len(df) > max_rows:
        df = df.head(max_rows)
        truncated = True
    else:
        truncated = False
    
    # Build markdown table
    headers = " | ".join(str(col) for col in df.columns)
    separator = " | ".join("---" for _ in df.columns)
    
    rows = []
    for _, row in df.iterrows():
        row_str = " | ".join(str(val) for val in row.values)
        rows.append(row_str)
    
    table = f"| {headers} |\n| {separator} |\n"
    table += "\n".join(f"| {row} |" for row in rows)
    
    if truncated:
        table += f"\n\n*... and {len(df) - max_rows} more rows*"
    
    return table


def parse_response(response: Any) -> ParsedResponse:
    """
    Parse an AIMessage or similar response into structured content.
    
    Extracts text, images, documents, code, and tabular data from the response
    for platform-specific rendering.
    
    Args:
        response: AIMessage, AgentResponse, or similar response object
        
    Returns:
        ParsedResponse with extracted content
    """
    parsed = ParsedResponse()
    
    if response is None:
        parsed.text = "I don't have a response for that."
        return parsed
    
    # Handle plain strings
    if isinstance(response, str):
        parsed.text = response
        return parsed
    
    # Extract primary text content
    if hasattr(response, 'response') and response.response:
        parsed.text = str(response.response)
    elif hasattr(response, 'content'):
        content = response.content
        if isinstance(content, str):
            parsed.text = content
        elif isinstance(content, list):
            # Handle list of content blocks
            text_parts = []
            for block in content:
                if isinstance(block, dict) and block.get('type') == 'text':
                    text_parts.append(block.get('text', ''))
                elif isinstance(block, str):
                    text_parts.append(block)
            parsed.text = "\n".join(text_parts)
        else:
            parsed.text = str(content)
    elif hasattr(response, 'output'):
        output = response.output
        if isinstance(output, str):
            parsed.text = output
        elif hasattr(output, 'to_string'):
            # pandas DataFrame
            parsed.table_data = output
            parsed.table_markdown = _dataframe_to_markdown(output)
            parsed.has_structured_output = True
        elif isinstance(output, dict):
            parsed.text = str(output)
            parsed.has_structured_output = True
        else:
            parsed.text = str(output)
    elif hasattr(response, 'text'):
        parsed.text = str(response.text)
    else:
        parsed.text = str(response)
    
    # Extract code
    if hasattr(response, 'code') and response.code:
        parsed.code = response.code
        # Try to detect language from content
        if parsed.code.strip().startswith('{'):
            parsed.code_language = "json"
        elif 'def ' in parsed.code or 'import ' in parsed.code:
            parsed.code_language = "python"
        else:
            parsed.code_language = None
    
    # Extract structured output / data
    if hasattr(response, 'data') and response.data is not None:
        data = response.data
        if HAS_PANDAS and isinstance(data, pd.DataFrame):
            parsed.table_data = data
            parsed.table_markdown = _dataframe_to_markdown(data)
            parsed.has_structured_output = True
        elif isinstance(data, dict) and 'rows' in data and 'columns' in data:
            # Tabular data as dict
            try:
                if HAS_PANDAS:
                    df = pd.DataFrame(data['rows'], columns=data['columns'])
                    parsed.table_data = df
                    parsed.table_markdown = _dataframe_to_markdown(df)
                    parsed.has_structured_output = True
            except Exception:
                pass
    
    if hasattr(response, 'structured_output') and response.structured_output is not None:
        structured = response.structured_output
        if HAS_PANDAS and isinstance(structured, pd.DataFrame):
            parsed.table_data = structured
            parsed.table_markdown = _dataframe_to_markdown(structured)
            parsed.has_structured_output = True
    
    # Extract images
    if hasattr(response, 'images') and response.images:
        for img_path in response.images:
            if img_path:
                path = Path(img_path) if isinstance(img_path, str) else img_path
                if path.exists():
                    parsed.images.append(path)
    
    # Extract media (videos, audio)
    if hasattr(response, 'media') and response.media:
        for media_path in response.media:
            if media_path:
                path = Path(media_path) if isinstance(media_path, str) else media_path
                if path.exists():
                    file_type = _classify_file(path)
                    if file_type == "image":
                        parsed.images.append(path)
                    else:
                        parsed.media.append(path)
    
    # Extract files/documents
    if hasattr(response, 'files') and response.files:
        for file_path in response.files:
            if file_path:
                path = Path(file_path) if isinstance(file_path, str) else file_path
                if path.exists():
                    file_type = _classify_file(path)
                    if file_type == "image":
                        parsed.images.append(path)
                    elif file_type in ("video", "audio"):
                        parsed.media.append(path)
                    else:
                        parsed.documents.append(path)
    
    if hasattr(response, 'documents') and response.documents:
        for doc in response.documents:
            if isinstance(doc, (str, Path)):
                path = Path(doc) if isinstance(doc, str) else doc
                if path.exists():
                    parsed.documents.append(path)
            elif isinstance(doc, dict) and 'path' in doc:
                path = Path(doc['path'])
                if path.exists():
                    parsed.documents.append(path)
    
    # Set default text if empty
    if not parsed.text and not parsed.has_table and not parsed.has_code:
        parsed.text = "..."
    
    return parsed
