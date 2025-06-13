from langchain_openai import (  # pylint: disable=E0401, E0611
    OpenAI,
    ChatOpenAI,
)
from langchain_core.rate_limiters import InMemoryRateLimiter
from tenacity import (
    retry,
    stop_after_attempt,
    wait_random_exponential,
    retry_if_exception_type,
)
from openai import RateLimitError, APIError, Timeout

from navconfig import config
from navconfig.logging import logging
from .abstract import AbstractLLM


logging.getLogger(name='openai').setLevel(logging.WARNING)
logging.getLogger(name='httpcore').setLevel(logging.WARNING)
logging.getLogger(name='httpx').setLevel(logging.WARNING)


rate_limiter = InMemoryRateLimiter(
    requests_per_second=0.5,  # Adjust based on your OpenAI rate limits
    check_every_n_seconds=0.5, # How frequently to check for token availability
    max_bucket_size=5         # Max burst of requests allowed
)

class BackoffChatOpenAI(ChatOpenAI):
    @retry(
        reraise=True,
        stop=stop_after_attempt(4),                            # try up to 4 times
        wait=wait_random_exponential(min=20, max=300),         # waits ~10s → 20s → 40s … up to 5min
        retry=(
            retry_if_exception_type(RateLimitError) |
            retry_if_exception_type(APIError)       |
            retry_if_exception_type(Timeout)
        ),
    )
    def _generate(self, messages, stop=None):
        return super()._generate(messages, stop)


class OpenAILLM(AbstractLLM):
    """OpenAI.
    Interact with OpenAI Language Model.

    Returns:
        _type_: an instance of OpenAI LLM Model.
    """
    model: str = "gpt-4-turbo"
    max_tokens: int = 8192
    top_k: float = 40
    top_p: float = 1.0
    supported_models: list = [
        "gpt-4.1",
        "gpt-4o-mini",
        'gpt-4.1-2025-04-14',
        'o4-mini-2025-04-16',
        "o3-2025-04-16",
        'gpt-4-turbo',
        'gpt-4o',
        'gpt-3.5-turbo',
        'gpt-3.5-turbo-instruct',
        'dall-e-3'
        'tts-1',
    ]

    def __init__(self, *args, use_chat: bool = False, **kwargs):
        self.model_type = kwargs.get("model_type", "text")
        super().__init__(*args, **kwargs)
        self.model = kwargs.get("model", "davinci")
        self._api_key = kwargs.pop('api_key', config.get('OPENAI_API_KEY'))
        organization = config.get("OPENAI_ORGANIZATION")
        if use_chat:
            base_llm = BackoffChatOpenAI
        else:
            base_llm = OpenAI
        args = {
            "api_key": self._api_key,
            "organization": organization,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "max_retries": 4,
            "top_p": self.top_p,
            "verbose": True,
        }
        self._llm = base_llm(
            model_name=self.model,
            rate_limiter=rate_limiter,
            **args
        )
