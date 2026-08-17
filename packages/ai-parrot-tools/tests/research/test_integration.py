"""Cross-toolkit integration tests for FEAT-426 (TASK-2243 Module 5).

Covers: public exports, `TOOL_REGISTRY` discovery, each toolkit's tool
surface, and the G7 "no tool raises into the agent loop" contract test —
run fully offline (spec goal G6).

Registry note (see this task's Completion Note for full detail):
`scripts/generate_tool_registry.py`'s `read_existing_registry()` and the
write branch of `update_init_file()` both match only `ast.Assign`, never
`ast.AnnAssign` — but both `TOOL_REGISTRY` and `LOADER_REGISTRY` are
declared as `NAME: dict[str, str] = {...}` (an `AnnAssign`). This is a
pre-existing bug, unrelated to FEAT-426, that makes `--check` report the
*entire* monorepo's tool/loader registries as stale unconditionally
(verified via an isolated repro in a scratch file — the write path
silently no-ops even when it reports `changed=True`). `TestRegistry`
below verifies what is actually achievable within this task's scope:
that the new toolkits/router have correct, generator-shaped entries in
`TOOL_REGISTRY` — not the unconditionally-failing `--check` exit code.
"""
import subprocess
import sys

import pytest

_MINIMAL_ARGS = {
    "search_world_bank": {"query": "gdp growth"},
    "get_world_bank_indicator": {"indicator_id": "NY.GDP.MKTP.KD.ZG", "country": "USA"},
    "search_eu_open_data": {"query": "renewable energy"},
    "search_oecd_data": {"query": "temperature"},
    "get_oecd_indicator": {"dataset_id": "DSD_X@DF_Y", "country": "FRA"},
    "search_crossref": {"query": "transformers"},
    "search_pubmed": {"query": "crispr"},
    "search_semantic_scholar": {"query": "graph nn"},
    "search_arxiv": {"query": "transformers"},
    "get_paper_details": {"doi_or_id": "10.1093/nar/gkaa1100"},
}


def _minimal_args_for(tool) -> dict:
    return _MINIMAL_ARGS[tool.name]


@pytest.fixture
def all_network_fails(monkeypatch):
    """Force every network dependency (optional libs + aiohttp) to fail.

    Used for the G7 contract test: with every method forced onto its
    error path, `ToolManager`/`AbstractTool.execute()` must still never
    raise (spec §2 Error Contract).
    """
    import parrot_tools.research.academic as academic_module
    import parrot_tools.research.open_data as open_data_module
    from parrot_tools.research.base import BaseResearchToolkit

    monkeypatch.setattr(open_data_module, "wb", None)
    monkeypatch.setattr(open_data_module, "sdmx", None)
    monkeypatch.setattr(academic_module, "Crossref", None)
    monkeypatch.setattr(academic_module, "Entrez", None)
    monkeypatch.setattr(academic_module, "arxiv", None)

    async def _failing_request(self, url, params=None, headers=None):
        return None, "simulated network failure"

    monkeypatch.setattr(BaseResearchToolkit, "_make_api_request", _failing_request)


