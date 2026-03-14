import contextlib
from typing import Any, Dict, List, Optional, Union
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from ..abstract import AbstractPipeline
from ..models import PlanogramConfig
from ...models.detections import (
    DetectionBox,
    ShelfRegion,
    IdentifiedProduct,
    Detection,
)
from ...models.compliance import (
    ComplianceStatus,
)
from .types import ProductOnShelves


class PlanogramCompliance(AbstractPipeline):
    """Pure-LLM Planogram Compliance Pipeline with Composable Delegation.

    Uses the Composable Pattern: PlanogramCompliance remains the single public
    entry point. Internally it resolves a type-specific composable class
    (e.g. ProductOnShelves, InkWall) from planogram_type in the config and
    delegates all type-specific steps to it.

    The handler always calls:
        pipeline = PlanogramCompliance(planogram_config=config, llm=llm)
        results = await pipeline.run(image)
    """

    _PLANOGRAM_TYPES = {
        "product_on_shelves": ProductOnShelves,
    }

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

        # Resolve composable type handler
        ptype = getattr(planogram_config, "planogram_type", None) or "product_on_shelves"
        composable_cls = self._PLANOGRAM_TYPES.get(ptype)
        if composable_cls is None:
            available = ", ".join(sorted(self._PLANOGRAM_TYPES.keys()))
            raise ValueError(
                f"Unknown planogram_type '{ptype}'. "
                f"Available types: {available}"
            )
        self._type_handler = composable_cls(pipeline=self, config=planogram_config)

    async def run(
        self,
        image: Union[str, Path, Image.Image],
        output_dir: Optional[Union[str, Path]] = None,
        image_id: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Run the planogram compliance pipeline.

        Delegates type-specific steps (ROI detection, product detection,
        compliance checking) to self._type_handler while keeping shared
        orchestration logic (image loading, debug rendering, result assembly).
        """
        _sfx = f"_{image_id}" if image_id else ""
        self.logger.info(
            "Starting Pure-LLM Planogram Compliance Pipeline"
        )

        # Step 1: Find Poster/Endcap (type-specific ROI detection)
        img = self.open_image(image)
        planogram_description = self.planogram_config.get_planogram_description()

        detections_step1 = {}
        endcap = None
        ad = None
        brand = None
        panel_text = None
        raw_dets = []

        try:
            endcap, ad, brand, panel_text, raw_dets = await self._type_handler.compute_roi(img)
            detections_step1 = {
                "endcap": endcap,
                "dataset": raw_dets
            }
        except Exception as e:
            self.logger.error(
                f"Step 1 Failed: {e}"
            )

        if output_dir:
            try:
                debug_img = img.copy()
                debug_draw = ImageDraw.Draw(debug_img)
                w, h = debug_img.size

                if detections_step1.get("dataset"):
                    for d in detections_step1["dataset"]:
                        if hasattr(d, 'bbox'):
                            b = d.bbox
                            x1, y1, x2, y2 = b.x1 * w, b.y1 * h, b.x2 * w, b.y2 * h
                            label = getattr(d, 'label', None) or 'unknown'
                            color = "blue" if "poster" in label else "green"
                            debug_draw.rectangle([x1, y1, x2, y2], outline=color, width=3)
                            debug_draw.text((x1, y1), label, fill=color)

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

        # Construct prompt and detect objects
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

        refs = list(self.reference_images.values()) if self.reference_images else []

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

        shelf_regions = []
        identified_products = []

        w, h = target_image.size

        self.logger.debug(f"Detected {len(detected_items)} items from LLM.")

        for item in detected_items:
            box = item.get("box_2d")
            if not box:
                continue

            x1, y1, x2, y2 = box
            abs_x1 = x1 + offset_x
            abs_y1 = y1 + offset_y
            abs_x2 = x2 + offset_x
            abs_y2 = y2 + offset_y

            label = item.get("label", "unknown")
            conf = item.get("confidence", 0.0)
            if "shelf" in label.lower():
                shelf_regions.append(
                    ShelfRegion(
                        shelf_id=f"shelf_{len(shelf_regions)}",
                        level=label,
                        bbox=DetectionBox(
                            x1=abs_x1, y1=abs_y1, x2=abs_x2, y2=abs_y2, confidence=conf
                        )
                    )
                )
            else:
                ptype = item.get("type", "product")
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
                    color = "blue" if "shelf" in label.lower() else "green"
                    if "Bose Logo Ad" in label:
                        color = "magenta"
                    debug_draw_2.rectangle([x1, y1, x2, y2], outline=color, width=4)
                    debug_draw_2.text((x1, y1), f"{label} ({conf:.2f})", fill=color)

            debug_path_2 = Path(output_dir) / f"debug_step2_detections{_sfx}.png"
            debug_img_2.save(debug_path_2)
            self.logger.info(f"Saved Step 2 Debug Image to {debug_path_2}")
        except Exception as e:
            self.logger.warning(f"Failed to save Step 2 debug image: {e}")

        # Build visual features lookup from planogram config
        _cfg_visuals_by_name: dict = {}
        _cfg_visuals_fallback: set = set()
        try:
            if planogram_description.shelves:
                for s in planogram_description.shelves:
                    for p_cfg in s.products:
                        if p_cfg.visual_features:
                            _cfg_visuals_by_name[p_cfg.name] = list(p_cfg.visual_features)
                            if p_cfg.product_type == "promotional_graphic" or "header" in s.level.lower():
                                _cfg_visuals_fallback.update(p_cfg.visual_features)
        except Exception as e:
            self.logger.warning(f"Failed to extract visual_features: {e}")

        # OCR Fallback & Visual Feature Verification for promotional items
        for p in identified_products:
            model_lower = (p.product_model or "").lower()
            if "logo ad" in model_lower or "backlit" in model_lower or p.product_type == "promotional_graphic":
                try:
                    p_box = p.detection_box
                    crop_box = (int(p_box.x1), int(p_box.y1), int(p_box.x2), int(p_box.y2))

                    if crop_box[0] < crop_box[2] and crop_box[1] < crop_box[3]:
                        p_img = img.crop(crop_box)
                        self.logger.info(f"Running OCR & Visual verification on promotional item: {p.product_model}")

                        item_visuals = _cfg_visuals_by_name.get(p.product_model) or list(_cfg_visuals_fallback)

                        visuals_prompt = ""
                        if item_visuals:
                            v_list = "\n".join([f"- {v}" for v in item_visuals])
                            visuals_prompt = f"\nAlso check if these visual elements are present:\n{v_list}\nFor each, output 'CONFIRMED: <feature sequence>'"

                        ocr_prompt = f"Read all visible text in this image.{visuals_prompt}\nReturn text content. If visual features confirmed, list them."
                        async with self.roi_client as client:
                            msg = await client.ask_to_image(
                                image=p_img,
                                prompt=ocr_prompt,
                                model="gemini-2.5-flash",
                                no_memory=True,
                                max_tokens=1024
                            )
                            found_content = msg.output if msg else ""
                            if found_content:
                                self.logger.info(f"Enrichment result: {found_content}")

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

                                if confirmed_features:
                                    self.logger.info(f"Confirmed visual features: {confirmed_features}")
                                    p.visual_features = (p.visual_features or []) + confirmed_features

                                p.product_type = "promotional_graphic"

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

        # Generate virtual shelves from Step 1 Endcap ROI (type-specific)
        if endcap and endcap.bbox:
            self.logger.info(
                "Generating virtual shelves from Endcap ROI..."
            )
            virtual_shelves = self._type_handler._generate_virtual_shelves(
                endcap.bbox, img.size, planogram_description
            )
            shelf_regions = virtual_shelves

        # Optionally refine shelf boundaries from detected fact-tag rows (type-specific)
        _pg_cfg = getattr(self.planogram_config, "planogram_config", {}) or {}
        if _pg_cfg.get("use_fact_tag_boundaries") and shelf_regions:
            shelf_regions = self._type_handler._refine_shelves_from_fact_tags(
                shelf_regions, identified_products
            )

        # Assign products to shelves (type-specific)
        _use_y1 = _pg_cfg.get("use_fact_tag_boundaries", False)
        self._type_handler._assign_products_to_shelves(
            identified_products, shelf_regions, use_y1_assignment=_use_y1
        )

        # Fact-tag OCR corroboration (type-specific)
        if _pg_cfg.get("use_fact_tag_boundaries"):
            _ft_shelf_map = await self._type_handler._ocr_fact_tags(
                identified_products, img, planogram_description,
                shelf_regions=shelf_regions,
            )
            self._type_handler._corroborate_products_with_fact_tags(
                identified_products, _ft_shelf_map, planogram_description
            )

        # Inject poster text as product if found
        if panel_text and getattr(panel_text, 'content', None):
            self.logger.info(f"Injecting poster text: {panel_text.content}")
            ocr_content = panel_text.content.strip()
            text_product = IdentifiedProduct(
                detection_box=DetectionBox(
                    x1=int(panel_text.bbox.x1 * img.width),
                    y1=int(panel_text.bbox.y1 * img.height),
                    x2=int(panel_text.bbox.x2 * img.width),
                    y2=int(panel_text.bbox.y2 * img.height),
                    confidence=float(getattr(panel_text, 'confidence', 1.0)),
                    ocr_text=ocr_content
                ),
                product_type="text_overlay",
                product_model="poster_text",
                confidence=float(getattr(panel_text, 'confidence', 1.0)),
                visual_features=[f"ocr:{ocr_content}"],
                shelf_location="header"
            )
            identified_products.append(text_product)

        # Inject brand logo if found
        if brand:
            brand_conf = float(getattr(brand, 'confidence', 1.0))
            bx1 = int(brand.bbox.x1 * img.width)
            by1 = int(brand.bbox.y1 * img.height)
            bx2 = int(brand.bbox.x2 * img.width)
            by2 = int(brand.bbox.y2 * img.height)
            brand_product = IdentifiedProduct(
                detection_box=DetectionBox(x1=bx1, y1=by1, x2=bx2, y2=by2, confidence=brand_conf),
                product_type="brand_logo",
                product_model=brand.label or "brand_logo",
                confidence=brand_conf,
                brand=planogram_description.brand,
                shelf_location="header"
            )
            identified_products.append(brand_product)
            self.logger.info(f"Injecting brand logo: {brand_product.brand}")

        # Step 3: Planogram Compliance Verification (type-specific)
        compliance_results = self._type_handler.check_planogram_compliance(
            identified_products, planogram_description
        )
        overall_score = 0.0
        overall_compliant = True
        if compliance_results:
            overall_score = sum(r.compliance_score for r in compliance_results) / len(compliance_results)
            overall_compliant = all(r.compliance_status == ComplianceStatus.COMPLIANT for r in compliance_results)

        # Step 4: Render evaluated image (shared, with type-specific colors)
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
    # Shared rendering (uses type-specific colors)
    # =========================================================================

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
        """Render compliance evaluation overlay on the image.

        Uses colors from self._type_handler.get_render_colors() for
        type-specific color schemes.
        """
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

        # Get type-specific render colors and merge with product-type colors
        _type_colors = self._type_handler.get_render_colors()
        colors = {
            "tv_demonstration": _type_colors.get("compliant", (0, 255, 0)),
            "promotional_graphic": (255, 0, 255),
            "promotional_base": (0, 0, 255),
            "fact_tag": (255, 255, 0),
            "product_box": (255, 128, 0),
            "printer": (255, 0, 0),
            "unknown": (200, 200, 200),
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
