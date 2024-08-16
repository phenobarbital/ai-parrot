import os
from navconfig import config, BASE_DIR
from google.cloud import aiplatform
from langchain_google_vertexai import (
    ChatVertexAI,
    VertexAI,
    VertexAIModelGarden,
    VertexAIEmbeddings
)
from .abstract import AbstractLLM

class VertexLLM(AbstractLLM):
    """VertexLLM.

    Interact with VertexAI Language Model.

    Returns:
        _type_: VertexAI LLM.
    """
    model: str = "gemini-1.0-pro"
    embed_model: str = "textembedding-gecko@003"
    max_tokens: int = 1024
    supported_models: list = [
        "gemini-1.0-pro",
        "gemini-1.5-pro-001",
        "gemini-1.5-pro-exp-0801",
        "gemini-1.5-flash-preview-0514",
        "gemini-1.5-flash-001",
        "chat-bison@001",
        "claude-3-opus@20240229",
        'claude-3-5-sonnet@20240620'
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        use_garden: bool = kwargs.get("use_garden", False)
        project_id = config.get("VERTEX_PROJECT_ID")
        region = config.get("VERTEX_REGION")
        config_file = config.get('GOOGLE_CREDENTIALS_FILE', 'env/google/vertexai.json')
        config_dir = BASE_DIR.joinpath(config_file)
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(config_dir)
        self.args = {
            "project": project_id,
            "location": region,
            "max_output_tokens": self.max_tokens,
            "temperature": self.temperature,
            "max_retries": 4,
            "top_p": self.top_p,
            "top_k": self.top_k,
            "verbose": True,
        }
        if use_garden is True:
            base_llm = VertexAIModelGarden
            self.args['endpoint_id'] = self.model
        elif self.model == "chat":
            self.args['model_name'] = "chat-bison@001"
            base_llm = ChatVertexAI
        else:
            self.args['model_name'] = self.model
            base_llm = VertexAI
        # LLM
        self._llm = base_llm(
            system_prompt="Always respond in the same language as the user's question. If the user's language is not English, translate your response into their language.",
            **self.args
        )
        # Embedding Model:
        embed_model = kwargs.get("embed_model", self.embed_model)
        self._embed = VertexAIEmbeddings(
            model_name=embed_model,
            project=project_id,
            location=region,
            request_parallelism=5,
            max_retries=4,
            temperature=self.temperature,
            top_p=self.top_p,
            top_k=self.top_k,
        )
        self._version_ = aiplatform.__version__
