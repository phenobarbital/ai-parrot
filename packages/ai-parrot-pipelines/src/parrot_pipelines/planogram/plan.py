import contextlib
from typing import Any, Dict, List, Optional, Union
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from ..abstract import AbstractPipeline
from ..models import PlanogramConfig
import asyncio
from typing import Sequence, Tuple

import numpy as np

from .backend import UNSET, _Unset
from .contracts import (
    AssessmentStatus,
    ComparisonResult,
    CreditPolicy,
    CycleContext,
    EvidenceWeights,
    IdentificationResult,
    ObservationSource,
    PerceptionResult,
    RenderRecord,
    ShapeKind,
    Slot,
)
from .perception.executor import CpuExecutor
from .perception.ocr import OcrReader
from .identification.detector import GENERIC_DETECTION_PROMPT, llm_detect_shapes
from .identification.vision import VisionAdapter
from .comparison.definition import (
    SlotsDefinition,
    SlotsDefinitionError,
    definition_coverage,
    load_slots_definition,
    validate_bindings,
)
from .identification.references import load_reference_bank
from .layout import LayoutProfile, resolve_layout_profile, validate_zone_selectors
from .stages.perceive import count_usable_targets, rebuild_geometry
from parrot.models.detections import (
    DetectionBox,
    ShelfRegion,
    IdentifiedProduct,
)
from .types import (
    ProductOnShelves,
    GraphicPanelDisplay,
    ProductCounter,
    EndcapNoShelvesPromotional,
    EndcapBacklitMultitier,
    InkWall,
)

