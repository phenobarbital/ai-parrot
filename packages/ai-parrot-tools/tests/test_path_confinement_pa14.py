"""PA-14: the real tools refuse paths outside the server-set root (real temp directories, nothing outside is touched)."""

from __future__ import annotations

from unittest.mock import AsyncMock, PropertyMock

import pytest

pytestmark = pytest.mark.asyncio

HTML = "<html><body><h1>t</h1></body></html>"


def _driver(written: list[str]):
    driver = AsyncMock()
    type(driver).current_url = PropertyMock(return_value="https://example.com/")
    driver.get_page_source = AsyncMock(return_value=HTML)
    driver.navigate = AsyncMock(return_value=None)
    driver.fill = AsyncMock(return_value=None)

    async def shot(path):
        with open(path, "wb") as fh:
            fh.write(b"png")
        written.append(str(path))

    driver.screenshot = shot
    return driver


@pytest.fixture
def scraping(tmp_path):
    pytest.importorskip("selenium")
    from parrot_tools.scraping.toolkit import WebScrapingToolkit

    plans = tmp_path / "tenant" / "plans"
    plans.mkdir(parents=True)
    toolkit = WebScrapingToolkit(plans_dir=plans, confine_paths=True, session_based=True)
    return toolkit, plans, tmp_path / "outside"


async def _scrape(toolkit, driver, steps):
    toolkit._session_driver = driver
    return await toolkit.scrape("https://example.com/", steps=steps)


async def test_screenshot_outside_the_root_is_refused_and_inside_lands_under_it(scraping):
    toolkit, plans, outside = scraping
    outside.mkdir()
    written: list[str] = []
    result = await _scrape(
        toolkit, _driver(written),
        [{"action": "screenshot", "output_path": str(outside), "output_name": "x.png"}],
    )
    assert written == [] and not list(outside.iterdir())
    assert result.metadata["step_errors"]

    result = await _scrape(
        toolkit, _driver(written), [{"action": "screenshot", "output_path": "shots", "output_name": "ok.png"}]
    )
    assert written == [str((plans / "files" / "shots" / "ok.png").resolve())]


async def test_screenshot_traversal_out_of_the_root_is_refused(scraping):
    toolkit, plans, outside = scraping
    written: list[str] = []
    await _scrape(
        toolkit, _driver(written),
        [{"action": "screenshot", "output_path": "../../../outside", "output_name": "x.png"}],
    )
    assert written == []
    assert not outside.exists()


async def test_upload_of_a_file_outside_the_root_is_refused(scraping, tmp_path):
    toolkit, plans, _ = scraping
    secret = tmp_path / "secret.txt"
    secret.write_text("s")
    driver = _driver([])
    result = await _scrape(
        toolkit, driver, [{"action": "upload_file", "selector": "input", "file_path": str(secret)}]
    )
    driver.fill.assert_not_called()
    assert result.metadata["step_errors"]


async def test_upload_of_a_file_inside_the_root_still_works(scraping):
    toolkit, plans, _ = scraping
    (plans / "files").mkdir()
    (plans / "files" / "a.txt").write_text("a")
    driver = _driver([])
    await _scrape(toolkit, driver, [{"action": "upload_file", "selector": "input", "file_path": "a.txt"}])
    driver.fill.assert_called_once()


async def test_an_unconfined_toolkit_is_unchanged(tmp_path):
    pytest.importorskip("selenium")
    from parrot_tools.scraping.toolkit import WebScrapingToolkit

    toolkit = WebScrapingToolkit(plans_dir=tmp_path / "plans", session_based=True)
    written: list[str] = []
    target = tmp_path / "anywhere"
    target.mkdir()
    await _scrape(toolkit, _driver(written), [{"action": "screenshot", "output_path": str(target), "output_name": "x.png"}])
    assert written == [str(target / "x.png")]


async def test_navigate_to_a_private_literal_is_refused_when_the_guard_is_on(scraping):
    import parrot.tools.egress as egress

    toolkit, _, _ = scraping
    driver = _driver([])
    egress.configure(True)
    try:
        await _scrape(toolkit, driver, [{"action": "navigate", "url": "http://169.254.169.254/latest/meta-data/"}])
    finally:
        egress.configure(False)
    driver.navigate.assert_not_called()


async def test_plan_delete_never_removes_a_file_outside_the_plans_dir(scraping, tmp_path):
    toolkit, plans, _ = scraping
    from parrot_tools.scraping.plan import ScrapingPlan

    victim = tmp_path / "other-tenant-plan.json"
    victim.write_text("{}")
    plan = ScrapingPlan(
        url="https://example.com/p", objective="o",
        steps=[{"action": "navigate", "url": "https://example.com/p"}],
    )
    registry = await toolkit._ensure_registry()
    await registry.register(plan, "../../../other-tenant-plan.json")
    with pytest.raises(ValueError):
        await toolkit.plan_delete(plan.name)
    assert victim.exists()


