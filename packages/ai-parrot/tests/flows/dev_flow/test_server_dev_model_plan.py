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
    async def _make(
        *,
        checkpoint_store: Any = None,
        dev_loop_flow_kwargs: dict[str, Any] | None = None,
        **app_overrides: Any,
    ):
        flow = _StubFlow()
        app = server_dev.build_app(redis_url="redis://x")
        app.on_startup.clear()
        app.on_cleanup.clear()
        # FEAT-490: `dev_loop_flow_kwargs` is what turns the runner's
        # recovery path on (same knob as test_server_dev.py's own
        # `make_client`) — omitted (the default) keeps every EXISTING test
        # below on the pre-FEAT-490 code path. Tests that need to exercise
        # an actual resume pass it (and a `checkpoint_store`) explicitly.
        runner = DevFlowRunner(
            flow,
            redis_url="redis://x",
            checkpoint_store=checkpoint_store,
            dev_loop_flow_kwargs=dev_loop_flow_kwargs,
        )
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
        client = await aiohttp_client(app)
        client.app_flow = flow  # type: ignore[attr-defined]
        client.app_runner = runner  # type: ignore[attr-defined]
        return client

    return _make


@pytest.fixture
def fake_store():
    """The in-memory CheckpointStore from the recovery suite (not re-declared)."""
    from .test_recovery import FakeCheckpointStore

    return FakeCheckpointStore()


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
        # Derived from llm_catalog.backends_for_role("research_partner")
        # (catalog order) instead of a hardcoded literal — assert the
        # membership, not the ordering.
        assert set(plan["partner_backends"]) == {"gpt", "nova"}

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
            server_dev._parse_model_plan({"review": {"primary": {"agent": "nova"}}})

    def test_model_ids_are_free_text(self, server_dev):
        """Catalog model lists are a suggestion, never a whitelist."""
        plan = server_dev._parse_model_plan({"dev_agents": [{"agent": "nova", "model": "not-in-any-catalog-list"}]})
        assert plan.dev_pool[0].model == "not-in-any-catalog-list"

    def test_partner_only_payload(self, server_dev):
        plan = server_dev._parse_model_plan({"research_partner": {"enabled": True}})
        assert plan.research_partner.enabled is True
        assert plan.dev_pool == []


@pytest.mark.asyncio
class TestRunEndpoint:
    async def test_run_accepts_a_valid_plan(self, make_client):
        client = await make_client()
        resp = await client.post(
            "/api/flow/run",
            json=_nl_form(
                dev_agents=[{"agent": "nova", "model": "zai.glm-5", "count": 1}],
                research_primary="claude-opus-5",
            ),
        )
        assert resp.status == 200
        body = await resp.json()
        assert body["model_plan"]["research_primary"] == "claude-opus-5"

    async def test_console_mints_a_fresh_run_id_when_none_is_supplied(self, make_client):
        """Pins the premise the fresh-path reporting rests on (spec §8 Q4).

        `handle_run` mints its own `run_id` (`f"run-{uuid.uuid4().hex[:8]}"`)
        whenever the payload carries none — that half of the spec's premise
        holds. What the spec did NOT anticipate (its §1 "no resume
        endpoint" claim, written before `_parse_resume_run_id` landed) is
        that a caller who DOES supply a `run_id` opts into a resume
        instead — see `TestRunResponseReportsIgnoredSeats`'s resume tests
        for that corrected branch.
        """
        client = await make_client()
        resp1 = await client.post("/api/flow/run", json=_nl_form())
        resp2 = await client.post("/api/flow/run", json=_nl_form())

        run_id_1 = (await resp1.json())["run_id"]
        run_id_2 = (await resp2.json())["run_id"]
        assert run_id_1.startswith("run-")
        assert run_id_2.startswith("run-")
        assert run_id_1 != run_id_2

    async def test_run_rejects_unknown_backend_with_supported_list(self, make_client):
        client = await make_client()
        resp = await client.post("/api/flow/run", json=_nl_form(dev_agents=[{"agent": "bogus"}]))
        assert resp.status == 400
        error = (await resp.json())["error"]
        assert "bogus" in error
        assert "claude-code" in error

    async def test_run_rejects_unknown_review_primary(self, make_client):
        client = await make_client()
        resp = await client.post("/api/flow/run", json=_nl_form(review={"primary": {"agent": "nova"}}))
        assert resp.status == 400
        assert "primary reviewer" in (await resp.json())["error"]

    async def test_response_echoes_the_effective_plan(self, make_client):
        """FEAT-490: a fresh console run genuinely applies the submission —
        the response must echo it, not the server's static build-time plan
        (which is the pre-FEAT-490 behaviour, now only true on a resume)."""
        client = await make_client()
        resp = await client.post(
            "/api/flow/run", json=_nl_form(dev_agents=[{"agent": "claude-code", "model": "", "count": 1}])
        )
        body = await resp.json()
        assert [(r["agent"], r["model"]) for r in body["model_plan"]["dev_agents"]] == [
            ("claude-code", ""),
        ]

    async def test_run_endpoint_applies_ideation_model(self, make_client):
        """Spec §4: a differing research_primary builds THIS run with it —
        the response echoes it back, with no server restart."""
        client = await make_client()
        resp = await client.post(
            "/api/flow/run", json=_nl_form(research_primary="claude-sonnet-5")
        )
        body = await resp.json()
        assert body["model_plan"]["research_primary"] == "claude-sonnet-5"

    async def test_run_without_plan_fields_still_works(self, make_client):
        client = await make_client()
        resp = await client.post("/api/flow/run", json=_nl_form())
        assert resp.status == 200
        assert "model_plan" in await resp.json()


