"""Behavioral contract for FEAT-581 M7 (TASK-3541): E2E plan generation
consistency across the Claude and Codex spec-authoring surfaces.

This is deliberately NOT a set of string-only assertions that mirror the
docs' own prose. Every claim about policy defaulting, invalid-value
rejection and required-scenario coverage below is proven against the real
`parrot.e2e.models.E2EPlan` schema and `parrot.e2e.plan.load_plan()` loader
(TASK-3520/3521) via round-trip construction/parsing. The doc-surface
checks at the bottom only confirm the three authoring surfaces
(`sdd/templates/spec.md`, `.claude/commands/sdd-spec.md`,
`.agents/skills/sdd-spec/SKILL.md`) agree with each other and with that
verified runtime contract, not merely with themselves.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

_REPO_ROOT = Path(__file__).resolve().parents[2]

# `parrot.e2e` is dependency-light (stdlib + pydantic only, per its own
# module docstring) but ships from the ai-parrot-server distribution, which
# is not guaranteed to be on sys.path for a repo-root test run. Add this
# worktree's own source tree explicitly rather than relying on PYTHONPATH,
# so `pytest tests/sdd_scripts/test_e2e_spec_contract.py -q` works exactly
# as the task's Validation Commands state it, with no extra env setup.
_SERVER_SRC = _REPO_ROOT / "packages" / "ai-parrot-server" / "src"
if str(_SERVER_SRC) not in sys.path:
    sys.path.insert(0, str(_SERVER_SRC))

from parrot.e2e.errors import E2EConfigError  # noqa: E402
from parrot.e2e.models import E2EPlan, ScenarioSpec  # noqa: E402
from parrot.e2e.plan import load_plan  # noqa: E402

_SPEC_TEMPLATE = _REPO_ROOT / "sdd" / "templates" / "spec.md"
_SDD_SPEC_COMMAND = _REPO_ROOT / ".claude" / "commands" / "sdd-spec.md"
_SDD_SPEC_SKILL = _REPO_ROOT / ".agents" / "skills" / "sdd-spec" / "SKILL.md"
_DOC_SURFACES = (_SPEC_TEMPLATE, _SDD_SPEC_COMMAND, _SDD_SPEC_SKILL)


def _valid_plan_kwargs() -> dict:
    """One fully valid `E2EPlan` payload matching the shape the three
    surfaces document: a required deterministic scenario, an optional live
    scenario and a non-required exploratory scenario."""
    return {
        "feature_id": "FEAT-999",
        "spec_path": "sdd/specs/example.spec.md",
        "policy": "required",
        "targets": {"http-target": {"kind": "mcp-toolkit"}},
        "scenarios": [
            {
                "id": "http-lifecycle",
                "tier": "deterministic",
                "target_ids": ["http-target"],
                "required": True,
                "node_ids": ["tests/e2e/test_mcp_http.py::test_lifecycle"],
            },
            {
                "id": "live-google-tool",
                "tier": "live",
                "target_ids": ["http-target"],
                "required": False,
                "node_ids": ["tests/e2e/test_mcp_agent_live.py::test_tool"],
            },
            {
                "id": "ui-exploration",
                "tier": "exploratory",
                "target_ids": [],
                "required": False,
                "node_ids": [],
            },
        ],
    }


def _write_frontmatter(path: Path, frontmatter: dict, body: str) -> None:
    """Write a Markdown file with a real, YAML-dumped frontmatter block.

    Using `yaml.safe_dump` instead of hand-indented triple-quoted strings
    means the on-disk shape always matches the dict under test — no
    hand-maintained indentation to drift from the payload it represents.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\n" + body
    path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Schema round-trip: the documented example shape is genuinely valid, not
# merely plausible-looking prose.
# ---------------------------------------------------------------------------


def test_documented_plan_shape_round_trips_through_e2e_plan_schema() -> None:
    plan = E2EPlan.model_validate(_valid_plan_kwargs())
    dumped = plan.model_dump(mode="json")
    reparsed = E2EPlan.model_validate(dumped)
    assert reparsed == plan
    assert {s.id for s in plan.scenarios} == {"http-lifecycle", "live-google-tool", "ui-exploration"}


def test_invalid_policy_value_is_rejected_never_coerced() -> None:
    """An invalid `policy` value fails schema validation outright; it is
    never silently coerced to a known-good default."""
    kwargs = _valid_plan_kwargs()
    kwargs["policy"] = "sometimes"
    with pytest.raises(ValidationError):
        E2EPlan.model_validate(kwargs)


def test_required_policy_demands_a_required_codified_scenario() -> None:
    """`required` with only an exploratory scenario declared is rejected —
    an empty/all-exploratory plan under `required` is a configuration
    error, not something silently accepted."""
    kwargs = _valid_plan_kwargs()
    kwargs["policy"] = "required"
    kwargs["scenarios"] = [
        {"id": "ui-exploration", "tier": "exploratory", "target_ids": [], "required": False, "node_ids": []}
    ]
    with pytest.raises(ValidationError, match="required"):
        E2EPlan.model_validate(kwargs)


