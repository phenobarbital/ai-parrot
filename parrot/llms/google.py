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
    model: str = "gemini-pro"
    supported_models: list = [
        "models/text-bison-001",
        "models/chat-bison-001",
        "gemini-pro"
    ]

    def __init__(self, *args, use_chat: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        self._api_key = kwargs.pop('api_key', config.get('GOOGLE_API_KEY'))
        if use_chat:
            base_llm = ChatGoogleGenerativeAI
        else:
            base_llm = GoogleGenerativeAI
        self._llm = base_llm(
            model=self.model,
            api_key=self._api_key,
            temperature=self.temperature,
            max_tokens=None,
            timeout=None,
            max_retries=3,
            **self.args
        )
