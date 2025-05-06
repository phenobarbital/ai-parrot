import os
from navconfig import config, BASE_DIR
from google.cloud import aiplatform
from vertexai.preview.vision_models import ImageGenerationModel
from langchain_google_vertexai import (
    ChatVertexAI,
    VertexAI,
    HarmBlockThreshold,
    HarmCategory
)
from .abstract import AbstractLLM


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
    max_tokens: int = 1024
    supported_models: list = [
        "gemini-2.5-pro-exp-03-25",
        "gemini-2.5-pro-preview-03-25",
        "gemini-2.5-flash-preview-04-17",
        "gemini-2.0-flash",
        "gemini-2.0-flash-lite",
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
        # vertexai.init(project=project_id, location="us-central1")
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
        if use_chat is True:
            base_llm = ChatVertexAI
        else:
            base_llm = VertexAI
        self._llm = base_llm(
            model_name=self.model,
            # system_prompt="Always respond in the same language as the user's question. If the user's language is not English, translate your response into their language.",
            **self.args
        )
        # LLM
        self._version_ = aiplatform.__version__
