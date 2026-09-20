"""Legacy cycle adapter: the ROI-first orchestration formerly inlined in ``PlanogramCompliance.run()``.

Behaviour-preserving move of steps 5-17 (``plan.py:98-343``). Same order, same ``hasattr`` guards.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Set, Tuple

from PIL import Image, ImageDraw

from parrot.models.detections import DetectionBox, IdentifiedProduct, ShelfRegion

from ..contracts import CycleContext, LegacyPayload, PerceptionResult

if TYPE_CHECKING:
    from .abstract import AbstractPlanogramType


async def legacy_perceive(
    handler: "AbstractPlanogramType", image: Image.Image, image_id: str, ctx: CycleContext
) -> PerceptionResult:
    """Run the legacy preparation and detection sequence for one image.

    Args:
        handler: The legacy type composable.
        image: The already-opened (enhanced) PIL image.
        image_id: Image identifier; also drives the debug-file suffix.
        ctx: Per-run context (only ``output_dir`` is read here).

    Returns:
        PerceptionResult with ``detection_source='legacy_llm'`` and the ``LegacyPayload``.
    """
    img = image
    errors: List[str] = []
    sfx = f"_{image_id}" if image_id else ""
    planogram_description = handler.config.get_planogram_description()
    endcap = brand = panel_text = None
    raw_dets: List[Any] = []
    try:  # step 5 — failure is logged, never raised (plan.py:98-102)
        endcap, _ad, brand, panel_text, raw_dets = await handler.compute_roi(img)
    except Exception as e:  # noqa: BLE001 - preserved legacy behaviour
        handler.logger.error(f"Step 1 Failed: {e}")
        errors.append(f"compute_roi failed: {e}")
    if ctx.output_dir:  # step 6
        _save_roi_debug(handler, img, endcap, raw_dets, Path(ctx.output_dir), sfx)
    identified_products, shelf_regions = await handler.detect_objects(img, roi=endcap, macro_objects=None)  # step 7
    handler.logger.info("Step 2 detected %d products, %d shelf regions", len(identified_products), len(shelf_regions))
    lookups = _config_lookups(handler, planogram_description)  # steps 9-10
    await _promo_ocr(handler, img, identified_products, planogram_description, lookups)  # step 11
    shelf_regions = await _shelves_and_fact_tags(  # steps 12-15
        handler, img, endcap, identified_products, shelf_regions, planogram_description
    )
    _inject_header_items(handler, img, identified_products, panel_text, brand, planogram_description)  # 16-17
    return PerceptionResult(
        image_id=image_id or "img0",
        image_size=img.size,
        shapes=[],
        slots=[],
        zones=[],
        row_count=0,
        detection_source="legacy_llm",
        ocr_available=False,
        legacy=LegacyPayload(identified_products=identified_products, shelf_regions=shelf_regions),
        errors=errors,
    )


def _save_roi_debug(
    handler: "AbstractPlanogramType",
    img: Image.Image,
    endcap: Any,
    raw_dets: List[Any],
    output_dir: Path,
    sfx: str,
) -> None:
    """Step 6: save the ROI debug overlay; failures are warnings only."""
    try:
        debug_img = img.copy()
        debug_draw = ImageDraw.Draw(debug_img)
        w, h = debug_img.size

        if raw_dets:
            for d in raw_dets:
                if hasattr(d, "bbox"):
                    b = d.bbox
                    x1, y1, x2, y2 = b.x1 * w, b.y1 * h, b.x2 * w, b.y2 * h
                    label = getattr(d, "label", None) or "unknown"
                    color = "blue" if "poster" in label else "green"
                    debug_draw.rectangle([x1, y1, x2, y2], outline=color, width=3)
                    debug_draw.text((x1, y1), label, fill=color)

        if endcap:
            b = endcap.bbox
            x1, y1, x2, y2 = b.x1 * w, b.y1 * h, b.x2 * w, b.y2 * h
            debug_draw.rectangle([x1, y1, x2, y2], outline="red", width=5)
            debug_draw.text((x1, y1), "ENDCAP ROI", fill="red")

        debug_path = output_dir / f"debug_step1_roi{sfx}.png"
        debug_img.save(debug_path)
        handler.logger.info(f"Saved Step 1 Debug Image to {debug_path}")
    except Exception as e:  # noqa: BLE001
        handler.logger.warning(f"Failed to save Step 1 debug image: {e}")


def _config_lookups(
    handler: "AbstractPlanogramType", planogram_description: Any
) -> Tuple[Dict[str, list], Set[str], Dict[str, list]]:
    """Steps 9-10: visual-feature and text-requirement lookups keyed by product name."""
    visuals_by_name: Dict[str, list] = {}
    visuals_fallback: Set[str] = set()
    text_reqs_by_name: Dict[str, list] = {}
    try:
        if planogram_description.shelves:
            for s in planogram_description.shelves:
                for p_cfg in s.products:
                    if p_cfg.visual_features:
                        visuals_by_name[p_cfg.name] = list(p_cfg.visual_features)
                        if p_cfg.product_type == "promotional_graphic" or "header" in s.level.lower():
                            visuals_fallback.update(p_cfg.visual_features)
    except Exception as e:  # noqa: BLE001
        handler.logger.warning(f"Failed to extract visual_features: {e}")

    # text_requirements is not a declared field on the ShelfProduct Pydantic model: read the raw dict.
    try:
        raw_config = getattr(handler.config, "planogram_config", {}) or {}
        for s_raw in raw_config.get("shelves", []):
            for p_raw in s_raw.get("products", []) if isinstance(s_raw, dict) else []:
                name = p_raw.get("name", "")
                text_reqs = p_raw.get("text_requirements")
                if name and text_reqs:
                    text_reqs_by_name[name] = list(text_reqs)
    except Exception as e:  # noqa: BLE001
        handler.logger.warning(f"Failed to extract text_requirements: {e}")
    return visuals_by_name, visuals_fallback, text_reqs_by_name


async def _promo_ocr(
    handler: "AbstractPlanogramType",
    img: Image.Image,
    identified_products: List[IdentifiedProduct],
    planogram_description: Any,
    lookups: Tuple[Dict[str, list], Set[str], Dict[str, list]],
) -> None:
    """Step 11: OCR + visual verification of promotional items (mutates products in place)."""
    visuals_by_name, visuals_fallback, text_reqs_by_name = lookups
    for p in identified_products:
        model_lower = (p.product_model or "").lower()
        if not ("logo ad" in model_lower or "backlit" in model_lower or p.product_type == "promotional_graphic"):
            continue
        try:
            p_box = p.detection_box
            crop_box = (int(p_box.x1), int(p_box.y1), int(p_box.x2), int(p_box.y2))
            if not (crop_box[0] < crop_box[2] and crop_box[1] < crop_box[3]):
                continue
            p_img = img.crop(crop_box)
            handler.logger.info(f"Running OCR & Visual verification on promotional item: {p.product_model}")
            ocr_prompt = _build_ocr_prompt(
                visuals_by_name.get(p.product_model) or list(visuals_fallback),
                text_reqs_by_name.get(p.product_model, []),
            )
            async with handler.pipeline.llm as client:
                msg = await client.ask_to_image(
                    image=p_img,
                    prompt=ocr_prompt,
                    **handler._vision_kwargs(),
                    max_tokens=1024,
                )
            found_content = msg.output if msg else ""
            if found_content:
                _apply_ocr_result(handler, p, found_content, planogram_description)
        except Exception as e:  # noqa: BLE001
            handler.logger.warning(f"Failed OCR fallback for {p.product_model}: {e}")


def _build_ocr_prompt(item_visuals: list, item_text_reqs: list) -> str:
    """Build the promo OCR prompt exactly as today."""
    visuals_prompt = ""
    if item_visuals:
        v_list = "\n".join([f"- {v}" for v in item_visuals])
        visuals_prompt = (
            f"\nAlso check if these visual elements are present:\n{v_list}\n"
            "For each, output 'CONFIRMED: <feature sequence>'"
        )

    text_reqs_prompt = ""
    if item_text_reqs:
        req_texts = [
            (r.get("required_text", r) if isinstance(r, dict) else getattr(r, "required_text", str(r)))
            for r in item_text_reqs
        ]
        r_list = "\n".join([f'- "{t}"' for t in req_texts if t])
        text_reqs_prompt = (
            f"\nAlso specifically look for these required texts (even if partially visible or at the edge):\n{r_list}"
            f"\nFor each found, output 'TEXT_FOUND: <exact required text>'"
        )

    return (
        f"Read all visible text in this image.{visuals_prompt}{text_reqs_prompt}\n"
        "Return text content. If visual features confirmed, list them."
    )


def _apply_ocr_result(
    handler: "AbstractPlanogramType", p: IdentifiedProduct, found_content: str, planogram_description: Any
) -> None:
    """Parse CONFIRMED:/TEXT_FOUND: lines and enrich ``p`` in place."""
    handler.logger.info(f"Enrichment result: {found_content}")

    confirmed_features = []
    found_texts = []
    clean_text_parts = []
    for line in found_content.split("\n"):
        if "CONFIRMED:" in line:
            feat = line.split("CONFIRMED:", 1)[1].strip()
            confirmed_features.append(feat)
        elif "TEXT_FOUND:" in line:
            txt = line.split("TEXT_FOUND:", 1)[1].strip()
            found_texts.append(txt)
        else:
            clean_text_parts.append(line)

    clean_text = "\n".join(clean_text_parts).strip()

    if clean_text:
        handler.logger.info(f"OCR Fallback found text: {clean_text}")
        p.ocr_text = clean_text
        p.visual_features = (p.visual_features or []) + [f"ocr:{clean_text}", clean_text]

    if confirmed_features:
        handler.logger.info(f"Confirmed visual features: {confirmed_features}")
        p.visual_features = (p.visual_features or []) + confirmed_features

    if found_texts:
        handler.logger.info(f"Confirmed required texts: {found_texts}")
        p.visual_features = (p.visual_features or []) + found_texts

    p.product_type = "promotional_graphic"

    brand_lower = (planogram_description.brand or "").lower()
    brand_in_ocr = brand_lower and brand_lower in clean_text.lower()
    brand_in_model = brand_lower and brand_lower in (p.product_model or "").lower()
    brand_in_features = brand_lower and any(brand_lower in (f or "").lower() for f in (confirmed_features or []))
    if planogram_description.brand and (brand_in_ocr or brand_in_model or brand_in_features):
        p.brand = planogram_description.brand
        handler.logger.info(f"Verified brand '{p.brand}' via OCR on {p.product_model}")


async def _shelves_and_fact_tags(
    handler: "AbstractPlanogramType",
    img: Image.Image,
    endcap: Any,
    identified_products: List[IdentifiedProduct],
    shelf_regions: List[ShelfRegion],
    planogram_description: Any,
) -> List[ShelfRegion]:
    """Steps 12-15: virtual shelves, fact-tag refinement, shelf assignment, fact-tag corroboration."""
    if endcap and endcap.bbox:  # step 12
        if hasattr(handler, "_generate_virtual_shelves"):
            handler.logger.info("Generating virtual shelves from Endcap ROI...")
            shelf_regions = handler._generate_virtual_shelves(endcap.bbox, img.size, planogram_description)
        else:
            handler.logger.debug("Type %s does not use _generate_virtual_shelves; skipping.", type(handler).__name__)
    pg_cfg = getattr(handler.config, "planogram_config", {}) or {}
    if pg_cfg.get("use_fact_tag_boundaries") and shelf_regions:  # step 13 — NO hasattr guard, as today
        shelf_regions = handler._refine_shelves_from_fact_tags(shelf_regions, identified_products)
    if hasattr(handler, "_assign_products_to_shelves"):  # step 14
        handler._assign_products_to_shelves(
            identified_products, shelf_regions, use_y1_assignment=pg_cfg.get("use_fact_tag_boundaries", False)
        )
    if pg_cfg.get("use_fact_tag_boundaries") and hasattr(handler, "_ocr_fact_tags"):  # step 15
        ft_shelf_map = await handler._ocr_fact_tags(
            identified_products, img, planogram_description, shelf_regions=shelf_regions
        )
        if hasattr(handler, "_corroborate_products_with_fact_tags"):
            handler._corroborate_products_with_fact_tags(identified_products, ft_shelf_map, planogram_description)
    return shelf_regions


def _inject_header_items(
    handler: "AbstractPlanogramType",
    img: Image.Image,
    identified_products: List[IdentifiedProduct],
    panel_text: Any,
    brand: Any,
    planogram_description: Any,
) -> None:
    """Steps 16-17: append the poster-text and brand-logo pseudo products."""
    if panel_text and getattr(panel_text, "content", None):
        handler.logger.info(f"Injecting poster text: {panel_text.content}")
        ocr_content = panel_text.content.strip()
        text_product = IdentifiedProduct(
            detection_box=DetectionBox(
                x1=int(panel_text.bbox.x1 * img.width),
                y1=int(panel_text.bbox.y1 * img.height),
                x2=int(panel_text.bbox.x2 * img.width),
                y2=int(panel_text.bbox.y2 * img.height),
                confidence=float(getattr(panel_text, "confidence", 1.0)),
                ocr_text=ocr_content,
            ),
            product_type="text_overlay",
            product_model="poster_text",
            confidence=float(getattr(panel_text, "confidence", 1.0)),
            visual_features=[f"ocr:{ocr_content}"],
            shelf_location="header",
        )
        identified_products.append(text_product)

    if brand:
        brand_conf = float(getattr(brand, "confidence", 1.0))
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
            shelf_location="header",
        )
        identified_products.append(brand_product)
        handler.logger.info(f"Injecting brand logo: {brand_product.brand}")
