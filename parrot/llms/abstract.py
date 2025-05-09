from abc import ABC
from typing import List
from langchain_core.prompts import ChatPromptTemplate


LLM_PRESETS = {
    "analytical": {"temperature": 0.1, "max_tokens": 4000},
    "creative": {"temperature": 0.7, "max_tokens": 6000},
    "balanced": {"temperature": 0.4, "max_tokens": 4000},
    "concise": {"temperature": 0.2, "max_tokens": 2000},
    "detailed": {"temperature": 0.3, "max_tokens": 8000},
    "comprehensive": {"temperature": 0.5, "max_tokens": 10000},
    "verbose": {"temperature": 0.6, "max_tokens": 12000},
}


class AbstractLLM(ABC):
    """Abstract Language Model class.
    """

    model: str = "databricks/dolly-v2-3b"
    supported_models: List[str] = []
    embed_model: str = None
    max_tokens: int = 2048
    max_retries: int = 2
    top_k: float = 41
    top_p: float = 0.90

    @classmethod
    def get_supported_models(cls):
        return cls.supported_models

    def __init__(self, *args, **kwargs):
        self.model = kwargs.get("model", self.model)
        self.task = kwargs.get("task", "text-generation")
        preset = kwargs.get("preset", None)
        if preset:
            presetting = LLM_PRESETS.get(preset, 'balanced')
            if presetting:
                self.temperature = presetting.get("temperature", 0.4)
                self.max_tokens = presetting.get("max_tokens", self.max_tokens)
            else:
                raise ValueError(f"Preset '{preset}' not found.")
        else:
            self.temperature: float = kwargs.get('temperature', 0.1)
            self.max_tokens: int = kwargs.get('max_tokens', self.max_tokens)
        self.top_k: float = kwargs.get('top_k', self.top_k)
        self.top_p: float = kwargs.get('top_p', self.top_p)
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