class TestPlanMismatchDiff:
    """The mismatch report must NAME the differing seat.

    Regression: the warning was gated on whole-model ``!=`` equality but
    printed four values (pool, research primary, review primary agent,
    counter model), so a difference in ``research_partner.*``,
    ``review.primary.model`` or a seat's ``count`` logged two identical-looking
    plans and read as a false positive.
    """

    @staticmethod
    def _roundtrip_form(server_dev, plan) -> dict[str, Any]:
        """Rebuild the payload the console posts back after hydrating from /api/config."""
        payload = server_dev._model_plan_payload(plan)
        return {
            "dev_agents": [
                {"agent": row["agent"], "model": row["model"], "count": row["count"]} for row in payload["dev_agents"]
            ],
            "research_primary": payload["research_primary"],
            "research_partner": dict(payload["research_partner"]),
            "review": {
                "primary": dict(payload["review"]["primary"]),
                "counter_model": payload["review"]["counter_model"],
            },
        }

    def test_hydrated_form_produces_no_diff(self, server_dev):
        """An untouched console form is not a mismatch."""
        effective = server_dev._console_default_model_plan()
        requested = server_dev._parse_model_plan(self._roundtrip_form(server_dev, effective))
        assert server_dev._plan_field_diffs(requested, effective) == []

    def test_partner_toggle_is_named(self, server_dev):
        """The field that used to be invisible in the warning."""
        effective = server_dev._console_default_model_plan()
        form = self._roundtrip_form(server_dev, effective)
        form["research_partner"]["enabled"] = True
        diffs = server_dev._plan_field_diffs(server_dev._parse_model_plan(form), effective)
        assert diffs == ["research_partner.enabled: requested=True effective=False"]

    def test_review_primary_model_is_named(self, server_dev):
        effective = server_dev._console_default_model_plan()
        form = self._roundtrip_form(server_dev, effective)
        form["review"]["primary"]["model"] = "claude-sonnet-5"
        diffs = server_dev._plan_field_diffs(server_dev._parse_model_plan(form), effective)
        assert diffs == ["review.primary.model: requested='claude-sonnet-5' effective='claude-opus-5'"]

    def test_blank_field_expresses_nothing(self, server_dev):
        """A cleared input means 'server default', never an ignored choice."""
        effective = server_dev._console_default_model_plan()
        form = self._roundtrip_form(server_dev, effective)
        form["review"]["primary"]["model"] = ""
        form["research_partner"]["model"] = ""
        assert server_dev._plan_field_diffs(server_dev._parse_model_plan(form), effective) == []

    def test_pool_seat_diff_names_the_seat(self, server_dev):
        effective = server_dev._console_default_model_plan()
        form = self._roundtrip_form(server_dev, effective)
        form["dev_agents"][1]["count"] = 3
        diffs = server_dev._plan_field_diffs(server_dev._parse_model_plan(form), effective)
        assert diffs == ["dev_pool[1].count: requested=3 effective=1"]

    def test_pool_length_diff_renders_both_pools(self, server_dev):
        effective = server_dev._console_default_model_plan()
        form = self._roundtrip_form(server_dev, effective)
        form["dev_agents"] = [{"agent": "claude-code", "model": "claude-opus-5", "count": 1}]
        diffs = server_dev._plan_field_diffs(server_dev._parse_model_plan(form), effective)
        assert diffs == [
            (
                "dev_pool: requested=claude-code:claude-opus-5 "
                "effective=nova:zai.glm-5, nova:qwen.qwen3-coder-480b-a35b-v1:0"
            )
        ]


