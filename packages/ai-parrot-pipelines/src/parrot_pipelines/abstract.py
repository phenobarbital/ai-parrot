from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, List, Tuple, Union
from pathlib import Path
import io
from PIL import Image, ImageDraw, ImageEnhance, ImageOps
from navconfig.logging import logging
from datamodel.parsers.json import JSONContent  # pylint: disable=E0611
from parrot.clients.factory import LLMFactory
from parrot_pipelines.planogram.backend import UNSET, ResolvedBackend, _Unset, resolve_backend

logging.getLogger("pytesseract").setLevel(logging.WARNING)


class AbstractPipeline(ABC):
    """Abstract base class for all pipelines."""

    def __init__(
        self,
        llm: Any = None,
        llm_provider: Union[str, _Unset] = UNSET,
        llm_model: Union[str, None, _Unset] = UNSET,
        *,
        config_backend: Optional[str] = None,
        **kwargs: Any,
    ):
        """Initialize the pipeline and resolve its LLM backend (FEAT-574).

        Backend precedence: an explicit ``llm`` (client instance or ``"provider:model"``
        string) → explicit ``llm_provider`` / ``llm_model`` applied over the configured
        backend → ``config_backend`` → the package default (``DEFAULT_LLM_BACKEND``).
        A provider switch without a model never inherits the other provider's model id.

        Args:
            llm: An LLM client instance, a ``"provider:model"`` string, or ``None``.
            llm_provider: Explicit provider name; omitted when ``UNSET``.
            llm_model: Explicit model name; omitted when ``UNSET`` or ``None``.
            config_backend: The configuration's ``llm_backend`` (``"provider:model"``);
                consumed here and never forwarded to the client constructor.
            **kwargs: Extra keyword arguments forwarded to the client constructor.
        """
        self.llm = llm
        self.llm_provider = None
        self.logger = logging.getLogger(f"parrot.pipelines.{self.__class__.__name__}")
        self._json = JSONContent()
        self.resolved_backend: ResolvedBackend = resolve_backend(llm, llm_provider, llm_model, config_backend)
        if llm is None or isinstance(llm, str):
            # No client instance given: build it from the resolved backend (FEAT-574).
            # _get_llm() overwrites llm_provider from the built client's client_name.
            self.llm_provider = self.resolved_backend.provider
            self.llm = self._get_llm(self.resolved_backend.provider, self.resolved_backend.model, **kwargs)
        else:
            self.llm_provider = llm.client_name.lower()
        self.logger.debug(
            "Resolved LLM backend: %s (%s)", self.resolved_backend.as_string(), self.resolved_backend.origin
        )
        # Ensure a Google Client for multi-modal capabilities:
        # FEAT-523 (TASK-2846): lazy import — core/satellites must not
        # import a provider client at module scope (AC-3).
        from parrot.clients.google import GoogleGenAIClient

        self.roi_client = GoogleGenAIClient(model="gemini-3-flash-preview", temperature=0.0, max_retries=2, timeout=20)

    def _get_llm(self, provider: str, model: Optional[str] = None, **kwargs: Any) -> Any:
        """
        Get the LLM client based on provider and model

        Args:
            provider: LLM provider name
            model: Specific model to use
            **kwargs: Additional parameters for client initialization

        Returns:
            Initialized LLM client
        """
        # FEAT-523 (TASK-2847): discover-then-return — SUPPORTED_CLIENTS is
        # lazily populated by LLMFactory._discover(); go through the
        # factory helper rather than importing the dict directly.
        supported_clients = LLMFactory.supported_clients()
        if provider not in supported_clients:
            raise ValueError(f"Unsupported LLM provider: {provider}")

        client_class = supported_clients[provider]
        # FEAT-523 (TASK-2852): a provider now registered via a real
        # `parrot.clients` entry point (rather than the transitional
        # in-core walk) is stored as `ep.load` itself — a zero-arg
        # callable, not the class directly. Resolve it the same way
        # LLMFactory.create() does before instantiating.
        if callable(client_class) and not isinstance(client_class, type):
            client_class = client_class()
        client = client_class(model=model, **kwargs)
        self.llm_provider = client.client_name.lower()
        return client

    def open_image(self, image_path: Union[Path, Image.Image], *, enhance: bool = True) -> Image.Image:
        """Open an image from a file path (or pass a PIL image through) as RGB.

        Args:
            image_path: Path/str to an image file, or an already opened PIL image.
            enhance: When True (default, legacy behaviour) apply ``_enhance_image``
                (brightness/contrast). The FEAT-574 cycle passes False so perception, OCR and
                LLM crops use the untouched full-resolution image.

        Returns:
            The RGB image.
        """
        try:
            if isinstance(image_path, (str, Path)):
                img = Image.open(str(image_path))
            else:
                img = image_path
            if img.mode != "RGB":
                img = img.convert("RGB")
            if enhance:
                img = self._enhance_image(img)
            self.logger.debug(f"Opened image {image_path} with size {img.size} and mode {img.mode}")
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
        poster_label: str = "poster_panel",
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
                draw.rectangle([(x1, y1), (x2, y2)], outline=color, width=3)
                draw.text((x1, y1 - 20), f"{label} {conf:.2f}", fill=color)

            # Draw final poster bounds in bright green
            x1, y1, x2, y2 = poster_bounds
            draw.rectangle([(x1, y1), (x2, y2)], outline=(0, 255, 0), width=4)
            draw.text((x1, y1 - 45), f"POSTER: {x2-x1}x{y2-y1}", fill=(0, 255, 0))

            # Save debug image
            Path(save_path).parent.mkdir(parents=True, exist_ok=True)
            debug_img.save(save_path, quality=95)
            self.logger.debug(f"Saved poster debug image to {save_path}")

        except Exception as e:
            self.logger.error(f"Failed to save debug image: {e}")

    def _enhance_image(self, pil_img: "Image.Image", brightness: float = 1.10, contrast: float = 1.20) -> "Image.Image":
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
            img = img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
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
