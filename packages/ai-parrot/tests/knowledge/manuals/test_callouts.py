"""FEAT-601 M6 Q8 — callouts (AC21)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from parrot.knowledge.manuals import figures as fg
from parrot.knowledge.manuals.models import Callout, CalloutMap, PartRef


def _mk_image(sha_suffix: str) -> fg.PageImage:
    """Build a synthetic PageImage without touching the filesystem."""
    return fg.PageImage(
        page=6,
        index=0,
        path=Path(f"/tmp/fake-figures/fake-{sha_suffix}.png"),
        bbox=(0.0, 0.0, 10.0, 10.0),
        width=10,
        height=10,
        sha256=("b" * 63) + sha_suffix,
    )


class FakeMapper:
    def __init__(self, result: CalloutMap) -> None:
        self.calls = 0
        self.result = result

    async def map_callouts(self, image, *, context):
        self.calls += 1
        return self.result


def _make_parts() -> list[PartRef]:
    return [
        PartRef(part_id="part-7", part_number="P-7", name={"value": "washer"}),
        PartRef(part_id="part-2", part_number=None, name={"value": "hex bolt m8"}),
    ]


async def test_map_callouts_structured_output(monkeypatch) -> None:
    monkeypatch.delenv(fg.CALLOUTS_ENABLED_ENV, raising=False)

    figure = fg.FigureCandidate(image=_mk_image("1"), label="2", caption_text="items 1, 2, 7")
    steps = [SimpleNamespace(figure_refs=[], callout_mentions=[])]
    parts = _make_parts()

    result = CalloutMap(
        callouts=[
            Callout(label="7", description="washer", part_number="P-7"),
            Callout(label="2", description="hex bolt m8", part_number=None),
            Callout(label="9", description="unknown bracket", part_number=None),
        ]
    )
    mapper = FakeMapper(result)

    # env unset => disabled by default, no mapper call
    links, unresolved = await fg.map_callouts([figure], mapper, parts=parts, steps=steps)
    assert links == []
    assert unresolved == []
    assert mapper.calls == 0

    # explicit enabled=False => still disabled, no mapper call
    links, unresolved = await fg.map_callouts([figure], mapper, parts=parts, steps=steps, enabled=False)
    assert links == []
    assert unresolved == []
    assert mapper.calls == 0

    # explicit enabled=True => exactly one structured call, deterministic resolution
    links, unresolved = await fg.map_callouts([figure], mapper, parts=parts, steps=steps, enabled=True)
    assert mapper.calls == 1
    assert len(links) == 2
    by_callout = {link.callout: link for link in links}
    assert by_callout["7"].part_id == "part-7"
    assert by_callout["7"].confidence == 1.0
    assert by_callout["7"].origin == "vision"
    assert by_callout["2"].part_id == "part-2"
    assert by_callout["2"].confidence >= 0.85
    assert len(unresolved) == 1
    assert unresolved[0].label == "9"


def test_is_exploded_view_counts_caption_and_step_mentions() -> None:
    figure = fg.FigureCandidate(image=_mk_image("2"), label="3", caption_text="item 1")
    # caption alone has only 1 distinct callout number -> not exploded
    assert fg.is_exploded_view(figure, []) is False

    steps = [SimpleNamespace(figure_refs=["Fig. 3"], callout_mentions=["4"])]
    # caption "1" + step mention "4" citing this figure's label -> 2 distinct -> exploded
    assert fg.is_exploded_view(figure, steps) is True

    unrelated_steps = [SimpleNamespace(figure_refs=["Fig. 9"], callout_mentions=["4", "5"])]
    # step mentions don't count unless the step actually cites this figure's label
    assert fg.is_exploded_view(figure, unrelated_steps) is False
