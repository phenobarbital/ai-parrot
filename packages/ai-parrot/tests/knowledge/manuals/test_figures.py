"""FEAT-601 M6 — figures (AC13)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from parrot.knowledge.manuals import figures as fg


def _mk_image(page: int, index: int, sha_suffix: str) -> fg.PageImage:
    """Build a synthetic PageImage without touching the filesystem."""
    return fg.PageImage(
        page=page,
        index=index,
        path=Path(f"/tmp/fake-figures/fake-{sha_suffix}.png"),
        bbox=(0.0, 0.0, 10.0, 10.0),
        width=10,
        height=10,
        sha256=("a" * 63) + sha_suffix,
    )


def test_pair_figures_primary_by_label_secondary_by_distance(tmp_path) -> None:
    fig_labelled = fg.FigureCandidate(image=_mk_image(4, 0, "1"), label="1", caption_text="Drive belt routing")
    fig_near = fg.FigureCandidate(image=_mk_image(5, 0, "2"))
    fig_far = fg.FigureCandidate(image=_mk_image(5, 3, "3"))
    figures = [fig_labelled, fig_near, fig_far]

    steps = [
        SimpleNamespace(figure_refs=["Fig. 1"]),
        SimpleNamespace(figure_refs=["Fig. 9"]),  # cited but no figure carries this label
        SimpleNamespace(figure_refs=[]),
        SimpleNamespace(figure_refs=[]),
    ]
    page_of_step = {0: 3, 1: 3, 2: 5, 3: 5}

    links = fg.pair_figures(steps, figures, page_of_step=page_of_step)
    by_step: dict[int, list] = {}
    for step_index, link in links:
        by_step.setdefault(step_index, []).append(link)

    # label -> primary/1.0
    assert len(by_step[0]) == 1
    primary = by_step[0][0]
    assert primary.role == "primary"
    assert primary.confidence == 1.0
    assert primary.origin == "manual"

    # cited but missing label -> no link at all (never a nearest-page guess)
    assert 1 not in by_step
    assert fg.unpaired_references(steps, figures) == ["9"]

    # uncaptioned same-page -> secondary, scaled by within-page distance
    near_link = by_step[2][0]
    far_link = by_step[3][0]
    assert near_link.role == "secondary"
    assert far_link.role == "secondary"
    assert 0 < far_link.confidence < near_link.confidence <= 0.9


async def test_resolve_captioner_capability(tmp_path) -> None:
    class Vision:
        async def ask_to_image(self, prompt, image, **kw):
            return SimpleNamespace(output="a bracket")

    class ClaudeAgentClient:
        async def ask_to_image(self, *a, **k):
            raise NotImplementedError

    assert await fg.resolve_captioner(Vision()).caption(tmp_path / "f.png", context="") == "a bracket"
    with pytest.raises(fg.CaptioningUnavailable):
        fg.resolve_captioner(ClaudeAgentClient())
    with pytest.raises(fg.CaptioningUnavailable):
        fg.resolve_captioner(object())
    with pytest.raises(fg.CaptioningUnavailable):
        fg.resolve_captioner(None)


async def test_presign_rejects_non_http() -> None:
    class FakeFM:
        def __init__(self, url: str) -> None:
            self.url = url
            self.calls: list[tuple[str, int]] = []

        async def get_file_url(self, path: str, expiry: int = 3600) -> str:
            self.calls.append((path, expiry))
            return self.url

    file_fm = FakeFM("file:///manuals/x.png")
    with pytest.raises(fg.MediaUnavailable):
        await fg.presign(file_fm, "manuals/x.png", expiry=120)
    assert file_fm.calls == [("manuals/x.png", 120)]

    https_fm = FakeFM("https://cdn.example.com/manuals/x.png?e=1")
    url = await fg.presign(https_fm, "manuals/x.png")
    assert url == "https://cdn.example.com/manuals/x.png?e=1"


def _page_texts(pdf_path: Path) -> dict[int, str]:
    """Build a page-number -> raw-text mapping using plain pymupdf extraction.

    Deliberately independent from ``pymupdf4llm``'s markdown reformatting
    so the synthetic manual's literal ``"Fig. N ..."`` caption text is
    preserved verbatim for a deterministic assertion.
    """
    import pymupdf

    texts: dict[int, str] = {}
    document = pymupdf.open(str(pdf_path))
    try:
        for physical_page, page in enumerate(document, start=1):
            texts[physical_page] = page.get_text()
    finally:
        document.close()
    return texts


def _build_captioned_manual(path: Path) -> Path:
    """Build a two-figure manual sized to clear ``extract_page_images``'s area filter.

    Mirrors ``tests/knowledge/_support/pdfs.py::build_manual_pdf`` (same
    caption style, one figure per page) but at 240x240 points instead of
    120x80: on the library's default ~595x842pt page the smaller size is
    ~1.9% of the page area, below ``extract_page_images``'s default
    ``min_area_ratio=0.05`` — the shared ``manual_pdf`` fixture (TASK-3698)
    was never exercised against that default (TASK-3704), and produces zero
    extracted images. 240x240 (~11.5%) clears it so this test exercises the
    real ``extract_page_images`` path end-to-end instead of only the
    caption-pairing logic.
    """
    import pymupdf

    path.parent.mkdir(parents=True, exist_ok=True)
    document = pymupdf.open()
    try:
        pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 240, 240), 0)
        pixmap.clear_with(180)
        png_bytes = pixmap.tobytes("png")

        figure_one = document.new_page()
        rect_one = pymupdf.Rect(72, 100, 312, 340)
        figure_one.insert_image(rect_one, stream=png_bytes)
        figure_one.insert_text((72, rect_one.y1 + 16), "Fig. 1 Drive belt routing")

        figure_two = document.new_page()
        rect_two = pymupdf.Rect(72, 100, 312, 340)
        figure_two.insert_image(rect_two, stream=png_bytes)
        figure_two.insert_text((72, rect_two.y1 + 16), "Fig. 2 Cover installation")

        document.save(str(path))
    finally:
        document.close()
    return path


async def test_extract_and_upload_figures(fake_file_manager, tmp_path) -> None:
    pytest.importorskip("pymupdf")
    manual = _build_captioned_manual(tmp_path / "manuals" / "captioned.pdf")
    page_texts = _page_texts(manual)
    work_dir = tmp_path / "figure-images"

    figures = fg.extract_figures(manual, work_dir, page_texts=page_texts)
    assert len(figures) == 2
    assert sorted(fig.label for fig in figures if fig.label) == ["1", "2"]

    refs = await fg.upload_figures(figures, fake_file_manager, prefix="manuals/model-x")
    assert len(refs) == len(figures)
    media_ids = {ref.media_id for ref in refs}
    assert len(media_ids) == len(refs)  # media_id is unique per figure
    for ref in refs:
        assert ref.kind == "figure"
        assert ref.storage_key is not None
        assert not ref.storage_key.startswith(("http://", "https://"))
        assert ref.storage_key in fake_file_manager.objects
