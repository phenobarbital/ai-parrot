from typing import Optional
from io import BytesIO
from PIL import Image
import numpy as np
import torch
from transformers import AutoImageProcessor, AutoModel
from .abstract import ImagePlugin

SUPPORTED_MODELS = {
    "dinov2-base": {
        "model": "facebook/dinov2-base",
        "vector_dim": 768
    },
    "vit-base": {
        "model": "google/vit-base-patch16-224-in21k",
        "vector_dim": 768
    },
    "dinov2-large": {
        "model": "facebook/dinov2-large",
        "vector_dim": 1024
    },
}


class VisionTransformerPlugin(ImagePlugin):
    """
    VisionTransformerPlugin is a plugin for generating vector representations of images.
    It extends the ImagePlugin class and implements the analyze method to generate vectors.
    """
    column_name: str = "image_vector"

    def __init__(self, *args, device: Optional[str] = None, **kwargs):
        super().__init__(*args, **kwargs)
        self._vector_model: str = kwargs.get("model_name", "dinov2-base")
        self._vector_size: int = kwargs.get("vector_size", 768)
        self._model_info = SUPPORTED_MODELS.get(self._vector_model)
        use_gpu: bool = kwargs.get("use_gpu", False)
        if use_gpu and not torch.cuda.is_available():
            raise ValueError("GPU is not available. Please set use_gpu to False.")
        if not self._model_info:
            raise ValueError(
                f"Unsupported model name: {self._vector_model}. "
                f"Supported models are: {list(SUPPORTED_MODELS.keys())}"
            )
        if use_gpu:
            self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        else:
            self.device = "cpu"

    async def start(self):
        self.processor = AutoImageProcessor.from_pretrained(self._model_info["model"])
        self.model = AutoModel.from_pretrained(self._model_info["model"]).to(self.device)
        self.model.eval()
        return self

    async def dispose(self):
        """
        Close the model and processor.
        """
        if hasattr(self, "model"):
            del self.model
        if hasattr(self, "processor"):
            del self.processor
        torch.cuda.empty_cache()
        return self

    async def analyze(self, image: Image.Image, **kwargs) -> np.ndarray:
        """
        Generate a vector representation of the given image.

        :param image: Image Bytes opened with PIL Image.open
        :return: Vector representation of the image.
        """
        if image is None:
            return None
        try:
            image = image.convert("RGB")
            # Resize and normalize the image
            # image = image.resize((224, 224))
            # image = np.array(image) / 255.0
            # image = np.transpose(image, (2, 0, 1))  # Change to CxHxW format
            # image = torch.tensor(image, dtype=torch.float32).unsqueeze(0).to(self.device)
            # # Normalize the image
            # image = (image - 0.5) / 0.5
            # Convert to tensor and move to device
            inputs = self.processor(images=image, return_tensors="pt").to(self.device)
            with torch.no_grad():
                outputs = self.model(**inputs)
                # Use CLS token representation
                vector = outputs.last_hidden_state[:, 0].squeeze().cpu().numpy()
                vector = vector / np.linalg.norm(vector)
                return vector.tolist()
        except Exception as e:
            self.logger.error(
                f"Error in VisionTransformer analysis: {str(e)}"
            )
            return None
        #     features = self.model(**image).last_hidden_state
        #     features = features[:, 0, :].cpu().numpy()
        # if features.shape[1] != self._vector_size:
        #     raise ValueError(
        #         f"Vector size mismatch: expected {self._vector_size}, got {features.shape[1]}"
        #     )
        # return features
