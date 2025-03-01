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

    def _get_device(self):
        return EMBEDDING_DEVICE

    @classmethod
    @abstractmethod
    def __new__(cls, model_name: str = None, **kwargs):
        """
        Create a new instance of the class.
        Args:
            model_name (str): The name of the model to use.

        Returns:
        An Embedding Model instance.
        """
