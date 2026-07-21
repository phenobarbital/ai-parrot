"""
Unit tests for the `FlowResult.infographic` field (FEAT-308).

TASK-1776: Add `infographic` Field to `FlowResult`

Verifies the new optional field defaults to None, does not break positional
construction, accepts an `InfographicRenderResult`, and is included in
`to_dict()` serialisation.

NOTE (Codebase Contract correction): the task's Codebase Contract described
`InfographicRenderResult.artifact_id` / `.html_url` as `Optional[str] = None`.
Verified against `infographic_toolkit.py:91-103`, both fields are REQUIRED
(`artifact_id: str`, `html_url: str`, no defaults). Tests below construct the
model with these required fields populated.
"""
from parrot.bots.flows.core.result import FlowResult


class TestFlowResultInfographicField:
    def test_default_is_none(self):
        """FlowResult default infographic is None."""
        r = FlowResult(output="hello")
        assert r.infographic is None

    def test_positional_construction_unaffected(self):
        """Existing positional args still work without infographic."""
        r = FlowResult("hello")
        assert r.output == "hello"
        assert r.infographic is None

    def test_set_infographic(self):
        """infographic field accepts an InfographicRenderResult."""
        from parrot.tools.infographic_toolkit import InfographicRenderResult
        fake = InfographicRenderResult(
            artifact_id="artifact-123",
            html_url="https://example.com/artifact-123.html",
            template_name="crew_report",
            theme="light",
            data_variables=[],
            enhanced=False,
        )
        r = FlowResult(output="hello", infographic=fake)
        assert r.infographic is fake
        assert r.infographic.template_name == "crew_report"

    def test_to_dict_includes_infographic_when_set(self):
        """to_dict() serialises the infographic field when populated."""
        from parrot.tools.infographic_toolkit import InfographicRenderResult
        fake = InfographicRenderResult(
            artifact_id="artifact-123",
            html_url="https://example.com/artifact-123.html",
            template_name="crew_report",
            theme="light",
            data_variables=[],
            enhanced=False,
        )
        r = FlowResult(output="hello", infographic=fake)
        d = r.to_dict()
        assert "infographic" in d
        assert d["infographic"]["template_name"] == "crew_report"

    def test_to_dict_infographic_none_when_unset(self):
        """to_dict() yields infographic=None when not populated."""
        r = FlowResult(output="hello")
        d = r.to_dict()
        assert d["infographic"] is None