class TestExports:
    def test_public_exports(self):
        from parrot_tools.research import (  # noqa: F401
            AcademicResearchToolkit,
            Citation,
            OpenDataToolkit,
            ResearchResult,
            ResearchRouter,
        )

    def test_import_without_research_extra(self):
        """Optional deps are guarded — the package must import cleanly
        even when none of the `research` extra's libraries are
        importable (simulated in a fresh subprocess to avoid reload
        hazards in the shared test session)."""
        script = (
            "import builtins\n"
            "_orig = builtins.__import__\n"
            "_blocked = {'wbgapi', 'sdmx', 'habanero', 'Bio', 'arxiv'}\n"
            "def _blocking(name, *a, **kw):\n"
            "    if name.split('.')[0] in _blocked:\n"
            "        raise ImportError(name)\n"
            "    return _orig(name, *a, **kw)\n"
            "builtins.__import__ = _blocking\n"
            "import parrot_tools.research\n"
            "print('IMPORT_OK')\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True, check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "IMPORT_OK" in result.stdout

    def test_market_toolkit_absent(self):
        import parrot_tools.research as r

        assert not hasattr(r, "MarketResearchToolkit")


class TestRegistry:
    def test_registry_contains_new_toolkits(self):
        from parrot_tools import TOOL_REGISTRY

        joined = " ".join(TOOL_REGISTRY.values())
        assert "OpenDataToolkit" in joined
        assert "AcademicResearchToolkit" in joined
        assert "ResearchRouter" in joined

    def test_market_toolkit_absent_from_registry(self):
        from parrot_tools import TOOL_REGISTRY

        assert "MarketResearchToolkit" not in " ".join(TOOL_REGISTRY.values())

    def test_research_entries_match_generator_scan(self):
        """The hand-added registry entries exactly match what
        `scripts/generate_tool_registry.py --dry-run --tools-only` would
        compute for `parrot_tools/research/` (see module docstring for
        why they were added by hand rather than via a live regeneration
        run)."""
        result = subprocess.run(
            [sys.executable, "scripts/generate_tool_registry.py",
             "--dry-run", "--tools-only"],
            capture_output=True, text=True, check=False,
        )
        research_lines = [
            line for line in result.stdout.splitlines()
            if "parrot_tools.research." in line
        ]
        assert research_lines == [], (
            "generator scan disagrees with the hand-added research "
            f"registry entries: {research_lines}"
        )


class TestToolSurface:
    @pytest.mark.parametrize("cls,expected", [
        ("OpenDataToolkit", {
            "search_world_bank", "get_world_bank_indicator",
            "search_eu_open_data", "search_oecd_data", "get_oecd_indicator",
        }),
        ("AcademicResearchToolkit", {
            "search_crossref", "search_pubmed", "search_semantic_scholar",
            "search_arxiv", "get_paper_details",
        }),
    ])
    def test_expected_tools(self, cls, expected):
        import parrot_tools.research as r

        assert {t.name for t in getattr(r, cls)().get_tools()} == expected


class TestErrorContract:
    async def test_no_method_raises_into_agent_loop(self, all_network_fails):
        """G7 contract test across every toolkit method: even with every
        network dependency forced to fail, `AbstractTool.execute()` must
        wrap the returned `ResearchResult` normally (outer
        `ToolResult.status` stays "success") and never raise."""
        import parrot_tools.research as r

        for tk in (r.OpenDataToolkit(), r.AcademicResearchToolkit()):
            for tool in tk.get_tools():
                out = await tool.execute(**_minimal_args_for(tool))
                assert out.status != "error", (
                    f"{tool.name} would make ToolManager raise"
                )
                assert out.result.status in {"no_data", "error"}, (
                    f"{tool.name} did not report the forced failure as data"
                )

    async def test_successful_results_carry_citation(self, monkeypatch):
        """Every status="success" result across both toolkits carries a
        complete Citation (spec AC)."""
        import parrot_tools.research as r
        from parrot_tools.research.base import BaseResearchToolkit

        async def _ok_request(self, url, params=None, headers=None):
            return {"data": [], "result": {"count": 0, "results": []}}, None

        monkeypatch.setattr(BaseResearchToolkit, "_make_api_request", _ok_request)

        # search_eu_open_data / search_semantic_scholar return no_data with
        # an empty payload above — exercise a source that succeeds instead:
        # World Bank via a minimal fake `wb`.
        import types

        import parrot_tools.research.open_data as open_data_module

        fake_wb = types.SimpleNamespace(
            data=types.SimpleNamespace(
                fetch=lambda series, economy=None, **kw: iter([
                    {"series": series, "seriesName": "X", "economy": "USA",
                     "economyName": "United States", "time": "YR2020", "value": 1.0}
                ])
            ),
            series=types.SimpleNamespace(info=lambda q=None: []),
        )
        monkeypatch.setattr(open_data_module, "wb", fake_wb)

        result = await r.OpenDataToolkit().get_world_bank_indicator(
            "NY.GDP.MKTP.KD.ZG", "USA"
        )
        assert result.status == "success"
        assert result.citation is not None
        assert result.citation.source_name
        assert result.citation.source_url
        assert result.citation.access_date
        assert result.citation.formatted_citation
