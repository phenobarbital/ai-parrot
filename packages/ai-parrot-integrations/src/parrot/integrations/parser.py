"""
Shared Response Parser for Integration Wrappers.

Provides a unified way to parse AIMessage responses into structured content
for rendering in different platforms (Telegram, MS Teams, etc.).
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional
import mimetypes
import base64

try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False


@dataclass
class ChartData:
    """
    Metadata for a generated chart.
    
    Attributes:
        path: Path to the chart image file
        title: Chart title
        chart_type: Type of chart (bar, line, pie, etc.)
        format: Output format (png, svg, pdf)
        base64_data: Base64-encoded image data (for inline embedding)
        public_url: Public URL if uploaded to cloud storage
    """
    path: Path
    title: str = "Chart"
    chart_type: str = "unknown"
    format: str = "png"
    base64_data: Optional[str] = None
    public_url: Optional[str] = None
    
    def to_base64(self) -> str:
        """
        Convert the chart image to base64-encoded string.
        
        Returns:
            Base64 string suitable for data URI embedding
        """
        if self.base64_data:
            return self.base64_data
        
        if not self.path.exists():
            raise FileNotFoundError(f"Chart file not found: {self.path}")
        
        with open(self.path, "rb") as f:
            self.base64_data = base64.b64encode(f.read()).decode('utf-8')
        
        return self.base64_data
    
    def to_data_uri(self) -> str:
        """
        Convert the chart to a data URI for inline embedding.
        
        Returns:
            Data URI string (e.g., "data:image/png;base64,...")
        """
        b64 = self.to_base64()
        mime_type = self._get_mime_type()
        return f"data:{mime_type};base64,{b64}"
    
    def _get_mime_type(self) -> str:
        """Get MIME type based on format."""
        mime_map = {
            "png": "image/png",
            "svg": "image/svg+xml",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "gif": "image/gif",
            "pdf": "application/pdf"
        }
        return mime_map.get(self.format.lower(), "application/octet-stream")


@dataclass
class ParsedResponse:
    """Structured response content extracted from AIMessage."""
    
    # Main text content
    text: str = ""
    
    # File attachments
    images: List[Path] = field(default_factory=list)
    documents: List[Path] = field(default_factory=list)
    media: List[Path] = field(default_factory=list)  # Videos, audio
    
    # Charts
    charts: List[ChartData] = field(default_factory=list)
    
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
        return bool(self.images or self.documents or self.media or self.charts)
    
    @property
    def has_table(self) -> bool:
        """Check if there is table data to render."""
        return self.table_data is not None or self.table_markdown is not None
    
    @property
    def has_code(self) -> bool:
        """Check if there is code to render."""
        return bool(self.code)

    @property
    def has_charts(self) -> bool:
        """Check if there are charts to render."""
        return bool(self.charts)


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


def _extract_table_from_inner(inner: Any, parsed: 'ParsedResponse') -> None:
    """Try to populate ``parsed.table_data`` from a nested data payload.

    Handles the two shapes produced by Pydantic structured outputs:
    - ``{columns: [...], rows: [[...], ...]}`` dict or model
    - list-of-dicts (``DataFrame.to_dict(orient='records')``)
    """
    cols = getattr(inner, 'columns', None)
    rws = getattr(inner, 'rows', None)
    if isinstance(cols, list) and isinstance(rws, list):
        try:
            if HAS_PANDAS:
                df = pd.DataFrame(rws, columns=cols)
                parsed.table_data = df
                parsed.table_markdown = _dataframe_to_markdown(df)
                parsed.has_structured_output = True
        except Exception:
            pass
    elif isinstance(inner, dict) and 'columns' in inner and 'rows' in inner:
        try:
            if HAS_PANDAS:
                df = pd.DataFrame(inner['rows'], columns=inner['columns'])
                parsed.table_data = df
                parsed.table_markdown = _dataframe_to_markdown(df)
                parsed.has_structured_output = True
        except Exception:
            pass
    elif isinstance(inner, list) and inner and isinstance(inner[0], dict):
        try:
            if HAS_PANDAS:
                df = pd.DataFrame(inner)
                parsed.table_data = df
                parsed.table_markdown = _dataframe_to_markdown(df)
                parsed.has_structured_output = True
        except Exception:
            pass


_PYDANTIC_TEXT_FIELDS = (
    "explanation", "answer", "text", "message",
    "response", "content", "summary", "output",
)


def _extract_text_from_pydantic(*candidates: Any) -> Optional[str]:
    """Return the first human-readable text field from Pydantic models.

    Iterates *candidates* (e.g. ``structured_output``, ``output``);
    for each that is a ``BaseModel``, checks well-known text field
    names and returns the first non-empty string.  Mirrors the logic
    in ``msagentsdk.agent.render_reply_text`` so both integration
    paths extract the same display text.
    """
    try:
        from pydantic import BaseModel
    except ImportError:
        return None

    for payload in candidates:
        if payload is None or not isinstance(payload, BaseModel):
            continue
        for field_name in _PYDANTIC_TEXT_FIELDS:
            value = getattr(payload, field_name, None)
            if isinstance(value, str) and value.strip():
                return value
    return None


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


def _parse_chart_item(chart: Any) -> Optional[ChartData]:
    """
    Parse a single chart item into ChartData.
    
    Args:
        chart: Can be a dict, Path, str, or ChartData
        
    Returns:
        ChartData if valid, None otherwise
    """
    if isinstance(chart, ChartData):
        return chart
    
    if isinstance(chart, (str, Path)):
        path = Path(chart)
        if path.exists():
            return ChartData(
                path=path,
                title="Chart",
                format=path.suffix.lstrip('.') or 'png'
            )
        return None
    
    if isinstance(chart, dict):
        path_str = chart.get('path', chart.get('chart_path', ''))
        if not path_str:
            return None
        
        path = Path(path_str)
        if not path.exists():
            return None
        
        return ChartData(
            path=path,
            title=chart.get('title', 'Chart'),
            chart_type=chart.get('type', chart.get('chart_type', 'unknown')),
            format=chart.get('format', path.suffix.lstrip('.') or 'png'),
            public_url=chart.get('url', chart.get('public_url'))
        )
    
    return None


def _extract_charts_from_response(response: Any, parsed: ParsedResponse) -> None:
    """
    Extract chart data from agent response.
    
    Looks for charts in:
    - response.charts (list of chart dicts or paths)
    - response.tool_results (ToolResult with chart_path in data)
    - response.files (paths ending in chart_*)
    
    Args:
        response: The agent response object
        parsed: ParsedResponse to populate with charts
    """
    # 1. Check for explicit charts attribute
    if hasattr(response, 'charts') and response.charts:
        for chart in response.charts:
            chart_data = _parse_chart_item(chart)
            if chart_data:
                parsed.charts.append(chart_data)
    
    # 2. Check tool_results for chart generation results
    if hasattr(response, 'tool_results') and response.tool_results:
        for result in response.tool_results:
            # Handle ToolResult objects - check both data and metadata
            sources = []
            if hasattr(result, 'data') and isinstance(result.data, dict):
                sources.append(result.data)
            if hasattr(result, 'metadata') and isinstance(result.metadata, dict):
                sources.append(result.metadata)
                
            for source in sources:
                if 'chart_path' in source:
                    path = Path(source['chart_path'])
                    if path.exists():
                        parsed.charts.append(ChartData(
                            path=path,
                            title=source.get('title', 'Chart'),
                            chart_type=source.get('chart_type', 'unknown'),
                            format=source.get('format', path.suffix.lstrip('.') or 'png')
                        ))
                    break # Found chart in this result
            
            # Handle files from ToolResult
            if hasattr(result, 'files') and result.files:
                for file_path in result.files:
                    path = Path(file_path) if isinstance(file_path, str) else file_path
                    if path.exists() and path.name.startswith('chart_'):
                        # Avoid duplicates
                        if not any(c.path == path for c in parsed.charts):
                            parsed.charts.append(ChartData(
                                path=path,
                                title="Generated Chart",
                                chart_type="unknown",
                                format=path.suffix.lstrip('.') or 'png'
                            ))
    
    # 3. Check files for chart patterns
    if hasattr(response, 'files') and response.files:
        for file_path in response.files:
            path = Path(file_path) if isinstance(file_path, str) else file_path
            if path.exists() and path.name.startswith('chart_'):
                # Avoid duplicates
                if not any(c.path == path for c in parsed.charts):
                    parsed.charts.append(ChartData(
                        path=path,
                        title="Chart",
                        chart_type="unknown",
                        format=path.suffix.lstrip('.') or 'png'
                    ))
    
    # 4. Check images for chart patterns (some might be charts)
    if hasattr(response, 'images') and response.images:
        for img_path in response.images:
            path = Path(img_path) if isinstance(img_path, str) else img_path
            if path.exists() and path.name.startswith('chart_'):
                # Move from images to charts
                if not any(c.path == path for c in parsed.charts):
                    parsed.charts.append(ChartData(
                        path=path,
                        title="Chart",
                        chart_type="unknown",
                        format=path.suffix.lstrip('.') or 'png'
                    ))
                # Remove from images to avoid duplicates
                if path in parsed.images:
                    parsed.images.remove(path)


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
    
    # Extract primary text content.
    # Prefer output/content (the channel-facing rendered text) over
    # .response (the raw text_response before formatting — may be a
    # short summary when structured output produced the real content).
    output = getattr(response, 'output', None)
    content = getattr(response, 'content', None)
    for value in (output, content):
        if isinstance(value, str) and value.strip():
            parsed.text = value
            break
        elif isinstance(value, list):
            text_parts = []
            for block in value:
                if isinstance(block, dict) and block.get('type') == 'text':
                    text_parts.append(block.get('text', ''))
                elif isinstance(block, str):
                    text_parts.append(block)
            joined = "\n".join(text_parts)
            if joined.strip():
                parsed.text = joined
                break
        elif value is not None and hasattr(value, 'to_string'):
            parsed.table_data = value
            parsed.table_markdown = _dataframe_to_markdown(value)
            parsed.has_structured_output = True
            break
        elif isinstance(value, dict):
            parsed.text = str(value)
            parsed.has_structured_output = True
            break
    else:
        # Try structured Pydantic model fields before falling back to
        # .response — handles PandasAgentResponse and similar models
        # whose output is a BaseModel with a text-ish field.
        extracted = _extract_text_from_pydantic(
            getattr(response, 'structured_output', None),
            output,
        )
        if extracted:
            parsed.text = extracted
            parsed.has_structured_output = True
        else:
            # Fall back to .response, then .text, then str()
            text = getattr(response, 'response', None)
            if isinstance(text, str) and text.strip():
                parsed.text = text
            elif hasattr(response, 'text') and response.text:
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
        elif isinstance(data, list) and data and isinstance(data[0], dict):
            # List-of-dicts (DataFrame.to_dict(orient='records')) — the
            # format PandasAgent serializes to before returning.
            try:
                if HAS_PANDAS:
                    df = pd.DataFrame(data)
                    parsed.table_data = df
                    parsed.table_markdown = _dataframe_to_markdown(df)
                    parsed.has_structured_output = True
            except Exception:
                pass
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
        elif parsed.table_data is None and hasattr(structured, 'data'):
            # Pydantic model with a .data attribute (e.g. PandasAgentResponse)
            inner = getattr(structured, 'data', None)
            if inner is not None:
                _extract_table_from_inner(inner, parsed)
    
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
            # Handle data URI strings (base64 images) - pass through directly
            if isinstance(doc, str) and doc.startswith('data:'):
                parsed.documents.append(doc)
            elif isinstance(doc, (str, Path)):
                path = Path(doc) if isinstance(doc, str) else doc
                if path.exists():
                    parsed.documents.append(path)
            elif isinstance(doc, dict) and 'path' in doc:
                path = Path(doc['path'])
                if path.exists():
                    parsed.documents.append(path)
    
    # Extract charts using the new helper
    try:
        _extract_charts_from_response(response, parsed)
    except Exception:
        pass
    
    # Set default text if empty
    if not parsed.text and not parsed.has_table and not parsed.has_code and not parsed.has_charts:
        parsed.text = "..."
    
    return parsed