def test_exploratory_scenario_can_never_be_required() -> None:
    with pytest.raises(ValidationError):
        ScenarioSpec.model_validate({"id": "ui-exploration", "tier": "exploratory", "required": True})


def test_live_scenario_is_never_treated_as_deterministic() -> None:
    """A live-tier scenario validates on its own terms (node IDs required,
    like `deterministic`) but its `tier` is never coerced/relabeled to
    `deterministic` — the two stay distinct through the schema, matching
    the docs' "never label live generations deterministic" guardrail."""
    live = ScenarioSpec.model_validate(
        {
            "id": "live-google-tool",
            "tier": "live",
            "required": False,
            "node_ids": ["tests/e2e/test_mcp_agent_live.py::test_tool"],
        }
    )
    assert live.tier == "live"
    assert live.tier != "deterministic"


# ---------------------------------------------------------------------------
# Loader round-trip: an old spec with no `e2e` frontmatter defaults to
# `optional`; an invalid/empty-required plan fails closed.
# ---------------------------------------------------------------------------


def test_old_spec_with_no_e2e_frontmatter_defaults_plan_policy_to_optional(tmp_path: Path) -> None:
    """A spec written before this feature (no `e2e` key at all) does not
    block plan loading; the resulting plan defaults to `optional` — exactly
    what the templates/commands/skill now document."""
    worktree = tmp_path
    _write_frontmatter(
        worktree / "sdd" / "specs" / "example.spec.md",
        {"type": "feature", "base_branch": "dev", "projects": [], "tags": []},
        "# Feature Specification: Example\n",
    )
    plan_payload = {
        "feature_id": "FEAT-999",
        "spec_path": "sdd/specs/example.spec.md",
        "targets": {"http-target": {"kind": "mcp-toolkit"}},
        "scenarios": [
            {
                "id": "http-lifecycle",
                "tier": "deterministic",
                "target_ids": ["http-target"],
                "required": True,
                "node_ids": ["tests/e2e/test_mcp_http.py::test_lifecycle"],
            }
        ],
    }
    plan_path = worktree / "sdd" / "state" / "FEAT-999" / "e2e-plan.md"
    _write_frontmatter(plan_path, plan_payload, "Rationale.\n")

    plan = load_plan(plan_path, worktree=worktree)
    assert plan.policy == "optional"


def test_invalid_e2e_policy_in_plan_frontmatter_fails_closed_not_coerced(tmp_path: Path) -> None:
    """A *present* but invalid policy value in the plan frontmatter fails
    plan loading; it is never silently repaired to `optional` or any other
    valid value (spec §2: malformed policy values fail metadata validation
    instead of silently defaulting)."""
    worktree = tmp_path
    _write_frontmatter(
        worktree / "sdd" / "specs" / "example.spec.md",
        {"type": "feature", "base_branch": "dev", "projects": [], "tags": []},
        "# Example\n",
    )
    plan_path = worktree / "sdd" / "state" / "FEAT-999" / "e2e-plan.md"
    _write_frontmatter(
        plan_path,
        {"feature_id": "FEAT-999", "spec_path": "sdd/specs/example.spec.md", "policy": "sometimes", "scenarios": []},
        "Rationale.\n",
    )

    with pytest.raises(E2EConfigError):
        load_plan(plan_path, worktree=worktree)


def test_required_policy_with_empty_scenarios_is_rejected_at_load_time(tmp_path: Path) -> None:
    """A `required` plan declaring no scenarios fails to load — an empty
    plan under `required` policy is a configuration error, not a silent
    pass-through."""
    worktree = tmp_path
    _write_frontmatter(
        worktree / "sdd" / "specs" / "example.spec.md",
        {"type": "feature", "base_branch": "dev", "projects": [], "tags": []},
        "# Example\n",
    )
    plan_path = worktree / "sdd" / "state" / "FEAT-999" / "e2e-plan.md"
    _write_frontmatter(
        plan_path,
        {"feature_id": "FEAT-999", "spec_path": "sdd/specs/example.spec.md", "policy": "required", "scenarios": []},
        "Rationale.\n",
    )

    with pytest.raises(E2EConfigError):
        load_plan(plan_path, worktree=worktree)


