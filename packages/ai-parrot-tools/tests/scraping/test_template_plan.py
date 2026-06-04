"""Tests for TemplatePlan & ParamSpec — FEAT-222 TASK-1448."""
import pytest

from parrot_tools.scraping.plan import ScrapingPlan
from parrot_tools.scraping.template_plan import ParamSpec, TemplatePlan


@pytest.fixture
def flight_template():
    return TemplatePlan(
        name="search-flights",
        objective_template="Search flights from {{origin}} to {{destination}}",
        url_template="https://example.com/flights?from={{origin}}&to={{destination}}",
        params=[
            ParamSpec(name="origin", type="string", required=True),
            ParamSpec(name="destination", type="string", required=True),
        ],
        steps_template=[
            {"action": "navigate", "url": "{{url}}"},
            {"action": "wait", "condition": ".results", "condition_type": "selector"},
        ],
    )


# ── ParamSpec ─────────────────────────────────────────────────────────

class TestParamSpec:
    def test_defaults(self):
        spec = ParamSpec(name="q")
        assert spec.type == "string"
        assert spec.required is True
        assert spec.default is None

    def test_enum_requires_choices(self):
        with pytest.raises(ValueError, match="choices"):
            ParamSpec(name="cls", type="enum")

    def test_enum_with_choices_ok(self):
        spec = ParamSpec(name="cls", type="enum", choices=["economy", "business"])
        assert spec.choices == ["economy", "business"]

    def test_bad_default_rejected_at_construction(self):
        with pytest.raises(ValueError, match="int"):
            ParamSpec(name="n", type="int", required=False, default="nope")

    def test_valid_default_ok(self):
        spec = ParamSpec(name="n", type="int", required=False, default=5)
        assert spec.default == 5

    def test_bad_enum_default_rejected(self):
        with pytest.raises(ValueError, match="must be one of"):
            ParamSpec(name="c", type="enum", choices=["a", "b"],
                      required=False, default="z")


# ── TemplatePlan.bind ─────────────────────────────────────────────────

class TestTemplatePlanBind:
    def test_bind_basic(self, flight_template):
        plan = flight_template.bind(origin="SEA", destination="LAX")
        assert isinstance(plan, ScrapingPlan)
        assert plan.url == "https://example.com/flights?from=SEA&to=LAX"
        assert "SEA" in plan.objective
        assert "LAX" in plan.objective

    def test_bind_renders_steps_url_placeholder(self, flight_template):
        plan = flight_template.bind(origin="SEA", destination="LAX")
        assert plan.steps[0]["url"] == "https://example.com/flights?from=SEA&to=LAX"

    def test_bind_missing_required_raises(self, flight_template):
        with pytest.raises(ValueError, match="origin"):
            flight_template.bind(destination="LAX")

    def test_bind_unique_fingerprints(self, flight_template):
        p1 = flight_template.bind(origin="SEA", destination="LAX")
        p2 = flight_template.bind(origin="SFO", destination="JFK")
        assert p1.fingerprint != p2.fingerprint

    def test_bind_stable_fingerprint(self, flight_template):
        p1 = flight_template.bind(origin="SEA", destination="LAX")
        p2 = flight_template.bind(origin="SEA", destination="LAX")
        assert p1.fingerprint == p2.fingerprint

    def test_bind_keeps_template_name(self, flight_template):
        plan = flight_template.bind(origin="SEA", destination="LAX")
        assert plan.name == "search-flights"

    def test_bind_defaults_filled(self):
        tmpl = TemplatePlan(
            name="search",
            objective_template="Search {{q}} page {{page}}",
            url_template="https://e.com/s?q={{q}}&p={{page}}",
            params=[
                ParamSpec(name="q", type="string", required=True),
                ParamSpec(name="page", type="int", required=False, default=1),
            ],
            steps_template=[],
        )
        plan = tmpl.bind(q="shoes")
        assert plan.url == "https://e.com/s?q=shoes&p=1"

    def test_bind_int_type_validation(self):
        tmpl = TemplatePlan(
            name="t", objective_template="o", url_template="https://e.com/{{n}}",
            params=[ParamSpec(name="n", type="int")], steps_template=[],
        )
        with pytest.raises(ValueError, match="int"):
            tmpl.bind(n="not-an-int")

    def test_bind_int_type_ok(self):
        tmpl = TemplatePlan(
            name="t", objective_template="o", url_template="https://e.com/{{n}}",
            params=[ParamSpec(name="n", type="int")], steps_template=[],
        )
        plan = tmpl.bind(n=5)
        assert plan.url == "https://e.com/5"

    def test_bind_date_validation(self):
        tmpl = TemplatePlan(
            name="t", objective_template="o", url_template="https://e.com/{{d}}",
            params=[ParamSpec(name="d", type="date")], steps_template=[],
        )
        plan = tmpl.bind(d="2026-06-04")
        assert plan.url == "https://e.com/2026-06-04"
        with pytest.raises(ValueError, match="ISO date"):
            tmpl.bind(d="not-a-date")

    def test_bind_enum_validation(self):
        tmpl = TemplatePlan(
            name="t", objective_template="o", url_template="https://e.com/{{c}}",
            params=[ParamSpec(name="c", type="enum", choices=["a", "b"])],
            steps_template=[],
        )
        plan = tmpl.bind(c="a")
        assert plan.url == "https://e.com/a"
        with pytest.raises(ValueError, match="must be one of"):
            tmpl.bind(c="z")

    def test_bind_url_validation(self):
        tmpl = TemplatePlan(
            name="t", objective_template="o", url_template="{{target}}",
            params=[ParamSpec(name="target", type="url")], steps_template=[],
        )
        plan = tmpl.bind(target="https://x.com/page")
        assert plan.url == "https://x.com/page"
        with pytest.raises(ValueError, match="http"):
            tmpl.bind(target="ftp://x.com")

    def test_single_braces_pass_through(self):
        tmpl = TemplatePlan(
            name="test", objective_template="test",
            url_template="http://example.com",
            params=[],
            steps_template=[{"action": "loop", "selector": ".item-{i}"}],
        )
        plan = tmpl.bind()
        assert plan.steps[0]["selector"] == ".item-{i}"

    def test_unknown_placeholder_left_intact(self):
        tmpl = TemplatePlan(
            name="t", objective_template="o",
            url_template="https://e.com/{{unknown}}",
            params=[], steps_template=[],
        )
        plan = tmpl.bind()
        assert plan.url == "https://e.com/{{unknown}}"

    def test_template_fingerprint_is_name_based(self, flight_template):
        # The template-level fingerprint is derived from the name and is
        # distinct from any bound plan's per-param fingerprint.
        assert isinstance(flight_template.fingerprint, str)
        assert len(flight_template.fingerprint) == 16

    def test_nested_steps_rendered(self):
        tmpl = TemplatePlan(
            name="t", objective_template="o", url_template="https://e.com",
            params=[ParamSpec(name="city", type="string")],
            steps_template=[
                {
                    "action": "fill",
                    "selector": "#city",
                    "value": "{{city}}",
                    "nested": {"deep": "{{city}}", "keep": "{i}"},
                    "list": ["{{city}}", "static"],
                }
            ],
        )
        plan = tmpl.bind(city="Miami")
        step = plan.steps[0]
        assert step["value"] == "Miami"
        assert step["nested"]["deep"] == "Miami"
        assert step["nested"]["keep"] == "{i}"
        assert step["list"] == ["Miami", "static"]
