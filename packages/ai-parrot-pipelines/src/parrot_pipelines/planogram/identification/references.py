"""Per-run reference-image bank and expectation-free selection (FEAT-612, spec §2 Stage 2 / Module 3)."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, List, Mapping, Sequence, Tuple

import cv2
import numpy as np
from PIL import Image

from parrot_pipelines.planogram.contracts import CycleContext, OcrReading, ReferenceImage
from parrot_pipelines.planogram.identification.vision import encode_png
from parrot_pipelines.planogram.layout import ReferencePolicy

logger = logging.getLogger(__name__)

LABEL_FORMAT: str = "ref-{:04d}"


def reference_label(index: int) -> str:
    """Return an opaque, stable label for a one-based flattened index."""
    return LABEL_FORMAT.format(index)


def flatten_references(reference_images: Mapping[str, Any]) -> List[Tuple[str, Any]]:
    """Flatten catalogue entries in sorted-key and stable-list order."""
    flattened: List[Tuple[str, Any]] = []
    for catalog_key in sorted(reference_images):
        source = reference_images[catalog_key]
        if isinstance(source, (list, tuple)):
            flattened.extend((catalog_key, item) for item in source)
        else:
            flattened.append((catalog_key, source))
    return flattened


def encode_reference_bytes(data: bytes) -> bytes:
    """Decode encoded image bytes and re-encode them as PNG."""
    decoded = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if decoded is None:
        raise ValueError("not a decodable image")
    return encode_png(decoded)


async def load_reference_bank(reference_images: Mapping[str, Any], ctx: CycleContext) -> List[ReferenceImage]:
    """Load and encode all valid references once, preserving stable flattened labels."""
    policy = ctx.layout.references if ctx.layout is not None else ReferencePolicy()
    bank: List[ReferenceImage] = []
    for index, (catalog_key, source) in enumerate(flatten_references(reference_images), start=1):
        try:
            if isinstance(source, (str, Path)):
                data = await asyncio.to_thread(Path(source).read_bytes)
                png = await ctx.executor.run(encode_reference_bytes, data)
            elif isinstance(source, Image.Image):
                bgr = np.asarray(source.convert("RGB"))[:, :, ::-1].copy()
                png = await ctx.executor.run(encode_png, bgr)
            else:
                raise TypeError(f"unsupported reference type: {type(source).__name__}")
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - one unreadable reference must not abort the bank
            message = f"references: unreadable {catalog_key}[{index}]: {exc}"
            logger.warning(message)
            ctx.errors.append(message)
            continue
        bank.append(
            ReferenceImage(
                label=reference_label(index),
                image=png,
                catalog_key=catalog_key,
                brand=policy.brand_by_reference.get(catalog_key),
            )
        )
    return bank


def select_references(
    bank: Sequence[ReferenceImage], readings: Mapping[str, OcrReading], policy: ReferencePolicy
) -> Tuple[List[ReferenceImage], List[str]]:
    """Select a stable capped subset using only current-call OCR readings."""
    if not policy.enabled:
        return [], ["references: disabled"]
    if not bank:
        return [], ["references: none configured"]

    diagnostics: List[str] = []
    candidates = list(bank)
    if policy.selection == "by_brand":
        texts = [reading.text.casefold() for reading in readings.values()]
        observed = {
            reference.brand
            for reference in bank
            if reference.brand and any(reference.brand.casefold() in text for text in texts)
        }
        if observed:
            candidates = [reference for reference in bank if reference.brand in observed]
        else:
            diagnostics.append("references: by_brand found no observed brand; fell back to all")

    selected = candidates[: policy.max_per_call]
    selected_labels = ", ".join(reference.label for reference in selected)
    diagnostics.append(f"references: selected {selected_labels}")
    omitted = candidates[policy.max_per_call :]
    if omitted:
        omitted_labels = ", ".join(reference.label for reference in omitted)
        diagnostics.append(f"references: omitted {omitted_labels} (cap {policy.max_per_call})")
    return selected, diagnostics
