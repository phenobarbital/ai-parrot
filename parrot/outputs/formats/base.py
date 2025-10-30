from typing import Any, List, Dict, Any, Optional, Tuple
from abc import ABC, abstractmethod
import re
from dataclasses import asdict
import html
from pygments import highlight
from pygments.lexers.python import PythonLexer
from pygments.formatters.html import HtmlFormatter


try:
    from ipywidgets import HTML as IPyHTML
    IPYWIDGETS_AVAILABLE = True
except ImportError:
    IPYWIDGETS_AVAILABLE = False


class BaseRenderer(ABC):
    """Base class for output renderers."""

    @staticmethod
    def _get_content(response: Any) -> str:
        """
        Extract content from response safely.

        Args:
            response: AIMessage response object

        Returns:
            String content from the response
        """
        # If response has 'response' attribute
        if hasattr(response, 'response'):
            return response.response or response.output
        if hasattr(response, 'content'):
            return response.content
        # Try to_text property
        if hasattr(response, 'to_text'):
            return response.to_text
        # Try output attribute
        if hasattr(response, 'output'):
            output = response.output
            return output if isinstance(output, str) else str(output)
        # Fallback
        return str(response)

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

    @abstractmethod
    def render(self, response: Any, **kwargs) -> str:
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
                <span>{icon} View Python Code</span>
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

    @abstractmethod
    def execute_code(self, code: str) -> Tuple[Any, Optional[str]]:
        """Execute chart code and return chart object or error."""
        pass

    @abstractmethod
    def to_html(self, chart_obj: Any, **kwargs) -> str:
        """Convert chart object to HTML."""
        pass

    def to_json(self, chart_obj: Any) -> Optional[Dict]:
        """Convert chart object to JSON (optional, not all charts support this)."""
        return None
