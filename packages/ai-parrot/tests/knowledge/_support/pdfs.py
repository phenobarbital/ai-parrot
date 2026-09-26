"""Synthetic manual PDFs built with pymupdf at test time (FEAT-601 §4)."""

from __future__ import annotations

from pathlib import Path

STEPS_REV_A: tuple[str, ...] = (
    "1. Remove the four M6 bolts from the base plate.",
    "2. Lift the cover and set it aside.",
    "3. Insert the drive belt around the pulley. See Fig. 1.",
    "4. Torque the tensioner bolt to 12 Nm.",
    "5. Reinstall the cover. See Fig. 2.",
)


def _png(width: int = 120, height: int = 80) -> bytes:
    """Return solid-colour PNG bytes generated with ``pymupdf.Pixmap``."""
    import pymupdf

    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, width, height), 0)
    pixmap.clear_with(180)
    return pixmap.tobytes("png")


def build_manual_pdf(path: Path, *, steps: tuple[str, ...] = STEPS_REV_A) -> Path:
    """Build a six-page manual with procedure, figures, captions, and warning."""
    import pymupdf

    path.parent.mkdir(parents=True, exist_ok=True)
    document = pymupdf.open()
    try:
        cover = document.new_page()
        cover.insert_text((72, 72), "MODEL X ASSEMBLY MANUAL")
        parts = document.new_page()
        parts.insert_text((72, 72), "PARTS TABLE\nBase plate\nCover\nDrive belt\nTensioner bolt")
        procedure = document.new_page()
        procedure.insert_text((72, 72), "ASSEMBLY PROCEDURE\n" + "\n".join(steps))
        png_bytes = _png()
        figure_one = document.new_page()
        rect_one = pymupdf.Rect(72, 100, 192, 180)
        figure_one.insert_image(rect_one, stream=png_bytes)
        figure_one.insert_text((72, rect_one.y1 + 16), "Fig. 1 Drive belt routing")
        figure_two = document.new_page()
        rect_two = pymupdf.Rect(72, 100, 192, 180)
        figure_two.insert_image(rect_two, stream=png_bytes)
        figure_two.insert_text((72, rect_two.y1 + 16), "Fig. 2 Cover installation")
        warning = document.new_page()
        warning.draw_rect(pymupdf.Rect(60, 60, 400, 140), color=(0.8, 0.2, 0.1), fill=(1, 0.9, 0.8))
        warning.insert_text((72, 90), "WARNING: Disconnect power before assembly.")
        document.save(str(path))
    finally:
        document.close()
    return path


def build_manual_pdf_rev_b(path: Path) -> Path:
    """Build revision B with a renumbered third step, revised fourth step, and no fifth step."""
    steps = (
        STEPS_REV_A[0],
        STEPS_REV_A[1],
        "3. Route the drive belt around the pulley. See Fig. 1.",
        "4. Tighten the tensioner bolt to 12 Nm using a torque wrench.",
    )
    return build_manual_pdf(path, steps=steps)


def build_image_only_pdf(path: Path) -> Path:
    """Build a one-page scanned-style PDF with no extractable text."""
    import pymupdf

    path.parent.mkdir(parents=True, exist_ok=True)
    document = pymupdf.open()
    try:
        page = document.new_page()
        page.draw_rect(pymupdf.Rect(72, 72, 300, 300), fill=(0.2, 0.2, 0.2))
        document.save(str(path))
    finally:
        document.close()
    return path
