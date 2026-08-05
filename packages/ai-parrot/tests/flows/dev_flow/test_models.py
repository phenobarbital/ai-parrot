"""Unit tests for the dev-flow Pydantic contracts (FEAT-412, TASK-2121).

Covers :class:`DevRequestBrief`, the :data:`DevFlowBrief` discriminated
union / :func:`parse_dev_brief` loader shim, and :class:`IdeationOutput`.
"""

from __future__ import annotations

import pytest
from parrot.flows.dev_flow.models import (
    DevRequestBrief,
    IdeationOutput,
    parse_dev_brief,
)
from parrot.flows.dev_loop.models import DevAgentSpec, FeatureBrief, JudgePanelConfig
from pydantic import ValidationError

# ─────────────────────────────────────────────────────────────────────
# DevRequestBrief
# ─────────────────────────────────────────────────────────────────────


def test_dev_request_brief_requires_title_and_description():
    """title/description are mandatory and must be non-empty."""
    with pytest.raises(ValidationError):
        DevRequestBrief(kind="enhancement", description="d")  # no title
    with pytest.raises(ValidationError):
        DevRequestBrief(kind="enhancement", title="t")  # no description
    with pytest.raises(ValidationError):
        DevRequestBrief(kind="enhancement", title="", description="d")
    with pytest.raises(ValidationError):
        DevRequestBrief(kind="enhancement", title="t", description="")


def test_dev_request_brief_defaults():
    brief = DevRequestBrief(
        kind="new_feature",
        title="compression budget telemetry",
        description="Add per-tool telemetry to the compression budget.",
    )
    assert brief.kind == "new_feature"
    assert brief.context == ""
    assert brief.jira_issue_key is None
    assert brief.dev_agents is None
    assert brief.judge_panel is None


def test_dev_request_brief_kind_literal():
    """Only the two NL intents are admissible — 'bug'/'feature' are rejected."""
    for bad in ("bug", "feature", "revision", ""):
        with pytest.raises(ValidationError):
            DevRequestBrief(kind=bad, title="t", description="d")


def test_dev_request_brief_has_no_document_fields():
    """DevRequestBrief is NL-only: no document_path/document_kind validators."""
    brief = DevRequestBrief(kind="enhancement", title="t", description="d")
    assert not hasattr(brief, "document_path")
    assert not hasattr(brief, "document_kind")


def test_dev_request_brief_optional_pool_and_panel():
    brief = DevRequestBrief(
        kind="enhancement",
        title="t",
        description="d",
        context="see PR #12",
        jira_issue_key="PARROT-1",
        dev_agents=[DevAgentSpec(agent="claude-code", model="sonnet", count=2)],
        judge_panel=JudgePanelConfig(judges=[{"agent": "codex"}]),
    )
    assert brief.jira_issue_key == "PARROT-1"
    assert brief.dev_agents is not None
    assert brief.dev_agents[0].count == 2
    assert brief.judge_panel is not None


# ─────────────────────────────────────────────────────────────────────
# DevFlowBrief union / parse_dev_brief
# ─────────────────────────────────────────────────────────────────────


def test_parse_dev_brief_discriminates_union(tmp_path):
    """All three dev-flow kinds resolve to the right model."""
    enh = parse_dev_brief({"kind": "enhancement", "title": "t", "description": "d"})
    assert isinstance(enh, DevRequestBrief)
    assert enh.kind == "enhancement"

    new = parse_dev_brief({"kind": "new_feature", "title": "t", "description": "d"})
    assert isinstance(new, DevRequestBrief)
    assert new.kind == "new_feature"

    doc = tmp_path / "x.proposal.md"
    doc.write_text("# p", encoding="utf-8")
    feat = parse_dev_brief(
        {"kind": "feature", "document_path": str(doc), "document_kind": "proposal"}
    )
    assert isinstance(feat, FeatureBrief)
    assert feat.kind == "feature"


