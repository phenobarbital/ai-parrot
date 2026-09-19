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
)
from .perception.executor import CpuExecutor
from .perception.membership import assign_membership, usable_shapes
from .perception.ocr import OcrReader
from .identification.detector import GENERIC_DETECTION_PROMPT, llm_detect_shapes
from .identification.vision import VisionAdapter
from .comparison.definition import load_slots_definition, validate_bindings
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
            **kwargs: Forwarded to the client constructor.

        Raises:
            ValueError: Unknown planogram type, or a configuration the type rejects.
            TypeError: The type implements neither contract.
        """
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
        self._definition: Any = None
        self._bindings: List[Any] = []
        self.planogram_config = planogram_config

        # Endcap geometry defaults
        geometry = planogram_config.endcap_geometry
        self.left_margin_ratio = geometry.left_margin_ratio
        self.right_margin_ratio = geometry.right_margin_ratio

        self.reference_images = planogram_config.reference_images or {}

        # Resolve composable type handler (validate_contract() runs in AbstractPlanogramType.__init__)
        ptype = getattr(planogram_config, "planogram_type", None) or "product_on_shelves"
        composable_cls = self._PLANOGRAM_TYPES.get(ptype)
        if composable_cls is None:
            available = ", ".join(sorted(self._PLANOGRAM_TYPES.keys()))
            raise ValueError(f"Unknown planogram_type '{ptype}'. " f"Available types: {available}")
        self._type_handler = composable_cls(pipeline=self, config=planogram_config)

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
            shelf_scores, coverage, definition_coverage, assessment_status, strict_compliance_score,
            evidence_quality, detection_source, ocr_available, resolved_backend, renders, errors).

        Raises:
            ValueError: ``image_id`` is a sequence whose length differs from ``image``.
        """
        inputs, single_sfx = self._normalize_inputs(image, image_id)
        out_dir = Path(output_dir) if output_dir else None
        self.logger.info("Planogram cycle: %d image(s), type=%s", len(inputs), type(self._type_handler).__name__)
        ctx = await self._build_context(out_dir)
        images: Dict[str, Image.Image] = {}
        ids: List[str] = []
        perceptions: List[PerceptionResult] = []
        identifications: List[IdentificationResult] = []
        try:
            for img_id, source in inputs:
                # A single legacy call without image_id keeps today's unsuffixed debug filename;
                # migrated types (own perceive hook) always receive the normalised id.
                legacy_unsuffixed = single_sfx == "" and not self._type_handler._implements("perceive")
                hook_id = "" if legacy_unsuffixed else img_id
                try:
                    img, perception = await self._perceive_one(source, hook_id, ctx)
                    identification = await self._type_handler.identify(img, perception, ctx)
                except Exception as exc:  # noqa: BLE001 - isolate one failed photo
                    self.logger.error("Image %s failed: %s", img_id, exc)
                    ctx.errors.append(f"{img_id}: {exc}")
                    continue
                images[img_id] = img
                ids.append(img_id)
                perceptions.append(perception)
                identifications.append(identification)
            comparison = await self._compare(perceptions, identifications, ctx)
            renders = await self._render_all(ids, images, perceptions, identifications, out_dir, single_sfx)
        finally:
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

    async def _build_context(self, output_dir: Optional[Path]) -> CycleContext:
        """Create the per-run shared services."""
        handler = self._type_handler
        if handler.requires_slots_definition and self._definition is None:
            source = self.planogram_config.slots_definition
            self._definition = await asyncio.to_thread(load_slots_definition, source)
            self._bindings = validate_bindings(self._definition, self.planogram_config.planogram_config)
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
            ocr=OcrReader(),
            definition=self._definition,
            bindings=list(self._bindings),
            credit_policy=CreditPolicy.default(),
            evidence_weights=EvidenceWeights(),
            output_dir=output_dir,
            errors=[],
        )

    async def _perceive_one(
        self, source: ImageInput, image_id: str, ctx: CycleContext
    ) -> Tuple[Image.Image, PerceptionResult]:
        """Load one image (untouched unless the type wants enhancement), perceive, apply the fallback."""
        handler = self._type_handler
        img = await asyncio.to_thread(self.open_image, source, enhance=handler.uses_enhanced_image)
        perception = await handler.perceive(img, image_id, ctx)
        perception = await self._fallback_if_needed(img, perception, ctx)
        return img, perception

    async def _fallback_if_needed(
        self, img: Image.Image, perception: PerceptionResult, ctx: CycleContext
    ) -> PerceptionResult:
        """LLM-detector fallback when usable on-fixture shapes are under the type threshold.

        Off-fixture and uncertain shapes never count toward the threshold. Fallback perceptions carry no
        slots: the type treats every on-fixture shape as its own slot. A failed fallback keeps the original
        shapes and records an error — never a silent empty result.
        """
        handler = self._type_handler
        threshold = handler.min_usable_shapes
        if threshold <= 0 or perception.legacy is not None:
            return perception
        if len(usable_shapes(perception.shapes)) >= threshold:
            return perception
        self.logger.warning("Image %s: usable shapes under %d — LLM detector fallback", perception.image_id, threshold)
        bgr = np.ascontiguousarray(np.asarray(img.convert("RGB"))[:, :, ::-1])
        prompt = handler.fallback_detection_prompt() or GENERIC_DETECTION_PROMPT
        shapes = await llm_detect_shapes(bgr, perception.image_id, ctx, prompt=prompt)
        if not shapes:
            message = f"{perception.image_id}: LLM detector fallback produced no shapes; perception kept as is"
            ctx.errors.append(message)
            return perception.model_copy(update={"errors": [*perception.errors, message]})
        zones = [s for s in shapes if s.kind == ShapeKind.ZONE] or list(perception.zones)
        others = [s for s in shapes if s.kind != ShapeKind.ZONE]
        others = assign_membership(others, zones, perception.image_size)
        return perception.model_copy(
            update={"shapes": others, "zones": zones, "slots": [], "detection_source": ObservationSource.LLM.value}
        )

    async def _compare(
        self, perceptions: List[PerceptionResult], identifications: List[IdentificationResult], ctx: CycleContext
    ) -> ComparisonResult:
        """Run the compare hook, or build the all-failed inconclusive result."""
        if perceptions:
            return await self._type_handler.compare(perceptions, identifications, ctx)
        return ComparisonResult(
            compliance_results=[],
            overall_compliance_score=0.0,
            strict_compliance_score=None,
            overall_compliant=False,
            coverage=None,
            definition_coverage=None,
            evidence_quality=None,
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
        """(identified_products, shelf_regions) of ONE image for rendering and the legacy result keys."""
        if perception.legacy is not None:
            return list(perception.legacy.identified_products), list(perception.legacy.shelf_regions)
        boxes: Dict[str, DetectionBox] = {s.shape_id: s.box for s in perception.shapes}
        boxes.update({s.slot_id: s.box for s in perception.slots})
        boxes.update({s.shape_id: s.box for s in identification.added})
        products: List[IdentifiedProduct] = []
        for ident in identification.identifications:
            box = boxes.get(ident.shape_id)
            if box is None:
                continue
            products.append(
                IdentifiedProduct(
                    product_type="product",
                    product_model=ident.product,
                    brand=ident.brand,
                    confidence=ident.raw_confidence,
                    detection_box=box,
                    ocr_text=ident.text,
                )
            )
        return products, []

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
