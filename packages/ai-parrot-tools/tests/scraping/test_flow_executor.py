"""Tests for FlowExecutor — FEAT-222 TASK-1452."""
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from bs4 import BeautifulSoup

from parrot_tools.scraping.flow_executor import FlowExecutor
from parrot_tools.scraping.flow_models import FlowNode, ScrapingFlow
from parrot_tools.scraping.models import ScrapingResult
from parrot_tools.scraping.template_plan import ParamSpec, TemplatePlan

EPS = "parrot_tools.scraping.flow_executor.execute_plan_steps"


# ── Helpers / fixtures ────────────────────────────────────────────────

def make_result(extracted=None, success=True, error=None, url="https://e.com"):
    return ScrapingResult(
        url=url,
        content="",
        bs_soup=BeautifulSoup("", "html.parser"),
        extracted_data=extracted or {},
        success=success,
        error_message=error,
    )


def make_browser():
    """A mock Playwright Browser; each new_context() returns a fresh context."""
    def make_context():
        ctx = MagicMock()
        ctx.close = AsyncMock()

        def make_page():
            page = MagicMock()
            page.close = AsyncMock()
            page.url = "https://e.com/page"
            return page

        ctx.new_page = AsyncMock(side_effect=make_page)
        return ctx

    browser = MagicMock()
    browser.new_context = AsyncMock(side_effect=lambda **kw: make_context())
    return browser


def simple_template(name, url_template="https://e.com/{{q}}", params=None):
    return TemplatePlan(
        name=name,
        objective_template="obj",
        url_template=url_template,
        params=params if params is not None else [
            ParamSpec(name="q", type="string", required=False, default="x")
        ],
        steps_template=[{"action": "navigate", "url": "{{url}}"}],
    )


# ── Linear flow ───────────────────────────────────────────────────────

class TestLinearFlow:
    async def test_simple_linear(self):
        flow = ScrapingFlow(name="f", nodes=[
            FlowNode(id="A", plan_ref="plan-a"),
            FlowNode(id="B", plan_ref="plan-b", inputs={"x": "A.ok"}),
        ])
        templates = {"plan-a": simple_template("plan-a"),
                     "plan-b": simple_template("plan-b")}

        calls = []

        async def fake(driver, plan, **kw):
            calls.append(plan.name)
            return make_result({"ok": plan.name})

        browser = make_browser()
        ex = FlowExecutor(browser, templates=templates)
        with patch(EPS, new=AsyncMock(side_effect=fake)):
            result = await ex.run(flow)

        assert result.success
        assert calls == ["plan-a", "plan-b"]  # topo order
        assert result.nodes_completed == 2
        assert result.nodes_total == 2
        assert result.node_results["A"] == {"ok": "plan-a"}


# ── Input resolution ──────────────────────────────────────────────────

class TestInputResolution:
    async def test_data_passes_between_nodes(self):
        flow = ScrapingFlow(name="f", nodes=[
            FlowNode(id="A", plan_ref="plan-a"),
            FlowNode(id="B", plan_ref="plan-b", inputs={"target": "A.product_url"}),
        ])
        templates = {
            "plan-a": simple_template("plan-a"),
            "plan-b": simple_template(
                "plan-b",
                url_template="https://e.com/d?u={{target}}",
                params=[ParamSpec(name="target", type="url", required=True)],
            ),
        }
        seen_plans = {}

        async def fake(driver, plan, **kw):
            seen_plans[plan.name] = plan
            if plan.name == "plan-a":
                return make_result({"product_url": "https://x.com/p"})
            return make_result({"done": True})

        ex = FlowExecutor(make_browser(), templates=templates)
        with patch(EPS, new=AsyncMock(side_effect=fake)):
            result = await ex.run(flow)

        assert result.success
        assert seen_plans["plan-b"].url == "https://e.com/d?u=https://x.com/p"

    async def test_index_reference(self):
        flow = ScrapingFlow(name="f", nodes=[
            FlowNode(id="A", plan_ref="plan-a"),
            FlowNode(id="B", plan_ref="plan-b", inputs={"q": "A.items[1]"}),
        ])
        templates = {"plan-a": simple_template("plan-a"),
                     "plan-b": simple_template("plan-b")}
        seen = {}

        async def fake(driver, plan, **kw):
            seen[plan.name] = plan
            if plan.name == "plan-a":
                return make_result({"items": ["first", "second", "third"]})
            return make_result({})

        ex = FlowExecutor(make_browser(), templates=templates)
        with patch(EPS, new=AsyncMock(side_effect=fake)):
            await ex.run(flow)

        assert seen["plan-b"].url == "https://e.com/second"


