from langchain_openai import (  # pylint: disable=E0401, E0611
    OpenAI,
    ChatOpenAI,
)
from navconfig import config
from .abstract import AbstractLLM


class OpenAILLM(AbstractLLM):
    """OpenAI.
    Interact with OpenAI Language Model.

    Returns:
        _type_: an instance of OpenAI LLM Model.
    """
    model: str = "gpt-4-turbo"
    max_tokens: int = 1024
    supported_models: list = [
        'gpt-4o-mini',
        'gpt-4-turbo',
        'gpt-4-turbo-preview',
        'gpt-4o',
        'gpt-3.5-turbo',
        'gpt-3.5-turbo-instruct',
        'dall-e-3'
        'tts-1',
    ]

    def __init__(self, *args, **kwargs):
        self.model_type = kwargs.get("model_type", "text")
        super().__init__(*args, **kwargs)
        self.model = kwargs.get("model", "davinci")
        self._api_key = kwargs.pop('api_key', config.get('OPENAI_API_KEY'))
        organization = config.get("OPENAI_ORGANIZATION")
        if self.model_type == 'chat':
            base_llm = ChatOpenAI
        else:
            base_llm = OpenAI
        self._llm = base_llm(
            model_name=self.model,
            api_key=self._api_key,
            organization=organization,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            **self.args
        )
