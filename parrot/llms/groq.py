from langchain_core.prompts import ChatPromptTemplate
from langchain_groq import ChatGroq
from navconfig import config
from navconfig.logging import logging
from .abstract import AbstractLLM


logging.getLogger(name='groq').setLevel(logging.WARNING)
# Set the logging level for the 'httpcore' logger to WARNING
logging.getLogger(name='httpcore').setLevel(logging.WARNING)
logging.getLogger(name='httpx').setLevel(logging.WARNING)
class GroqLLM(AbstractLLM):
    """GroqLLM.
        Using Groq Open-source models.
    """
    model: str = "llama-3.3-70b-versatile"
    max_tokens: int = 8192
    top_k: float = 40
    top_p: float = 1.0
    supported_models: list = [
        "llama-3.3-70b-versatile",
        "qwen-2.5-32b",
        "qwen-2.5-coder-32b",
        "deepseek-r1-distill-qwen-32b",
        "deepseek-r1-distill-llama-70b",
        "meta-llama/llama-4-scout-17b-16e-instruct",
        "gemma2-9b-it",
        "llama3-70b-8192",
        "llama3-80b-8192",
        "llama3-8b-8192",
        "llama-guard-3-8b",
        "llama-3.1-8b-instant",
        "mistral-saba-24b",
        "mixtral-8x7b-32768",
        "whisper-large-v3",
        "whisper-large-v3-turbo",
    ]

    def __init__(self, *args, **kwargs):
        self.model_type = kwargs.get("model_type", "text")
        system = kwargs.pop('system_prompt', "You are a helpful assistant.")
        human = kwargs.pop('human_prompt', "{question}")
        frequency: float = kwargs.get('frequency', 0.5)
        presence: float = kwargs.get('presence', 0.5)
        super().__init__(*args, **kwargs)
        self._api_key = kwargs.pop('api_key', config.get('GROQ_API_KEY'))
        args = {
            "temperature": self.temperature,
            "api_key": self._api_key,
            "max_retries": 4,
            "max_tokens": self.max_tokens,
            "verbose": True,
        }
        self._llm = ChatGroq(
            model_name=self.model,
            **args,
            model_kwargs={
                "top_p": self.top_p,
                # "top_k": self.top_k,
                "frequency_penalty": frequency,
                "presence_penalty": presence
            },
        )
        self._embed = None # Not supported
        self.prompt = ChatPromptTemplate.from_messages(
            [("system", system), ("human", human)]
        )