# ── Fan-out ───────────────────────────────────────────────────────────

class TestFanOut:
    async def test_fan_out_clones_per_item(self):
        flow = ScrapingFlow(name="f", nodes=[
            FlowNode(id="A", plan_ref="plan-a"),
            FlowNode(id="B", plan_ref="plan-b", inputs={"q": "A.urls[*]"}),
        ])
        templates = {"plan-a": simple_template("plan-a"),
                     "plan-b": simple_template("plan-b")}
        b_urls = []

        async def fake(driver, plan, **kw):
            if plan.name == "plan-a":
                return make_result({"urls": ["u1", "u2", "u3"]})
            b_urls.append(plan.url)
            return make_result({"v": plan.url})

        ex = FlowExecutor(make_browser(), concurrency=2, templates=templates)
        with patch(EPS, new=AsyncMock(side_effect=fake)):
            result = await ex.run(flow)

        assert result.success
        assert sorted(b_urls) == ["https://e.com/u1", "https://e.com/u2",
                                  "https://e.com/u3"]
        assert len(result.node_results["B"]["items"]) == 3


# ── Error handling ────────────────────────────────────────────────────

class TestErrorHandling:
    async def test_abort_on_error(self):
        flow = ScrapingFlow(name="f", nodes=[
            FlowNode(id="A", plan_ref="plan-a"),
            FlowNode(id="B", plan_ref="plan-b", inputs={"x": "A.ok"},
                     on_error="abort"),
            FlowNode(id="C", plan_ref="plan-c", inputs={"x": "B.ok"}),
        ])
        templates = {n: simple_template(n) for n in ("plan-a", "plan-b", "plan-c")}
        calls = []

        async def fake(driver, plan, **kw):
            calls.append(plan.name)
            if plan.name == "plan-b":
                return make_result(success=False, error="boom")
            return make_result({"ok": plan.name})

        ex = FlowExecutor(make_browser(), templates=templates)
        with patch(EPS, new=AsyncMock(side_effect=fake)):
            result = await ex.run(flow)

        assert result.success is False
        assert "B" in result.error_message
        assert "plan-c" not in calls  # flow aborted before C

    async def test_skip_on_error_cascades(self):
        flow = ScrapingFlow(name="f", nodes=[
            FlowNode(id="A", plan_ref="plan-a"),
            FlowNode(id="B", plan_ref="plan-b", inputs={"x": "A.ok"},
                     on_error="skip"),
            FlowNode(id="C", plan_ref="plan-c", inputs={"x": "B.ok"}),
            FlowNode(id="D", plan_ref="plan-d"),
        ])
        templates = {n: simple_template(n)
                     for n in ("plan-a", "plan-b", "plan-c", "plan-d")}
        calls = []

        async def fake(driver, plan, **kw):
            calls.append(plan.name)
            if plan.name == "plan-b":
                return make_result(success=False, error="boom")
            return make_result({"ok": plan.name})

        ex = FlowExecutor(make_browser(), templates=templates)
        with patch(EPS, new=AsyncMock(side_effect=fake)):
            result = await ex.run(flow)

        # Flow continues; B failed (skip), C cascaded-skipped, A and D ran.
        assert result.success is True
        assert "plan-c" not in calls
        assert "plan-a" in calls
        assert "plan-d" in calls

    async def test_retry_on_error(self):
        flow = ScrapingFlow(name="f", nodes=[
            FlowNode(id="A", plan_ref="plan-a", on_error="retry", max_retries=3),
        ])
        templates = {"plan-a": simple_template("plan-a")}
        outcomes = [
            make_result(success=False, error="e1"),
            make_result(success=False, error="e2"),
            make_result({"ok": True}, success=True),
        ]
        calls = {"n": 0}

        async def fake(driver, plan, **kw):
            i = calls["n"]
            calls["n"] += 1
            return outcomes[i]

        ex = FlowExecutor(make_browser(), templates=templates)
        with patch(EPS, new=AsyncMock(side_effect=fake)):
            result = await ex.run(flow)

        assert result.success is True
        assert calls["n"] == 3  # two failures + one success

    async def test_retry_exhausted_aborts(self):
        flow = ScrapingFlow(name="f", nodes=[
            FlowNode(id="A", plan_ref="plan-a", on_error="retry", max_retries=2),
        ])
        templates = {"plan-a": simple_template("plan-a")}

        async def fake(driver, plan, **kw):
            return make_result(success=False, error="always")

        ex = FlowExecutor(make_browser(), templates=templates)
        with patch(EPS, new=AsyncMock(side_effect=fake)):
            result = await ex.run(flow)

        assert result.success is False