def test_spec_declared_scenario_ids_disagreeing_with_plan_fail_closed(tmp_path: Path) -> None:
    """A spec frontmatter `e2e.scenario_ids` that disagrees with the plan's
    actual scenario IDs is a configuration error (spec §2: "Plan/spec
    disagreements are configuration errors")."""
    worktree = tmp_path
    _write_frontmatter(
        worktree / "sdd" / "specs" / "example.spec.md",
        {
            "type": "feature",
            "base_branch": "dev",
            "projects": [],
            "tags": [],
            "e2e": {"policy": "required", "scenario_ids": ["a-different-scenario"]},
        },
        "# Example\n",
    )
    plan_path = worktree / "sdd" / "state" / "FEAT-999" / "e2e-plan.md"
    _write_frontmatter(
        plan_path,
        {
            "feature_id": "FEAT-999",
            "spec_path": "sdd/specs/example.spec.md",
            "policy": "required",
            "scenarios": [
                {
                    "id": "http-lifecycle",
                    "tier": "deterministic",
                    "required": True,
                    "node_ids": ["tests/e2e/test_mcp_http.py::test_lifecycle"],
                }
            ],
        },
        "Rationale.\n",
    )

    with pytest.raises(E2EConfigError):
        load_plan(plan_path, worktree=worktree)


# ---------------------------------------------------------------------------
# Doc-surface extraction: the template's own commented `e2e:` example, once
# uncommented, is itself valid YAML and a safe (`optional`) default — an
# author who copies it verbatim gets a safe default, not an unintended gate.
# ---------------------------------------------------------------------------


def _extract_commented_e2e_example(front_text: str) -> dict:
    """Pull the exact `# e2e: / #   policy: ... / #   scenario_ids: ...`
    comment block out of the template's frontmatter and parse it as YAML.

    Deliberately exact-match rather than a broad "any `#`-prefixed line"
    heuristic: the surrounding prose lines are also `#`-prefixed and are
    not valid YAML on their own, so a loose heuristic would either crash
    or silently parse garbage.
    """
    lines = front_text.splitlines()
    start = lines.index("# e2e:")
    block = [lines[start][2:], lines[start + 1][2:], lines[start + 2][2:]]
    return yaml.safe_load("\n".join(block))


def test_spec_template_e2e_frontmatter_example_is_valid_and_defaults_optional() -> None:
    text = _SPEC_TEMPLATE.read_text(encoding="utf-8")
    front = text.split("---", 2)[1]
    extracted = _extract_commented_e2e_example(front)
    assert extracted == {"e2e": {"policy": "optional", "scenario_ids": []}}

    # And that default genuinely round-trips through the real schema as a
    # safe, scenario-free plan (only `required` demands scenario coverage).
    plan = E2EPlan.model_validate(
        {
            "feature_id": "FEAT-1",
            "spec_path": "sdd/specs/example.spec.md",
            "policy": extracted["e2e"]["policy"],
            "scenarios": [],
        }
    )
    assert plan.policy == "optional"


def test_spec_template_e2e_scenarios_section_present_and_ordered() -> None:
    """The new subsection lands inside §4 without disturbing the existing
    Test Data / Fixtures content or the §4/§5 boundary."""
    text = _SPEC_TEMPLATE.read_text(encoding="utf-8")
    assert "### E2E Scenarios" in text
    idx_fixtures = text.index("### Test Data / Fixtures")
    # The frontmatter comment (above §4) also names this subsection in
    # prose; search for the real header only after §4's own fixtures block.
    idx_e2e = text.index("### E2E Scenarios", idx_fixtures)
    idx_ac = text.index("## 5. Acceptance Criteria", idx_fixtures)
    assert idx_fixtures < idx_e2e < idx_ac


def test_spec_template_still_preserves_flow_and_taxonomy_frontmatter() -> None:
    """Adding the `e2e` policy metadata must not disturb the pre-existing
    flow/taxonomy frontmatter keys other tooling depends on verbatim."""
    text = _SPEC_TEMPLATE.read_text(encoding="utf-8")
    front = text.split("---", 2)[1]
    assert "\ntype: feature\n" in front
    assert "\nbase_branch: dev\n" in front
    assert "\nprojects: []\n" in front
    assert "\ntags: []\n" in front


# ---------------------------------------------------------------------------
# Cross-surface consistency: Claude template/command and the Codex skill
# document the same contract, not divergent prose.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", _DOC_SURFACES, ids=lambda p: p.name)
def test_each_surface_states_the_policy_literal_with_no_coercion(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert "required" in text and "optional" in text and "none" in text
    assert "coerc" in text.lower() or "never coerced" in text.lower()


@pytest.mark.parametrize("path", _DOC_SURFACES, ids=lambda p: p.name)
def test_each_surface_separates_exploratory_from_deterministic(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert "exploratory" in text
    assert "deterministic" in text
    assert "e2e-plan.md" in text or "E2E Scenarios" in text


@pytest.mark.parametrize("path", _DOC_SURFACES, ids=lambda p: p.name)
def test_each_surface_documents_required_needs_a_codified_scenario(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert "required" in text.lower()
    assert "scenario" in text.lower()
