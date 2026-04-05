"""Grid-based detection orchestrator.

Orchestrates parallel per-cell LLM detection calls for grid-decomposed
planogram compliance pipelines.

Flow:
    1. For each GridCell: crop image, downscale, build focused prompt
    2. Filter reference images to cell's expected products
    3. Execute all cell calls in parallel via asyncio.gather()
    4. Handle per-cell failures (log and skip — don't block others)
    5. Parse raw LLM dicts into IdentifiedProduct with cell-relative coords
    6. Pass to CellResultMerger for offset correction + IoU deduplication
"""
import asyncio
import logging
import time
from typing import Any, Dict, List, Optional, Tuple, Union
from pathlib import Path

from PIL import Image

from parrot_pipelines.planogram.grid.models import DetectionGridConfig, GridCell
from parrot_pipelines.planogram.grid.merger import CellResultMerger
from parrot.models.detections import DetectionBox, IdentifiedProduct


class GridDetector:
    """Orchestrates parallel per-cell LLM detection calls.

    Takes a list of GridCells, crops images, builds per-cell prompts with
    filtered hints and reference images, executes calls in parallel, and
    returns a merged, deduplicated product list.

    Args:
        llm: LLM client with an async detect_objects() method.
        reference_images: Dict mapping product keys to image paths/objects.
            Values may be a single image (str/Path/Image) or a list of images.
        logger: Logger instance for debug/error output.
    """

    def __init__(
        self,
        llm: Any,
        reference_images: Dict[str, Any],
        logger: logging.Logger,
    ) -> None:
        self.llm = llm
        self.reference_images = reference_images
        self.logger = logger
        self.merger = CellResultMerger()

    async def detect_cells(
        self,
        cells: List[GridCell],
        image: Image.Image,
        grid_config: DetectionGridConfig,
    ) -> List[IdentifiedProduct]:
        """Detect products in all cells in parallel.

        Args:
            cells: List of GridCell defining regions to detect independently.
            image: Full (or ROI-cropped) PIL image.
            grid_config: Grid configuration (uses max_image_size).

        Returns:
            Merged list of IdentifiedProduct with absolute image coordinates.
        """
        tasks = [
            self._detect_single_cell(cell, image, grid_config)
            for cell in cells
        ]

        self.logger.info(
            "Grid detection: %d cells dispatched in parallel.", len(cells)
        )

        results = await asyncio.gather(*tasks, return_exceptions=True)

        cell_results: List[Tuple[GridCell, List[IdentifiedProduct]]] = []
        for cell, result in zip(cells, results):
            if isinstance(result, Exception):
                self.logger.error(
                    "Cell '%s' detection failed: %s", cell.cell_id, result
                )
                continue
            cell_results.append((cell, result))

        self.logger.info(
            "Grid detection: %d/%d cells succeeded.", len(cell_results), len(cells)
        )

        return self.merger.merge(cell_results)

    async def _detect_single_cell(
        self,
        cell: GridCell,
        image: Image.Image,
        grid_config: DetectionGridConfig,
    ) -> List[IdentifiedProduct]:
        """Detect products in a single grid cell.

        Args:
            cell: The grid cell to detect products in.
            image: Full (or ROI-cropped) image.
            grid_config: Grid config (max_image_size).

        Returns:
            List of IdentifiedProduct with coordinates relative to cell origin.
        """
        t0 = time.monotonic()

        # 1. Crop image to cell bbox
        x1, y1, x2, y2 = cell.bbox
        cell_image = image.crop((x1, y1, x2, y2))

        # 2. Downscale to max_image_size
        cell_image = cell_image.copy()
        cell_image.thumbnail(
            [grid_config.max_image_size, grid_config.max_image_size]
        )

        # 3. Build per-cell prompt with only this cell's expected products
        hints_str = ", ".join(cell.expected_products) if cell.expected_products else "any products"
        prompt = self._build_cell_prompt(cell, hints_str)

        # 4. Filter reference images to only this cell's expected products
        refs = self._filter_references(cell.reference_image_keys)

        # 5. Call LLM
        raw = await self.llm.detect_objects(
            image=cell_image,
            prompt=prompt,
            reference_images=refs if refs else None,
            output_dir=None,
        )

        elapsed = time.monotonic() - t0
        self.logger.debug(
            "Cell '%s': %d raw detections in %.2fs.",
            cell.cell_id,
            len(raw),
            elapsed,
        )

        # 6. Parse raw dicts into IdentifiedProduct (cell-relative coords)
        return self._parse_detections(raw, cell_image.size)

    def _build_cell_prompt(self, cell: GridCell, hints_str: str) -> str:
        """Build a per-cell detection prompt.

        Args:
            cell: The grid cell being detected.
            hints_str: Comma-separated product name hints for this cell.

        Returns:
            Prompt string for the LLM.
        """
        level_note = f" (shelf level: {cell.level})" if cell.level else ""
        return (
            f"Detect all retail products, empty slots, and shelf regions in this image{level_note}.\n"
            "Use the provided reference images to identify specific products.\n\n"
            "IMPORTANT:\n"
            "- If you see a cardboard box containing a product image/name, label it as \"[Product Name] box\".\n"
            "- If you see the bare product itself (e.g. a loose printer), label it as \"[Product Name]\".\n"
            f"- Prefer the following product names if they match: {hints_str}\n"
            "- Report ALL objects you see, even if they are not in the expected list.\n"
            "- If an item is NOT in the list, provide a descriptive name (e.g. \"Ink Bottle\", \"Printer\") "
            "rather than just \"unknown\".\n"
            "- Do not output \"unknown\" unless strictly necessary.\n\n"
            "Output a JSON array where each entry contains:\n"
            '- "label": The item label.\n'
            '- "box_2d": [ymin, xmin, ymax, xmax] normalized 0-1000.\n'
            '- "confidence": 0.0-1.0.\n'
            '- "type": "product", "product_box", "promotional_graphic", "fact_tag", "shelf", or "gap".\n'
        )

    def _filter_references(
        self,
        reference_image_keys: List[str],
    ) -> List[Any]:
        """Filter reference images to only those relevant for this cell.

        Args:
            reference_image_keys: Product keys to include.

        Returns:
            Flat list of image references (str, Path, or PIL.Image objects).
            If no keys specified, returns all reference images.
        """
        if not reference_image_keys:
            # No specific keys — fall back to all references
            return self._flatten_references(list(self.reference_images.values()))

        refs: List[Any] = []
        for key in reference_image_keys:
            value = self.reference_images.get(key)
            if value is None:
                continue
            # Handle both single image and list of images per product
            if isinstance(value, list):
                refs.extend(value)
            else:
                refs.append(value)
        return refs

    def _flatten_references(self, values: List[Any]) -> List[Any]:
        """Flatten a mixed list of single images and image lists.

        Args:
            values: List items that may themselves be lists or single images.

        Returns:
            Flat list of individual image references.
        """
        flat: List[Any] = []
        for v in values:
            if isinstance(v, list):
                flat.extend(v)
            else:
                flat.append(v)
        return flat

    def _parse_detections(
        self,
        raw: List[Dict[str, Any]],
        cell_size: Tuple[int, int],
    ) -> List[IdentifiedProduct]:
        """Parse raw LLM detection dicts into IdentifiedProduct objects.

        LLM returns box_2d as [ymin, xmin, ymax, xmax] normalized 0-1000.
        We convert to pixel coordinates relative to the cell image.

        Note: The existing product_on_shelves.py treats box_2d values directly
        as pixel coordinates (no normalization multiplication), so we follow
        the same pattern for consistency.

        Args:
            raw: List of dicts from LLM with keys: label, box_2d, confidence, type.
            cell_size: Cell image (width, height) — used for bounds clamping only.

        Returns:
            List of IdentifiedProduct with cell-relative detection_box coords.
        """
        products: List[IdentifiedProduct] = []
        cell_w, cell_h = cell_size

        for item in raw:
            box = item.get("box_2d")
            if not box:
                continue

            # LLM returns [ymin, xmin, ymax, xmax] normalized 0-1000
            # The existing pipeline treats these as direct pixel values
            try:
                coord_a, coord_b, coord_c, coord_d = box
            except (TypeError, ValueError):
                self.logger.warning("Skipping malformed box_2d: %s", box)
                continue

            x1, y1, x2, y2 = int(coord_b), int(coord_a), int(coord_d), int(coord_c)

            label = item.get("label", "unknown")
            conf = item.get("confidence", 0.0)
            ptype = item.get("type", "product")

            if "shelf" in label.lower():
                # Skip shelf detections in per-cell output — handled externally
                continue

            if "box" in label.lower() or "carton" in label.lower():
                ptype = "product_box"

            products.append(
                IdentifiedProduct(
                    detection_box=DetectionBox(
                        x1=x1, y1=y1, x2=x2, y2=y2,
                        confidence=conf,
                        class_id=0,
                        class_name="llm_detected",
                        area=abs(x2 - x1) * abs(y2 - y1),
                    ),
                    product_model=label,
                    confidence=conf,
                    product_type=ptype,
                )
            )

        return products
