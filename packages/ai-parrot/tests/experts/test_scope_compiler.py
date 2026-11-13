"""Golden and validation tests for scope grid loading and compilation."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from parrot.bots.flows.core.gates import register_gate_kind
from parrot.bots.flows.flow.flow import AgentsFlow
from parrot.experts.grid.compiler import compile_scope
from parrot.experts.grid.loader import BUNDLED_SCOPES_DIR, load_scopes
from parrot.experts.grid.models import ScopeGrid, ScopeGridError, ScopeGridErrorCode
from parrot.experts.loader import discover_expert_bundles


class FakeRegistry:
    """Minimal registry exposing the compiler's synchronous lookup contract."""

    def __init__(self, capabilities: dict[str, list[str]]) -> None:
        """Build fake experts with the manifest capability shape."""
        self._experts = {
            name: SimpleNamespace(bundle=SimpleNamespace(manifest=SimpleNamespace(capabilities=values)))
            for name, values in capabilities.items()
        }

    def get(self, name: str, *, tenant: str | None = None) -> object:
        """Return the named fake expert or preserve ExpertRegistry's KeyError behavior."""
        return self._experts[name]


@pytest.fixture
def registry() -> FakeRegistry:
    """Provide the bundled scope experts with their real capabilities."""
    register_gate_kind("approval", description="scope approval")
    return FakeRegistry({"cve-analyst": ["validate", "write", "review"], "cve-remediation": ["write"]})


def test_compile_scope_golden(registry: FakeRegistry) -> None:
    """The security-patch grid compiles to the checked-in flow definition."""
    grid = load_scopes(None)["security-patch"]
    actual = compile_scope(grid, registry=registry).model_dump(by_alias=True, mode="json")
    fixture = Path(__file__).parent / "fixtures" / "security_patch_flow.json"
    assert actual == json.loads(fixture.read_text(encoding="utf-8"))


def test_compiled_scope_materializes_with_unchanged_agents_flow(registry: FakeRegistry) -> None:
    """The generated definition uses registered node types and can materialize."""
    definition = compile_scope(load_scopes(None)["security-patch"], registry=registry)

    flow = AgentsFlow.from_definition(definition, agent_registry=object())

    assert set(flow._materialize_nodes()) == {"__start__", "intake", "plan", "__end__"}


def test_compile_scope_expands_pipeline_and_follows_mob_with_synthesis(registry: FakeRegistry) -> None:
    """Pipeline experts become a chain and mob output is passed through synthesis."""
    grid = ScopeGrid.model_validate(
        {
            "scope": "combined",
            "stages": [
                {"stage": "pipeline", "experts": ["cve-analyst", "cve-remediation"], "mode": "pipeline"},
                {"stage": "mob", "experts": ["cve-analyst"], "mode": "mob"},
            ],
        }
    )

    flow = compile_scope(grid, registry=registry)

    assert [node.id for node in flow.nodes] == [
        "__start__",
        "pipeline-1",
        "pipeline-2",
        "mob",
        "mob-synthesis",
        "__end__",
    ]
    assert flow.nodes[1].config["mode"] == "subagent"
    assert flow.nodes[2].config["experts"] == ["cve-remediation"]
    assert flow.edges[-2].from_ == "mob"
    assert flow.edges[-2].to == "mob-synthesis"


@pytest.mark.parametrize(
    ("grid", "code"),
    [
        (
            {"scope": "missing", "stages": [{"stage": "a", "experts": ["missing"], "mode": "subagent"}]},
            ScopeGridErrorCode.UNKNOWN_EXPERT,
        ),
        (
            {
                "scope": "reviewer",
                "stages": [
                    {
                        "stage": "a",
                        "experts": ["cve-analyst"],
                        "mode": "subagent",
                        "gate": {"kind": "approval", "title": "Approve", "pre_review": "cve-remediation"},
                    }
                ],
            },
            ScopeGridErrorCode.CAPABILITY_MISMATCH,
        ),
        (
            {
                "scope": "bad-gate",
                "stages": [
                    {
                        "stage": "a",
                        "experts": ["cve-analyst"],
                        "mode": "subagent",
                        "gate": {"kind": "missing", "title": "Approve"},
                    }
                ],
            },
            ScopeGridErrorCode.UNKNOWN_GATE_KIND,
        ),
    ],
)
def test_compile_scope_errors(registry: FakeRegistry, grid: dict[str, object], code: ScopeGridErrorCode) -> None:
    """Compiler failures retain their documented stable error codes."""
    with pytest.raises(ScopeGridError) as error:
        compile_scope(ScopeGrid.model_validate(grid), registry=registry)
    assert error.value.code is code


def test_workspace_scope_shadows_bundled_and_expert_discovery_ignores_scopes(tmp_path: Path) -> None:
    """Scope overlays do not turn scope files into expert bundles."""
    workspace_scope = tmp_path / "experts" / "scopes"
    workspace_scope.mkdir(parents=True)
    (workspace_scope / "security-patch.yaml").write_text(
        "scope: security-patch\nstages:\n  - stage: local\n    experts: [cve-analyst]\n    mode: subagent\n",
        encoding="utf-8",
    )

    scopes = load_scopes(tmp_path)
    bundles, skipped = discover_expert_bundles(tmp_path / "experts")

    assert BUNDLED_SCOPES_DIR.is_dir()
    assert scopes["security-patch"].stages[0].stage == "local"
    assert bundles == []
    assert skipped == []
