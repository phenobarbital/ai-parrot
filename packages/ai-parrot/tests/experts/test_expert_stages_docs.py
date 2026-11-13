"""The expert-stages wiki pages exist and only cite symbols that really exist (FEAT-890)."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
WIKI = REPO_ROOT / "wiki"

#: page -> dotted public symbols it documents. Each must import AND be named in the page.
PAGES: dict[str, list[str]] = {
    "experts/expert-stages-and-scope-grid.md": [
        "parrot.experts.grid.models.ScopeGrid",
        "parrot.experts.grid.models.ExpertStageConfig",
        "parrot.experts.grid.models.ScopeGridError",
        "parrot.experts.grid.models.ScopeGridErrorCode",
        "parrot.experts.grid.compiler.compile_scope",
        "parrot.experts.grid.loader.load_scopes",
        "parrot.experts.stages.inline.build_inline_conductor",
        "parrot.experts.stages.inline.InlineCompositionError",
        "parrot.experts.stages.node.ExpertStageError",
        "parrot.experts.knowledge.sources.episodes.record_episode",
        "parrot.experts.knowledge.sources.episodes.EpisodeSource",
        "parrot.experts.lease_store.LeaseDurableCheckpointStore",
        "parrot.flows.dev_loop.sdd_coder.roster.eligible_seats_for_tier",
    ],
    "flows/generic-gate-host.md": [
        "parrot.bots.flows.core.gates.GateHost",
        "parrot.bots.flows.core.gates.GateSpec",
        "parrot.bots.flows.core.gates.GateRecord",
        "parrot.bots.flows.core.gates.GateEvent",
        "parrot.bots.flows.core.gates.GateError",
        "parrot.bots.flows.core.gates.GateErrorCode",
        "parrot.bots.flows.core.gates.GateStore",
        "parrot.bots.flows.core.gates.AUTO_APPROVER",
        "parrot.bots.flows.core.gates.register_gate_kind",
        "parrot.bots.flows.core.gates.is_registered",
        "parrot.bots.flows.core.gates.registered_kinds",
        "parrot.bots.flows.core.gates.stores.resolve_gate_store",
        "parrot.flows.dev_loop.gate_adapter.DevLoopGateAdapter",
    ],
    "sdd-tooling/sdd/expert-consult.md": [
        "parrot.experts.contributions.Contribution",
        "parrot.experts.contributions.Finding",
        "parrot.experts.promotion.promote_finding",
    ],
}


@pytest.mark.parametrize("page", sorted(PAGES))
def test_page_exists_with_frontmatter(page: str) -> None:
    path = WIKI / page
    assert path.is_file(), f"{path} is missing"
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    head = text.split("---\n", 2)[1]
    assert "title:" in head and "summary:" in head


@pytest.mark.parametrize(("page", "symbol"), [(p, s) for p, symbols in sorted(PAGES.items()) for s in symbols])
def test_page_names_a_symbol_that_exists(page: str, symbol: str) -> None:
    module_path, _, name = symbol.rpartition(".")
    assert hasattr(importlib.import_module(module_path), name), f"{symbol} does not exist"
    assert name in (WIKI / page).read_text(encoding="utf-8"), f"{page} does not mention {name}"


def test_consult_page_documents_the_real_cli_commands() -> None:
    from click.testing import CliRunner

    from parrot.sdd.experts_cli import experts

    text = (WIKI / "sdd-tooling/sdd/expert-consult.md").read_text(encoding="utf-8")
    for command in ("consult", "triage", "promote"):
        assert f"parrot sdd experts {command}" in text
        assert command in CliRunner().invoke(experts, ["--help"]).output


def test_index_has_the_experts_section() -> None:
    assert "id: experts" in (WIKI / "_index.yaml").read_text(encoding="utf-8")
