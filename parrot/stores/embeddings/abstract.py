from abc import ABC, abstractmethod
from ...conf import (
    MAX_BATCH_SIZE,
    EMBEDDING_DEFAULT_MODEL,
    EMBEDDING_DEVICE
)

class AbstractEmbed(ABC):
    """A wrapper class for Create embeddings."""
    model_name: str = EMBEDDING_DEFAULT_MODEL
    encode_kwargs: str = {
        'normalize_embeddings': True,
        "batch_size": MAX_BATCH_SIZE
    }
    model_kwargs = {
        'device': EMBEDDING_DEVICE,
        'trust_remote_code':True
    }

    def __init__(self, model_name: str = None, **kwargs):
        self._embedding = self._create_embedding(model_name, **kwargs)

    @property
    def embedding(self):
        return self._embedding

    def free(self):
        """
        Free the resources.
        """
        pass

    def _get_device(self):
        return EMBEDDING_DEVICE

    @abstractmethod
    def _create_embedding(self, model_name: str = None, **kwargs):
        """
        Create Embedding Model.
        Args:
            model_name (str): The name of the model to use.

        Returns:
            Callable: Embedding Model.
        """
        pass
