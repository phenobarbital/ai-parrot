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

    def __init__(self, *args, **kwargs):
        self.model_type = kwargs.get("model_type", "chat")
        super().__init__(*args, **kwargs)
        self._api_key = kwargs.pop('api_key', config.get('GOOGLE_API_KEY'))
        if self.model_type == 'chat':
            base_llm = ChatGoogleGenerativeAI
        else:
            base_llm = GoogleGenerativeAI
        self._llm = base_llm(
            model=self.model,
            api_key=self._api_key,
            temperature=self.temperature,
            **self.args
        )
