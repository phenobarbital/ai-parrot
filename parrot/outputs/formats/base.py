from typing import Any, List, Dict, Any
from abc import ABC, abstractmethod


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

    @abstractmethod
    def render(self, response: Any, **kwargs) -> str:
        pass
