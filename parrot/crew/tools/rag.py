from typing import Union
from pathlib import Path
from pydantic import PrivateAttr
from crewai_tools import BaseTool, RagTool

class RagSearchTool(BaseTool):
    """RagTool is designed to answer questions by leveraging the power of RAG by leveraging (EmbedChain)."""
    name: str = "RAG Tool"
    description: str = "enables users to dynamically query a knowledge base"
    _directory: PrivateAttr

    def __init__(self, directory: Union[Path, str] = None, **kwargs):
        super().__init__(**kwargs)
        self._directory = directory

    def get_rag(self):
        """Return the RAG Tool."""
        return RagTool(
            config={
                "llm": {
                    "provider": "vertexai",
                    "config": {
                        "model": "gemini-pro",
                        "temperature": 0.4,
                        "top_p": 1,
                        "stream": True
                    }
                },
                "embedder": {
                    "provider": "vertexai",
                    "config": {
                        "model": "embedding-001"
                    }
                }
            }
        )

    def _run(self, query: str, **kwargs) -> dict:
        """Query Several sources of information for knowledge base."""
        rag = self.get_rag()
        if self._directory:
            return rag.from_directory(self._directory)
