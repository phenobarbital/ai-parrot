from typing import Optional
import torch
from .abstract import AbstractEmbed
from ...conf import CUDA_DEFAULT_DEVICE, EMBEDDING_DEVICE


class BaseEmbed(AbstractEmbed):
    """A wrapper class for Base embeddings.

    Use this class to Embedding Models that requires Torch/Transformers.
    """
    def _get_device(self, device_type: str = None, cuda_number: Optional[int] = None):
        """Get Default device for Torch and transformers.

        """
        # torch.backends.cudnn.deterministic = True
        if device_type is not None:
            return torch.device(device_type)
        if torch.cuda.is_available():
            # Use CUDA GPU if available
            if cuda_number is None:
                cuda_number = CUDA_DEFAULT_DEVICE
            return torch.device(f'cuda:{cuda_number}')
        if torch.backends.mps.is_available():
            # Use CUDA Multi-Processing Service if available
            return torch.device("mps")
        if EMBEDDING_DEVICE == 'cuda':
            if cuda_number is None:
                cuda_number = CUDA_DEFAULT_DEVICE
            return torch.device(f'cuda:{cuda_number}')
        else:
            return torch.device(EMBEDDING_DEVICE)
