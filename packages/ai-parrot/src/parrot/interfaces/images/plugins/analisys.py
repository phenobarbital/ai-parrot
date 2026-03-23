from pathlib import Path
from typing import Union, Dict, List
import yaml
from pydantic import BaseModel
from PIL import Image
from .abstract import ImagePlugin
from ....clients.google import GoogleModel, GoogleGenAIClient


class AnalysisPlugin(ImagePlugin):
    """Plugin for analyzing images."""
    column_name: str = "image_features"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._model_name: str = kwargs.get(
            "model_name", GoogleModel.GEMINI_2_5_FLASH.value
        )
        self.prompt_path = kwargs.get("prompt_path", Path.cwd() / "prompts")
        self.prompt_file: Union[str, Path] = kwargs.get(
            "prompt_file", "default_analysis_prompt.json"
        )
        self._structured_outputs: Dict[str, BaseModel] = kwargs.get(
            "structured_outputs", {}
        )
        self.filter_by: List[str] = kwargs.get(
            "filter_by", ["Boxes on Floor"]
        )
        self.filter_column: str = kwargs.get(
            "filter_column", "category"
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

    async def start(self, **kwargs):
        """Initialize the plugin and load the prompt."""
        if isinstance(self.prompt_file, str):
            self.prompt_file = Path(self.prompt_file)
        if not self.prompt_file.is_absolute():
            self.prompt_file = self.prompt_path.joinpath(self.prompt_file)
        if not self.prompt_file.exists():
            raise FileNotFoundError(
                f"Prompt file {self.prompt_file} does not exist."
            )
        # From the prompt File, load the prompt content:
        content = self.prompt_file.read_text()
        # open from YAML file:
        try:
            self.prompt = yaml.safe_load(content).get('analysis_configs', {})
        except Exception as e:
            raise ValueError(
                f"Failed to decode YAML from prompt file {self.prompt_file}. Error: {e}"
            )
        # Iterate over all prompts and load the models:
        for key, value in self.prompt.items():
            structured_output = value.get("structured_output", None)
            if structured_output is None:
                self.logger.warning(
                    f"No structured output defined for {key} in prompt file."
                )
                continue
            try:
                self._structured_outputs[key] = self._load_model(structured_output)
            except Exception as e:
                raise ValueError(
                    f"Failed to load structured output model for {key}. Error: {e}"
                )

    def _extract_analysis_results(self, result) -> dict:
        """
        Extract analysis results from AIMessage object and return as dictionary.

        Args:
            result: AIMessage object with structured_output containing InkWallAnalysis

        Returns:
            dict: Dictionary with analysis data
        """
        if hasattr(result, 'output') and result.output:
            analysis_result = result.output
            # Convert Pydantic model to dictionary
            return analysis_result.dict()
        else:
            raise ValueError("No output found in the result object.")

    async def analyze(self, image: Union[Path, Image.Image], **kwargs) -> dict:
        """
        Analyze the ink wall image and perform structured analysis.

        :param image: Image Bytes opened with PIL Image.open
        :return: A dictionary containing the updated detections column.
        """
        row = kwargs.get("row", None)
        # Check filter condition
        if hasattr(self, 'filter_column') and hasattr(self, 'filter_by'):
            if row[self.filter_column] not in self.filter_by:
                self.logger.info(
                    f"Skipping for analysis for row {row.name} with category {row[self.filter_column]}"
                )
                return None
        image_classification = row[self.filter_column]
        if not image_classification:
            self.logger.warning(
                f"Row {row.name} has no valid category for analysis."
            )
            return None
        structured_output = self._structured_outputs.get(image_classification, None)
        if structured_output is None:
            self.logger.error(
                f"No structured output defined for image classification: {image_classification}"
            )
            return None
        # Perform analysis based on the image classification
        try:
            async with GoogleGenAIClient() as client:
                _result = await client.ask_to_image(
                    image=image,
                    prompt=self.prompt[image_classification]['prompt'],
                    structured_output=structured_output,
                    model=self._model_name
                )
                if _result and isinstance(_result.output, structured_output):
                    content = self._extract_analysis_results(_result)
                    return {
                        "analysis:": image_classification,
                        **content
                    }
                else:
                    self.logger.error(
                        f"Unexpected output format for {image_classification} analysis."
                    )
                    return None
        except Exception as e:
            self.logger.error(
                f"Error during analysis for {image_classification}: {e}"
            )
            return None
