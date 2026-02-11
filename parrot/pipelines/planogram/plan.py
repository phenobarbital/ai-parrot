import asyncio
import contextlib
import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple, Union
from pathlib import Path
from collections import defaultdict
from PIL import Image, ImageDraw, ImageFont
from ..abstract import AbstractPipeline
from ..models import PlanogramConfig
from ...models.detections import (
    DetectionBox,
    ShelfRegion,
    IdentifiedProduct,
    Detection,
    BoundingBox,
    Detections
)
from ...models.compliance import (
    ComplianceResult,
    BrandComplianceResult,
    TextComplianceResult,
    ComplianceStatus,
    TextMatcher
)

class PlanogramCompliance(AbstractPipeline):
    """
    Pure-LLM Planogram Compliance Pipeline.

    Step 1: Endcap/Poster Detection (LLM-based _find_poster)
    Step 2: Object Detection & Identification (Gemini 3 Flash)
    Step 3: Planogram Compliance Verification
    """

    def __init__(
        self,
        planogram_config: PlanogramConfig,
        llm: Any = None,
        llm_provider: str = "google",
        llm_model: Optional[str] = None,
        **kwargs: Any
    ):
        super().__init__(
            llm=llm,
            llm_provider=llm_provider,
            llm_model=llm_model,
            **kwargs
        )
        self.planogram_config = planogram_config

        # Endcap geometry defaults
        geometry = planogram_config.endcap_geometry
        self.left_margin_ratio = geometry.left_margin_ratio
        self.right_margin_ratio = geometry.right_margin_ratio

        self.reference_images = planogram_config.reference_images or {}

    async def run(
        self,
        image: Union[str, Path, Image.Image],
        output_dir: Optional[Union[str, Path]] = None,
        image_id: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        # Build filename suffix so outputs are unique per image (e.g. "_1239218").
        _sfx = f"_{image_id}" if image_id else ""
        self.logger.info(
            "Starting Pure-LLM Planogram Compliance Pipeline"
        )

        # Step 1: Find Poster/Endcap
        img = self.open_image(image)
        planogram_description = self.planogram_config.get_planogram_description()

        detections_step1 = {}
        endcap = None
        ad = None
        brand = None
        panel_text = None
        raw_dets = []

        try:
            # reuse _find_poster logic
            endcap, ad, brand, panel_text, raw_dets = await self._find_poster(
                img,
                planogram_description,
                partial_prompt=self.planogram_config.roi_detection_prompt
            )
            detections_step1 = {
                "endcap": endcap,
                "dataset": raw_dets
            }
        except Exception as e:
            self.logger.error(
                f"Step 1 Failed: {e}"
            )

        if output_dir:
            # Debug Step 1: Draw Poster and Endcap on original image
            try:
                debug_img = img.copy()
                debug_draw = ImageDraw.Draw(debug_img)
                w, h = debug_img.size

                # Draw detections if avail
                if detections_step1.get("dataset"):
                    for d in detections_step1["dataset"]:
                        # d is likely Detection object or dict? _find_poster returns 'raw_dets'
                        # which is list of Detection objects
                        if hasattr(d, 'bbox'):
                            b = d.bbox
                            x1, y1, x2, y2 = b.x1 * w, b.y1 * h, b.x2 * w, b.y2 * h
                            label = getattr(d, 'label', None) or 'unknown'
                            color = "blue" if "poster" in label else "green"
                            debug_draw.rectangle([x1, y1, x2, y2], outline=color, width=3)
                            debug_draw.text((x1, y1), label, fill=color)

                # Draw calculated Endcap ROI
                if endcap:
                    b = endcap.bbox
                    x1, y1, x2, y2 = b.x1 * w, b.y1 * h, b.x2 * w, b.y2 * h
                    debug_draw.rectangle([x1, y1, x2, y2], outline="red", width=5)
                    debug_draw.text((x1, y1), "ENDCAP ROI", fill="red")

                debug_path = Path(output_dir) / f"debug_step1_roi{_sfx}.png"
                debug_img.save(debug_path)
                self.logger.info(
                    f"Saved Step 1 Debug Image to {debug_path}"
                )
            except Exception as e:
                self.logger.warning(
                    f"Failed to save Step 1 debug image: {e}"
                )

        # Step 2: Object Detection & Identification
        # We process the ROI if found, else the whole image?
        # Better to process the whole image but focus on ROI?
        # Or crop?
        # User sample uses `extract_segmentation_masks` on the image.
        # If we have endcap, we should probably crop to it to help the model?
        # Or pass the ROI as a hint?
        # The user said "stay with _find_poster method to find area... this is the Endcap Region of Interest".
        # So likely we should crop or draw a box?
        # Typically cropping is better for resolution.
        target_image = img
        offset_x, offset_y = 0, 0
        if endcap:
            w, h = img.size
            x1, y1, x2, y2 = endcap.bbox.get_pixel_coordinates(width=w, height=h)
            target_image = img.crop((x1, y1, x2, y2))
            offset_x, offset_y = x1, y1
            self.logger.info(f"Cropped to Endcap ROI: {x1},{y1},{x2},{y2}")
            if output_dir:
                try:
                    roi_path = Path(output_dir) / f"debug_roi_crop{_sfx}.png"
                    target_image.save(roi_path)
                    self.logger.info(f"Saved ROI crop to {roi_path}")
                except Exception as e:
                    self.logger.warning(f"Failed to save ROI crop: {e}")

        # Construct prompt/call
        # We need to ask for products, shelf regions, etc?
        # User sample returns "segmentation masks".
        # We need to map these to "IdentifiedProduct" and "ShelfRegion".
        # Prompt needs to be specific.
        # Extract hints from planogram description
        hints = []
        if planogram_description:
            for shelf in getattr(planogram_description, "shelves", []):
                for p in getattr(shelf, "products", []):
                    if name := getattr(p, "name", ""):
                        hints.append(name)

        hints_str = ", ".join(set(hints))
        prompt = f"""
Detect all retail products, empty slots, and shelf regions in this image.
Use the provided reference images to identify specific products.

IMPORTANT:
- If you see a cardboard box containing a product image/name, label it as "[Product Name] box".
- If you see the bare product itself (e.g. a loose printer), label it as "[Product Name]".
- Prefer the following product names if they match: {hints_str}
- If an item is NOT in the list, provide a descriptive name (e.g. "Ink Bottle", "Printer") rather than just "unknown".
- Do not output "unknown" unless strictly necessary.

Output a JSON list where each entry contains:
- "label": The identified product name/model or 'shelf' or 'unknown'.
- "box_2d": [ymin, xmin, ymax, xmax] normalized 0-1000.
- "confidence": 0-1.
- "type": "product" (for loose items), "product_box" (for boxes), "shelf", "gap".
        """

        # Pass reference images
        refs = list(self.reference_images.values()) if self.reference_images else []

        # Use planogram-specific object identification prompt if provided,
        # otherwise fall back to the generic detection prompt.
        _output_format = (
            "\n\nOutput a JSON array where each entry contains:\n"
            '- "label": The item label.\n'
            '- "box_2d": [ymin, xmin, ymax, xmax] normalized 0-1000.\n'
            '- "confidence": 0.0-1.0.\n'
            '- "type": "product", "promotional_graphic", "fact_tag", "shelf", or "gap".\n'
        )
        _base_prompt = getattr(self.planogram_config, "object_identification_prompt", None) or prompt
        obj_prompt = _base_prompt + _output_format

        detected_items = await self.llm.detect_objects(
            image=target_image,
            prompt=obj_prompt,
            reference_images=refs,
            output_dir=output_dir or None
        )

        # Convert to internal models (IdentifiedProduct, ShelfRegion)
        # We need to map coordinates back to full image if cropped

        shelf_regions = []
        identified_products = []

        w, h = target_image.size  # Size of the image passed to detector

        self.logger.debug(f"Detected {len(detected_items)} items from LLM.")

        for item in detected_items:
            # item["box_2d"] is [x1, y1, x2, y2] absolute pixels in target_image
            # (as per my implementation of detect_objects)
            # detect_objects implementation returns [x0, y0, x1, y1]
            # (StartLine 4930 in snippet: x0, y0, x1, y1)

            box = item.get("box_2d")  # [x1, y1, x2, y2]
            if not box:
                continue

            x1, y1, x2, y2 = box
            # Map to original image
            abs_x1 = x1 + offset_x
            abs_y1 = y1 + offset_y
            abs_x2 = x2 + offset_x
            abs_y2 = y2 + offset_y

            label = item.get("label", "unknown")
            conf = item.get("confidence", 0.0)
            # Mapping "type" from label for now.
            if "shelf" in label.lower():
                # Shelf Region
                shelf_regions.append(
                    ShelfRegion(
                        shelf_id=f"shelf_{len(shelf_regions)}",
                        level=label,  # simplistic
                        bbox=DetectionBox(
                            x1=abs_x1, y1=abs_y1, x2=abs_x2, y2=abs_y2, confidence=conf
                        )
                    )
                )
            else:
                # Product
                ptype = item.get("type", "product")
                # Heuristic: if label contains 'box', force type 'product_box'
                if "box" in label.lower() or "carton" in label.lower():
                    ptype = "product_box"
                identified_products.append(
                    IdentifiedProduct(
                        detection_box=DetectionBox(
                            x1=abs_x1, y1=abs_y1, x2=abs_x2, y2=abs_y2, confidence=conf
                        ),
                        product_model=label,
                        confidence=conf,
                        product_type=ptype
                    )
                )
        
        # DEBUG: Visualize Step 2 raw detections
        try:
            debug_img_2 = target_image.copy()
            debug_draw_2 = ImageDraw.Draw(debug_img_2)
            for item in detected_items:
                box = item.get("box_2d")
                if box:
                    x1, y1, x2, y2 = box
                    label = item.get("label", "unknown")
                    conf = item.get("confidence", 0.0)
                    # Draw green for products, blue for shelves
                    color = "blue" if "shelf" in label.lower() else "green"
                    if "Bose Logo Ad" in label:
                        color = "magenta" # Highlight our missing item
                    debug_draw_2.rectangle([x1, y1, x2, y2], outline=color, width=4)
                    debug_draw_2.text((x1, y1), f"{label} ({conf:.2f})", fill=color)
            
            debug_path_2 = Path(output_dir) / f"debug_step2_detections{_sfx}.png"
            debug_img_2.save(debug_path_2)
            self.logger.info(f"Saved Step 2 Debug Image to {debug_path_2}")
        except Exception as e:
            self.logger.warning(f"Failed to save Step 2 debug image: {e}")


        # Build a lookup: product_name -> visual_features from config (covers all shelves/types)
        _cfg_visuals_by_name: dict = {}
        _cfg_visuals_fallback: set = set()
        try:
            if planogram_description.shelves:
                for s in planogram_description.shelves:
                    for p_cfg in s.products:
                        if p_cfg.visual_features:
                            _cfg_visuals_by_name[p_cfg.name] = list(p_cfg.visual_features)
                            # Fallback set: only promotional/header features (old behaviour)
                            if p_cfg.product_type == "promotional_graphic" or "header" in s.level.lower():
                                _cfg_visuals_fallback.update(p_cfg.visual_features)
        except Exception as e:
            self.logger.warning(f"Failed to extract visual_features: {e}")

        # OCR Fallback & Visual Feature Verification
        # If Step 1 didn't find the text, we ask the model to look at the detected promotional item specifically
        for p in identified_products:
            # Check if this is a promotional item that needs text verification
            model_lower = (p.product_model or "").lower()
            if "logo ad" in model_lower or "backlit" in model_lower or p.product_type == "promotional_graphic":
                # If we don't have text yet (Step 1 panel_text is handled later, but maybe we missed it)
                # Let's actively read text from this specific crop
                try:
                    p_box = p.detection_box
                    # Map back to crop coordinates if needed?
                    # p.detection_box is in original image coordinates (abs_x1...)
                    # We need to crop from 'img' (original image) using these coords
                    crop_box = (int(p_box.x1), int(p_box.y1), int(p_box.x2), int(p_box.y2))

                    # Validate crop box
                    if crop_box[0] < crop_box[2] and crop_box[1] < crop_box[3]:
                        p_img = img.crop(crop_box)
                        self.logger.info(f"Running OCR & Visual verification on promotional item: {p.product_model}")

                        # Use per-item expected features when available; fall back to
                        # the global promotional set for unknown item names.
                        item_visuals = _cfg_visuals_by_name.get(p.product_model) or list(_cfg_visuals_fallback)

                        visuals_prompt = ""
                        if item_visuals:
                            v_list = "\n".join([f"- {v}" for v in item_visuals])
                            visuals_prompt = f"\nAlso check if these visual elements are present:\n{v_list}\nFor each, output 'CONFIRMED: <feature sequence>'"

                        prompt = f"Read all visible text in this image.{visuals_prompt}\nReturn text content. If visual features confirmed, list them."
                        # Use the ROI client for text reading
                        async with self.roi_client as client:
                            msg = await client.ask_to_image(
                                image=p_img,
                                prompt=prompt,
                                model="gemini-2.5-flash",
                                no_memory=True,
                                max_tokens=1024
                            )
                            found_content = msg.output if msg else ""
                            if found_content:
                                self.logger.info(f"Enrichment result: {found_content}")

                                # Extract Text
                                # Simple heuristic: Text is usually the main output. Visual confirmations strictly formatted?
                                # Let's assume content includes everything. We add it all to visual_features as raw strings
                                # But we also want cleaner text for 'ocr_text'.

                                # Parse 'CONFIRMED: ...'
                                confirmed_features = []
                                clean_text_parts = []
                                for line in found_content.split('\n'):
                                    if "CONFIRMED:" in line:
                                        feat = line.split("CONFIRMED:", 1)[1].strip()
                                        confirmed_features.append(feat)
                                    else:
                                        clean_text_parts.append(line)

                                clean_text = "\n".join(clean_text_parts).strip()

                                if clean_text:
                                    self.logger.info(f"OCR Fallback found text: {clean_text}")
                                    p.ocr_text = clean_text
                                    p.visual_features = (p.visual_features or []) + [f"ocr:{clean_text}", clean_text]

                                # Add confirmed visual features (exact strings matching expected if possible to trigger match)
                                # The verification logic compares strings.
                                # If VLM returns 'CONFIRMED: large backlit background panel', we add that.
                                if confirmed_features:
                                    self.logger.info(f"Confirmed visual features: {confirmed_features}")
                                    p.visual_features = (p.visual_features or []) + confirmed_features

                                # Force type to promotional_graphic so check_planogram_compliance sees it as a promo
                                p.product_type = "promotional_graphic"

                                # Check for brand match in OCR text, product model name, or confirmed visual features
                                brand_lower = (planogram_description.brand or "").lower()
                                brand_in_ocr = brand_lower and brand_lower in clean_text.lower()
                                brand_in_model = brand_lower and brand_lower in (p.product_model or "").lower()
                                brand_in_features = brand_lower and any(
                                    brand_lower in (f or "").lower()
                                    for f in (confirmed_features or [])
                                )
                                if planogram_description.brand and (brand_in_ocr or brand_in_model or brand_in_features):
                                    p.brand = planogram_description.brand
                                    self.logger.info(f"Verified brand '{p.brand}' via OCR on {p.product_model}")
                except Exception as e:
                    self.logger.warning(f"Failed OCR fallback for {p.product_model}: {e}")

        # Generate virtual shelves from Step 1 Endcap ROI as per user request
        if endcap and endcap.bbox:
            self.logger.info(
                "Generating virtual shelves from Endcap ROI..."
            )
            virtual_shelves = self._generate_virtual_shelves(
                endcap.bbox, img.size, planogram_description
            )
            # Use virtual shelves instead of model detections
            shelf_regions = virtual_shelves

        # Assign products to shelves
        self._assign_products_to_shelves(identified_products, shelf_regions)
        # If Step 1 found text, add it as a 'promotional_graphic' product
        if panel_text and getattr(panel_text, 'content', None):
            self.logger.info(f"Injecting poster text: {panel_text.content}")
            # Ensure text is treated as OCR content
            ocr_content = panel_text.content.strip()
            # Create a separate product for the text, or attach to the poster product if we had one?
            # Creating a new one ensures it's in the 'promos' list in check_compliance
            text_product = IdentifiedProduct(
                detection_box=DetectionBox(
                    x1=int(panel_text.bbox.x1 * img.width),
                    y1=int(panel_text.bbox.y1 * img.height),
                    x2=int(panel_text.bbox.x2 * img.width),
                    y2=int(panel_text.bbox.y2 * img.height),
                    confidence=float(getattr(panel_text, 'confidence', 1.0)),
                    ocr_text=ocr_content
                ),
                product_type="promotional_graphic",
                product_model="poster_text",
                confidence=float(getattr(panel_text, 'confidence', 1.0)),
                visual_features=[f"ocr:{ocr_content}"],
                shelf_location="header"
            )
            identified_products.append(text_product)

        # If Step 1 found brand logo, add it to satisfy brand check
        if brand:
            brand_conf = float(getattr(brand, 'confidence', 1.0))
            # Map coords
            bx1 = int(brand.bbox.x1 * img.width)
            by1 = int(brand.bbox.y1 * img.height)
            bx2 = int(brand.bbox.x2 * img.width)
            by2 = int(brand.bbox.y2 * img.height)
            brand_product = IdentifiedProduct(
                detection_box=DetectionBox(x1=bx1, y1=by1, x2=bx2, y2=by2, confidence=brand_conf),
                product_type="brand_logo",
                product_model=brand.label or "brand_logo",
                confidence=brand_conf,
                brand=planogram_description.brand,  # Use the expected brand name
                shelf_location="header"
            )
            identified_products.append(brand_product)
            self.logger.info(f"Injecting brand logo: {brand_product.brand}")
        # Step 3: Planogram Compliance Verification
        compliance_results = self.check_planogram_compliance(
            identified_products, planogram_description
        )
        overall_score = 0.0
        overall_compliant = True
        if compliance_results:
            overall_score = sum(r.compliance_score for r in compliance_results) / len(compliance_results)
            overall_compliant = all(r.compliance_status == ComplianceStatus.COMPLIANT for r in compliance_results)

        # ... (Render) ...
        rendered_image = self.render_evaluated_image(
            img,
            shelf_regions=shelf_regions,
            identified_products=identified_products,
            save_to=str(Path(output_dir) / f"compliance_render{_sfx}.png") if output_dir else None
        )

        return {
            "step3_compliance_results": compliance_results,
            "compliance_results": compliance_results,
            "overall_compliance_score": overall_score,
            "overall_compliant": overall_compliant,
            "identified_products": identified_products,
            "shelf_regions": shelf_regions,
            "rendered_image": rendered_image,
            "overlay_path": str(Path(output_dir) / f"compliance_render{_sfx}.png") if output_dir else None
        }

    # =========================================================================
    # Helpers (Copied/Adapted)
    # =========================================================================

    async def _find_poster(
        self,
        image: Image.Image,
        planogram: Any,  # PlanogramDescription
        partial_prompt: str
    ) -> Any:
        # Ask VISION Model to find the main promotional graphic
        brand = (getattr(planogram, "brand", "") or "").strip()
        tags = [t.strip() for t in getattr(planogram, "tags", []) or []]
        endcap = getattr(planogram, "advertisement_endcap", None)
        geometry = self.planogram_config.endcap_geometry
        if endcap and getattr(endcap, "text_requirements", None):
            for tr in endcap.text_requirements:
                if getattr(tr, "required_text", None):
                    tags.append(tr.required_text)
        tag_hint = ", ".join(sorted({f"'{t}'" for t in tags if t}))

        # downscale for LLM
        image_small = self._downscale_image(image, max_side=1024, quality=78)
        prompt = partial_prompt.format(
            brand=brand,
            tag_hint=tag_hint,
            image_size=image_small.size
        )
        max_attempts = 2
        msg = None
        for attempt in range(max_attempts):
            try:
                async with self.roi_client as client:
                    msg = await client.ask_to_image(
                        image=image_small,
                        prompt=prompt,
                        model="gemini-2.5-flash",
                        no_memory=True,
                        structured_output=Detections,
                        max_tokens=8192
                    )
                break
            except Exception as e:
                if attempt < max_attempts - 1:
                    await asyncio.sleep(10)
                else:
                    raise e

        data = msg.structured_output or msg.output or {}
        # If Pydantic validation failed (e.g. LLM returned pixel coords instead
        # of normalized), 'data' will be a raw JSON string.  Try to recover by
        # normalizing the bbox values against the downscaled image dimensions.
        if isinstance(data, str):
            import json as _json
            try:
                raw = _json.loads(data)
                iw, ih = image_small.size
                for d in raw.get("detections", []):
                    b = d.get("bbox", {})
                    # If any coordinate exceeds 1.0 it's in pixel space → normalize.
                    if any(v > 1.0 for v in (b.get("x1", 0), b.get("y1", 0),
                                             b.get("x2", 0), b.get("y2", 0))):
                        b["x1"] = min(1.0, max(0.0, b.get("x1", 0) / iw))
                        b["y1"] = min(1.0, max(0.0, b.get("y1", 0) / ih))
                        b["x2"] = min(1.0, max(0.0, b.get("x2", 0) / iw))
                        b["y2"] = min(1.0, max(0.0, b.get("y2", 0) / ih))
                data = Detections(**raw)
                self.logger.info("Recovered Step 1 detections after normalizing pixel coordinates.")
            except Exception as parse_err:
                self.logger.warning(f"Step 1 coordinate recovery failed: {parse_err}")
                return None, None, None, None, []

        dets = data.detections or []
        if not dets:
            return None, None, None, None, []

        def _norm_label(det: Detection) -> str:
            return (det.label or "").strip().lower()

        def _first_by_labels(labels: List[str]) -> Optional[Detection]:
            wanted = {lbl.strip().lower() for lbl in labels}
            return next((d for d in dets if _norm_label(d) in wanted), None)

        panel_det = (
            _first_by_labels(["poster_panel", "poster"])
            or (max(dets, key=lambda x: float(x.confidence)) if dets else None)
        )

        text_det = _first_by_labels(["poster_text"])
        brand_det = _first_by_labels(["brand_logo", "brand logo"])

        if not panel_det:
            self.logger.error(
                "Critical failure: Could not detect the poster_panel."
            )
            return None, None, None, None, []

        promo_graphic_det = _first_by_labels(["promotional_graphic"])

        if promo_graphic_det and panel_det:
            if not (promo_graphic_det.bbox.x1 >= panel_det.bbox.x1 and promo_graphic_det.bbox.x2 <= panel_det.bbox.x2):
                panel_det.bbox.x1 = min(panel_det.bbox.x1, promo_graphic_det.bbox.x1)
                panel_det.bbox.x2 = max(panel_det.bbox.x2, promo_graphic_det.bbox.x2)

        config_width_percent = geometry.width_margin_percent
        config_height_percent = geometry.height_margin_percent
        config_top_margin_percent = geometry.top_margin_percent
        side_margin_percent = geometry.side_margin_percent

        # If planogram has is_background shelves (e.g. a wide promotional panel
        # that may sit *beside* the product display), force full image width so
        # the ROI crop always includes the background graphic.
        has_background_shelf = any(
            getattr(s, "is_background", False)
            for s in (getattr(planogram, "shelves", None) or [])
        )
        if has_background_shelf:
            side_margin_percent = max(side_margin_percent, 0.5)

        panel_det.bbox.x1 = max(0.0, panel_det.bbox.x1 - side_margin_percent)
        panel_det.bbox.x2 = min(1.0, panel_det.bbox.x2 + side_margin_percent)

        if panel_det and text_det:
            text_bottom_y2 = text_det.bbox.y2
            padding = 0.08
            new_panel_y2 = min(text_bottom_y2 + padding, 1.0)
            panel_det.bbox.y2 = new_panel_y2

        # Consolidate endcap logic
        endcap_det = _first_by_labels(["endcap", "endcap_roi", "endcap-roi", "endcap roi"])
        px1, py1, px2, py2 = panel_det.bbox.x1, panel_det.bbox.y1, panel_det.bbox.x2, panel_det.bbox.y2

        if endcap_det:
            # If endcap found, ensure it includes the poster (UNION)
            ex1 = min(endcap_det.bbox.x1, px1)
            ey1 = min(endcap_det.bbox.y1, py1)
            ex2 = max(endcap_det.bbox.x2, px2)
            ey2 = max(endcap_det.bbox.y2, py2)
        else:
            # If no endcap, start with poster
            ex1, ey1, ex2, ey2 = px1, py1, px2, py2
            # Heuristic: The Endcap usually includes a riser/shelf below the poster.
            # Extend downwards by ~35% of poster height to capture it.
            panel_h = py2 - py1
            ey2 = min(1.0, ey2 + (panel_h * 0.35))

        # Add horizontal buffer
        x_buffer = max(
            self.left_margin_ratio * (px2 - px1), self.right_margin_ratio * (px2 - px1)
        )
        ex1 = min(ex1, px1 - x_buffer)
        ex2 = max(ex2, px2 + x_buffer)

        # If the endcap is a header with shelves below, use the panel to set width
        # but extend ROI height to cover the full display.
        full_height_hint = False
        if endcap and getattr(endcap, "position", None) == "header" and getattr(endcap, "full_height_roi", True):
            shelves = getattr(planogram, "shelves", []) or []
            has_non_header = any(
                getattr(s, "level", None) and getattr(s, "level") != "header"
                for s in shelves
            )
            full_height_hint = has_non_header
        if full_height_hint:
            ey2 = 1.0
            ey1 = min(ey1, py1)

        # Clip to image bounds
        ex1 = max(0.0, ex1)
        ex2 = min(1.0, ex2)
        if ex2 <= ex1:
            ex2 = ex1 + 1e-6
        ey1 = max(0.0, ey1)
        ey2 = min(1.0, ey2)
        if ey2 <= ey1:
            ey2 = ey1 + 1e-6

        if endcap_det is None:
            endcap_det = Detection(
                label="endcap",
                confidence=0.9,
                content=None,
                bbox=BoundingBox(x1=ex1, y1=ey1, x2=ex2, y2=ey2)
            )
        else:
            endcap_det.bbox.x1 = ex1
            endcap_det.bbox.x2 = ex2
            endcap_det.bbox.y1 = ey1
            endcap_det.bbox.y2 = ey2

        return endcap_det, panel_det, brand_det, text_det, dets

    def check_planogram_compliance(
        self,
        identified_products: List[IdentifiedProduct],
        planogram_description: Any
    ) -> List[ComplianceResult]:
        """Check compliance of identified products against the planogram."""
        # All LLM aliases that map to a promotional_graphic concept
        _PROMO_TYPES = {
            "promotional_graphic", "graphic", "banner", "backlit_graphic", "backlit",
            "advertisement", "advertisement_graphic", "display_graphic",
            "promotional_display", "promotional_material", "promotional_materials"
        }

        # Configurable product subtypes — custom types declared in
        # planogram_config.product_subtypes that should match 'product'.
        _pcfg = getattr(planogram_description, 'planogram_config', None) or {}
        if isinstance(_pcfg, dict):
            _product_subtypes = set(_pcfg.get('product_subtypes', []))
        else:
            _product_subtypes = set(getattr(_pcfg, 'product_subtypes', []) or [])

        def _matches(ek, fk) -> bool:
            (e_ptype, e_base), (f_ptype, f_base) = ek, fk

            # Relaxed type matching
            type_match = (e_ptype == f_ptype)
            if not type_match:
                # specific overrides
                if {e_ptype, f_ptype} <= {"printer", "product"}:
                    type_match = True
                # product_box is a subtype of product
                elif {e_ptype, f_ptype} <= {"product", "product_box"}:
                    type_match = True
                # promotional_graphic in config may be detected as 'product' by LLM
                elif "promotional_graphic" in {e_ptype, f_ptype} and "product" in {e_ptype, f_ptype}:
                    type_match = True
                # Any promo-like type aliases are treated as equivalent
                elif e_ptype in _PROMO_TYPES and f_ptype in _PROMO_TYPES:
                    type_match = True
                # Custom semantic product types (e.g. soundbar, headphones, camera)
                # are never returned by the LLM; allow them to match 'product'.
                elif "product" in {e_ptype, f_ptype}:
                    other_type = f_ptype if e_ptype == "product" else e_ptype
                    # 1) Configurable: planogram_config.product_subtypes
                    if _product_subtypes and other_type in _product_subtypes:
                        type_match = True
                    else:
                        # 2) Hardcoded fallback for unlisted types
                        _non_product_types = {
                            "promotional_graphic", "graphic", "banner", "backlit_graphic",
                            "backlit", "advertisement", "advertisement_graphic",
                            "display_graphic", "promotional_display", "promotional_material",
                            "promotional_materials", "product_box", "printer",
                            "fact_tag", "price_tag", "slot", "brand_logo", "gap", "shelf",
                        }
                        if other_type not in _non_product_types:
                            type_match = True

            if not type_match:
                return False
            if not e_base or not f_base:
                return True
            if not e_base:
                return True
            if f_base == e_base or e_base in f_base or f_base in e_base:
                return True
            if e_ptype == "promotional_graphic":
                def fam(s):
                    return "canvas-tv" if "canvas-tv" in s else s
                return fam(e_base) == fam(f_base)
            return e_base in f_base or f_base in e_base

        results: List[ComplianceResult] = []
        planogram_brand = planogram_description.brand.lower()
        found_brand_product = next((
            p for p in identified_products if p.brand and p.brand.lower() == planogram_brand
        ), None)

        brand_compliance_result = BrandComplianceResult(
            expected_brand=planogram_description.brand,
            found_brand=found_brand_product.brand if found_brand_product else None,
            found=bool(found_brand_product),
            confidence=found_brand_product.confidence if found_brand_product else 0.0
        )
        brand_check_ok = brand_compliance_result.found
        by_shelf = defaultdict(list)

        for p in identified_products:
            by_shelf[p.shelf_location].append(p)

        for shelf_cfg in planogram_description.shelves:
            shelf_level = shelf_cfg.level
            products_on_shelf = by_shelf.get(shelf_level, [])
            expected = []

            for sp in shelf_cfg.products:
                if sp.product_type in ("fact_tag", "price_tag", "slot"):
                    continue
                e_ptype, e_base = self._canonical_expected_key(sp, brand=planogram_brand)
                expected.append((e_ptype, e_base))

            found_keys = []
            found_lookup = []
            promos = []
            for p in products_on_shelf:
                if p.product_type in ("fact_tag", "price_tag", "slot", "brand_logo", "gap", "shelf"):
                    continue
                f_ptype, f_base, f_conf = self._canonical_found_key(p, brand=planogram_brand)
                found_keys.append((f_ptype, f_base))
                if p.product_type in _PROMO_TYPES:
                    promos.append(p)
                label = p.product_model or p.product_type or "unknown"
                found_lookup.append((f_ptype, f_base, label))

            matched = [False] * len(expected)
            consumed = [False] * len(found_keys)
            visual_feature_scores = []

            for i, ek in enumerate(expected):
                for j, fk in enumerate(found_keys):
                    if matched[i] or consumed[j]:
                        continue
                    match_result = _matches(ek, fk)
                    if match_result:
                        matched[i] = True
                        consumed[j] = True
                        shelf_product = shelf_cfg.products[i]
                        identified_product = products_on_shelf[j]
                        if hasattr(shelf_product, 'visual_features') and shelf_product.visual_features:
                            detected_features = getattr(identified_product, 'visual_features', []) or []
                            # Only score visual features when enrichment was actually
                            # performed (detected_features non-empty).  If the product
                            # was found geometrically but no OCR/visual enrichment ran
                            # (e.g. 'product' type items), skip the penalty so the
                            # score reflects detection success, not enrichment absence.
                            if detected_features:
                                vf_score = self._calculate_visual_feature_match(
                                    shelf_product.visual_features, detected_features
                                )
                                visual_feature_scores.append(vf_score)
                        break

            expected_readable = [f"{e_ptype}:{e_base}" if e_base else f"{e_ptype}" for (e_ptype, e_base) in expected]
            found_readable = []
            for (used, (f_ptype, f_base), (_, _, original_label)) in zip(consumed, found_keys, found_lookup):
                tag = original_label
                if f_base:
                    tag = f"{original_label} [{f_ptype}:{f_base}]"
                found_readable.append(tag)

            missing = [expected_readable[i] for i, ok in enumerate(matched) if not ok]
            unexpected = []
            if not shelf_cfg.allow_extra_products:
                for used, (f_ptype, f_base), (_, _, original_label) in zip(consumed, found_keys, found_lookup):
                    if not used:
                        lbl = original_label
                        if f_base:
                            lbl = f"{original_label} [{f_ptype}:{f_base}]"
                        unexpected.append(lbl)

            basic_score = (
                sum(1 for ok in matched if ok) / (len(expected) or 1.0)
            )

            visual_feature_score = 1.0
            if visual_feature_scores:
                visual_feature_score = sum(visual_feature_scores) / len(visual_feature_scores)

            text_results, text_score, overall_text_ok = [], 1.0, True
            endcap = planogram_description.advertisement_endcap
            if endcap and endcap.enabled and endcap.position == shelf_level:
                if endcap.text_requirements:
                    all_features = []
                    ocr_blocks = []
                    for promo in promos:
                        if getattr(promo, "visual_features", None):
                            all_features.extend(promo.visual_features)
                            for feat in promo.visual_features:
                                if isinstance(feat, str) and feat.startswith("ocr:"):
                                    ocr_blocks.append(feat[4:].strip())
                            ocr_text = getattr(promo, 'ocr_text', None) or getattr(promo.detection_box, 'ocr_text', '')
                            if ocr_text:
                                ocr_blocks.append(ocr_text.strip())
                    if ocr_blocks:
                        ocr_norm = self._normalize_ocr_text(" ".join(ocr_blocks))
                        if ocr_norm:
                            all_features.append(ocr_norm)

                    if not promos and shelf_level == "header":
                        overall_text_ok = False
                        for text_req in endcap.text_requirements:
                            text_results.append(TextComplianceResult(
                                required_text=text_req.required_text,
                                found=False,
                                matched_features=[],
                                confidence=0.0,
                                match_type=text_req.match_type
                            ))
                    else:
                        for text_req in endcap.text_requirements:
                            result = TextMatcher.check_text_match(
                                required_text=text_req.required_text,
                                visual_features=all_features,
                                match_type=text_req.match_type,
                                case_sensitive=text_req.case_sensitive,
                                confidence_threshold=text_req.confidence_threshold
                            )
                            text_results.append(result)
                            if not result.found and text_req.mandatory:
                                overall_text_ok = False
                        if text_results:
                            text_score = sum(
                                r.confidence for r in text_results if r.found
                            ) / len(text_results)

            elif shelf_level != "header":
                overall_text_ok = True
                text_score = 1.0

            threshold = getattr(
                shelf_cfg,
                "compliance_threshold",
                planogram_description.global_compliance_threshold or 0.8
            )
            major_unexpected = [
                p for p in unexpected if "ink" not in p.lower() and "price tag" not in p.lower()
            ]

            status = ComplianceStatus.NON_COMPLIANT
            if shelf_level != "header":
                if basic_score >= threshold and not major_unexpected:
                    status = ComplianceStatus.COMPLIANT
                elif basic_score == 0.0 and len(expected) > 0:
                    status = ComplianceStatus.MISSING
            else:
                if not brand_check_ok:
                    status = ComplianceStatus.NON_COMPLIANT
                elif basic_score >= threshold and not major_unexpected and overall_text_ok:
                    status = ComplianceStatus.COMPLIANT
                elif basic_score == 0.0 and len(expected) > 0:
                    status = ComplianceStatus.MISSING
                else:
                    status = ComplianceStatus.NON_COMPLIANT

            visual_weight = getattr(
                planogram_description,
                'visual_features_weight',
                0.2
            )
            if shelf_level == "header" and endcap:
                adjusted_product_weight = endcap.product_weight * (1 - visual_weight)
                visual_feature_weight = endcap.product_weight * visual_weight
                combined_score = (
                    (basic_score * adjusted_product_weight) +
                    (text_score * endcap.text_weight) +
                    (brand_compliance_result.confidence * getattr(endcap, "brand_weight", 0.0)) +
                    (visual_feature_score * visual_feature_weight)
                )
            else:
                combined_score = (
                    basic_score * (1 - visual_weight) +
                    text_score * 0.1 +
                    visual_feature_score * visual_weight
                )

            combined_score = min(1.0, max(0.0, combined_score))
            text_score = min(1.0, max(0.0, text_score))

            results.append(
                ComplianceResult(
                    shelf_level=shelf_level,
                    expected_products=expected_readable,
                    found_products=found_readable,
                    missing_products=missing,
                    unexpected_products=unexpected,
                    compliance_status=status,
                    compliance_score=combined_score,
                    text_compliance_results=text_results,
                    text_compliance_score=text_score,
                    overall_text_compliant=overall_text_ok,
                    brand_compliance_result=brand_compliance_result
                )
            )
        return results

    def render_evaluated_image(
        self,
        image: Union[str, Path, Image.Image],
        *,
        shelf_regions: Optional[List[ShelfRegion]] = None,
        detections: Optional[List[DetectionBox]] = None,
        identified_products: Optional[List[IdentifiedProduct]] = None,
        mode: str = "identified",
        show_shelves: bool = True,
        save_to: Optional[Union[str, Path]] = None,
    ) -> Image.Image:
        """Enhanced render."""
        def _norm_box(x1, y1, x2, y2):
            x1, x2, y1, y2 = int(x1), int(x2), int(y1), int(y2)
            if x1 > x2:
                x1, x2 = x2, x1
            if y1 > y2:
                y1, y2 = y2, y1
            if x2 - x1 < 1:
                x2 = x1 + 1
            if y2 - y1 < 1:
                y2 = y1 + 1
            return x1, y1, x2, y2

        if isinstance(image, (str, Path)):
            base = Image.open(image).convert("RGB").copy()
        else:
            base = image.convert("RGB").copy()

        draw = ImageDraw.Draw(base)
        try:
            font = ImageFont.load_default()
        except Exception:
            font = None

        W, H = base.size

        def _clip(x1, y1, x2, y2):
            return max(0, x1), max(0, y1), min(W - 1, x2), min(H - 1, y2)

        def _txt(draw_obj, xy, text, fill, bg=None):
            try:
                if not font:
                    draw_obj.text(xy, text, fill=fill)
                    return
                bbox = draw_obj.textbbox(xy, text, font=font)
                if bg is not None:
                    draw_obj.rectangle(bbox, fill=bg)
                draw_obj.text(xy, text, fill=fill, font=font)
            except Exception:
                with contextlib.suppress(Exception):
                    draw_obj.text(xy, text, fill=fill)

        colors = {
            "tv_demonstration": (0, 255, 0), "promotional_graphic": (255, 0, 255),
            "promotional_base": (0, 0, 255), "fact_tag": (255, 255, 0),
            "product_box": (255, 128, 0), "printer": (255, 0, 0), "unknown": (200, 200, 200)
        }

        if show_shelves and shelf_regions:
            for sr in shelf_regions:
                try:
                    x1, y1, x2, y2 = _clip(sr.bbox.x1, sr.bbox.y1, sr.bbox.x2, sr.bbox.y2)
                    x1, y1, x2, y2 = _norm_box(x1, y1, x2, y2)
                    draw.rectangle([x1, y1, x2, y2], outline=(255, 255, 0), width=3)
                    _txt(
                        draw, (x1 + 3, max(0, y1 - 14)), f"SHELF {sr.level}", fill=(0, 0, 0), bg=(255, 255, 0)
                    )
                except Exception as e:
                    self.logger.warning(
                        f"Could not draw shelf {sr.level}: {e}"
                    )

        if identified_products:
            for i, p in enumerate(identified_products):
                try:
                    box = p.detection_box
                    if not box:
                        continue
                    x1, y1, x2, y2 = _clip(box.x1, box.y1, box.x2, box.y2)
                    x1, y1, x2, y2 = _norm_box(x1, y1, x2, y2)

                    ptype = (p.product_type or "unknown").lower()
                    color = colors.get(ptype, colors["unknown"])

                    draw.rectangle([x1, y1, x2, y2], outline=color, width=2)

                    label = f"{i + 1}. {p.product_model or ptype}"
                    if p.confidence:
                        label += f" ({p.confidence:.2f})"

                    _txt(
                        draw, (x1, max(0, y1 - 20)), label, fill=color, bg=(0, 0, 0)
                    )
                except Exception as e:
                    self.logger.warning(f"Failed to draw product: {e}")

        if save_to:
            try:
                base.save(save_to)
                self.logger.info(f"Saved rendered image to {save_to}")
            except Exception as e:
                self.logger.error(f"Failed save image to {save_to}: {e}")

        return base

    def _base_model_from_str(self, s: str, brand: str = None) -> str:
        """
        Extract normalized base model from any text, supporting multiple brands.
        """
        if not s:
            return ""

        t = s.lower().strip()
        t = t.replace("—", "-").replace("–", "-").replace("_", "-")

        # Brand-specific patterns
        if brand and brand.lower() == "epson":
            m = re.search(r"(et)[- ]?(\d{4})", t)
            if m:
                return f"{m.group(1)}-{m.group(2)}"

        elif brand and brand.lower() == "hisense":
            if re.search(r"canvas[\s-]*tv", t):
                return "canvas-tv"
            if re.search(r"canvas", t):
                return "canvas"
            patterns = [
                r"(\d*)(u\d+)([a-z]*)",
                r"(u\d+)",
            ]
            for pattern in patterns:
                m = re.search(pattern, t)
                if m:
                    if len(m.groups()) >= 2:
                        size = m.group(1) if m.group(1) else ""
                        series = m.group(2)
                        variant = m.group(3) if len(m.groups()) > 2 and m.group(3) else ""
                        return f"{size}{series}{variant}".lower()
                    else:
                        return m.group(1).lower()

        # Generic
        generic_patterns = [
            r"([a-z]+)[- ]?(\d{3,4})",
            r"([a-z]\d+)",
            r"(\d{4})",
        ]
        for pattern in generic_patterns:
            m = re.search(pattern, t)
            if m:
                if len(m.groups()) >= 2:
                    return f"{m.group(1)}-{m.group(2)}"
                else:
                    return m.group(1).lower()
        return ""

    def _canonical_expected_key(self, sp: Any, brand: str) -> Tuple[str, str]:
        ptype = (getattr(sp, "product_type", "") or "").strip().lower()
        type_mappings = {
            "tv_demonstration": "tv",
            "promotional_graphic": "promotional_graphic",
            "product_box": "product_box",
            "printer": "printer",
            "promotional_materials": "promotional_materials"
        }
        ptype = type_mappings.get(ptype, ptype)
        model_str = getattr(sp, "name", "") or getattr(sp, "product_model", "") or ""
        base = self._base_model_from_str(model_str, brand=brand)
        return ptype or "unknown", base or ""

    def _canonical_found_key(self, p: Any, brand: str) -> Tuple[str, str, float]:
        ptype = (getattr(p, "product_type", "") or "").strip().lower()
        type_mappings = {
            "tv_demonstration": "tv",
            "promotional_graphic": "promotional_graphic",
            "product_box": "product_box",
            "printer": "printer",
            "promotional_material": "promotional_material",
            "promotional_display": "promotional_display"
        }
        ptype = type_mappings.get(ptype, ptype)
        model_str = getattr(p, "product_model", "") or getattr(p, "product_type", "") or ""
        base = self._base_model_from_str(model_str, brand=brand)
        conf = float(getattr(p, "confidence", 0.0) or 0.0)

        # Only reclassify as product_box for generic types; never override promotional types
        _no_reclassify = {"promotional_graphic", "graphic", "banner", "backlit_graphic", "backlit",
                          "advertisement", "advertisement_graphic", "promotional_display",
                          "promotional_material", "promotional_materials"}
        if ptype not in _no_reclassify and self._looks_like_box(getattr(p, "visual_features", None)):
            if ptype != "product_box":
                ptype = "product_box"
            conf = min(1.0, conf + 0.05)
        return ptype or "unknown", base or "", conf

    def _looks_like_box(self, visual_features: Optional[List[str]]) -> bool:
        if not visual_features:
            return False
        # Use whole-word match for "box" to avoid false positives like "lightbox"
        whole_word_keywords = {"packaging", "package", "cardboard", "blue packaging", "printer image on box"}
        norm = " ".join(visual_features).lower()
        if any(k in norm for k in whole_word_keywords):
            return True
        # "box" only as whole word (not part of "lightbox", "mailbox", etc.)
        if re.search(r'\bbox\b', norm):
            return True
        return False

    def _normalize_ocr_text(self, s: str) -> str:
        if not s:
            return ""
        s = unicodedata.normalize("NFKC", s)
        s = "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch))
        s = re.sub(r"[—–‐-‒–—―…“”\"'·•••·•—–/\\|_=+^°™®©§]", " ", s)
        s = re.sub(r"[^A-Za-z0-9 ]+", " ", s)
        s = re.sub(r"\s+", " ", s).strip().lower()
        return s

    def _calculate_visual_feature_match(
        self,
        expected_features: List[str],
        detected_features: List[str]
    ) -> float:
        if not expected_features:
            return 1.0
        if not detected_features:
            return 0.0

        def extract_keywords(text):
            text = text.lower().strip()
            stop_words = {
                'a', 'an', 'the', 'is', 'are', 'on', 'of', 'in', 'at',
                'to', 'for', 'with', 'visible', 'displayed', 'showing'
            }
            words = [w for w in text.split() if w not in stop_words and len(w) > 1]
            return set(words)

        semantic_mappings = {
            'active': ['active', 'on', 'powered', 'illuminated', 'lit'],
            'display': ['display', 'screen', 'tv', 'television', 'monitor'],
            'illuminated': ['illuminated', 'backlit', 'lit', 'bright', 'glowing'],
            'logo': ['logo', 'text', 'branding', 'brand'],
            'dynamic': ['dynamic', 'colorful', 'graphics', 'content'],
            'official': ['official', 'partner'],
            'white': ['white', 'large']
        }

        def semantic_match(expected_word, detected_keywords):
            if expected_word in detected_keywords:
                return True
            if expected_word in semantic_mappings:
                synonyms = semantic_mappings[expected_word]
                return any(syn in detected_keywords for syn in synonyms)
            return any(expected_word in keyword for keyword in detected_keywords)

        matches = 0
        for expected in expected_features:
            expected_keywords = extract_keywords(expected)
            all_detected_keywords = set()
            for detected in detected_features:
                all_detected_keywords.update(extract_keywords(detected))

            feature_matched = False
            for exp_keyword in expected_keywords:
                if semantic_match(exp_keyword, all_detected_keywords):
                    feature_matched = True
                    break

            if feature_matched:
                matches += 1

        return matches / len(expected_features)

    def _get_default_shelf_configs(self) -> List[Dict[str, Any]]:
        """
        Returns default shelf configuration when no planogram config is provided.
        Default: Header (0.34), Middle (0.25), Bottom (rest ~0.41)
        """
        return [
            {"level": "header", "height_ratio": 0.34},
            {"level": "middle", "height_ratio": 0.25},
            {"level": "bottom", "height_ratio": 0.41},
        ]

    def _generate_virtual_shelves(
        self,
        roi_bbox: DetectionBox,
        image_size: Tuple[int, int],
        planogram: Any
    ) -> List[ShelfRegion]:
        """
        Generates virtual shelf regions based on ROI and planogram configuration ratios.
        """
        w, h = image_size
        r_x1, r_y1, r_x2, r_y2 = roi_bbox.x1, roi_bbox.y1, roi_bbox.x2, roi_bbox.y2

        # Ensure absolute coords
        if r_x1 <= 1.0 and r_x2 <= 1.0:
            r_x1 *= w
            r_y1 *= h
            r_x2 *= w
            r_y2 *= h

        roi_h = r_y2 - r_y1
        shelves = []
        current_y = r_y1

        # Get shelf config from planogram
        # If no config, fallback to default thirds: Header (0.34), Middle (0.25), Bottom (rest)
        shelf_configs = getattr(planogram, "shelves", []) or self._get_default_shelf_configs()
        shelf_padding_ratio = 0.0
        if hasattr(self.planogram_config, "endcap_geometry"):
            shelf_padding_ratio = float(getattr(self.planogram_config.endcap_geometry, "inter_shelf_padding", 0.0) or 0.0)
        allow_overlap = getattr(planogram, "allow_overlap", False)
        if not allow_overlap and hasattr(planogram, "planogram_config") and isinstance(planogram.planogram_config, dict):
            allow_overlap = planogram.planogram_config.get("allow_overlap", False)
            if not allow_overlap:
                # Also check nested under 'aisle' key (common config pattern)
                aisle_cfg = planogram.planogram_config.get("aisle", {})
                if isinstance(aisle_cfg, dict):
                    allow_overlap = aisle_cfg.get("allow_overlap", False)

        used_ratio = 0.0
        for i, cfg in enumerate(shelf_configs):
            level = getattr(cfg, "level", f"shelf_{i}")

            # Determine start Y — always honour explicit y_start_ratio
            start_ratio = getattr(cfg, "y_start_ratio", None)
            if start_ratio is not None:
                s_y1 = r_y1 + (roi_h * float(start_ratio))
            else:
                s_y1 = current_y

            if ratio := getattr(cfg, "height_ratio", None):
                s_h = roi_h * float(ratio)
                used_ratio += float(ratio)
            elif i == len(shelf_configs) - 1 and start_ratio is None:
                # Last shelf takes the rest (only if implicit stacking)
                s_h = max(0, (r_y2 - s_y1))
            else:
                s_h = roi_h * 0.25  # Default?

            base_y2 = min(r_y2, s_y1 + s_h)
            pad = roi_h * shelf_padding_ratio
            s_y2 = min(r_y2, base_y2 + pad) if pad > 0 else base_y2

            # Read is_background flag from config (handles both dict and object)
            if isinstance(cfg, dict):
                is_background = cfg.get("is_background", False)
            else:
                is_background = getattr(cfg, "is_background", False)

            shelves.append(ShelfRegion(
                shelf_id=f"virtual_{level}",
                level=level,
                bbox=DetectionBox(
                    x1=int(r_x1),
                    y1=int(s_y1),
                    x2=int(r_x2),
                    y2=int(s_y2),
                    confidence=1.0
                ),
                is_background=is_background
            ))

            # Always advance current_y so stacking fallback works for
            # shelves that lack an explicit y_start_ratio.
            current_y = base_y2
            if current_y >= r_y2:
                break

        return shelves

    def _assign_products_to_shelves(
        self,
        products: List[IdentifiedProduct],
        shelves: List[ShelfRegion]
    ):
        """
        Assigns each product to the spatially best-fitting shelf.
        Modifies 'shelf_location' in-place.
        Supports 'is_background' flag for layered shelf assignment.
        """
        if not shelves:
            return

        # Sort just in case, though virtual generator creates them ordered
        shelves.sort(key=lambda s: s.bbox.y1)

        # Identify background shelves for promotional graphics
        background_shelves = [s for s in shelves if getattr(s, 'is_background', False)]

        _promo_types_assign = {
            "promotional_graphic", "graphic", "banner", "backlit_graphic", "backlit",
            "advertisement", "advertisement_graphic", "display_graphic",
            "promotional_display", "promotional_material", "promotional_materials"
        }
        _structural_types = {"gap", "shelf"}
        for p in products:
            if p.product_type in _structural_types:
                continue  # Skip structural LLM detections (gaps, shelf lines)
            if p.product_type in _promo_types_assign and p.shelf_location == "header":
                continue  # Already assigned to header, keep it

            # Check if this is a promotional/advertisement item that should go to background
            # Check various fields for promotional indicators
            model_lower = (p.product_model or "").lower()
            type_lower = (p.product_type or "").lower()
            brand_lower = (getattr(p, 'brand', '') or "").lower()
            
            # Items with explicit promotional names like "Logo Ad" should always go to background
            is_explicit_ad = ("logo" in model_lower and "ad" in model_lower) or "backlit" in model_lower
            
            # Regular products should NOT go to background (unless explicitly an ad)
            is_regular_product = p.product_type in ("product", "printer", "speaker", "pa_system") and not is_explicit_ad
            
            is_promotional = (
                is_explicit_ad or
                (not is_regular_product and (
                    p.product_type in ("promotional_graphic", "advertisement", "graphic", "logo", "banner", "backlit_graphic") or
                    "logo" in model_lower or
                    " ad" in model_lower or
                    "advertisement" in model_lower or
                    "graphic" in type_lower or
                    "banner" in type_lower or
                    "logo" in brand_lower
                ))
            )

            # For promotional items, prefer background shelves over foreground —
            # but only when the item's center actually falls inside that shelf's
            # Y range.  If the center lies below the background shelf (e.g. a
            # comparison table or base graphic detected as promotional_graphic),
            # fall through to the regular spatial assignment so it lands on the
            # correct foreground shelf.
            if is_promotional and background_shelves:
                bg = background_shelves[0]
                p_box_check = p.detection_box
                if p_box_check is not None:
                    p_cy_check = (p_box_check.y1 + p_box_check.y2) / 2
                    if bg.bbox.y1 <= p_cy_check <= bg.bbox.y2:
                        p.shelf_location = bg.level
                        continue
                    # else: fall through to spatial assignment below
                else:
                    p.shelf_location = bg.level
                    continue

            p_box = p.detection_box

            # For regular products, prefer foreground shelves (non-background)
            # Only fall back to background shelves if no foreground shelf matches
            foreground_shelves = [s for s in shelves if not getattr(s, 'is_background', False)]
            search_shelves = foreground_shelves if foreground_shelves else shelves

            # If no detection_box (LLM-identified products without bbox), fall back
            # to assigning by order: use shelf_location already set by LLM if valid,
            # otherwise assign to middle foreground shelf
            if p_box is None:
                valid_levels = {s.level for s in search_shelves}
                if p.shelf_location and p.shelf_location in valid_levels:
                    continue  # keep LLM-assigned shelf if it's a valid foreground shelf
                # Assign to the middle foreground shelf as best guess
                mid_idx = len(search_shelves) // 2
                p.shelf_location = search_shelves[mid_idx].level
                continue

            p_cy = (p_box.y1 + p_box.y2) / 2

            best_shelf = None
            max_iou = 0.0
            min_dist = float('inf')

            # Use Vertical Intersection similar to user request
            for s in search_shelves:
                s_box = s.bbox
                sy1, sy2 = s_box.y1, s_box.y2
                py1, py2 = p_box.y1, p_box.y2

                inter_y1 = max(sy1, py1)
                inter_y2 = min(sy2, py2)

                if inter_y2 > inter_y1:
                    iy = inter_y2 - inter_y1
                    ph = py2 - py1
                    overlap = iy / ph if ph > 0 else 0
                    if overlap > 0.5:
                        best_shelf = s
                        break

            if not best_shelf:
                # Vertical center distance fallback - still prefer foreground
                for s in search_shelves:
                    s_box = s.bbox
                    s_cy = (s_box.y1 + s_box.y2) / 2
                    dist = abs(p_cy - s_cy)
                    if dist < min_dist:
                        min_dist = dist
                        best_shelf = s

            # If still no match in foreground, fall back to any shelf
            if not best_shelf and foreground_shelves:
                for s in shelves:
                    s_box = s.bbox
                    s_cy = (s_box.y1 + s_box.y2) / 2
                    dist = abs(p_cy - s_cy)
                    if dist < min_dist:
                        min_dist = dist
                        best_shelf = s

            if best_shelf:
                p.shelf_location = best_shelf.level
