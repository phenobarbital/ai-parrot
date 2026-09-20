"""Offline tests for examples/planogram/descriptor_assistant.py (loaded by file path)."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from parrot_pipelines.planogram.comparison import load_slots_definition

_SCRIPT = Path(__file__).resolve().parents[4] / "examples" / "planogram" / "descriptor_assistant.py"


@pytest.fixture(scope="module")
def assistant():
    """The script loaded as a module (no PyMuPDF, no provider SDK needed)."""
    spec = importlib.util.spec_from_file_location("descriptor_assistant", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # Pydantic resolves postponed annotations through sys.modules
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.modules.pop(spec.name, None)


class FakeAdapter:
    """Returns one canned PageProposals per ask() call; records calls."""

    def __init__(self, answers):
        self.answers, self.calls = list(answers), []

    async def ask(self, prompt, images, schema, *, stage, prompt_version, system_prompt=None):
        self.calls.append({"prompt": prompt, "stage": stage, "images": images})
        item = self.answers.pop(0)
        if isinstance(item, Exception):
            raise item
        return schema.model_validate(item)


def _definition_dict() -> dict:
    return {
        "version": "1",
        "shelves": [
            {
                "shelf_id": "shelf-1",
                "shelf_number": 1,
                "facings": [
                    {"facing_id": "shelf-1:1", "shelf_id": "shelf-1", "slot": 1, "product": "SKU-A", "brand": "Epson"},
                    {
                        "facing_id": "shelf-1:2",
                        "shelf_id": "shelf-1",
                        "slot": 2,
                        "product": "SKU-B",
                        "descriptors": {"display_name": "Ink B"},
                    },
                ],
            }
        ],
    }


@pytest.fixture
def definition():
    return load_slots_definition(_definition_dict())


@pytest.fixture
def two_pages(assistant, monkeypatch):
    monkeypatch.setattr(assistant, "render_pdf_pages", lambda pdf, dpi=150: [b"png1", b"png2"])


def test_script_is_not_gitignored():
    assert _SCRIPT.is_file()


def test_strip_price_is_recursive_and_non_mutating(assistant):
    payload = {"a": 1, "Price": "9", "nested": [{"price": 1, "b": {"PRICE": 2, "c": 3}}]}
    snapshot = json.dumps(payload, sort_keys=True)
    stripped = assistant._strip_price(payload)
    assert stripped == {"a": 1, "nested": [{"b": {"c": 3}}]}
    assert json.dumps(payload, sort_keys=True) == snapshot


def test_descriptor_proposal_has_no_price_field(assistant):
    assert "price" not in assistant.DescriptorProposal.model_fields


@pytest.mark.asyncio
async def test_never_proposes_price(assistant, definition, two_pages, tmp_path):
    """Fake model returns a price at two depths; the written JSON has no 'price' anywhere."""
    adapter = FakeAdapter(
        [
            {
                "price": "1.00",
                "proposals": [{"facing_id": "shelf-1:1", "price": "19.99", "display_name": "Epson 802", "page": 99}],
            },
            {"proposals": []},
        ]
    )
    proposals = await assistant.propose_descriptors(tmp_path / "pog.pdf", definition, adapter)
    assert proposals["shelf-1:1"].page == 1
    assert adapter.calls[0]["stage"] == assistant.STAGE
    assert "NEVER output a price" in adapter.calls[0]["prompt"]
    # only the undescribed facing is listed in the prompt
    assert "shelf-1:1" in adapter.calls[0]["prompt"] and "shelf-1:2" not in adapter.calls[0]["prompt"]
    definition_path = tmp_path / "slots.json"
    definition_path.write_text(json.dumps(_definition_dict()), encoding="utf-8")
    out = assistant.write_proposal(proposals, definition_path)
    assert "price" not in out.read_text(encoding="utf-8").lower()


@pytest.mark.asyncio
async def test_unknown_facing_ids_dropped_and_failed_page_isolated(assistant, definition, two_pages, caplog):
    adapter = FakeAdapter(
        [
            RuntimeError("provider down"),
            {
                "proposals": [
                    {"facing_id": "ghost", "display_name": "X"},
                    {"facing_id": "shelf-1:1", "display_name": "Epson 802"},
                    {"facing_id": "shelf-1:1", "display_name": "Epson 802", "family": "802", "colors": ["black"]},
                    {"facing_id": "shelf-1:1", "display_name": "Other"},
                ]
            },
        ]
    )
    with caplog.at_level("WARNING", logger="descriptor_assistant"):
        proposals = await assistant.propose_descriptors(Path("pog.pdf"), definition, adapter)
    assert set(proposals) == {"shelf-1:1"}
    assert proposals["shelf-1:1"].family == "802" and proposals["shelf-1:1"].page == 2
    assert len(adapter.calls) == 2
    messages = " ".join(r.getMessage() for r in caplog.records)
    assert "page 1 failed" in messages and "ghost" in messages


def test_write_proposal_never_touches_definition(assistant, tmp_path):
    definition_path = tmp_path / "slots.json"
    definition_path.write_text(json.dumps(_definition_dict()), encoding="utf-8")
    before = definition_path.read_bytes()
    proposal = assistant.DescriptorProposal(facing_id="shelf-1:1", display_name="Epson 802")
    out = assistant.write_proposal({"shelf-1:1": proposal}, definition_path)
    assert out.name == "slots.descriptors.proposal.json" and out.parent == tmp_path
    assert definition_path.read_bytes() == before
    assert json.loads(out.read_text(encoding="utf-8"))["shelf-1:1"]["display_name"] == "Epson 802"


def test_render_pdf_pages_missing_file(assistant, tmp_path):
    with pytest.raises(FileNotFoundError):
        assistant.render_pdf_pages(tmp_path / "missing.pdf")
