from abc import ABC
from typing import List
from langchain_core.prompts import ChatPromptTemplate


class AbstractLLM(ABC):
    """Abstract Language Model class.
    """

    model: str = "databricks/dolly-v2-3b"
    supported_models: List[str] = []
    embed_model: str = None
    max_tokens: int = 1024
    max_retries: int = 3

    @classmethod
    def get_supported_models(cls):
        return cls.supported_models

    def __init__(self, *args, **kwargs):
        self.model = kwargs.get("model", "databricks/dolly-v2-3b")
        self.task = kwargs.get("task", "text-generation")
        self.temperature: float = kwargs.get('temperature', 0.6)
        self.max_tokens: int = kwargs.get('max_tokens', 1024)
        self.top_k: float = kwargs.get('top_k', 10)
        self.top_p: float = kwargs.get('top_p', 0.90)
        self.args = {
            "top_p": self.top_p,
            "top_k": self.top_k,
        }
        self._llm = None
        self._embed = None

    def get_llm(self):
        return self._llm

    def get_embedding(self):
        return self._embed

    def __call__(self, text: str, **kwargs):
        return self._llm.invoke(text, **kwargs)

    def get_prompt(self, system: tuple, human: str) -> ChatPromptTemplate:
        """Get a prompt for the LLM."""
        return ChatPromptTemplate.from_messages(
            [("system", system), ("human", human)]
        )
