"""Abstract base class for planogram type composables."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple, Union, TYPE_CHECKING

from PIL import Image

from parrot.models.detections import (
    Detection,
    IdentifiedProduct,
    ShelfRegion,
)
from parrot.models.compliance import ComplianceResult

if TYPE_CHECKING:
    from ..plan import PlanogramCompliance
    from ..models import PlanogramConfig


class AbstractPlanogramType(ABC):
    """Contract for planogram type composables.

    Each composable receives a reference to the parent PlanogramCompliance
    pipeline for access to shared utilities (LLM, image helpers, config).

    Concrete implementations handle the type-specific logic for:
    - ROI computation (how to find the region of interest)
    - Macro object detection (poster, logo, backlit, etc.)
    - Product detection and identification
    - Planogram compliance checking

    Args:
        pipeline: Parent PlanogramCompliance instance providing shared
            utilities (LLM clients, image processing, config).
        config: The PlanogramConfig for this compliance run.
    """

    def __init__(
        self,
        pipeline: "PlanogramCompliance",
        config: "PlanogramConfig",
    ) -> None:
        self.pipeline = pipeline
        self.config = config
        self.logger = pipeline.logger

    @abstractmethod
    async def compute_roi(
        self,
        img: Image.Image,
    ) -> Tuple[
        Optional[Tuple[int, int, int, int]],
        Optional[Any],
        Optional[Any],
        Optional[Any],
        List[Any],
    ]:
        """Compute the region of interest for this planogram type.

        Args:
            img: The input PIL image.

        Returns:
            Tuple of (endcap_bbox, ad_detection, brand_detection,
            panel_text_detection, raw_detections_list).
        """

    @abstractmethod
    async def detect_objects_roi(
        self,
        img: Image.Image,
        roi: Any,
    ) -> List[Detection]:
        """Detect macro objects within the ROI.

        Identifies large, visually prominent objects such as poster panels,
        brand logos, backlit graphics, and promotional displays.

        Args:
            img: The input PIL image.
            roi: ROI data from compute_roi().

        Returns:
            List of Detection objects for macro-level items.
        """

    @abstractmethod
    async def detect_objects(
        self,
        img: Image.Image,
        roi: Any,
        macro_objects: Any,
    ) -> Tuple[List[IdentifiedProduct], List[ShelfRegion]]:
        """Detect and identify all products within the ROI.

        Args:
            img: The input PIL image.
            roi: ROI data from compute_roi().
            macro_objects: Macro detections from detect_objects_roi().

        Returns:
            Tuple of (identified_products, shelf_regions).
        """

    @abstractmethod
    def check_planogram_compliance(
        self,
        identified_products: List[IdentifiedProduct],
        planogram_description: Any,
    ) -> List[ComplianceResult]:
        """Compare detected products against the expected planogram.

        Args:
            identified_products: Products detected in the image.
            planogram_description: Expected planogram layout from config.

        Returns:
            List of ComplianceResult, one per shelf/zone.
        """

    def get_render_colors(self) -> Dict[str, Tuple[int, int, int]]:
        """Return color scheme for rendering compliance overlays.

        Override in concrete types to customize colors per planogram type.

        Returns:
            Dict mapping color role to RGB tuple.
        """
        return {
            "roi": (0, 255, 0),
            "detection": (255, 165, 0),
            "product": (0, 255, 255),
            "compliant": (0, 200, 0),
            "non_compliant": (255, 0, 0),
        }
