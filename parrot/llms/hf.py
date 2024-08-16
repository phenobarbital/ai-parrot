from langchain_community.llms import HuggingFacePipeline  # pylint: disable=import-error, E0611
from transformers import AutoModelForCausalLM, AutoTokenizer
from .abstract import AbstractLLM

class HuggingFace(AbstractLLM):
    """HuggingFace.

    Load a LLM (Language Model) from HuggingFace Hub.

    Only supports text-generation, text2text-generation, summarization and translation for now.

    Returns:
        _type_: an instance of HuggingFace LLM Model.
    """
    model: str = "databricks/dolly-v2-3b"
    embed_model: str = None
    max_tokens: int = 1024
    supported_models: list = [
        "databricks/dolly-v2-3b",
        "gpt2",
        "bigscience/bloom-1b7",
        "meta-llama/Llama-2-7b-hf"
    ]

    def __init__(self, *args, **kwargs):
        self.batch_size = kwargs.get('batch_size', 4)
        super().__init__(*args, **kwargs)
        self._tokenizer = AutoTokenizer.from_pretrained(self.model, chunk_size=self.max_tokens)
        self._model = AutoModelForCausalLM.from_pretrained(self.model, trust_remote_code=True)
        self._llm = HuggingFacePipeline.from_model_id(
            model_id=self.model,
            task=self.task,
            device_map='auto',
            batch_size=self.batch_size,
            model_kwargs={
                "max_length": self.max_tokens,
                "trust_remote_code": True
            },
            pipeline_kwargs={
                "temperature": self.temperature,
                "repetition_penalty":1.1,
                "max_new_tokens": self.max_tokens,
                **self.args
            }
        )
