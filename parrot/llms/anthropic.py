from navconfig import config
from navconfig.logging import logging
from langchain_anthropic import ChatAnthropic  # pylint: disable=E0401, E0611
from .abstract import AbstractLLM

logging.getLogger(name='anthropic').setLevel(logging.WARNING)

class AnthropicLLM(AbstractLLM):
    """AnthropicLLM.

    Interact with Anthropic Language Model.

    Returns:
        _type_: an instance of Anthropic (Claude) LLM Model.
    """
    model: str = 'claude-3-5-sonnet-20240620'  # Updated default to newer model
    embed_model: str = None
    max_tokens: int = 4096
    supported_models: list = [
        'claude-3-opus-20240229',
        'claude-3-sonnet-20240229',
        'claude-3-haiku-20240307',
        'claude-3-5-sonnet-20240620',
        'claude-3-5-sonnet-20240620',
        'claude-3-7-sonnet'
    ]

    # Models that support tool-calling
    tool_calling_models: list = [
        'claude-3-5-sonnet-20240620',
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.use_tools: bool = kwargs.get("use_tools", False)
        self.model = kwargs.get("model", 'claude-3-5-sonnet-20240620')
        self._api_key = kwargs.pop('api_key', config.get('ANTHROPIC_API_KEY'))
        args = {
            "temperature": self.temperature,
            "max_retries": 4,
            "top_p": self.top_p,
            "top_k": self.top_k,
            "verbose": True,
        }
        if self.use_tools:
            self.model = self.tool_calling_models[0]
        self._llm = ChatAnthropic(
            model_name=self.model,
            api_key=self._api_key,
            **args
        )