ImageInput = Union[str, Path, Image.Image]
MIGRATION_RUNBOOK = "docs/pipelines/planogram-cycle-migration.md"
_PRODUCT_TYPE_BY_KIND: Dict[ShapeKind, str] = {
    ShapeKind.PRODUCT: "product",
    ShapeKind.BOX: "product_box",
    ShapeKind.FACT_TAG: "fact_tag",
    ShapeKind.PRICE_TAG: "price_tag",
    ShapeKind.ZONE: "promotional_graphic",
    ShapeKind.UNKNOWN: "unknown",
}


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
        "graphic_panel_display": GraphicPanelDisplay,
        "product_counter": ProductCounter,
        "endcap_no_shelves_promotional": EndcapNoShelvesPromotional,
        "endcap_backlit_multitier": EndcapBacklitMultitier,
        "ink_wall": InkWall,
    }

    def __init__(
        self,
        planogram_config: PlanogramConfig,
        llm: Any = None,
        llm_provider: Union[str, _Unset] = UNSET,
        llm_model: Union[str, None, _Unset] = UNSET,
        *,
        cpu_workers: int = 2,
        llm_concurrency: int = 4,
        llm_timeout: float = 120.0,
        vision_cache_dir: Optional[Path] = None,
        enabled_ocr: Optional[bool] = None,
        **kwargs: Any,
    ):
        """Build the pipeline and its planogram type composable.

        Args:
            planogram_config: The planogram configuration (``llm_backend`` feeds backend resolution).
            llm: A client instance or a ``"provider:model"`` string.
            llm_provider: Explicit provider (``UNSET`` when omitted).
            llm_model: Explicit model (``UNSET`` when omitted).
            cpu_workers: Worker processes of the per-run CPU executor.
            llm_concurrency: Concurrent vision calls per run.
            llm_timeout: Timeout of one vision call (seconds).
            vision_cache_dir: Optional response cache directory for the vision adapter.
            enabled_ocr: Enable optional local RapidOCR detection. Disabled by default; the LLM still
                identifies products and occupancy when local OCR is disabled.
            **kwargs: Forwarded to the client constructor.

        Raises:
            ValueError: Unknown planogram type, or a configuration the type rejects.
            TypeError: The type implements neither contract.
        """
        config_name = planogram_config.config_name
        ptype = getattr(planogram_config, "planogram_type", None) or "product_on_shelves"
        composable_cls = self._PLANOGRAM_TYPES.get(ptype)
        if composable_cls is None:
            available = ", ".join(sorted(self._PLANOGRAM_TYPES))
            raise ValueError(f"Unknown planogram_type '{ptype}'. Available types: {available}")
        if planogram_config.slots_definition is None:
            raise ValueError(
                f"PlanogramConfig {config_name!r} ({ptype}) has no slots_definition; convert it as described in {MIGRATION_RUNBOOK}"
            )
        super().__init__(
            llm=llm,
            llm_provider=llm_provider,
            llm_model=llm_model,
            config_backend=getattr(planogram_config, "llm_backend", None),
            **kwargs,
        )
        self.cpu_workers = cpu_workers
        self.llm_concurrency = llm_concurrency
        self.llm_timeout = llm_timeout
        self.vision_cache_dir = vision_cache_dir
        self.enabled_ocr = enabled_ocr
        self._layout: LayoutProfile = resolve_layout_profile(
            composable_cls.default_layout_profile(), planogram_config.planogram_config or {}, config_name=config_name
        )
        self._definition: Optional[SlotsDefinition] = None
        self._bindings: List[Any] = []
        self._definition_path: Optional[Path] = None
        self.planogram_config = planogram_config

        # Endcap geometry defaults
        geometry = planogram_config.endcap_geometry
        self.left_margin_ratio = geometry.left_margin_ratio
        self.right_margin_ratio = geometry.right_margin_ratio

        self.reference_images = planogram_config.reference_images or {}

        source = planogram_config.slots_definition
        if isinstance(source, dict):
            self._definition, self._bindings = self._load_definition(source)
        else:
            self._definition_path = Path(source)
            if not self._definition_path.is_file():
                raise ValueError(
                    f"PlanogramConfig {config_name!r}: slots_definition path {self._definition_path} does not exist; convert it as described in {MIGRATION_RUNBOOK}"
                )
        self._type_handler = composable_cls(pipeline=self, config=planogram_config)

    def _load_definition(self, source: Union[Dict[str, Any], str, Path]) -> Tuple[SlotsDefinition, List[Any]]:
        """Load and validate a definition, bindings, and layout zone selectors."""
        config_name = self.planogram_config.config_name
        try:
            definition = load_slots_definition(source)
            bindings = validate_bindings(definition, self.planogram_config.planogram_config or {})
            validate_zone_selectors(self._layout, definition, config_name=config_name)
        except (SlotsDefinitionError, ValueError) as exc:
            raise SlotsDefinitionError(f"PlanogramConfig {config_name!r}: {exc}") from exc
        return definition, bindings

    async def _ensure_definition(self) -> Tuple[SlotsDefinition, List[Any]]:
        """Return the cached definition, loading a configured path off the event loop once."""
        if self._definition is None:
            self._definition, self._bindings = await asyncio.to_thread(self._load_definition, self._definition_path)
        return self._definition, list(self._bindings)

    def _make_ocr(self) -> Optional[OcrReader]:
        """Create OCR unless explicitly disabled."""
        if self.enabled_ocr is False:
            return None
        reader = OcrReader()
        if self.enabled_ocr is True and not reader.available:
            self.logger.warning("enabled_ocr=True but rapidocr is not installed; text is read by the vision model")
        return reader

    async def run(
        self,
        image: Union[ImageInput, Sequence[ImageInput]],
        output_dir: Optional[Union[str, Path]] = None,
        image_id: Optional[Union[str, Sequence[str]]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Run the perceive -> identify -> compare cycle on one image or several photos of one fixture.

        Args:
            image: One image (path or PIL image) or a sequence of photos of the same fixture.
            output_dir: Optional directory for debug and render files.
            image_id: One id, or a sequence matching ``image`` (default ``img0..imgN``).
            **kwargs: Accepted and ignored (backwards compatibility).

        Returns:
            The 8 legacy keys plus the additive keys (detections, identifications, position_results,
            shelf_scores, coverage, detected_products, definition_coverage, assessment_status,
            strict_compliance_score, evidence_quality, detection_source, ocr_available, resolved_backend,
            renders, errors).

        Raises:
            ValueError: ``image_id`` is a sequence whose length differs from ``image``.
        """
        inputs, single_sfx = self._normalize_inputs(image, image_id)
        out_dir = Path(output_dir) if output_dir else None
        self.logger.info("Planogram cycle: %d image(s), type=%s", len(inputs), type(self._type_handler).__name__)
        definition, bindings = await self._ensure_definition()
        ctx = await self._build_context(out_dir, definition, bindings)
        ids: List[str] = []
        perceptions: List[PerceptionResult] = []
        identifications: List[IdentificationResult] = []
        try:
            if self._layout.references.enabled and self.reference_images:
                ctx.reference_bank = await load_reference_bank(self.reference_images, ctx)
            for img_id, source in inputs:
                try:
                    img, perception = await self._perceive_one(source, img_id, ctx)
                    ctx.images[img_id] = img
                    identification = await self._type_handler.identify(img, perception, ctx)
                except Exception as exc:  # noqa: BLE001 - isolate one failed photo
                    self.logger.error("Image %s failed: %s", img_id, exc)
                    ctx.errors.append(f"{img_id}: {exc}")
                    ctx.images.pop(img_id, None)
                    continue
                ids.append(img_id)
                perceptions.append(perception)
                identifications.append(identification)
            comparison = await self._compare(perceptions, identifications, ctx)
            renders = await self._render_all(ids, ctx.images, perceptions, identifications, out_dir, single_sfx)
        finally:
            ctx.images.clear()
            await ctx.executor.aclose()
            closer = getattr(ctx.vision, "aclose", None)
            if callable(closer):
                await closer()
        return self._assemble(perceptions, identifications, comparison, renders, ctx)

    def _normalize_inputs(self, image: Any, image_id: Any) -> Tuple[List[Tuple[str, ImageInput]], Optional[str]]:
        """Return ([(image_id, source)], single_image_suffix). Suffix is None for multi-image calls.

        Raises:
            ValueError: Mismatching, duplicate or wrongly typed ids, or an empty image list.
        """
        if isinstance(image, (str, Path, Image.Image)):
            if image_id is not None and not isinstance(image_id, str):
                raise ValueError("image_id must be a string when a single image is given")
            return [(image_id or "img0", image)], (f"_{image_id}" if image_id else "")
        sources = list(image)
        if not sources:
            raise ValueError("run() needs at least one image")
        if image_id is None:
            ids = [f"img{n}" for n in range(len(sources))]
        elif isinstance(image_id, str):
            raise ValueError("image_id must be a sequence matching the image list")
        else:
            ids = list(image_id)
        if len(ids) != len(sources):
            raise ValueError(f"image_id has {len(ids)} entries for {len(sources)} images")
        if len(set(ids)) != len(ids):
            raise ValueError(f"image_id entries must be unique, got {ids}")
        return list(zip(ids, sources, strict=True)), None

    async def _build_context(
        self, output_dir: Optional[Path], definition: SlotsDefinition, bindings: List[Any]
    ) -> CycleContext:
        """Create the per-run shared services."""
        vision = VisionAdapter(
            self.llm,
            self.resolved_backend,
            semaphore=asyncio.Semaphore(self.llm_concurrency),
            cache_dir=self.vision_cache_dir,
            timeout=self.llm_timeout,
        )
        return CycleContext(
            vision=vision,
            executor=CpuExecutor(max_workers=self.cpu_workers),
            ocr=self._make_ocr(),
            definition=definition,
            bindings=bindings,
            credit_policy=CreditPolicy.default(),
            evidence_weights=EvidenceWeights(),
            output_dir=output_dir,
            errors=[],
            layout=self._layout,
            reference_bank=[],
            images={},
        )

    async def _perceive_one(
        self, source: ImageInput, image_id: str, ctx: CycleContext
    ) -> Tuple[Image.Image, PerceptionResult]:
        """Load one untouched image, perceive it, and apply the bounded fallback."""
        img = await asyncio.to_thread(self.open_image, source, enhance=False)
        perception = await self._type_handler.perceive(img, image_id, ctx)
        perception = await self._fallback_if_needed(img, perception, ctx)
        return img, perception

    async def _fallback_if_needed(
        self, img: Image.Image, perception: PerceptionResult, ctx: CycleContext
    ) -> PerceptionResult:
        """Use at most one generic detector fallback and rebuild its geometry."""
        layout = self._layout
        threshold = layout.min_usable_shapes
        if threshold <= 0 or layout.perception_mode == "llm_detector":
            return perception
        if count_usable_targets(perception, layout) >= threshold:
            return perception
        self.logger.warning("Image %s: usable shapes under %d — LLM detector fallback", perception.image_id, threshold)
        bgr = np.ascontiguousarray(np.asarray(img.convert("RGB"))[:, :, ::-1])
        try:
            shapes = await llm_detect_shapes(bgr, perception.image_id, ctx, prompt=GENERIC_DETECTION_PROMPT)
        except Exception as exc:  # noqa: BLE001
            ctx.errors.append(f"llm_detector {perception.image_id}: {exc}")
            shapes = []
        if not shapes:
            message = f"{perception.image_id}: LLM detector fallback produced no shapes; perception kept as is"
            ctx.errors.append(message)
            return perception.model_copy(update={"errors": [*perception.errors, message]})
        zones = [shape for shape in shapes if shape.kind == ShapeKind.ZONE] or list(perception.zones)
        merged = [*zones, *(shape for shape in shapes if shape.kind != ShapeKind.ZONE)]
        source = (
            ObservationSource.LLM.value if all(shape.source == ObservationSource.LLM for shape in merged) else "mixed"
        )
        rebuilt = await rebuild_geometry(img, merged, perception.image_id, ctx, detection_source=source)
        return rebuilt.model_copy(update={"errors": [*perception.errors, *rebuilt.errors]})

    async def _compare(
        self, perceptions: List[PerceptionResult], identifications: List[IdentificationResult], ctx: CycleContext
    ) -> ComparisonResult:
        """Run the compare hook, or build the all-failed inconclusive result."""
        if perceptions:
            return await self._type_handler.compare(perceptions, identifications, ctx)
        return ComparisonResult(
            compliance_results=[],
            overall_compliance_score=0.0,
            strict_compliance_score=0.0,
            overall_compliant=False,
            coverage=0.0,
            definition_coverage=definition_coverage(ctx.definition)[0] if ctx.definition is not None else None,
            evidence_quality=0.0,
            assessment_status=AssessmentStatus.INCONCLUSIVE,
            errors=["no image could be processed"],
        )

    async def _render_all(
        self,
        ids: List[str],
        images: Dict[str, Image.Image],
        perceptions: List[PerceptionResult],
        identifications: List[IdentificationResult],
        output_dir: Optional[Path],
        single_sfx: Optional[str],
    ) -> List[RenderRecord]:
        """Render every successfully processed image with ITS OWN boxes only."""
        records: List[RenderRecord] = []
        for img_id, perception, identification in zip(ids, perceptions, identifications, strict=True):
            sfx = single_sfx if single_sfx is not None else f"_{img_id}"
            save_to = str(output_dir / f"compliance_render{sfx}.png") if output_dir else None
            products, shelves = self._render_inputs(perception, identification)
            rendered = await asyncio.to_thread(
                self.render_evaluated_image,
                images[img_id],
                shelf_regions=shelves,
                identified_products=products,
                save_to=save_to,
            )
            records.append(RenderRecord(image_id=img_id, rendered_image=rendered, overlay_path=save_to))
        return records

    def _render_inputs(
        self, perception: PerceptionResult, identification: IdentificationResult
    ) -> Tuple[List[IdentifiedProduct], List[ShelfRegion]]:
        """Build render inputs from observed shapes, slots, rows, and zones."""
        shapes = {shape.shape_id: shape for shape in [*perception.shapes, *perception.zones, *identification.added]}
        slots = {slot.slot_id: slot for slot in perception.slots}
        products: List[IdentifiedProduct] = []
        for ident in identification.identifications:
            shape = shapes.get(ident.shape_id)
            slot = slots.get(ident.shape_id)
            if shape is not None:
                box = shape.box
                product_type = _PRODUCT_TYPE_BY_KIND[shape.kind]
            elif slot is not None:
                box = slot.box
                anchor = shapes.get(slot.anchor_shape_id or "")
                product_type = "product_box" if anchor is not None and anchor.kind == ShapeKind.BOX else "product"
            else:
                continue
            if ident.occupancy == "empty":
                product_type = "empty_slot"
            products.append(
                IdentifiedProduct(
                    product_type=product_type,
                    product_model=ident.product,
                    brand=ident.brand,
                    confidence=ident.raw_confidence,
                    detection_box=box,
                    ocr_text=ident.text,
                )
            )
        return products, self._observed_regions(perception)

    @staticmethod
    def _observed_regions(perception: PerceptionResult) -> List[ShelfRegion]:
        """Create row and zone regions only from observed geometry."""
        rows: Dict[int, List[Slot]] = {}
        for slot in perception.slots:
            rows.setdefault(slot.row_index, []).append(slot)
        regions: List[ShelfRegion] = []
        for row_index, row_slots in sorted(rows.items()):
            boxes = [slot.box for slot in row_slots]
            regions.append(
                ShelfRegion(
                    shelf_id=f"{perception.image_id}:row{row_index}",
                    level=f"row{row_index}",
                    bbox=DetectionBox(
                        x1=min(box.x1 for box in boxes),
                        y1=min(box.y1 for box in boxes),
                        x2=max(box.x2 for box in boxes),
                        y2=max(box.y2 for box in boxes),
                        confidence=min(box.confidence for box in boxes),
                    ),
                    objects=boxes,
                )
            )
        regions.extend(
            ShelfRegion(shelf_id=zone.shape_id, level=zone.profile or "zone", bbox=zone.box, is_background=True)
            for zone in perception.zones
        )
        return regions

    def _assemble(
        self,
        perceptions: List[PerceptionResult],
        identifications: List[IdentificationResult],
        comparison: ComparisonResult,
        renders: List[RenderRecord],
        ctx: CycleContext,
    ) -> Dict[str, Any]:
        """Eight legacy keys + additive keys."""
        first = renders[0] if renders else None
        products, shelves = self._render_inputs(perceptions[0], identifications[0]) if perceptions else ([], [])
        sources = {str(p.detection_source) for p in perceptions}
        results = comparison.compliance_results
        return {
            "step3_compliance_results": results,
            "compliance_results": results,
            "overall_compliance_score": comparison.overall_compliance_score,
            "overall_compliant": bool(comparison.overall_compliant and results),
            "identified_products": products,
            "shelf_regions": shelves,
            "rendered_image": first.rendered_image if first else None,
            "overlay_path": first.overlay_path if first else None,
            # additive
            "detections": [p.model_dump() for p in perceptions],
            "identifications": [i.model_dump() for i in identifications],
            "position_results": comparison.position_results,
            "shelf_scores": comparison.shelf_scores,
            "coverage": comparison.coverage,
            "detected_products": comparison.detected_products,
            "definition_coverage": comparison.definition_coverage,
            "assessment_status": AssessmentStatus(comparison.assessment_status).value,
            "strict_compliance_score": comparison.strict_compliance_score,
            "evidence_quality": comparison.evidence_quality,
            "detection_source": (sources.pop() if len(sources) == 1 else ("mixed" if sources else None)),
            "ocr_available": bool(getattr(ctx.ocr, "available", False)),
            "resolved_backend": self.resolved_backend.as_string(),
            "renders": renders,
            "errors": list(ctx.errors) + list(comparison.errors),
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
                    _txt(draw, (x1 + 3, max(0, y1 - 14)), f"SHELF {sr.level}", fill=(0, 0, 0), bg=(255, 255, 0))
                except Exception as e:
                    self.logger.warning(f"Could not draw shelf {sr.level}: {e}")

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

                    _txt(draw, (x1, max(0, y1 - 20)), label, fill=color, bg=(0, 0, 0))
                except Exception as e:
                    self.logger.warning(f"Failed to draw product: {e}")

        if save_to:
            try:
                base.save(save_to)
                self.logger.info(f"Saved rendered image to {save_to}")
            except Exception as e:
                self.logger.error(f"Failed save image to {save_to}: {e}")

        return base
