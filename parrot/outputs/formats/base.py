from typing import Any, List, Dict, Optional, Tuple, Type, TYPE_CHECKING
from abc import ABC, abstractmethod
import contextlib
from datetime import datetime
from dataclasses import is_dataclass, asdict, dataclass, field
import pandas as pd
import numpy as np
from pydantic import BaseModel
import orjson
from datamodel.parsers.json import json_encoder  # pylint: disable=E0611  # noqa
from pygments import highlight
from pygments.lexers.data import JsonLexer
from pygments.formatters.html import HtmlFormatter
if TYPE_CHECKING:
    from ...tools.pythonpandas import PythonPandasTool


@dataclass
class RenderError:
    """Structured error information from rendering.

    Attributes:
        message: Human-readable error message
        error_type: Type of error (e.g., 'json_parse', 'validation', 'execution')
        raw_output: The original output that failed to render
        details: Additional error details (stack trace, position, etc.)
    """
    message: str
    error_type: str
    raw_output: Optional[str] = None
    details: Optional[Dict[str, Any]] = field(default_factory=dict)


@dataclass
class RenderResult:
    """Structured result from rendering operation.

    This provides more detailed information about the rendering outcome,
    including whether it succeeded and any error information.

    Attributes:
        success: Whether rendering succeeded
        content: The rendered content (may be partial on error)
        wrapped_content: Optional wrapped version (e.g., HTML)
        error: Error information if rendering failed
    """
    success: bool
    content: Any
    wrapped_content: Optional[Any] = None
    error: Optional[RenderError] = None


