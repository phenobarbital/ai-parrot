from typing import Any, List, Dict, Any
from abc import ABC, abstractmethod
from dataclasses import asdict


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
        # If it's an AIMessage, extract relevant data
        if hasattr(response, 'model_dump'):
            # It's a Pydantic model
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

        # Handle other types
        return BaseRenderer._serialize_any(response)

    @abstractmethod
    def render(self, response: Any, **kwargs) -> str:
        pass