async def test_a_plan_whose_domain_traverses_is_not_written_outside(scraping, tmp_path):
    from parrot_tools.scraping.plan import ScrapingPlan
    from parrot_tools.scraping.plan_io import save_plan_to_disk

    toolkit, plans, _ = scraping
    plan = ScrapingPlan(
        url="https://example.com/p", objective="o",
        steps=[{"action": "navigate", "url": "https://example.com/p"}],
    )
    object.__setattr__(plan, "domain", "../../escaped")
    with pytest.raises(ValueError):
        await save_plan_to_disk(plan, plans)
    assert not (tmp_path / "escaped").exists()


# ── document_converter ───────────────────────────────────────────────────────────────────────────────────────────────


async def test_document_converter_url_only_never_reads_a_local_file(tmp_path):
    from parrot_tools.doc_converter import DocumentConverterTool

    secret = tmp_path / "secret.pdf"
    secret.write_bytes(b"%PDF-1.4 secret")
    tool = DocumentConverterTool(url_only=True)
    result = await tool._execute(source=str(secret))
    assert result.success is False and "http(s) URL" in result.error
    result = await tool._execute(source=f"file://{secret}")
    assert result.success is False


async def test_document_converter_url_only_does_not_fetch_a_private_url():
    import parrot.tools.egress as egress
    from aiohttp import web
    from parrot_tools.doc_converter import DocumentConverterTool

    hits: list[str] = []

    async def handler(request):
        hits.append(request.path)
        return web.Response(body=b"x")

    app = web.Application()
    app.router.add_get("/{t:.*}", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.2", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    egress.configure(True)
    try:
        result = await DocumentConverterTool(url_only=True)._execute(source=f"http://127.0.0.2:{port}/a.pdf")
    finally:
        egress.configure(False)
        await runner.cleanup()
    assert result.success is False and hits == []


# ── wiki ─────────────────────────────────────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def wiki(tmp_path):
    from unittest.mock import Mock

    from parrot.knowledge.wiki.toolkit import LLMWikiToolkit
    from parrot.knowledge.wiki.models import WikiConfig

    config = WikiConfig(wiki_name="w", storage_dir=tmp_path / "wiki", storage_backend="memory")
    toolkit = LLMWikiToolkit(
        pageindex_toolkit=Mock(), graphindex_toolkit=Mock(), okf_toolkit=Mock(), config=config, confine_sources=True
    )
    toolkit._ingest_orch = Mock()
    toolkit._ingest_orch.ingest = AsyncMock(return_value=Mock(model_dump=lambda: {"status": "ok"}))
    return toolkit, tmp_path


async def test_wiki_ingest_source_refuses_a_path_outside_the_upload_root(wiki):
    toolkit, tmp_path = wiki
    secret = tmp_path / "etc-passwd"
    secret.write_text("root")
    with pytest.raises(ValueError):
        await toolkit.ingest_source("w", str(secret))
    with pytest.raises(ValueError):
        await toolkit.ingest_source("w", "../../etc-passwd")
    toolkit._ingest_orch.ingest.assert_not_called()


async def test_wiki_ingest_source_accepts_a_file_under_the_upload_root_and_a_url(wiki):
    toolkit, tmp_path = wiki
    uploads = tmp_path / "wiki" / "sources"
    uploads.mkdir(parents=True, exist_ok=True)
    (uploads / "note.md").write_text("# n")
    assert (await toolkit.ingest_source("w", "note.md"))["status"] == "ok"
    assert toolkit._ingest_orch.ingest.call_args[0][0] == str((uploads / "note.md").resolve())
    await toolkit.ingest_source("w", "https://example.com/doc.md")
    assert toolkit._ingest_orch.ingest.call_args[0][0] == "https://example.com/doc.md"


async def test_wiki_unconfined_toolkit_still_takes_any_path(tmp_path):
    from unittest.mock import Mock

    from parrot.knowledge.wiki.toolkit import LLMWikiToolkit
    from parrot.knowledge.wiki.models import WikiConfig

    config = WikiConfig(wiki_name="w", storage_dir=tmp_path / "wiki", storage_backend="memory")
    toolkit = LLMWikiToolkit(pageindex_toolkit=Mock(), graphindex_toolkit=Mock(), okf_toolkit=Mock(), config=config)
    toolkit._ingest_orch = Mock()
    toolkit._ingest_orch.ingest = AsyncMock(return_value=Mock(model_dump=lambda: {"status": "ok"}))
    await toolkit.ingest_source("w", "/anywhere/x.md")
    assert toolkit._ingest_orch.ingest.call_args[0][0] == "/anywhere/x.md"


# -- PA-V2 review fix 2: the joined destination, the file name included ----------------------------------------------


@pytest.mark.parametrize(
    "name", ["../x", "../../../outside/x", "sub/../../x", "/tmp/abs-x", "a\\..\\..\\x"],
    ids=["dotdot", "deep", "inner", "absolute", "backslash"],
)
async def test_an_output_name_with_path_components_cannot_leave_the_root(scraping, tmp_path, name):
    toolkit, plans, _ = scraping
    written: list[str] = []
    result = await _scrape(toolkit, _driver(written), [{"action": "screenshot", "output_path": ".", "output_name": name}])
    assert written == [] and result.metadata["step_errors"]
    assert not (plans / "x.png").exists() and not (tmp_path / "x.png").exists()
    assert not [p for p in tmp_path.rglob("*.png")]


async def test_a_plain_output_name_still_lands_in_the_root(scraping):
    toolkit, plans, _ = scraping
    written: list[str] = []
    await _scrape(toolkit, _driver(written), [{"action": "screenshot", "output_path": "shots", "output_name": "p"}])
    assert written == [str((plans / "files" / "shots" / "p.png").resolve())]


async def test_a_symlinked_name_inside_the_root_cannot_leave_it(scraping, tmp_path):
    toolkit, plans, outside = scraping
    outside.mkdir()
    (plans / "files").mkdir()
    (plans / "files" / "p.png").symlink_to(outside / "stolen.png")
    written: list[str] = []
    await _scrape(toolkit, _driver(written), [{"action": "screenshot", "output_path": ".", "output_name": "p"}])
    assert written == [] and not list(outside.iterdir())


def test_a_null_byte_is_a_confinement_error_not_a_crash(tmp_path):
    from parrot_tools.scraping.confine import FILES_ROOT, PathConfinementError, within_root

    token = FILES_ROOT.set(tmp_path)
    try:
        with pytest.raises(PathConfinementError):
            within_root("a\0b")
    finally:
        FILES_ROOT.reset(token)


@pytest.fixture
def direct_tool(tmp_path):
    pytest.importorskip("selenium")
    from parrot_tools.scraping.tool import WebScrapingTool

    plans = tmp_path / "tenant" / "plans"
    plans.mkdir(parents=True)
    with pytest.warns(DeprecationWarning):
        tool = WebScrapingTool(plans_dir=plans, confine_paths=True, auto_install=False)
    return tool, plans


async def test_a_directly_used_scraping_tool_confines_screenshots_too(direct_tool, tmp_path):
    """``WebScrapingTool`` with no toolkit around it: its own workflow sets the file root (real tool, fake browser)."""
    from unittest.mock import AsyncMock, MagicMock

    from parrot_tools.scraping.confine import FILES_ROOT
    from parrot_tools.scraping.models import Screenshot, ScrapingStep

    tool, plans = direct_tool
    tool.driver_type = "selenium"
    tool.delay_between_actions = 0
    tool.driver = MagicMock()
    tool.driver.get_screenshot_as_png.return_value = b"png"
    tool.driver.page_source = "<html><body>t</body></html>"
    tool.driver.current_url = "https://example.com/"
    tool._session_alive = lambda: True
    tool.cleanup = AsyncMock()

    def step(name):
        return ScrapingStep(action=Screenshot(output_path=".", output_name=name), description="shot")

    await tool.execute_scraping_workflow([step("../escaped")])
    assert not list(tmp_path.rglob("escaped*"))                         # the traversal name is refused
    await tool.execute_scraping_workflow([step("kept")])
    assert (plans / "files" / "kept.png").read_bytes() == b"png"        # a plain name lands under the root
    assert FILES_ROOT.get() is None                                     # and the root does not leak out of the call


# -- PA-V2 review fix 5: the browser never navigates to a disguised or resolved-internal host -------------------------


@pytest.mark.parametrize(
    "url",
    ["http://127.1/", "http://0x7f.0.0.1/", "http://0177.0.0.1/", "http://localhost./", "http://127.0.0.1./",
     "http://metadata.google.internal/computeMetadata/v1/", "http://169.254.169.254./latest/meta-data/"],
)
async def test_navigate_refuses_the_disguised_internal_hosts(scraping, url):
    import parrot.tools.egress as egress

    toolkit, _, _ = scraping
    driver = _driver([])
    egress.configure(True)
    try:
        await _scrape(toolkit, driver, [{"action": "navigate", "url": url}])
    finally:
        egress.configure(False)
    driver.navigate.assert_not_called()


async def test_navigate_resolves_a_name_and_refuses_a_private_answer(scraping, monkeypatch):
    import aiohttp
    import parrot.tools.egress as egress

    async def private(self, host, port=0, family=0):
        return [{"hostname": host, "host": "10.9.8.7", "port": port, "family": family, "proto": 0, "flags": 0}]

    monkeypatch.setattr(aiohttp.ThreadedResolver, "resolve", private)
    toolkit, _, _ = scraping
    driver = _driver([])
    egress.configure(True)
    try:
        await _scrape(toolkit, driver, [{"action": "navigate", "url": "http://rebind.example.com/"}])
    finally:
        egress.configure(False)
    driver.navigate.assert_not_called()