@pytest.mark.asyncio
class TestRunResponseReportsIgnoredSeats:
    """FEAT-490: a fresh console run now genuinely APPLIES a submitted plan
    (TASK-2686/2688), so ``model_plan_ignored`` is always ``[]`` for one —
    even when the submission differs from the server's static default.
    The one case that remains is a RESUME (TASK-2687's rule: the run keeps
    the seats it was created with), simulated below the same way
    ``test_server_dev.py``'s own resume suite does — ``run_id`` in the
    payload + a stubbed ``inspect_checkpoint``/``prepare`` reporting
    ``"resumed"`` — since ``handle_run`` decides ``model_plan_ignored``
    synchronously from ``resume_run_id``, before the background run even
    starts.
    """

    async def test_matching_plan_reports_nothing_ignored(self, make_client, server_dev):
        client = await make_client()
        form = TestPlanMismatchDiff._roundtrip_form(server_dev, server_dev._console_default_model_plan())
        resp = await client.post("/api/flow/run", json=_nl_form(**form))
        assert (await resp.json())["model_plan_ignored"] == []

    async def test_run_endpoint_reports_nothing_ignored_on_fresh_run(self, make_client, server_dev):
        """A differing submission on a FRESH run is fully honoured now."""
        client = await make_client()
        form = TestPlanMismatchDiff._roundtrip_form(server_dev, server_dev._console_default_model_plan())
        form["research_partner"]["enabled"] = True
        resp = await client.post("/api/flow/run", json=_nl_form(**form))
        assert (await resp.json())["model_plan_ignored"] == []

    async def test_dev_pool_is_never_reported_as_ignored(self, make_client, server_dev):
        """The development pool IS per-run — reporting it as ignored was wrong.

        The console's `dev_agents` rows also travel on the brief, and
        `DevelopmentNode._resolve_pool_config` reads the brief before its
        injected build-time config, so a per-run pool really does take
        effect regardless of the ideation/review seats above.
        """
        client = await make_client()
        form = TestPlanMismatchDiff._roundtrip_form(server_dev, server_dev._console_default_model_plan())
        form["dev_agents"] = [{"agent": "nova", "model": "moonshotai.kimi-k2.5", "count": 1}]
        resp = await client.post("/api/flow/run", json=_nl_form(**form))
        body = await resp.json()

        assert body["model_plan_ignored"] == []
        # ...and the rows still reach the flow on the brief.
        flow = client.app["flow"]
        brief = flow.contexts[-1].shared_data["dev_brief"]
        assert [(spec.agent, spec.model) for spec in brief.dev_agents] == [("nova", "moonshotai.kimi-k2.5")]

    @staticmethod
    async def _resume_client(make_client, run_id: str, *, monkeypatch):
        """A console client wired for recovery, with `run_id` preflighted
        as a resumable checkpoint (mirrors test_server_dev.py's own
        `test_resumable_run_id_is_used_as_the_run_identity`)."""
        client = await make_client(dev_loop_flow_kwargs={"skip_qa": False})

        async def _fake_inspect(rid, *, brief=None):
            return {
                "run_id": rid,
                "workflow": "dev-flow",
                "flow_id": f"dev-flow/{rid}",
                "recovery_enabled": True,
                "found": True,
                "resumable": True,
                "reason": None,
                "status": "running",
                "checkpoint_id": 1,
                "created_at": "2026-09-01T10:00:00+00:00",
                "completed_nodes": ["dev_intake", "ideation", "planner"],
            }

        monkeypatch.setattr(client.app_runner, "inspect_checkpoint", _fake_inspect)

        async def _fake_prepare(**kwargs):
            return client.app_flow, "resumed"

        monkeypatch.setattr(client.app_runner._checkpoint_coordinator, "prepare", _fake_prepare)
        return client

    async def test_ignored_seat_is_reported_on_resume(self, make_client, server_dev, monkeypatch):
        """A differing submission on a RESUME is reported as not applied —
        the run keeps the seats it was created with (spec §8 Q1)."""
        client = await self._resume_client(make_client, "run-resume-diff", monkeypatch=monkeypatch)
        form = TestPlanMismatchDiff._roundtrip_form(server_dev, server_dev._console_default_model_plan())
        form["research_partner"]["enabled"] = True
        form["run_id"] = "run-resume-diff"

        resp = await client.post("/api/flow/run", json=_nl_form(**form))

        assert resp.status == 200
        body = await resp.json()
        assert body["model_plan_ignored"] == ["research_partner.enabled: requested=True effective=False"]
        # ...and the response echoes the server's default (what the resumed
        # run actually keeps), not the submission.
        assert body["model_plan"]["research_partner"]["enabled"] is False

    async def test_matching_plan_on_resume_reports_nothing_ignored(self, make_client, server_dev, monkeypatch):
        client = await self._resume_client(make_client, "run-resume-match", monkeypatch=monkeypatch)
        form = TestPlanMismatchDiff._roundtrip_form(server_dev, server_dev._console_default_model_plan())
        form["run_id"] = "run-resume-match"

        resp = await client.post("/api/flow/run", json=_nl_form(**form))

        assert (await resp.json())["model_plan_ignored"] == []

    async def test_warning_names_the_differing_seat_on_resume(self, make_client, server_dev, monkeypatch, caplog):
        import logging

        client = await self._resume_client(make_client, "run-resume-warn", monkeypatch=monkeypatch)
        form = TestPlanMismatchDiff._roundtrip_form(server_dev, server_dev._console_default_model_plan())
        form["research_partner"]["enabled"] = True
        form["run_id"] = "run-resume-warn"

        with caplog.at_level(logging.WARNING, logger="dev_flow.server"):
            await client.post("/api/flow/run", json=_nl_form(**form))

        assert any("research_partner.enabled" in record.getMessage() for record in caplog.records)
        # The copy no longer tells the operator to restart the console for
        # a seat that is now per-run (TASK-2689 narrows dev.html/README to
        # match) — this backend log line is the resume-specific half.
        assert any("resumed a checkpoint" in record.getMessage() for record in caplog.records)


