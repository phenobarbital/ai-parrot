from pathlib import Path
from typing import List, Union, Optional
from enum import Enum, EnumMeta
from pydantic import BaseModel, Field
from PIL import Image
from .abstract import ImagePlugin
from ....clients.google import GoogleModel, GoogleGenAIClient

DEFAULT_PROMPT = """
You are an expert in retail image analysis. Your task is to classify the provided image into one of the following categories.
Please read the definitions carefully and choose the single best fit.
"""

def is_model_class(cls) -> bool:
    return isinstance(cls, type) and issubclass(cls, BaseModel)


def is_enum_class(cls) -> bool:
    return isinstance(cls, type) and issubclass(cls, Enum)

class ImageCategory(str, Enum):
    """Enumeration for retail image categories."""
    INK_WALL = "Ink Wall"
    FRONT_OF_STORE = "Front of Store"
    SHELVES_WITH_PRODUCTS = "Shelves with Products"
    BOXES_ON_FLOOR = "Boxes on Floor"
    MERCHANDISING_ENDCAP = "Merchandising Endcap"
    OTHER = "Other"


class ImageClassification(BaseModel):
    """Schema for classifying a retail image."""
    category: ImageCategory = Field(
        ...,
        description="The best-fitting category for the image based on the provided definitions."
    )
    confidence_score: float = Field(
        ..., ge=0.0, le=1.0,
        description="The model's confidence in its classification, from 0.0 to 1.0."
    )
    reasoning: str = Field(
        ...,
        description="A brief explanation for why the image was assigned to this category."
    )


class ClassificationPlugin(ImagePlugin):
    """
    ClassificationPlugin is a plugin for performing image classification.
    Uses Gemini 2.5 multimodal model for image classification tasks.
    """
    column_name: str = "image_classifications"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._model_name: str = kwargs.get(
            "model_name", GoogleModel.GEMINI_2_5_FLASH.value
        )
        self.prompt: List[str] = kwargs.get("prompt", DEFAULT_PROMPT)
        self.confidence: float = kwargs.get("confidence", 0.5)
        self._classification_model = kwargs.get(
            "classification_model", self._load_classification_model(
                ImageClassification
            )
        )
        self._category_model = kwargs.get(
            "category_model", self._load_category_model(
                ImageCategory
            )
        )

    def _load_model(self, model_name: str) -> BaseModel:
        """ Load the classification or categorization model based on the provided model name.
        This method uses importlib to dynamically import the model class.
        """
        try:
            module_path, class_name = model_name.rsplit('.', 1)
            module = __import__(module_path, fromlist=[class_name])
            return getattr(module, class_name)
        except (ImportError, AttributeError) as e:
            raise ValueError(
                f"Failed to load categorization model: {model_name}. Error: {e}"
            )

    def _load_category_model(self, model_name: Union[str, Enum]) -> Enum:
        """
        Load the categorization model based on the provided model name.

        Category Model is a BaseModel that defines the structure of the categorization result.
        model_name will be the python path where the model is stored.
        for example, resources.models.categorization_models.ImageCategory
        uses importlib to dynamically import the model class.
        """
        if is_enum_class(model_name):
            # Already a Enum instance, return it directly
            return model_name
        elif isinstance(model_name, str):
            # Attempt to import the model class dynamically
            return self._load_model(model_name)
        else:
            raise ValueError(
                "Category model_name must be a string or a Enum instance."
            )

    def _load_classification_model(self, model_name: Union[str, BaseModel]) -> BaseModel:
        """
        Load the classification model based on the provided model name.
        """
        if is_model_class(model_name):
            # Already a BaseModel instance, return it directly
            return model_name
        elif isinstance(model_name, str):
            # Attempt to import the model class dynamically
            return self._load_model(model_name)
        else:
            raise ValueError(
                "Classification model_name must be a string or a BaseModel instance."
            )

    async def analyze(self, image: Union[Path, Image.Image], **kwargs) -> dict:
        """
        Analyze the image and classify it into a retail category.

        :param image: Image Bytes opened with PIL Image.open
        :return: A dictionary containing the classification result.
        """
        async with GoogleGenAIClient() as client:
            _result = await client.ask_to_image(
                image=image,
                prompt=self.prompt,
                structured_output=self._classification_model,
                model=self._model_name
            )
            if _result and isinstance(_result.output, self._classification_model):
                result = _result.output
                # evaluate if confidence_score is above the threshold
                if result.confidence_score < self.confidence:
                    self.logger.warning(
                        f"Classification confidence {result.confidence_score} "
                        f"is below the threshold {self.confidence}. "
                        "Returning None."
                    )
                    return None
                # If the model returns a valid classification result
                return result.dict()
            else:
                self.logger.error(
                    "The model did not return a valid classification result."
                )
                return None
