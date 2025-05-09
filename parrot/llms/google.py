from langchain_google_genai import (
    GoogleGenerativeAI,
    ChatGoogleGenerativeAI,
)
from navconfig import config
from .abstract import AbstractLLM


class GoogleGenAI(AbstractLLM):
    """GoogleGenAI.
        Using Google Generative AI models with Google Cloud AI Platform.
    """
    model: str = "gemini-2.0-flash"
    max_tokens: int = 4096
    top_k: float = 40
    top_p: float = 1.0
    supported_models: list = [
        "gemini-2.0-flash-exp",
        "gemini-2.0-flash",
        "gemini-2.0-flash-lite",
        "gemini-1.5-flash-001",
    ]

    def __init__(self, *args, use_chat: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        self.model = kwargs.get("model", "gemini-2.0-flash")
        self._api_key = kwargs.pop('api_key', config.get('GOOGLE_API_KEY'))
        if use_chat:
            base_llm = ChatGoogleGenerativeAI
        else:
            base_llm = GoogleGenerativeAI
        args = {
            "temperature": self.temperature,
            "api_key": self._api_key,
            "max_tokens": self.max_tokens,
            "max_retries": 4,
            "top_p": self.top_p,
            "top_k": self.top_k,
            "verbose": True
        }
        self._llm = base_llm(
            model=self.model,
            **args
        )
