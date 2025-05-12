import os
from navconfig import config, BASE_DIR
from google.cloud import aiplatform
from google.oauth2 import service_account
from vertexai.preview.vision_models import ImageGenerationModel
from langchain_google_vertexai import (
    ChatVertexAI,
    VertexAI,
    HarmBlockThreshold,
    HarmCategory
)
from navconfig.logging import logging
from .abstract import AbstractLLM

logging.getLogger(name='httpcore').setLevel(logging.WARNING)
logging.getLogger(name='httpx').setLevel(logging.WARNING)

safety_settings = {
    HarmCategory.HARM_CATEGORY_UNSPECIFIED: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_LOW_AND_ABOVE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_ONLY_HIGH,
}


class VertexLLM(AbstractLLM):
    """VertexLLM.

    Interact with VertexAI Language Model.

    Returns:
        _type_: VertexAI LLM.
    """
    model: str = "gemini-1.5-pro"
    max_tokens: int = 8192
    top_k: float = 40
    top_p: float = 0.95
    supported_models: list = [
        "gemini-2.5-pro-exp-03-25",
        "gemini-2.5-pro-preview-03-25",
        "gemini-2.5-flash-preview-04-17",
        "gemini-2.0-flash",
        "gemini-2.0-flash-lite",
        "gemini-2.0-flash-001",
        "gemini-1.5-pro",
        "gemini-1.5-flash-8b",
        "gemini-1.5-pro-exp-0801",
        "gemini-1.5-flash-preview-0514",
        "gemini-1.5-flash-001",
        "chat-bison@001",
        "chat-bison@002",
        "imagen-3.0-generate-002",
        "gemini-2.0-flash-live-001",
        "veo-2.0-generate-001"
    ]

    def __init__(self, *args, use_chat: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        project_id = config.get("VERTEX_PROJECT_ID")
        region = config.get("VERTEX_REGION")
        config_file = config.get('GOOGLE_CREDENTIALS_FILE', 'env/google/vertexai.json')
        config_dir = BASE_DIR.joinpath(config_file)
        vertex_credentials = service_account.Credentials.from_service_account_file(
            str(config_dir)
        )
        # os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(config_dir)
        args = {
            "project": project_id,
            "location": region,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "max_retries": 4,
            "top_p": self.top_p,
            # "top_k": self.top_k,
            "verbose": True,
            "credentials": vertex_credentials,
            # "safety_settings": safety_settings
        }
        if use_chat is True:
            base_llm = ChatVertexAI
        else:
            base_llm = VertexAI
        self._llm = base_llm(
            model_name=self.model,
            **args
        )
        # LLM
        self._version_ = aiplatform.__version__