def test_parse_dev_brief_feature_passthrough(tmp_path):
    """The `feature` kind yields the existing FeatureBrief — document must exist."""
    doc = tmp_path / "y.brainstorm.md"
    doc.write_text("# b", encoding="utf-8")
    brief = parse_dev_brief(
        {
            "kind": "feature",
            "document_path": str(doc),
            "document_kind": "brainstorm",
            "jira_issue_key": "PARROT-9",
        }
    )
    assert isinstance(brief, FeatureBrief)
    assert brief.document_path == str(doc)
    assert brief.jira_issue_key == "PARROT-9"

    with pytest.raises(ValidationError):
        parse_dev_brief(
            {
                "kind": "feature",
                "document_path": str(tmp_path / "missing.spec.md"),
                "document_kind": "spec",
            }
        )


def test_parse_dev_brief_requires_explicit_kind():
    """Unlike parse_brief, there is no legacy default kind to fall back on."""
    with pytest.raises(ValueError):
        parse_dev_brief({"title": "t", "description": "d"})
    with pytest.raises(ValueError):
        parse_dev_brief({"kind": "bug", "title": "t", "description": "d"})


def test_dev_flow_brief_union_validates_via_type_adapter(tmp_path):
    """The Annotated union itself discriminates on `kind`."""
    from parrot.flows.dev_flow.models import DevFlowBrief
    from pydantic import TypeAdapter

    adapter = TypeAdapter(DevFlowBrief)
    assert isinstance(
        adapter.validate_python(
            {"kind": "new_feature", "title": "t", "description": "d"}
        ),
        DevRequestBrief,
    )
    doc = tmp_path / "z.spec.md"
    doc.write_text("# s", encoding="utf-8")
    assert isinstance(
        adapter.validate_python(
            {"kind": "feature", "document_path": str(doc), "document_kind": "spec"}
        ),
        FeatureBrief,
    )


# ─────────────────────────────────────────────────────────────────────
# IdeationOutput
# ─────────────────────────────────────────────────────────────────────


def test_ideation_output_defaults():
    out = IdeationOutput(
        document_path="sdd/proposals/foo.brainstorm.md",
        document_kind="brainstorm",
        slug="foo",
    )
    assert out.resumed_existing is False
    assert out.committed is False
    assert out.open_questions == []
    assert out.summary == ""


def test_ideation_output_document_kind_literal():
    """Only brainstorm/proposal — 'spec' is not an ideation product."""
    for bad in ("spec", "brief", ""):
        with pytest.raises(ValidationError):
            IdeationOutput(
                document_path="sdd/proposals/foo.md",
                document_kind=bad,
                slug="foo",
            )


def test_ideation_output_full_roundtrip():
    raw = {
        "document_path": "sdd/proposals/bar.proposal.md",
        "document_kind": "proposal",
        "slug": "bar",
        "resumed_existing": True,
        "open_questions": ["Which store?", "Sync or async?"],
        "summary": "Light proposal for bar.",
        "committed": True,
    }
    out = IdeationOutput(**raw)
    assert out.resumed_existing is True
    assert out.committed is True
    assert len(out.open_questions) == 2
    assert out.model_dump() == raw


def test_ideation_output_requires_core_fields():
    with pytest.raises(ValidationError):
        IdeationOutput(document_kind="proposal", slug="s")
    with pytest.raises(ValidationError):
        IdeationOutput(document_path="p", slug="s")
    with pytest.raises(ValidationError):
        IdeationOutput(document_path="p", document_kind="proposal")


# ─────────────────────────────────────────────────────────────────────
# Package exports
# ─────────────────────────────────────────────────────────────────────


def test_package_reexports_models():
    from parrot.flows import dev_flow

    assert dev_flow.DevRequestBrief is DevRequestBrief
    assert dev_flow.IdeationOutput is IdeationOutput
    assert dev_flow.parse_dev_brief is parse_dev_brief
    with pytest.raises(AttributeError):
        dev_flow.definitely_not_a_symbol  # noqa: B018
