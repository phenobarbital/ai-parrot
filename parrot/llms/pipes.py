import torch
from langchain_community.llms import HuggingFacePipeline  # pylint: disable=import-error, E0611
from transformers import (
    AutoModelForCausalLM,
    AutoProcessor,
    LlavaForConditionalGeneration,
    AutoTokenizer,
    GenerationConfig,
    pipeline
)
from .abstract import AbstractLLM


class PipelineLLM(AbstractLLM):
    """PipelineLLM.

    Load a LLM (Language Model) from HuggingFace Hub.

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
        "meta-llama/Llama-2-7b-hf",
        'llava-hf/llava-1.5-7b-hf'
    ]

    def __init__(self, *args, **kwargs):
        self.batch_size = kwargs.get('batch_size', 4)
        self.use_llava: bool = kwargs.get('use_llava', False)
        self.model_args = kwargs.get('model_args', {})
        super().__init__(*args, **kwargs)
        dtype = kwargs.get('dtype', 'float16')
        if dtype == 'bfloat16':
            torch_dtype = torch.bfloat16
        if dtype == 'float16':
            torch_dtype = torch.float16
        elif dtype == 'float32':
            torch_dtype = torch.float32
        elif dtype == 'float8':
            torch_dtype = torch.float8
        else:
            torch_dtype = "auto"
        use_fast = kwargs.get('use_fast', True)
        if self.use_llava is False:
            self.tokenizer = AutoTokenizer.from_pretrained(
                self.model,
                chunk_size=self.max_tokens
            )
            self._model = AutoModelForCausalLM.from_pretrained(
                self.model,
                device_map="auto",
                torch_dtype=torch_dtype,
                trust_remote_code=True,
            )
            config = GenerationConfig(
                do_sample=True,
                temperature=self.temperature,
                max_new_tokens=self.max_tokens,
                top_p=self.top_p,
                top_k=self.top_k,
                repetition_penalty=1.15,
            )
            self._pipe = pipeline(
                task=self.task,
                model=self._model,
                tokenizer=self.tokenizer,
                return_full_text=True,
                use_fast=use_fast,
                device_map='auto',
                batch_size=self.batch_size,
                generation_config=config,
                pad_token_id = 50256,
                framework="pt"
            )
        else:
            self._model = LlavaForConditionalGeneration.from_pretrained(
                self.model,
                device_map="auto",
                torch_dtype=torch_dtype,
                trust_remote_code=True,
                low_cpu_mem_usage=True,
            )
            self.tokenizer = AutoTokenizer.from_pretrained(self.model)
            processor = AutoProcessor.from_pretrained(self.model)
            self._pipe = pipeline(
                task=self.task,
                model=self._model,
                tokenizer=self.tokenizer,
                use_fast=use_fast,
                device_map='auto',
                batch_size=self.batch_size,
                image_processor=processor.image_processor,
                framework="pt",
                **self.model_args
            )
        self._pipe.tokenizer.pad_token_id = self._pipe.model.config.eos_token_id
        self._llm = HuggingFacePipeline(
            model_id=self.model,
            pipeline=self._pipe,
            verbose=True
        )

    def pipe(self, *args, **kwargs):
        return self._pipe(
            *args,
            **kwargs,
            generate_kwargs={"max_new_tokens": self.max_tokens}
        )
