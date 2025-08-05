from typing import Optional
import gc
import torch
from .abstract import AbstractEmbed
from ...conf import CUDA_DEFAULT_DEVICE, EMBEDDING_DEVICE


class BaseEmbed(AbstractEmbed):
    """A wrapper class for Base embeddings.

    Use this class to Embedding Models that requires Torch/Transformers.
    """
    model_kwargs = {
        'device': EMBEDDING_DEVICE,
        'trust_remote_code':True
    }
    def _get_device(self, device_type: str = None, cuda_number: Optional[int] = None):
        """Get Default device for Torch and transformers.

        """
        # torch.backends.cudnn.deterministic = True
        if device_type is not None:
            return torch.device(device_type)
        if torch.cuda.is_available():
            if CUDA_DEFAULT_DEVICE == 'cpu':
                # Use CPU even if CUDA is available
                return torch.device('cpu')
            if cuda_number is not None:
                # Use specified CUDA GPU
                return torch.device(f'cuda:{cuda_number}')
            # Use CUDA GPU if available
            if cuda_number is None:
                return torch.device(f'cuda:0')
        if torch.backends.mps.is_available():
            # Use CUDA Multi-Processing Service if available
            return torch.device("mps")
        if EMBEDDING_DEVICE == 'cuda':
            if cuda_number is None and CUDA_DEFAULT_DEVICE != 'cpu':
                # Use CUDA GPU if available
                cuda_number = CUDA_DEFAULT_DEVICE
                return torch.device(f'cuda:{cuda_number}')
        return torch.device(EMBEDDING_DEVICE)

    def free(self):
        """
        Free the resources.
        """
        try:
            gc.collect()               # Run Python garbage collector to free unreferenced objects
            torch.cuda.empty_cache()   # Release cached memory blocks back to the GPU
        except Exception as e:
            print(f"Error: {e}")