# ── Multi-session ─────────────────────────────────────────────────────

class TestMultiSession:
    async def test_distinct_contexts_per_session(self):
        flow = ScrapingFlow(name="f", nodes=[
            FlowNode(id="A", plan_ref="plan-a", session="s1"),
            FlowNode(id="B", plan_ref="plan-b", inputs={"x": "A.ok"}, session="s2"),
        ])
        templates = {"plan-a": simple_template("plan-a"),
                     "plan-b": simple_template("plan-b")}

        async def fake(driver, plan, **kw):
            return make_result({"ok": plan.name})

        browser = make_browser()
        ex = FlowExecutor(browser, templates=templates)
        with patch(EPS, new=AsyncMock(side_effect=fake)):
            result = await ex.run(flow)

        assert result.success
        # Two distinct sessions → two contexts created.
        assert browser.new_context.call_count == 2

    async def test_instance_reusable_concurrently(self):
        """Session state is local to run(); one instance drives concurrent flows."""
        import asyncio

        templates = {"plan-a": simple_template("plan-a")}

        async def fake(driver, plan, **kw):
            await asyncio.sleep(0)  # yield to interleave the two runs
            return make_result({"ok": plan.name})

        ex = FlowExecutor(make_browser(), templates=templates)
        flow1 = ScrapingFlow(name="f1", nodes=[FlowNode(id="A", plan_ref="plan-a")])
        flow2 = ScrapingFlow(name="f2", nodes=[FlowNode(id="A", plan_ref="plan-a")])
        with patch(EPS, new=AsyncMock(side_effect=fake)):
            r1, r2 = await asyncio.gather(ex.run(flow1), ex.run(flow2))
        assert r1.success and r2.success
        assert r1.nodes_completed == 1 and r2.nodes_completed == 1


# ── Checkpoint & resume ───────────────────────────────────────────────

class TestCheckpointResume:
    async def test_checkpoint_written(self, tmp_path):
        flow = ScrapingFlow(name="cpflow", nodes=[
            FlowNode(id="A", plan_ref="plan-a"),
        ])
        templates = {"plan-a": simple_template("plan-a")}

        async def fake(driver, plan, **kw):
            return make_result({"product_url": "https://x.com/p"})

        ex = FlowExecutor(make_browser(), checkpoint_dir=tmp_path, templates=templates)
        with patch(EPS, new=AsyncMock(side_effect=fake)):
            result = await ex.run(flow)

        # Filename is keyed by a params token: cpflow.<token>.checkpoint.json
        assert result.checkpoint_path is not None
        cp = Path(result.checkpoint_path)
        assert cp.exists()
        assert cp.parent == tmp_path
        assert cp.name.startswith("cpflow.") and cp.name.endswith(".checkpoint.json")

    async def test_resume_skips_completed(self, tmp_path):
        flow = ScrapingFlow(name="cpflow2", nodes=[
            FlowNode(id="A", plan_ref="plan-a"),
            FlowNode(id="B", plan_ref="plan-b", inputs={"target": "A.product_url"}),
        ])
        templates = {
            "plan-a": simple_template("plan-a"),
            "plan-b": simple_template(
                "plan-b",
                url_template="https://e.com/d?u={{target}}",
                params=[ParamSpec(name="target", type="url", required=True)],
            ),
        }

        # First run: both complete, checkpoint written.
        async def fake_full(driver, plan, **kw):
            if plan.name == "plan-a":
                return make_result({"product_url": "https://x.com/p"})
            return make_result({"done": True})

        ex1 = FlowExecutor(make_browser(), checkpoint_dir=tmp_path, templates=templates)
        with patch(EPS, new=AsyncMock(side_effect=fake_full)):
            await ex1.run(flow)

        # Resume from B: A must NOT re-execute.
        resume_calls = []

        async def fake_resume(driver, plan, **kw):
            resume_calls.append(plan.name)
            return make_result({"done": True})

        ex2 = FlowExecutor(make_browser(), checkpoint_dir=tmp_path, templates=templates)
        with patch(EPS, new=AsyncMock(side_effect=fake_resume)):
            result = await ex2.run(flow, resume_from="B")

        assert result.success
        assert resume_calls == ["plan-b"]  # A skipped (loaded from checkpoint)
        assert result.resumed_from == "B"
