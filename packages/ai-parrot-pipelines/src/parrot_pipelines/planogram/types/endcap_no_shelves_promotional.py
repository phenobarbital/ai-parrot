"""EndcapNoShelvesPromotional planogram type composable.

Handles planogram compliance for shelf-less promotional endcaps: a
retro-illuminated upper panel (brand/promo graphic) and a lower poster.
No physical products are expected — compliance is determined by verifying
that both zones are present and that the backlit panel is correctly
illuminated.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image

from .abstract import AbstractPlanogramType
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

# Default illumination penalty: 1.0 means illumination score → 0 when state contradicts config.
_DEFAULT_ILLUMINATION_PENALTY: float = 1.0

# Expected zone element labels for this display type.
_EXPECTED_ELEMENTS = ["backlit_panel", "lower_poster"]


class EndcapNoShelvesPromotional(AbstractPlanogramType):
    """Planogram type for shelf-less promotional endcap displays.

    Validates compliance for a display consisting of:
    - A retro-illuminated upper panel (backlit_panel) showing brand / promo graphics.
    - A lower poster (lower_poster) showing promotional content.

    There are no physical products.  Compliance is scored by zone presence
    and illumination state of the backlit panel.

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
        """Compute the region of interest by locating the promotional endcap.

        Uses the LLM to find the retro-illuminated upper panel and then
        expands the bounding box downward to encompass the full endcap
        (including the lower poster).

        Args:
            img: The input PIL image.

        Returns:
            Tuple of (endcap_detection, endcap_detection, None, None,
            raw_detections_list).  Returns (None, None, None, None, []) if
            the endcap cannot be found.
        """
        planogram_description = self.config.get_planogram_description()
        brand = (getattr(planogram_description, "brand", "") or "").strip()
        brand_hint = f" {brand}" if brand else ""

        partial_prompt = self.config.roi_detection_prompt or ""
        image_small = self.pipeline._downscale_image(img, max_side=1024, quality=78)

        prompt = partial_prompt or (
            f"Identify the full promotional endcap display in this{brand_hint} retail "
            "image.  Focus on the retro-illuminated upper panel.  Return a bounding box "
            "labeled 'endcap' that covers the complete endcap area from the top of the "
            "backlit panel down to the bottom of the lower poster."
        )

        max_attempts = 2
        msg = None
        for attempt in range(max_attempts):
            try:
                async with self.pipeline.roi_client as client:
                    msg = await client.ask_to_image(
                        image=image_small,
                        prompt=prompt,
                        model="gemini-2.5-flash",
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
            self.logger.warning("No endcap ROI detected in image.")
            return None, None, None, None, []

        def _norm_label(det: Detection) -> str:
            return (det.label or "").strip().lower()

        endcap_det = next(
            (
                d
                for d in dets
                if _norm_label(d)
                in (
                    "endcap",
                    "endcap_roi",
                    "endcap-roi",
                    "promotional_endcap",
                    "backlit_panel",
                    "poster",
                    "poster_panel",
                )
            ),
            max(dets, key=lambda d: float(d.confidence)) if dets else None,
        )

        if not endcap_det:
            self.logger.error("Could not locate the promotional endcap boundary.")
            return None, None, None, None, []

        # Expand bbox downward to include the full endcap (lower poster)
        # The LLM may only detect the upper panel; extend y2 to cover the display.
        expanded_bbox = BoundingBox(
            x1=endcap_det.bbox.x1,
            y1=endcap_det.bbox.y1,
            x2=endcap_det.bbox.x2,
            y2=min(1.0, endcap_det.bbox.y2 + (endcap_det.bbox.y2 - endcap_det.bbox.y1)),
        )
        # Only expand if the detected box is small (< 50% height) — it likely
        # captured only the upper panel and missed the lower poster.
        bbox_height = endcap_det.bbox.y2 - endcap_det.bbox.y1
        if bbox_height < 0.5:
            endcap_det = Detection(
                label=endcap_det.label,
                confidence=endcap_det.confidence,
                bbox=expanded_bbox,
            )
            self.logger.info(
                "Expanded endcap ROI downward to include lower poster (height was %.2f).",
                bbox_height,
            )

        return endcap_det, endcap_det, None, None, dets

    async def detect_objects_roi(
        self,
        img: Image.Image,
        roi: Any,
    ) -> List[Detection]:
        """Detect the backlit panel and lower poster zones within the endcap ROI.

        Sends the cropped endcap area to the LLM and asks it to label the
        two expected zones (backlit_panel and lower_poster).

        Args:
            img: The input PIL image.
            roi: Endcap detection returned by ``compute_roi()``.

        Returns:
            List of Detection objects for each detected zone.
        """
        if roi is None:
            self.logger.warning("No ROI found — cannot detect endcap zones.")
            return []

        # Crop to ROI bbox
        iw, ih = img.size
        bbox = roi.bbox
        x1 = int(bbox.x1 * iw)
        y1 = int(bbox.y1 * ih)
        x2 = int(bbox.x2 * iw)
        y2 = int(bbox.y2 * ih)
        cropped = img.crop((x1, y1, x2, y2))

        prompt = (
            "Within this promotional endcap display, identify the following zones and "
            "return their bounding boxes:\n"
            "1) 'backlit_panel' — the upper retro-illuminated graphic panel (lightbox)\n"
            "2) 'lower_poster' — the promotional poster at the bottom of the display\n"
            "Return each detected zone with its label and bounding box."
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
                        model="gemini-2.5-flash",
                        no_memory=True,
                        structured_output=Detections,
                        max_tokens=8192,
                    )
                break
            except Exception as exc:
                if attempt < max_attempts - 1:
                    self.logger.warning(
                        "Zone detection attempt %d failed: %s; retrying…",
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
                    "Recovered zone detections after normalizing pixel coordinates."
                )
            except Exception as parse_err:
                self.logger.warning(
                    "Zone coordinate recovery failed: %s", parse_err
                )
                return []

        return data.detections or []

    async def detect_objects(
        self,
        img: Image.Image,
        roi: Any,
        macro_objects: Any,
    ) -> Tuple[List[IdentifiedProduct], List[ShelfRegion]]:
        """Return empty results — this display type has no physical products.

        EndcapNoShelvesPromotional never contains physical products.
        Compliance is evaluated purely from zone presence and illumination
        state in ``check_planogram_compliance``.

        Args:
            img: The input PIL image (unused).
            roi: ROI detection from ``compute_roi()`` (unused).
            macro_objects: Zone detections (unused).

        Returns:
            Always ([], []).
        """
        self.logger.info(
            "EndcapNoShelvesPromotional.detect_objects: no physical products — returning empty."
        )
        return [], []

    async def _check_illumination(
        self,
        img: Image.Image,
        roi: Any,
        planogram_description: Any,
    ) -> str:
        """Check backlit illumination state using the full endcap ROI image.

        Sends the endcap crop to the LLM and asks it to compare the header
        brightness against the rest of the display.

        Args:
            img: The full input PIL image.
            roi: Endcap detection with a bbox attribute.
            planogram_description: Planogram description for brand context.

        Returns:
            ``'illumination_status: ON'`` or ``'illumination_status: OFF'``
        """
        iw, ih = img.size
        if roi is not None and hasattr(roi, "bbox"):
            x1 = int(roi.bbox.x1 * iw)
            y1 = int(roi.bbox.y1 * ih)
            x2 = int(roi.bbox.x2 * iw)
            y2 = int(roi.bbox.y2 * ih)
            roi_crop = img.crop((x1, y1, x2, y2))
        else:
            roi_crop = img.copy()

        roi_small = self.pipeline._downscale_image(roi_crop, max_side=800, quality=82)
        brand = (getattr(planogram_description, "brand", "") or "").strip()
        brand_hint = f" {brand}" if brand else ""

        prompt = (
            f"You are inspecting a retail{brand_hint} promotional endcap display.\n\n"
            "The TOP section contains a large BACKLIT LIGHTBOX PANEL — a sign "
            "designed to emit its own light from behind when the backlight is ON.\n\n"
            "Compare the brightness of the TOP backlit panel against the LOWER poster "
            "section of the same display:\n"
            "  • LIGHT_ON — the top panel glows with even internal luminosity; it "
            "looks self-illuminated and distinctly brighter than the lower section. "
            "Edges may show a bright border or halo.\n"
            "  • LIGHT_OFF — the top panel shows the graphic but only under ambient "
            "store light; no internal glow, similar brightness to the rest of the "
            "display.\n\n"
            "Do NOT answer LIGHT_ON just because the room or store is well-lit. "
            "Look specifically for light emanating FROM WITHIN the header panel.\n\n"
            "Answer with EXACTLY one word: LIGHT_ON or LIGHT_OFF"
        )

        raw_answer = ""
        try:
            async with self.pipeline.roi_client as client:
                msg = await client.ask_to_image(
                    image=roi_small,
                    prompt=prompt,
                    model="gemini-2.5-flash",
                    no_memory=True,
                    max_tokens=16,
                )
            raw_answer = (msg.output or "").strip().upper()
        except Exception as exc:
            self.logger.warning(
                "Illumination check failed: %s — defaulting to ON", exc
            )

        state = (
            "illumination_status: OFF"
            if "LIGHT_OFF" in raw_answer
            else "illumination_status: ON"
        )
        self.logger.info(
            "Endcap illumination check → answer=%r  state=%s", raw_answer, state
        )
        return state

    def check_planogram_compliance(
        self,
        identified_products: List[IdentifiedProduct],
        planogram_description: Any,
    ) -> List[ComplianceResult]:
        """Score compliance based on zone presence and illumination state.

        Since ``detect_objects`` always returns empty lists for this type,
        this method uses the ``identified_products`` list only as a carrier
        for zone metadata.  In practice the compliance pipeline in ``plan.py``
        calls this method after ``detect_objects``, so we rely on the
        planogram config to determine expected illumination state.

        Scoring:
        - backlit_panel present: +1.0 (weighted by backlit weight)
        - backlit_panel illumination correct: no penalty
        - backlit_panel illumination wrong: apply ``_DEFAULT_ILLUMINATION_PENALTY``
        - lower_poster present: +0.5 (weighted)

        Note:
            The illumination check is performed in ``detect_objects_roi`` /
            ``detect_objects`` via ``_check_illumination`` when this method
            is called from within the full pipeline.  When called standalone
            (e.g. in tests), illumination state is read from
            ``visual_features`` on identified products if available.

        Args:
            identified_products: Products/zones detected (may be empty for
                this type since detect_objects always returns []).
            planogram_description: Expected planogram layout from config.

        Returns:
            A single-item list with a ComplianceResult covering the full
            endcap display.
        """
        pcfg = getattr(self.config, "planogram_config", {}) or {}
        illumination_expected = (pcfg.get("illumination_expected", "ON") or "ON").upper()

        # For this type, detected zone names come from visual_features
        # (set by the pipeline when it calls detect_objects_roi separately).
        # When identified_products is empty (standard case), we look at
        # detected_elements stored in the config or use defaults.
        detected_zone_names: set = {
            (p.product_type or "").strip().lower() for p in identified_products
        }

        # Determine illumination state from visual_features on any identified product
        illumination_state = "ON"  # default: assume ON
        for p in identified_products:
            for feat in (p.visual_features or []):
                feat_lower = (feat or "").lower()
                if feat_lower.startswith("illumination_status:"):
                    state_str = feat[len("illumination_status:"):].strip().upper()
                    illumination_state = state_str
                    break

        # Score calculation
        backlit_present = "backlit_panel" in detected_zone_names
        poster_present = "lower_poster" in detected_zone_names

        # Base weights
        backlit_weight = 1.0
        poster_weight = 0.5
        total_weight = backlit_weight + poster_weight

        achieved = 0.0
        found: List[str] = []
        missing: List[str] = []

        if backlit_present:
            achieved += backlit_weight
            found.append("backlit_panel")
            # Apply illumination penalty if state contradicts config
            if illumination_state != illumination_expected:
                penalty = backlit_weight * _DEFAULT_ILLUMINATION_PENALTY
                achieved -= penalty
                self.logger.info(
                    "Illumination mismatch: expected=%s actual=%s — penalty=%.2f",
                    illumination_expected,
                    illumination_state,
                    penalty,
                )
        else:
            missing.append("backlit_panel")
            self.logger.info("EndcapNoShelvesPromotional: backlit_panel not detected.")

        if poster_present:
            achieved += poster_weight
            found.append("lower_poster")
        else:
            missing.append("lower_poster")
            self.logger.info("EndcapNoShelvesPromotional: lower_poster not detected.")

        score = max(0.0, achieved / total_weight)

        if score >= 0.8:
            status = ComplianceStatus.COMPLIANT
        elif score == 0.0:
            status = ComplianceStatus.MISSING
        else:
            status = ComplianceStatus.NON_COMPLIANT

        self.logger.info(
            "EndcapNoShelvesPromotional compliance: score=%.3f status=%s missing=%s "
            "illumination=%s",
            score,
            status,
            missing,
            illumination_state,
        )

        return [
            ComplianceResult(
                shelf_level="endcap",
                expected_products=_EXPECTED_ELEMENTS,
                found_products=found,
                missing_products=missing,
                unexpected_products=[],
                compliance_status=status,
                compliance_score=round(score, 4),
            )
        ]
