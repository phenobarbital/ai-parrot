from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, List, Tuple, Union
from pathlib import Path
import io
from PIL import (
    Image,
    ImageDraw,
    ImageFont,
    ImageEnhance,
    ImageOps
)
from navconfig.logging import logging
from datamodel.parsers.json import JSONContent  # pylint: disable=E0611
from ..clients import SUPPORTED_CLIENTS
from ..clients.google import GoogleGenAIClient, GoogleModel


logging.getLogger('pytesseract').setLevel(logging.WARNING)

class AbstractPipeline(ABC):
    """Abstract base class for all pipelines."""
    def __init__(
        self,
        llm: Any = None,
        llm_provider: str = "google",
        llm_model: Optional[str] = None,
        **kwargs: Any
    ):
        """
        Initialize the 3-step pipeline

        Args:
            llm_provider: LLM provider for identification
            llm_model: Specific LLM model
            api_key: API key
            detection_model: Object detection model to use
        """
        self.llm = llm
        self.llm_provider = None
        self.logger = logging.getLogger(f'parrot.pipelines.{self.__class__.__name__}')
        self._json  = JSONContent()
        if not llm:
            self.llm_provider = llm_provider.lower()
            self.llm = self._get_llm(
                llm_provider,
                llm_model,
                **kwargs
            )
        else:
            self.llm_provider = llm.client_name.lower()
        # Ensure a Google Client for multi-modal capabilities:
        self.roi_client = GoogleGenAIClient(
            model=GoogleModel.GEMINI_2_5_FLASH,
            temperature=0.0,
            max_retries=2,
            timeout=20
        )

    def _get_llm(
        self,
        provider: str,
        model: Optional[str] = None,
        **kwargs: Any
    ) -> Any:
        """
        Get the LLM client based on provider and model

        Args:
            provider: LLM provider name
            model: Specific model to use
            **kwargs: Additional parameters for client initialization

        Returns:
            Initialized LLM client
        """
        if provider not in SUPPORTED_CLIENTS:
            raise ValueError(
                f"Unsupported LLM provider: {provider}"
            )

        client_class = SUPPORTED_CLIENTS[provider]
        client = client_class(model=model, **kwargs)
        self.llm_provider = client.client_name.lower()
        return client

    def open_image(self, image_path: Union[Path, Image.Image]) -> Image.Image:
        """Open an image from a file path."""
        try:
            if isinstance(image_path, (str, Path)):
                img = Image.open(str(image_path))
            else:
                img = image_path
            if img.mode != "RGB":
                img = img.convert("RGB")
            img = self._enhance_image(img)
            self.logger.debug(
                f"Opened image {image_path} with size {img.size} and mode {img.mode}"
            )
            return img
        except Exception as e:
            self.logger.error(f"Error opening image {image_path}: {e}")
            raise

    def _clamp(self, w, h, x1, y1, x2, y2):
        x1, x2 = int(max(0, min(w - 1, min(x1, x2)))), int(max(0, min(w - 1, max(x1, x2))))
        y1, y2 = int(max(0, min(h - 1, min(y1, y2)))), int(max(0, min(h - 1, max(y1, y2))))
        return x1, y1, x2, y2

    def _save_detections(
        self,
        pil_image: Image.Image,
        poster_bounds: Tuple[int, int, int, int],
        detections: List[dict],
        save_path: str,
        poster_label: str = 'poster_panel',
    ) -> None:
        """Save debug image showing poster detection results"""
        try:
            debug_img = pil_image.copy()
            draw = ImageDraw.Draw(debug_img)
            # draw the detections:
            for det in detections:
                label = det.label
                conf = float(det.confidence or 0.0)
                bbox = det.bbox
                x1 = int(bbox.x1 * debug_img.width)
                y1 = int(bbox.y1 * debug_img.height)
                x2 = int(bbox.x2 * debug_img.width)
                y2 = int(bbox.y2 * debug_img.height)
                x1, y1, x2, y2 = self._clamp(debug_img.width, debug_img.height, x1, y1, x2, y2)

                color = (255, 165, 0) if label == poster_label else (0, 255, 255)
                draw.rectangle(
                    [(x1, y1), (x2, y2)],
                    outline=color,
                    width=3
                )
                draw.text(
                    (x1, y1 - 20),
                    f"{label} {conf:.2f}",
                    fill=color
                )

            # Draw final poster bounds in bright green
            x1, y1, x2, y2 = poster_bounds
            draw.rectangle(
                [(x1, y1), (x2, y2)],
                outline=(0, 255, 0),
                width=4
            )
            draw.text(
                (x1, y1 - 45),
                f"POSTER: {x2-x1}x{y2-y1}",
                fill=(0, 255, 0)
            )

            # Save debug image
            Path(save_path).parent.mkdir(parents=True, exist_ok=True)
            debug_img.save(save_path, quality=95)
            self.logger.debug(
                f"Saved poster debug image to {save_path}"
            )

        except Exception as e:
            self.logger.error(f"Failed to save debug image: {e}")

    def _enhance_image(
        self,
        pil_img: "Image.Image",
        brightness: float = 1.10,
        contrast: float = 1.20
    ) -> "Image.Image":
        """
        Enhances a PIL image by adjusting brightness and contrast.
        This generic utility can be used by any pipeline subclass.
        """
        self.logger.debug("Applying generic image enhancement...")
        # Brightness/contrast + autocontrast; tweak if needed
        pil = ImageEnhance.Brightness(pil_img).enhance(brightness)
        pil = ImageEnhance.Contrast(pil).enhance(contrast)
        pil = ImageOps.autocontrast(pil)
        return pil

    def _downscale_image(self, img: Image.Image, max_side=1024, quality=82) -> Image.Image:
        if img.mode != "RGB":
            img = img.convert("RGB")
        w, h = img.size
        s = max(w, h)
        if s > max_side:
            scale = max_side / float(s)
            img = img.resize((int(w*scale), int(h*scale)), Image.Resampling.LANCZOS)
        # (Optional) strip metadata by re-encoding
        bio = io.BytesIO()
        img.save(bio, format="JPEG", quality=quality, optimize=True)
        bio.seek(0)
        return Image.open(bio)

    @abstractmethod
    async def run(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        """
        Run the pipeline with the provided arguments

        Args:
            *args: Positional arguments for the pipeline
            **kwargs: Keyword arguments for the pipeline

        Returns:
            Dictionary with results of the pipeline execution
        """
        raise NotImplementedError("Subclasses must implement this method")
