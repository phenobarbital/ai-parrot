from pathlib import Path
from typing import List, Optional, Union
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
        # Modified: filter_column can be None to disable filtering
        self.filter_column: Optional[str] = kwargs.get("filter_column", None)

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

    def _should_apply_filter(self) -> bool:
        """
        Determine if filtering should be applied based on filter_column.
        Returns False if filter_column is None, True otherwise.
        """
        return self.filter_column is not None

    def _filter_dataset(self, dataset: pd.DataFrame) -> pd.DataFrame:
        """
        Apply filtering to the dataset if filter_column is specified.
        If filter_column is None, return the entire dataset unchanged.

        Args:
            dataset: Input DataFrame to potentially filter

        Returns:
            Filtered DataFrame or original dataset if no filtering should be applied
        """
        if not self._should_apply_filter():
            self.logger.debug(
                "Filter column is None - processing entire dataset without filtering"
            )
            return dataset

        if self.filter_column not in dataset.columns:
            self.logger.warning(
                f"Filter column '{self.filter_column}' not found in dataset. "
                "Processing entire dataset."
            )
            return dataset

        # Apply filtering logic
        if not self.filter_by:
            self.logger.warning("filter_by is empty - processing entire dataset")
            return dataset

        # Filter the dataset based on filter_by values in filter_column
        mask = dataset[self.filter_column].apply(
            lambda x: self._is_valid_filter_value(x) and x in self.filter_by
        )

        filtered_dataset = dataset[mask].copy()

        self.logger.info(
            f"Filtered dataset from {len(dataset)} to {len(filtered_dataset)} rows "
            f"using filter_column='{self.filter_column}' with values {self.filter_by}"
        )

        return filtered_dataset

    async def process_dataset(self, dataset: pd.DataFrame) -> pd.DataFrame:
        """
        Process the dataset with optional filtering.
        This method should be implemented by subclasses to handle the actual classification.

        Args:
            dataset: Input DataFrame

        Returns:
            Processed DataFrame with classification results
        """
        # Apply filtering (or not, depending on filter_column)
        filtered_dataset = self._filter_dataset(dataset)

        # Placeholder for actual classification logic
        # Subclasses should override this method
        processed_dataset = await self._classify_images(filtered_dataset)

        return processed_dataset

    async def _classify_images(self, dataset: pd.DataFrame) -> pd.DataFrame:
        """
        Perform the actual image classification.
        This method should be implemented by subclasses.

        Args:
            dataset: Filtered (or unfiltered) DataFrame to classify

        Returns:
            DataFrame with classification results
        """
        raise NotImplementedError("Subclasses must implement _classify_images method")

    def configure_filtering(
        self,
        filter_column: Optional[str] = None,
        filter_by: Optional[List[str]] = None
    ) -> None:
        """
        Dynamically configure filtering parameters.

        Args:
            filter_column: Column to filter by. Set to None to disable filtering.
            filter_by: Values to filter by. Only used if filter_column is not None.
        """
        if filter_column is not None:
            self.filter_column = filter_column

        if filter_by is not None:
            self.filter_by = filter_by

        self.logger.info(
            f"Filtering configured: filter_column='{self.filter_column}', "
            f"filter_by={self.filter_by if self.filter_column else 'N/A (filtering disabled)'}"
        )