class TestUiSurfacesTheOverride:
    """Code-review fix: a silently-ignored selection is a UX trap.

    The server already logs the mismatch and echoes the effective plan;
    these guard the browser side actually telling the operator, since a
    changed selector that does nothing and says nothing is worse than no
    selector at all.
    """

    @staticmethod
    def _dev_html() -> str:
        return (_REPO_ROOT / "examples" / "dev_loop" / "static" / "dev.html").read_text(encoding="utf-8")

    def test_mismatch_warning_helper_exists(self):
        source = self._dev_html()
        assert "function planMismatchWarning(" in source
        assert "function showPlanWarning(" in source

    def test_warning_is_driven_by_the_run_response(self):
        source = self._dev_html()
        assert "planMismatchWarning(data)" in source
        assert "model_plan_ignored" in source

    def test_warning_does_not_use_the_collapsed_form_error_box(self):
        """#form-err lives inside #request-form, hidden once a run starts."""
        source = self._dev_html()
        warn_fn = source[source.index("function showPlanWarning(") :]
        warn_fn = warn_fn[: warn_fn.index("\nasync function submit")]
        assert "form-err" not in warn_fn
        assert "exec-section" in warn_fn

    def test_ui_banner_no_longer_tells_operators_to_restart(self):
        """FEAT-490 TASK-2689: seats are per-run now — the banner must stop
        telling operators to restart the console with DEV_FLOW_* env keys,
        and must instead name the one case that remains (a resumed run
        keeping its original seats)."""
        source = self._dev_html()
        warn_fn = source[source.index("function planMismatchWarning(") :]
        warn_fn = warn_fn[: warn_fn.index("\nfunction showPlanWarning(")]
        assert "restart" not in warn_fn.lower()
        assert "DEV_FLOW_*" not in warn_fn
        assert "resumed a checkpoint" in warn_fn

    def test_readme_no_longer_tells_operators_to_restart(self):
        """Same correction applied to the README's model-plan section."""
        source = (_REPO_ROOT / "examples" / "dev_loop" / "README.md").read_text(encoding="utf-8")
        section = source[source.index("### Per-seat LLM selectors") :]
        section = section[: section.index("### New configuration keys")]
        assert "restart the console" not in section
        assert "per-run" in section
        assert "resumed run" in section
