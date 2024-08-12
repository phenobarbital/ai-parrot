from langchain_core.prompts import ChatPromptTemplate
from langchain_groq import ChatGroq
from navconfig import config
from .abstract import AbstractLLM


class GroqLLM(AbstractLLM):
    """GroqLLM.
        Using Groq Open-source models.
    """
    model: str = "mixtral-8x7b-32768"

    def __init__(self, *args, **kwargs):
        self.model_type = kwargs.get("model_type", "text")
        system = kwargs.pop('system_prompt', "You are a helpful assistant.")
        human = kwargs.pop('human_prompt', "{question}")
        super().__init__(*args, **kwargs)
        self._api_key = kwargs.pop('api_key', config.get('GROQ_API_KEY'))
        self._llm = ChatGroq(
            model_name=self.model,
            groq_api_key=self._api_key,
            temperature=self.temperature,
            max_retries=self.max_retries,
            max_tokens=self.max_tokens,
            model_kwargs={
                "top_p": self.top_p,
                # "top_k": self.top_k,
            },
        )
        self._embed = None # Not supported
        self.prompt = ChatPromptTemplate.from_messages(
            [("system", system), ("human", human)]
        )
