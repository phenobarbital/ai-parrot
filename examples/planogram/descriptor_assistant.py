"""Propose per-position descriptors from a POG PDF, for human review (FEAT-574).

POG PDF only: no catalog, SKU or price lookup. ``price`` is never proposed.
Usage: python examples/planogram/descriptor_assistant.py --pdf POG.pdf --definition slots.json \
           --backend anthropic:claude-sonnet-5
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from pydantic import BaseModel, Field

from parrot_pipelines.planogram.comparison.definition import (
    SlotsDefinition,
    definition_coverage,
    load_slots_definition,
)

logger = logging.getLogger("descriptor_assistant")
PROMPT_VERSION = "descriptors-v1"
STAGE = "descriptors"
_RENDER_DPI = 150  # set from --dpi by the CLI


class DescriptorProposal(BaseModel):
    """Proposed descriptors for one facing. There is deliberately NO price field."""

    facing_id: str
    display_name: Optional[str] = None
    family: Optional[str] = None
    xl: Optional[bool] = None
    colors: List[str] = Field(default_factory=list)
    pack: Optional[str] = None
    identifiers: List[str] = Field(default_factory=list)
    aliases: List[str] = Field(default_factory=list)
    page: int = 0
    evidence: str = ""


class PageProposals(BaseModel):
    """Structured output of one page call."""

    proposals: List[DescriptorProposal] = Field(default_factory=list)


def _strip_price(payload: Any) -> Any:
    """Recursively drop every ``price`` key from a model payload without mutating the caller's object.

    Args:
        payload: A dict / list / scalar.

    Returns:
        A copy without any ``price`` key (case-insensitive) at any depth.
    """
    if isinstance(payload, dict):
        dropped = [k for k in payload if isinstance(k, str) and k.casefold() == "price"]
        if dropped:
            logger.info("dropping price field(s) from a model answer: prices are never proposed")
        return {k: _strip_price(v) for k, v in payload.items() if k not in dropped}
    if isinstance(payload, list):
        return [_strip_price(item) for item in payload]
    return payload


def render_pdf_pages(pdf: Path, *, dpi: Optional[int] = None) -> List[bytes]:
    """Render every page of ``pdf`` to PNG bytes (blocking — call via asyncio.to_thread).

    Args:
        pdf: The POG PDF.
        dpi: Rendering resolution (defaults to the CLI's --dpi, 150).

    Returns:
        PNG bytes, one entry per page.

    Raises:
        RuntimeError: When PyMuPDF is not installed (message names `uv pip install pymupdf`).
        FileNotFoundError: When ``pdf`` does not exist.
    """
    if not Path(pdf).is_file():
        raise FileNotFoundError(str(pdf))
    try:
        import fitz  # PyMuPDF — optional, not a dependency of ai-parrot-pipelines
    except ImportError as exc:
        raise RuntimeError("PyMuPDF is required to render the POG PDF: run `uv pip install pymupdf`") from exc
    pages: List[bytes] = []
    with fitz.open(str(pdf)) as doc:
        for index in range(doc.page_count):
            page = doc.load_page(index)
            pages.append(page.get_pixmap(dpi=dpi or _RENDER_DPI).tobytes("png"))
    return pages


def _filled(proposal: DescriptorProposal) -> int:
    """Number of non-empty descriptor fields of a proposal."""
    fields = ("display_name", "family", "xl", "colors", "pack", "identifiers", "aliases")
    return sum(1 for name in fields if getattr(proposal, name) not in (None, "", []))


async def propose_descriptors(pdf: Path, definition: SlotsDefinition, adapter: Any) -> Dict[str, DescriptorProposal]:
    """facing_id → proposal (descriptors without price, page number, evidence text).

    Args:
        pdf: The POG PDF.
        definition: The slots definition to describe.
        adapter: A ``VisionAdapter``-like object exposing ``ask``.

    Returns:
        Proposals keyed by facing id.
    """
    pages = await asyncio.to_thread(render_pdf_pages, pdf)
    known = {f.facing_id: f for shelf in definition.shelves for f in shelf.facings}
    proposals: Dict[str, DescriptorProposal] = {}
    for number, png in enumerate(pages, start=1):
        try:
            answer = await adapter.ask(
                _build_prompt(definition, number), [png], PageProposals, stage=STAGE, prompt_version=PROMPT_VERSION
            )
        except Exception as exc:  # noqa: BLE001 - one failed page never aborts the run
            logger.warning("page %d failed: %s", number, exc)
            continue
        for raw in _strip_price(answer.model_dump())["proposals"]:
            proposal = DescriptorProposal.model_validate({**raw, "page": number})
            if proposal.facing_id not in known:
                logger.warning("page %d: unknown facing_id %s dropped", number, proposal.facing_id)
                continue
            current = proposals.get(proposal.facing_id)
            if current is None or _filled(proposal) > _filled(current):
                proposals[proposal.facing_id] = proposal
    return proposals


def _build_prompt(definition: SlotsDefinition, page: int) -> str:
    """Prompt listing facing_id + product + brand of the positions to describe (undescribed ones only)."""
    _fraction, undescribed = definition_coverage(definition)
    wanted = set(undescribed)
    positions = [
        {"facing_id": f.facing_id, "product": f.product, "brand": f.brand}
        for f in definition.all_facings()
        if f.facing_id in wanted
    ]
    return (
        f"This is page {page} of a planogram (POG) document. For each listed position, propose the product "
        "descriptors printed on THIS page: display_name, family, xl (true/false), colors, pack, identifiers "
        "(model codes printed on the page) and aliases.\n"
        "- Use ONLY what is printed on this page and quote it in evidence.\n"
        "- Leave a field null (or an empty list) when the page does not show it — do not guess.\n"
        "- NEVER output a price.\n"
        "- Only report positions from the list, using their facing_id.\n\n"
        f"POSITIONS: {json.dumps(positions, ensure_ascii=False)}"
    )


def write_proposal(proposals: Dict[str, DescriptorProposal], definition_path: Path) -> Path:
    """Write ``<stem>.descriptors.proposal.json`` next to the definition. Never the definition itself.

    Args:
        proposals: Proposals keyed by facing id.
        definition_path: The slots definition file.

    Returns:
        The proposal file path.

    Raises:
        ValueError: When the output path would be the definition file.
    """
    out = definition_path.with_name(f"{definition_path.stem}.descriptors.proposal.json")
    if out.resolve() == definition_path.resolve():
        raise ValueError("refusing to overwrite the slots definition")
    payload = {fid: _strip_price(p.model_dump()) for fid, p in sorted(proposals.items())}
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


async def _run(args: argparse.Namespace) -> int:
    """Build the adapter from --backend and write the proposal file."""
    from parrot.clients.factory import LLMFactory
    from parrot_pipelines.planogram.backend import UNSET, resolve_backend
    from parrot_pipelines.planogram.identification.vision import VisionAdapter

    definition = await asyncio.to_thread(load_slots_definition, args.definition)
    backend = resolve_backend(args.backend, UNSET, UNSET, None)
    client = LLMFactory.create(args.backend)
    adapter = VisionAdapter(client, backend, semaphore=asyncio.Semaphore(2), cache_dir=args.cache_dir)
    global _RENDER_DPI
    _RENDER_DPI = args.dpi
    if hasattr(client, "__aenter__"):
        async with client:
            proposals = await propose_descriptors(args.pdf, definition, adapter)
    else:
        proposals = await propose_descriptors(args.pdf, definition, adapter)
    out = write_proposal(proposals, args.definition)
    logger.info("%d proposal(s) for %d position(s)", len(proposals), len(definition.all_facings()))
    sys.stdout.write(f"{out}\n")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--definition", type=Path, required=True)
    parser.add_argument("--backend", required=True, help='"provider:model"')
    parser.add_argument("--dpi", type=int, default=150)
    parser.add_argument("--cache-dir", type=Path, default=None)
    logging.basicConfig(level=logging.INFO)
    return asyncio.run(_run(parser.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
