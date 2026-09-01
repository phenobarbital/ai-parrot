"""Dev-console per-seat LLM plan surface (FEAT-486 TASK-2658).

Spec §4 rows ``test_server_config_payload`` and
``test_server_run_parses_plan_fields``. Loads ``examples/dev_loop/server_dev.py``
the same way ``test_server_dev.py`` does (importlib from the file path,
because ``examples/`` is not a package) and drives it with
``aiohttp_client``.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest
from parrot.bots.flows.core.result import FlowResult
from parrot.bots.flows.core.types import FlowStatus
from parrot.flows.dev_flow.model_plan import DevFlowModelPlan
from parrot.flows.dev_flow.runner import DevFlowRunner

_REPO_ROOT = Path(__file__).resolve().parents[5]


def _load_module(name: str, filename: str):
    path = _REPO_ROOT / "examples" / "dev_loop" / filename
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def server_dev():
    return _load_module("dev_flow_server_dev_plan", "server_dev.py")


class _StubFlow:
    def __init__(self) -> None:
        self.contexts: list[Any] = []
        self._run_id_holder: dict[str, str] = {}

    async def run_flow(self, ctx, **kwargs) -> FlowResult:
        self.contexts.append(ctx)
        return FlowResult(output=ctx.shared_data["run_id"], status=FlowStatus.COMPLETED)


@pytest.fixture
def make_client(server_dev, aiohttp_client):
    async def _make(**app_overrides: Any):
        flow = _StubFlow()
        app = server_dev.build_app(redis_url="redis://x")
        app.on_startup.clear()
        app.on_cleanup.clear()
        runner = DevFlowRunner(flow, redis_url="redis://x")
        app["runner"] = runner
        app["dev_loop_runner"] = runner
        app["flow"] = flow
        app["flow_tasks"] = {}
        app["wiki_search"] = None
        app["jira_toolkit"] = None
        app["codereview_agent_key"] = "parallel"
        app["development_pool_max"] = 4
        app["require_plan_approval"] = False
        app["model_plan"] = server_dev._console_default_model_plan()
        app["review_pair_active"] = False
        app.update(app_overrides)
        return await aiohttp_client(app)

    return _make


def _nl_form(**extra: Any) -> dict[str, Any]:
    payload = {
        "kind": "new_feature",
        "title": "compression budget telemetry",
        "description": "Add per-tool telemetry to the compression budget.",
    }
    payload.update(extra)
    return payload


class TestConsoleDefaultPlan:
    """Spec §3 Module 6 defaults."""

    def test_default_pool_is_bedrock_glm_plus_qwen(self, server_dev):
        plan = server_dev._console_default_model_plan()
        assert [(s.agent, s.model) for s in plan.dev_pool] == [
            ("nova", "zai.glm-5"),
            ("nova", "qwen.qwen3-coder-480b-a35b-v1:0"),
        ]

    def test_default_research_primary_is_opus_5(self, server_dev):
        assert server_dev._console_default_model_plan().research_primary == "claude-opus-5"

    def test_partner_is_off_by_default_but_defaults_to_gpt_5_6_sol(self, server_dev):
        partner = server_dev._console_default_model_plan().research_partner
        assert partner.enabled is False
        assert partner.model == "gpt-5.6-sol"

    def test_default_review_pair(self, server_dev):
        review = server_dev._console_default_model_plan().review
        assert (review.primary.agent, review.primary.model) == (
            "claude-code",
            "claude-opus-5",
        )
        assert review.counter_model == "gpt-5.6-sol"

    def test_nim_is_never_a_default(self, server_dev):
        plan = server_dev._console_default_model_plan()
        assert all(spec.agent != "nvidia" for spec in plan.dev_pool)


@pytest.mark.asyncio
class TestConfigPayload:
    async def test_config_carries_plan_defaults(self, make_client):
        client = await make_client()
        payload = await (await client.get("/api/config")).json()
        plan = payload["defaults"]["model_plan"]
        assert plan["research_primary"] == "claude-opus-5"
        assert plan["research_partner"]["enabled"] is False
        assert plan["research_partner"]["model"] == "gpt-5.6-sol"
        assert [(r["agent"], r["model"]) for r in plan["dev_agents"]] == [
            ("nova", "zai.glm-5"),
            ("nova", "qwen.qwen3-coder-480b-a35b-v1:0"),
        ]
        assert plan["review"]["primary"] == {
            "agent": "claude-code",
            "model": "claude-opus-5",
        }
        assert plan["review"]["counter_model"] == "gpt-5.6-sol"

    async def test_config_lists_selectable_backends(self, make_client):
        client = await make_client()
        plan = (await (await client.get("/api/config")).json())["defaults"]["model_plan"]
        assert "nova" in plan["pool_backends"]
        assert "claude-code" in plan["review_primary_backends"]
        assert plan["partner_backends"] == ["gpt", "nova"]

    async def test_nim_listed_not_default(self, make_client):
        """NIM must remain selectable in the catalog but never preselected."""
        client = await make_client()
        payload = await (await client.get("/api/config")).json()
        assert "nvidia" in [b["id"] for b in payload["backends"]]
        assert "nvidia" in payload["roles"]["development"]
        plan = payload["defaults"]["model_plan"]
        assert all(r["agent"] != "nvidia" for r in plan["dev_agents"])

    async def test_config_reports_review_pair_activity_honestly(self, make_client):
        """This console wires the judge panel, so the pair is not active."""
        client = await make_client()
        plan = (await (await client.get("/api/config")).json())["defaults"]["model_plan"]
        assert plan["review_pair_active"] is False

    async def test_adversarial_note_still_says_mandatory(self, make_client):
        client = await make_client()
        payload = await (await client.get("/api/config")).json()
        assert payload["adversarial_review"]["mandatory"] is True
        assert "cannot be switched off" in payload["adversarial_review"]["note"]


class TestPlanParsing:
    """``_parse_model_plan`` — backends strict, models free text."""

    def test_absent_fields_mean_no_plan(self, server_dev):
        assert server_dev._parse_model_plan({"kind": "new_feature"}) is None

    def test_run_parses_plan_fields(self, server_dev):
        plan = server_dev._parse_model_plan(
            {
                "dev_agents": [
                    {"agent": "nova", "model": "zai.glm-5", "count": 1},
                    {"agent": "moonshot", "model": "kimi-k3", "count": 2},
                ],
                "research_primary": "claude-opus-5",
                "research_partner": {"enabled": True, "backend": "nova", "model": "nova-2-lite"},
                "review": {
                    "primary": {"agent": "codex", "model": "gpt-5.5"},
                    "counter_model": "openai.gpt-oss-120b",
                },
            }
        )
        assert isinstance(plan, DevFlowModelPlan)
        assert [(s.agent, s.model, s.count) for s in plan.dev_pool] == [
            ("nova", "zai.glm-5", 1),
            ("moonshot", "kimi-k3", 2),
        ]
        assert plan.research_primary == "claude-opus-5"
        assert plan.research_partner.enabled is True
        assert plan.research_partner.backend == "nova"
        assert plan.review.primary.agent == "codex"
        assert plan.review.counter_model == "openai.gpt-oss-120b"

    def test_unknown_pool_backend_rejected(self, server_dev):
        with pytest.raises(ValueError, match="unknown dev agent backend"):
            server_dev._parse_model_plan({"dev_agents": [{"agent": "bogus"}]})

    def test_unknown_pool_backend_names_supported_set(self, server_dev):
        with pytest.raises(ValueError, match="claude-code"):
            server_dev._parse_model_plan({"dev_agents": [{"agent": "bogus"}]})

    def test_unknown_review_primary_rejected(self, server_dev):
        with pytest.raises(ValueError, match="cannot serve as the primary reviewer"):
            server_dev._parse_model_plan(
                {"review": {"primary": {"agent": "nova"}}}
            )

    def test_model_ids_are_free_text(self, server_dev):
        """Catalog model lists are a suggestion, never a whitelist."""
        plan = server_dev._parse_model_plan(
            {"dev_agents": [{"agent": "nova", "model": "not-in-any-catalog-list"}]}
        )
        assert plan.dev_pool[0].model == "not-in-any-catalog-list"

    def test_partner_only_payload(self, server_dev):
        plan = server_dev._parse_model_plan(
            {"research_partner": {"enabled": True}}
        )
        assert plan.research_partner.enabled is True
        assert plan.dev_pool == []


@pytest.mark.asyncio
class TestRunEndpoint:
    async def test_run_accepts_a_valid_plan(self, make_client):
        client = await make_client()
        resp = await client.post("/api/flow/run", json=_nl_form(
            dev_agents=[{"agent": "nova", "model": "zai.glm-5", "count": 1}],
            research_primary="claude-opus-5",
        ))
        assert resp.status == 200
        body = await resp.json()
        assert body["model_plan"]["research_primary"] == "claude-opus-5"

    async def test_run_rejects_unknown_backend_with_supported_list(self, make_client):
        client = await make_client()
        resp = await client.post(
            "/api/flow/run", json=_nl_form(dev_agents=[{"agent": "bogus"}])
        )
        assert resp.status == 400
        error = (await resp.json())["error"]
        assert "bogus" in error
        assert "claude-code" in error

    async def test_run_rejects_unknown_review_primary(self, make_client):
        client = await make_client()
        resp = await client.post(
            "/api/flow/run", json=_nl_form(review={"primary": {"agent": "nova"}})
        )
        assert resp.status == 400
        assert "primary reviewer" in (await resp.json())["error"]

    async def test_response_echoes_the_effective_plan(self, make_client):
        """A differing request must be told what will REALLY run."""
        client = await make_client()
        resp = await client.post("/api/flow/run", json=_nl_form(
            dev_agents=[{"agent": "claude-code", "model": "", "count": 1}]
        ))
        body = await resp.json()
        # The server's build-time plan, not the submitted one.
        assert [(r["agent"], r["model"]) for r in body["model_plan"]["dev_agents"]] == [
            ("nova", "zai.glm-5"),
            ("nova", "qwen.qwen3-coder-480b-a35b-v1:0"),
        ]

    async def test_run_without_plan_fields_still_works(self, make_client):
        client = await make_client()
        resp = await client.post("/api/flow/run", json=_nl_form())
        assert resp.status == 200
        assert "model_plan" in await resp.json()


class TestUiSurfacesTheOverride:
    """Code-review fix: a silently-ignored selection is a UX trap.

    The server already logs the mismatch and echoes the effective plan;
    these guard the browser side actually telling the operator, since a
    changed selector that does nothing and says nothing is worse than no
    selector at all.
    """

    @staticmethod
    def _dev_html() -> str:
        return (_REPO_ROOT / "examples" / "dev_loop" / "static" / "dev.html").read_text(
            encoding="utf-8"
        )

    def test_mismatch_warning_helper_exists(self):
        source = self._dev_html()
        assert "function planMismatchWarning(" in source
        assert "function showPlanWarning(" in source

    def test_warning_is_driven_by_the_run_response(self):
        source = self._dev_html()
        assert "planMismatchWarning(payload, data.model_plan)" in source

    def test_warning_does_not_use_the_collapsed_form_error_box(self):
        """#form-err lives inside #request-form, hidden once a run starts."""
        source = self._dev_html()
        warn_fn = source[source.index("function showPlanWarning("):]
        warn_fn = warn_fn[: warn_fn.index("\nasync function submit")]
        assert "form-err" not in warn_fn
        assert "exec-section" in warn_fn
