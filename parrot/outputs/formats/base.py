from typing import Any, List, Dict, Optional, Tuple, Type, TYPE_CHECKING
from abc import ABC, abstractmethod
import contextlib
import re
import html
from datetime import datetime
from dataclasses import is_dataclass, asdict
import pandas as pd
import numpy as np
from pydantic import BaseModel
import orjson
from datamodel.parsers.json import json_encoder  # pylint: disable=E0611  # noqa
from pygments import highlight
from pygments.lexers.python import PythonLexer
from pygments.formatters.html import HtmlFormatter

if TYPE_CHECKING:
    from ...tools.pythonpandas import PythonPandasTool


try:
    from ipywidgets import HTML as IPyHTML
    IPYWIDGETS_AVAILABLE = True
except ImportError:
    IPYWIDGETS_AVAILABLE = False


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
            option = orjson.OPT_INDENT_2 if indent is not None else 0
            # orjson returns bytes, decode to str
            return orjson.dumps(
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
            from pygments import highlight
            from pygments.lexers import JsonLexer
            from pygments.formatters import HtmlFormatter

            formatter = HtmlFormatter(style='default', full=False, noclasses=True)
            highlighted_code = highlight(content, JsonLexer(), formatter)
            return f'<div class="json-response" style="padding:1em; border:1px solid #ddd; border-radius:4px;">{highlighted_code}</div>'
        except ImportError:
            return f'<pre><code class="language-json">{content}</code></pre>'


    @abstractmethod
    async def render(
        self,
        response: Any,
        environment: str = 'terminal',
        export_format: str = 'html',
        return_code: bool = True,
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


class BaseChart(BaseRenderer):
    """Base class for chart renderers - extends BaseRenderer with chart-specific methods"""

    @staticmethod
    def _extract_code(content: str) -> Optional[str]:
        """Extract Python code from markdown blocks."""
        pattern = r'```(?:python)?\n(.*?)```'
        matches = re.findall(pattern, content, re.DOTALL)
        return matches[0].strip() if matches else None

    @staticmethod
    def _highlight_code(code: str, theme: str = 'monokai') -> str:
        """Apply syntax highlighting to code."""
        try:
            formatter = HtmlFormatter(style=theme, noclasses=True, cssclass='code')
            return highlight(code, PythonLexer(), formatter)
        except ImportError:
            escaped = html.escape(code)
            return f'<pre class="code"><code>{escaped}</code></pre>'

    @staticmethod
    def _wrap_for_environment(content: Any, environment: str) -> Any:
        """Wrap content based on environment."""
        if isinstance(content, str) and environment in {'jupyter', 'colab'} and IPYWIDGETS_AVAILABLE:
                return IPyHTML(value=content)
        return content

    @staticmethod
    def _build_code_section(code: str, theme: str, icon: str = "📊") -> str:
        """Build collapsible code section."""
        highlighted = BaseChart._highlight_code(code, theme)
        return f'''
        <details class="code-accordion">
            <summary class="code-header">
                <span>{icon} View Code</span>
                <span class="toggle-icon">▶</span>
            </summary>
            <div class="code-content">
                {highlighted}
            </div>
        </details>
        '''

    @staticmethod
    def _render_error(error: str, code: str, theme: str) -> str:
        """Render error message with code."""
        highlighted = BaseChart._highlight_code(code, theme)
        return f'''
        {BaseChart._get_chart_styles()}
        <div class="error-container">
            <h3>⚠️ Chart Generation Error</h3>
            <p class="error-message">{error}</p>
            <details class="code-accordion" open>
                <summary class="code-header">Code with Error</summary>
                <div class="code-content">{highlighted}</div>
            </details>
        </div>
        '''

    @staticmethod
    def _get_chart_styles() -> str:
        """CSS styles specific to charts."""
        return '''
        <style>
            .chart-container {
                background: white;
                border-radius: 8px;
                box-shadow: 0 2px 8px rgba(0,0,0,0.1);
                padding: 20px;
                margin: 20px 0;
            }
            .chart-wrapper {
                min-height: 400px;
                display: flex;
                justify-content: center;
                align-items: center;
            }
            .chart-guidance {
                background: #f0f4ff;
                border-left: 4px solid #667eea;
                padding: 16px 20px;
                margin-bottom: 20px;
                border-radius: 6px;
            }
            .chart-guidance h3 {
                margin-bottom: 10px;
                font-size: 16px;
                font-weight: 600;
                color: #364152;
            }
            .chart-guidance ol {
                margin: 0 0 0 20px;
                padding: 0;
            }
            .chart-guidance li {
                margin-bottom: 6px;
                line-height: 1.4;
            }
            .chart-note {
                background: #fffaf0;
                border-left: 4px solid #f6ad55;
                padding: 12px 16px;
                border-radius: 6px;
                margin-bottom: 20px;
                color: #744210;
                font-size: 14px;
            }
            .code-accordion {
                margin-top: 20px;
                border: 1px solid #e0e0e0;
                border-radius: 6px;
                overflow: hidden;
            }
            .code-header {
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                padding: 12px 20px;
                cursor: pointer;
                display: flex;
                justify-content: space-between;
                align-items: center;
                font-weight: 600;
                user-select: none;
            }
            .code-header:hover {
                background: linear-gradient(135deg, #5568d3 0%, #653a8e 100%);
            }
            .toggle-icon {
                transition: transform 0.3s ease;
            }
            details[open] .toggle-icon {
                transform: rotate(90deg);
            }
            .code-content {
                background: #272822;
                padding: 15px;
                overflow-x: auto;
            }
            .code-content pre {
                margin: 0;
                font-family: 'Monaco', 'Menlo', 'Consolas', monospace;
                font-size: 13px;
                line-height: 1.5;
            }
            .error-container {
                background: #fff3cd;
                border: 1px solid #ffc107;
                border-radius: 8px;
                padding: 20px;
                margin: 20px 0;
            }
            .error-message {
                color: #856404;
                font-weight: 500;
                margin: 10px 0;
            }
        </style>
        '''

    @staticmethod
    def _build_html_document(
        chart_content: str,
        code_section: str = '',
        title: str = 'AI-Parrot Chart',
        extra_head: str = '',
        mode: str = 'partial'
    ) -> str:
        """Build HTML document wrapper for charts."""
        if mode == 'partial':
            return f'''
            {BaseChart._get_chart_styles()}
            <div class="chart-container">
                <div class="chart-wrapper">
                    {chart_content}
                </div>
            </div>
            {code_section}
            '''

        elif mode == 'complete':
            return f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>

    {extra_head}

    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto,
                         'Helvetica Neue', Arial, sans-serif;
            background: #f5f7fa;
            padding: 20px;
            line-height: 1.6;
        }}

        .container {{
            max-width: 1200px;
            margin: 0 auto;
        }}

        .chart-container {{
            background: white;
            border-radius: 12px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.07), 0 2px 4px rgba(0,0,0,0.05);
            padding: 30px;
            margin-bottom: 20px;
        }}

        .chart-wrapper {{
            min-height: 400px;
            display: flex;
            justify-content: center;
            align-items: center;
        }}

        .code-accordion {{
            margin-top: 20px;
            border: 1px solid #e0e0e0;
            border-radius: 8px;
            overflow: hidden;
            background: white;
        }}

        .code-header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 14px 20px;
            cursor: pointer;
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-weight: 600;
            user-select: none;
            transition: all 0.3s ease;
        }}

        .code-header:hover {{
            background: linear-gradient(135deg, #5568d3 0%, #653a8e 100%);
        }}

        .toggle-icon {{
            transition: transform 0.3s ease;
            font-size: 12px;
        }}

        details[open] .toggle-icon {{
            transform: rotate(90deg);
        }}

        .code-content {{
            background: #272822;
            padding: 20px;
            overflow-x: auto;
        }}

        .code-content pre {{
            margin: 0;
            font-family: 'Monaco', 'Menlo', 'Consolas', 'Courier New', monospace;
            font-size: 14px;
            line-height: 1.6;
        }}

        .error-container {{
            background: #fff3cd;
            border: 2px solid #ffc107;
            border-radius: 8px;
            padding: 20px;
            margin: 20px 0;
        }}

        .error-container h3 {{
            color: #856404;
            margin-bottom: 10px;
        }}

        .error-message {{
            color: #856404;
            font-weight: 500;
            margin: 10px 0;
        }}

        @media (max-width: 768px) {{
            body {{
                padding: 10px;
            }}

            .chart-container {{
                padding: 15px;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="chart-container">
            <div class="chart-wrapper">
                {chart_content}
            </div>
        </div>

        {code_section}
    </div>
</body>
</html>'''

        else:
            raise ValueError(f"Invalid mode: {mode}. Must be 'partial' or 'complete'")

    @abstractmethod
    def _render_chart_content(self, chart_obj: Any, **kwargs) -> str:
        """
        Render the chart-specific content (to be embedded in HTML).
        This should return just the chart div/script, not the full HTML document.

        Each chart renderer must implement this method to generate their
        specific chart content (Altair vega-embed, Plotly div, etc.)
        """
        pass

    def to_html(
        self,
        chart_obj: Any,
        mode: str = 'partial',
        include_code: bool = False,
        code: Optional[str] = None,
        theme: str = 'monokai',
        title: str = 'AI-Parrot Chart',
        **kwargs
    ) -> str:
        """
        Convert chart object to HTML.

        Args:
            chart_obj: Chart object to render
            mode: 'partial' for embeddable HTML or 'complete' for full document
            include_code: Whether to include code section
            code: Python code to display
            theme: Code highlighting theme
            title: Document title (for complete mode)
            **kwargs: Additional parameters passed to _render_chart_content

        Returns:
            HTML string based on mode
        """
        # Get chart-specific content from subclass
        chart_content = self._render_chart_content(chart_obj, **kwargs)

        # Build code section if requested
        code_section = ''
        if include_code and code:
            code_section = self._build_code_section(code, theme, kwargs.get('icon', '📊'))

        # Get extra head content if provided by subclass
        extra_head = kwargs.get('extra_head', '')

        # Build final HTML
        return self._build_html_document(
            chart_content=chart_content,
            code_section=code_section,
            title=title,
            extra_head=extra_head,
            mode=mode
        )

    def to_json(self, chart_obj: Any) -> Optional[Dict]:
        """Convert chart object to JSON (optional, not all charts support this)."""
        return None