class BaseRenderer(ABC):
    """Base class for output renderers."""

    @classmethod
    def get_expected_content_type(cls) -> Type:
        """
        Define what type of content this renderer expects.
        Override in subclasses to specify expected type.

        Returns:
            Type: The expected type (str, pd.DataFrame, dict, etc.)
        """
        return str

    @classmethod
    def _get_content(cls, response: Any) -> Any:
        """
        Extract content from response based on expected type.

        Args:
            response: AIMessage response object

        Returns:
            Content in the expected type
        """
        expected_type = cls.get_expected_content_type()

        # First, try to get the output attribute (structured data)
        if hasattr(response, 'output') and response.output is not None:
            output = response.output

            # If output matches expected type, return it
            if isinstance(output, expected_type):
                return output

            # Special handling for DataFrames
            if expected_type == pd.DataFrame:
                if isinstance(output, pd.DataFrame):
                    return output
                # Try to convert dict/list to DataFrame
                elif isinstance(output, (dict, list)):
                    with contextlib.suppress(Exception):
                        return pd.DataFrame(output)

        # Fallback to string extraction for code-based renderers
        if expected_type == str:
            # If response has 'response' attribute (string content)
            if hasattr(response, 'response') and response.response:
                return response.response

            # Try content attribute
            if hasattr(response, 'content'):
                return response.content

            # Try to_text property
            if hasattr(response, 'to_text'):
                return response.to_text

            # Try output as string
            if hasattr(response, 'output'):
                output = response.output
                return output if isinstance(output, str) else str(output)

        # Last resort: string conversion
        return str(response)

    def execute_code(
        self,
        code: str,
        pandas_tool: "PythonPandasTool | None" = None,
        execution_state: Optional[Dict[str, Any]] = None,
        extra_namespace: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """Execute code within the PythonPandasTool or fallback namespace."""
        if tool := pandas_tool:
            try:
                tool.execute_sync(code, debug=kwargs.get('debug', False))
                return tool.locals, None
            except Exception as exc:
                return None, f"Execution error: {exc}"

        namespace: Dict[str, Any] = {'pd': pd, 'np': np}
        if extra_namespace:
            namespace |= extra_namespace

        locals_dict: Dict[str, Any] = {}
        if execution_state:
            namespace.update(execution_state.get('dataframes', {}))
            namespace.update(execution_state.get('execution_results', {}))
            namespace.update(execution_state.get('variables', {}))
            globals_state = execution_state.get('globals') or {}
            if isinstance(globals_state, dict):
                namespace.update(globals_state)
            locals_state = execution_state.get('locals') or {}
            if isinstance(locals_state, dict):
                locals_dict = locals_state.copy()

        try:
            exec(code, namespace, locals_dict)
            combined: Dict[str, Any] = {}
            combined |= namespace
            combined.update(locals_dict)
            return combined, None
        except Exception as exc:
            return None, f"Execution error: {exc}"

    @staticmethod
    def _create_tools_list(tool_calls: List[Any]) -> List[Dict[str, str]]:
        """Create a list for tool calls."""
        calls = []
        for idx, tool in enumerate(tool_calls, 1):
            name = getattr(tool, 'name', 'Unknown')
            status = getattr(tool, 'status', 'completed')
            calls.append({
                "No.": str(idx),
                "Tool Name": name,
                "Status": status
            })
        return calls

    @staticmethod
    def _create_sources_list(sources: List[Any]) -> List[Dict[str, str]]:
        """Create a list for source documents."""
        sources = []
        for idx, source in enumerate(sources, 1):
            # Handle both SourceDocument objects and dict-like sources
            if hasattr(source, 'source'):
                source_name = source.source
            elif isinstance(source, dict):
                source_name = source.get('source', 'Unknown')
            else:
                source_name = str(source)
            if hasattr(source, 'score'):
                score = source.score
            elif isinstance(source, dict):
                score = source.get('score', 'N/A')
            else:
                score = 'N/A'
            sources.append({
                "No.": str(idx),
                "Source": source_name,
                "Score": score,
            })
        return sources

    @staticmethod
    def _serialize_any(obj: Any) -> Any:
        """Serialize any Python object to a compatible format"""
        # Pydantic BaseModel
        if hasattr(obj, 'model_dump'):
            return obj.model_dump()

        # Dataclass
        if hasattr(obj, '__dataclass_fields__'):
            return asdict(obj)

        # Dict-like
        if hasattr(obj, 'items'):
            return dict(obj)

        # List-like
        if hasattr(obj, '__iter__') and not isinstance(obj, (str, bytes)):
            return list(obj)

        # Primitives
        if isinstance(obj, (str, int, float, bool, type(None))):
            return obj

        # Fallback to string representation
        return str(obj)

    @staticmethod
    def _clean_data(data: dict) -> dict:
        """Clean data for Serialization (remove non-serializable types)"""
        cleaned = {}
        for key, value in data.items():
            # Skip None values
            if value is None:
                continue

            # Handle datetime objects
            if hasattr(value, 'isoformat'):
                cleaned[key] = value.isoformat()
            # Handle Path objects
            elif hasattr(value, '__fspath__'):
                cleaned[key] = str(value)
            # Handle nested dicts
            elif isinstance(value, dict):
                cleaned[key] = BaseRenderer._clean_data(value)
            # Handle lists
            elif isinstance(value, list):
                cleaned[key] = [
                    BaseRenderer._clean_data(item) if isinstance(item, dict) else item
                    for item in value
                ]
            # Primitives
            else:
                cleaned[key] = value

        return cleaned

    @staticmethod
    def _prepare_data(response: Any, include_metadata: bool = False) -> dict:
        """
        Prepare response data for serialization.

        Args:
            response: AIMessage or any object
            include_metadata: Whether to include full metadata

        Returns:
            Dictionary ready for YAML serialization
        """
        if not hasattr(response, 'model_dump'):
            # Handle other types
            return BaseRenderer._serialize_any(response)
        # If it's an AIMessage, extract relevant data
        data = response.model_dump(
            exclude_none=True,
            exclude_unset=True
        )

        if not include_metadata:
            # Return simplified version
            result = {
                'input': data.get('input'),
                'output': data.get('output'),
            }

            # Add essential metadata
            if data.get('model'):
                result['model'] = data['model']
            if data.get('provider'):
                result['provider'] = data['provider']
            if data.get('usage'):
                result['usage'] = data['usage']

            return result

        # Full metadata mode
        return BaseRenderer._clean_data(data)

    def _default_serializer(self, obj: Any) -> Any:
        """Custom serializer for non-JSON-serializable objects."""
        if isinstance(obj, (datetime, pd.Timestamp)):
            return obj.isoformat()
        if isinstance(obj, pd.DataFrame):
            return obj.to_dict(orient='records')
        if isinstance(obj, set):
            return list(obj)
        raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

    def _extract_data(self, response: Any) -> Any:
        """
        Extract serializable data based on response content type rules.
        """
        # 1. Check for PandasAgentResponse (duck typing to avoid circular imports)
        # We check for specific attributes that define a PandasAgentResponse
        output = getattr(response, 'output', None)

        if output is not None:
            # Handle PandasAgentResponse specifically
            if hasattr(output, 'to_dataframe') and hasattr(output, 'explanation') and hasattr(output, 'data'):
                # response.data is usually a PandasTable
                return output.to_dataframe() if output.data is not None else []

            # 2. Handle direct DataFrame output
            if isinstance(output, pd.DataFrame):
                return output.to_dict(orient='records')

            # 3. Handle Pydantic Models
            if isinstance(output, BaseModel):
                return output.model_dump()

            # 4. Handle Dataclasses
            if is_dataclass(output):
                return asdict(output)

        # 5. Fallback for unstructured/plain text responses
        # "if there is no 'structured output response', build a JSON with input/output"
        is_structured = getattr(response, 'is_structured', False)
        if not is_structured and output:
            return {
                "input": getattr(response, 'input', ''),
                "output": output,
                "metadata": getattr(response, 'metadata', {})
            }

        return output

    def _serialize(self, data: Any, indent: Optional[int] = None) -> str:
        """Serialize data to JSON string using orjson if available."""
        try:
            option = orjson.OPT_INDENT_2 if indent is not None else 0  # pylint: disable=E1101
            # orjson returns bytes, decode to str
            return orjson.dumps(  # pylint: disable=E1101
                data,
                default=self._default_serializer,
                option=option
            ).decode('utf-8')
        except Exception:
            return json_encoder(
                data
            )

    def _wrap_html(self, content: str) -> str:
        """Helper to wrap JSON in HTML with highlighting."""
        try:
            formatter = HtmlFormatter(style='default', full=False, noclasses=True)
            highlighted_code = highlight(content, JsonLexer(), formatter)
            return f'<div class="json-response" style="padding:1em; border:1px solid #ddd; border-radius:4px;">{highlighted_code}</div>'
        except ImportError:
            return f'<pre><code class="language-json">{content}</code></pre>'

    def _create_error_result(
        self,
        message: str,
        error_type: str,
        raw_output: Optional[str] = None,
        content: Optional[Any] = None,
        wrapped_content: Optional[Any] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> RenderResult:
        """
        Create a structured error result for render failures.

        This method standardizes error reporting across renderers and makes
        it easier to detect and handle errors in retry logic.

        Args:
            message: Human-readable error message
            error_type: Category of error (e.g., 'json_parse', 'validation', 'execution')
            raw_output: The original output that failed to render
            content: Fallback content to return (often the raw output or error message)
            wrapped_content: Fallback wrapped content if any
            details: Additional error details

        Returns:
            RenderResult with success=False and error information
        """
        error = RenderError(
            message=message,
            error_type=error_type,
            raw_output=raw_output,
            details=details or {}
        )
        return RenderResult(
            success=False,
            content=content or raw_output or message,
            wrapped_content=wrapped_content,
            error=error
        )

    def _create_success_result(
        self,
        content: Any,
        wrapped_content: Optional[Any] = None
    ) -> RenderResult:
        """
        Create a successful render result.

        Args:
            content: The primary rendered content
            wrapped_content: Optional wrapped version (e.g., HTML)

        Returns:
            RenderResult with success=True
        """
        return RenderResult(
            success=True,
            content=content,
            wrapped_content=wrapped_content
        )

    @abstractmethod
    async def render(
        self,
        response: Any,
        environment: str = 'terminal',
        export_format: str = 'html',
        include_code: bool = False,
        **kwargs,
    ) -> Tuple[Any, Optional[Any]]:
        """
        Render response in the appropriate format.

        Returns:
            Tuple[Any, Optional[Any]]: (content, wrapped)
            - content: Primary formatted output
            - wrapped: Optional wrapped version (e.g., HTML, standalone file)
        """
        pass
