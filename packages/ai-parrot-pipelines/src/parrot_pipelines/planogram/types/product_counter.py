"""ProductCounter planogram type composable.

Handles planogram compliance for product-on-counter displays: a single
product placed on a counter/podium with a promotional background and an
information label.  No shelves, no grid — compliance is scored by element
presence alone.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image

from .abstract import AbstractPlanogramType
from parrot.models.google import GoogleModel
from parrot.models.detections import (
    Detection,
    DetectionBox,
    BoundingBox,
    Detections,
    IdentifiedProduct,
    ShelfRegion,
)
from parrot.models.compliance import (
    ComplianceResult,
    ComplianceStatus,
)

# Default scoring weights for counter elements.
_DEFAULT_WEIGHTS: Dict[str, float] = {
    "product": 1.0,
    "promotional_background": 0.5,
    "information_label": 0.3,
}

# Macro element labels the LLM is expected to return.
_EXPECTED_ELEMENTS = ["product", "promotional_background", "information_label"]


class ProductCounter(AbstractPlanogramType):
    """Planogram type for product-on-counter/podium displays.

    Validates compliance for a display consisting of:
    - A single main product on a counter or podium.
    - A promotional background (backdrop or side panel).
    - An information label (price tag, spec card, or similar).

    Compliance is scored by element presence with configurable weights.
    Missing elements are penalised; a missing information label reduces the
    score but does not zero it.

    Args:
        pipeline: Parent PlanogramCompliance instance providing shared
            utilities (LLM clients, image helpers, config).
        config: The PlanogramConfig for this compliance run.
    """

    def __init__(self, pipeline: Any, config: Any) -> None:
        super().__init__(pipeline, config)

    # ------------------------------------------------------------------
    # Abstract method implementations
    # ------------------------------------------------------------------

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
        """Compute the region of interest by finding the counter/podium area.

        Uses the LLM via ``roi_detection_prompt`` to locate the counter or
        podium display area.  Returns an endcap-compatible tuple so that the
        pipeline orchestrator can handle it uniformly.

        Args:
            img: The input PIL image.

        Returns:
            Tuple of (counter_detection, counter_detection, None, None,
            raw_detections_list).  Returns (None, None, None, None, []) if
            the counter area cannot be found.
        """
        planogram_description = self.config.get_planogram_description()
        brand = (getattr(planogram_description, "brand", "") or "").strip()
        brand_hint = f" {brand}" if brand else ""

        partial_prompt = self.config.roi_detection_prompt or ""
        image_small = self.pipeline._downscale_image(img, max_side=1024, quality=78)

        prompt = partial_prompt or (
            f"Identify the product counter or podium display area in this{brand_hint} "
            "retail image.  Return a bounding box labeled 'counter' that covers the "
            "entire counter surface including any product, backdrop, and label."
        )

        max_attempts = 2
        msg = None
        for attempt in range(max_attempts):
            try:
                async with self.pipeline.roi_client as client:
                    msg = await client.ask_to_image(
                        image=image_small,
                        prompt=prompt,
                        model=GoogleModel.GEMINI_3_FLASH_PREVIEW,
                        no_memory=True,
                        structured_output=Detections,
                        max_tokens=8192,
                    )
                break
            except Exception as exc:
                if attempt < max_attempts - 1:
                    self.logger.warning(
                        "ROI detection attempt %d failed: %s; retrying…",
                        attempt + 1,
                        exc,
                    )
                    await asyncio.sleep(10)
                else:
                    self.logger.error(
                        "ROI detection failed after %d attempts: %s", max_attempts, exc
                    )
                    return None, None, None, None, []

        data = msg.structured_output or msg.output or {}

        # Pixel-coordinate recovery (same pattern as GraphicPanelDisplay)
        if isinstance(data, str):
            try:
                raw = json.loads(data)
                iw_s, ih_s = image_small.size
                for d in raw.get("detections", []):
                    b = d.get("bbox", {})
                    if any(
                        v > 1.0
                        for v in (
                            b.get("x1", 0),
                            b.get("y1", 0),
                            b.get("x2", 0),
                            b.get("y2", 0),
                        )
                    ):
                        b["x1"] = min(1.0, max(0.0, b.get("x1", 0) / iw_s))
                        b["y1"] = min(1.0, max(0.0, b.get("y1", 0) / ih_s))
                        b["x2"] = min(1.0, max(0.0, b.get("x2", 0) / iw_s))
                        b["y2"] = min(1.0, max(0.0, b.get("y2", 0) / ih_s))
                data = Detections(**raw)
                self.logger.info(
                    "Recovered ROI detections after normalizing pixel coordinates."
                )
            except Exception as parse_err:
                self.logger.warning("ROI coordinate recovery failed: %s", parse_err)
                return None, None, None, None, []

        dets = data.detections or []
        if not dets:
            self.logger.warning("No counter ROI detected in image.")
            return None, None, None, None, []

        def _norm_label(det: Detection) -> str:
            return (det.label or "").strip().lower()

        counter_det = next(
            (
                d
                for d in dets
                if _norm_label(d)
                in ("counter", "podium", "counter_display", "display", "endcap")
            ),
            max(dets, key=lambda d: float(d.confidence)) if dets else None,
        )

        if not counter_det:
            self.logger.error("Could not locate the counter display area.")
            return None, None, None, None, []

        return counter_det, counter_det, None, None, dets

    async def detect_objects_roi(
        self,
        img: Image.Image,
        roi: Any,
    ) -> List[Detection]:
        """Detect macro elements within the counter ROI.

        Sends the cropped counter area to the LLM using the planogram's
        ``object_identification_prompt`` and asks it to locate the three
        expected elements: product, promotional_background, information_label.

        Args:
            img: The input PIL image.
            roi: Counter detection returned by ``compute_roi()``.

        Returns:
            List of Detection objects for each detected macro element.
        """
        if roi is None:
            self.logger.warning("No ROI found — cannot detect counter elements.")
            return []

        # Crop to ROI bbox
        iw, ih = img.size
        bbox = roi.bbox
        x1 = int(bbox.x1 * iw)
        y1 = int(bbox.y1 * ih)
        x2 = int(bbox.x2 * iw)
        y2 = int(bbox.y2 * ih)
        cropped = img.crop((x1, y1, x2, y2))

        prompt = self.config.object_identification_prompt or (
            "Within this counter/podium display, identify the following elements and "
            "return their bounding boxes:\n"
            "1) 'product' — the main product placed on the counter\n"
            "2) 'promotional_background' — any backdrop, banner, or side panel behind "
            "   or around the product\n"
            "3) 'information_label' — any price tag, specification card, or info label\n"
            "Return each detected element with its label and bounding box."
        )
        image_small = self.pipeline._downscale_image(cropped, max_side=1024, quality=78)

        max_attempts = 2
        msg = None
        for attempt in range(max_attempts):
            try:
                async with self.pipeline.roi_client as client:
                    msg = await client.ask_to_image(
                        image=image_small,
                        prompt=prompt,
                        model=GoogleModel.GEMINI_3_FLASH_PREVIEW,
                        no_memory=True,
                        structured_output=Detections,
                        max_tokens=8192,
                    )
                break
            except Exception as exc:
                if attempt < max_attempts - 1:
                    self.logger.warning(
                        "Element detection attempt %d failed: %s; retrying…",
                        attempt + 1,
                        exc,
                    )
                    await asyncio.sleep(10)
                else:
                    raise

        data = msg.structured_output or msg.output or {}

        # Pixel-coordinate recovery
        if isinstance(data, str):
            try:
                raw = json.loads(data)
                iw_s, ih_s = image_small.size
                for d in raw.get("detections", []):
                    b = d.get("bbox", {})
                    if any(
                        v > 1.0
                        for v in (
                            b.get("x1", 0),
                            b.get("y1", 0),
                            b.get("x2", 0),
                            b.get("y2", 0),
                        )
                    ):
                        b["x1"] = min(1.0, max(0.0, b.get("x1", 0) / iw_s))
                        b["y1"] = min(1.0, max(0.0, b.get("y1", 0) / ih_s))
                        b["x2"] = min(1.0, max(0.0, b.get("x2", 0) / iw_s))
                        b["y2"] = min(1.0, max(0.0, b.get("y2", 0) / ih_s))
                data = Detections(**raw)
                self.logger.info(
                    "Recovered element detections after normalizing pixel coordinates."
                )
            except Exception as parse_err:
                self.logger.warning(
                    "Element coordinate recovery failed: %s", parse_err
                )
                return []

        return data.detections or []

    async def detect_objects(
        self,
        img: Image.Image,
        roi: Any,
        macro_objects: Any,
    ) -> Tuple[List[IdentifiedProduct], List[ShelfRegion]]:
        """Map detected macro elements to IdentifiedProduct instances.

        For ProductCounter, the detected macro elements (product,
        promotional_background, information_label) are mapped directly to
        IdentifiedProduct objects.  No shelf regions are produced because
        counters have no shelving structure.

        Args:
            img: The input PIL image.
            roi: Counter detection from ``compute_roi()``.
            macro_objects: Element detections from ``detect_objects_roi()``.

        Returns:
            Tuple of (identified_products, []).  The second element is always
            an empty list — counter displays have no shelf regions.
        """
        if macro_objects is None and roi is not None:
            macro_objects = await self.detect_objects_roi(img, roi)

        element_detections: List[Detection] = macro_objects or []
        identified: List[IdentifiedProduct] = []

        iw, ih = img.size
        roi_x1_px, roi_y1_px = 0, 0
        roi_w_px, roi_h_px = float(iw), float(ih)
        if roi is not None and hasattr(roi, "bbox"):
            roi_x1_px = int(roi.bbox.x1 * iw)
            roi_y1_px = int(roi.bbox.y1 * ih)
            roi_w_px = (roi.bbox.x2 - roi.bbox.x1) * iw
            roi_h_px = (roi.bbox.y2 - roi.bbox.y1) * ih

        planogram_description = self.config.get_planogram_description()
        brand = getattr(planogram_description, "brand", None)

        for det in element_detections:
            label = (det.label or "unknown").strip().lower()

            # Convert ROI-relative normalised coords to absolute pixel coords
            abs_x1 = max(0, int(roi_x1_px + det.bbox.x1 * roi_w_px))
            abs_y1 = max(0, int(roi_y1_px + det.bbox.y1 * roi_h_px))
            abs_x2 = min(iw, int(roi_x1_px + det.bbox.x2 * roi_w_px))
            abs_y2 = min(ih, int(roi_y1_px + det.bbox.y2 * roi_h_px))

            det_box = DetectionBox(
                x1=abs_x1,
                y1=abs_y1,
                x2=abs_x2,
                y2=abs_y2,
                confidence=float(det.confidence),
            )

            identified.append(
                IdentifiedProduct(
                    product_type=label,
                    product_model=label,
                    confidence=max(float(det.confidence), 0.5),
                    brand=brand,
                    visual_features=[],
                    detection_box=det_box,
                )
            )

        self.logger.info(
            "ProductCounter: detected %d elements on counter.", len(identified)
        )
        # Always return empty shelf regions — no shelving on a counter
        return identified, []

    def check_planogram_compliance(
        self,
        identified_products: List[IdentifiedProduct],
        planogram_description: Any,
    ) -> List[ComplianceResult]:
        """Score compliance based on the presence of expected counter elements.

        Each expected element (product, promotional_background,
        information_label) carries a configurable weight.  The compliance
        score is the ratio of detected-element weights to the total expected
        weight.

        A missing information_label penalises the score but never zeros it
        (its weight is lower than the product and background combined).

        Args:
            identified_products: Elements detected on the counter.
            planogram_description: Expected planogram layout from config.

        Returns:
            A single-item list with a ComplianceResult covering the full
            counter display.
        """
        # Resolve scoring weights from config or fall back to defaults
        pcfg = getattr(self.config, "planogram_config", {}) or {}
        scoring = pcfg.get("scoring_weights", {})
        weights: Dict[str, float] = {
            elem: float(scoring.get(elem, _DEFAULT_WEIGHTS.get(elem, 0.0)))
            for elem in _EXPECTED_ELEMENTS
        }

        # Collect detected element names (normalised, from product_type field)
        detected_labels = {
            (p.product_type or "").strip().lower() for p in identified_products
        }

        total_weight = sum(weights.values())
        if total_weight == 0:
            total_weight = 1.0  # safety — avoid division by zero

        achieved_weight = 0.0
        missing: List[str] = []
        found: List[str] = []
        for elem, weight in weights.items():
            if elem in detected_labels:
                achieved_weight += weight
                found.append(elem)
            else:
                missing.append(elem)
                self.logger.info(
                    "ProductCounter: missing element '%s' (weight=%.2f).", elem, weight
                )

        score = achieved_weight / total_weight
        status: ComplianceStatus
        if score >= 0.8:
            status = ComplianceStatus.COMPLIANT
        elif score == 0.0:
            status = ComplianceStatus.MISSING
        else:
            status = ComplianceStatus.NON_COMPLIANT

        self.logger.info(
            "ProductCounter compliance: score=%.3f status=%s missing=%s",
            score,
            status,
            missing,
        )

        return [
            ComplianceResult(
                shelf_level="counter",
                expected_products=_EXPECTED_ELEMENTS,
                found_products=found,
                missing_products=missing,
                unexpected_products=[],
                compliance_status=status,
                compliance_score=round(score, 4),
            )
        ]
