"""Unit tests for the BOE consolidated XML parser (TASK-2372)."""

from itertools import pairwise
from pathlib import Path

import pytest
from parrot_tools.legal.boe.parser import parse_consolidated

FIXTURE = Path(__file__).parent / "fixtures" / "boe_consolidated_sample.xml"


@pytest.fixture
def parsed():
    return parse_consolidated(FIXTURE.read_text(encoding="utf-8"))


class TestBOEParser:
    def test_norma_keyed_by_boe_id(self, parsed):
        assert parsed.norma["boe_id"].startswith("BOE-")

    def test_single_version_article(self, parsed):
        art = next(a for a in parsed.articulos if len(a["versions"]) == 1)
        v = art["versions"][0]
        assert v["n"] == 0 and v["modified_by"] is None and v["valid_to"] is None

    def test_version_chain_has_no_gaps(self, parsed):
        art = next(a for a in parsed.articulos if len(a["versions"]) >= 3)
        vs = art["versions"]
        for prev, nxt in pairwise(vs):
            assert prev["valid_to"] == nxt["valid_from"]
        assert vs[-1]["valid_to"] is None

    def test_supresion_has_null_text(self, parsed):
        for a in parsed.articulos:
            for v in a["versions"]:
                if v["kind"] == "supresion":
                    assert v["text"] is None

    def test_all_versions_are_boe_sourced_and_not_derived(self, parsed):
        for a in parsed.articulos:
            for v in a["versions"]:
                assert v["source"] == "boe_consolidada"
                assert v["derived"] is False

    def test_malformed_reports_error_not_silence(self):
        result = parse_consolidated("<not-valid-boe/>")
        assert result.errors, "malformed input must surface an error"

    def test_norma_key_is_normalized_boe_id(self, parsed):
        assert parsed.norma["boe_id"] == "BOE-A-2015-10566"

    def test_articulo_keyed_by_norma_and_article(self, parsed):
        art = next(a for a in parsed.articulos if a["numero"] == "50")
        assert art["articulo_key"] == "BOE-A-2015-10566:50"
        assert art["norma_ref"] == "BOE-A-2015-10566"

    def test_modifica_relations_extracted(self, parsed):
        modifica = [r for r in parsed.relations if r["type"] == "modifica"]
        assert any(r["from"] == "BOE-A-2020-17340" and r["to"] == "BOE-A-2015-10566:50" for r in modifica)
        assert any(r["from"] == "BOE-A-2021-21653" and r["to"] == "BOE-A-2015-10566:50" for r in modifica)

    def test_deroga_relations_extracted(self, parsed):
        deroga = [r for r in parsed.relations if r["type"] == "deroga"]
        assert any(r["from"] == "BOE-A-2015-10566" and r["to"] == "BOE-A-2014-9467" for r in deroga)
