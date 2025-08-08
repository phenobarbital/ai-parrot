from pathlib import Path
from typing import List, Optional
from pydantic import BaseModel
import pandas as pd
from .abstract import ImagePlugin
from ....clients.google import GoogleModel
from ....models import ObjectDetectionResult


def is_model_class(cls) -> bool:
    return isinstance(cls, type) and issubclass(cls, BaseModel)


DEFAULT_PROMPT = ''


class ClassifyBase(ImagePlugin):
    """
    ClassifyBase is an Abstract base class for performing image classification.
    Uses Gemini 2.5 multimodal model for image classification tasks.
    """
    column_name: str = "detections"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._model_name: str = kwargs.get(
            "model_name", GoogleModel.GEMINI_2_5_FLASH.value
        )
        model = kwargs.get(
            "detection_model",
            ObjectDetectionResult
        )
        self.reference_image: Optional[Path] = kwargs.get("reference_image", None)
        self._detection_model: Optional[BaseModel] = self._load_model(model)
        self.prompt: List[str] = kwargs.get("prompt", DEFAULT_PROMPT)
        self.filter_by: List[str] = kwargs.get(
            "filter_by", ["Boxes on Floor"]
        )
        self.filter_column: str = kwargs.get(
            "filter_column", "category"
        )

    async def start(self, **kwargs):
        if isinstance(self.reference_image, str):
            self.reference_image = Path(self.reference_image)
        if self.reference_image and not self.reference_image.is_absolute():
            self.reference_image = Path.cwd() / self.reference_image
        if self.reference_image and not self.reference_image.exists():
            self.logger.warning(
                f"Reference image {self.reference_image} does not exist. "
                "Classification may not work as expected."
            )
            self.reference_image = None

    def _load_model(self, model_name: str) -> BaseModel:
        """ Load the classification or categorization model based on the provided model name.
        This method uses importlib to dynamically import the model class.
        """
        if is_model_class(model_name):
            # Already a BaseModel instance, return it directly
            return model_name
        try:
            module_path, class_name = model_name.rsplit('.', 1)
            module = __import__(module_path, fromlist=[class_name])
            return getattr(module, class_name)
        except (ImportError, AttributeError) as e:
            raise ValueError(
                f"Failed to load categorization model: {model_name}. Error: {e}"
            )

    def _is_valid_filter_value(self, value):
        """Check if a filter value is valid (not NA/NaN/None)."""
        if pd.isna(value):
            return False
        if value is None:
            return False
        return True
