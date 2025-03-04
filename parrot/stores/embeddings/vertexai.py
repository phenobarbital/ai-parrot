from langchain_google_vertexai import VertexAIEmbeddings
from ...conf import VERTEX_PROJECT_ID, VERTEX_REGION
from .abstract import AbstractEmbed

class VertexAIEmbed(AbstractEmbed):
    """A wrapper class for VertexAI embeddings."""
    model_name: str = "text-embedding-004"

    def _create_embedding(self, model_name: str = None, project_id: str = None, region: str = None):
        # Embedding Model:
        return VertexAIEmbeddings(
            model_name=model_name or self.model_name,
            project=project_id or VERTEX_PROJECT_ID,
            location=region or VERTEX_REGION,
            request_parallelism=5,
            max_retries=4,
        )
