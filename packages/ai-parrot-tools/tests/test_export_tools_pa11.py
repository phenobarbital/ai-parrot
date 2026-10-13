"""PA-11: export tools take no path arguments and write ONLY through the tenant-partitioned artifact store.

Real tools, a real ``ArtifactStore`` (SQLite backend + local file manager); a filesystem snapshot over HOME, the temp
directory, the working directory and the tools' own output/template directories proves nothing else is written. The
tool scope is bound exactly as the Studio runtime binds it (``studio_scope`` in the request context).
"""
from __future__ import annotations

import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

import pandas as pd
import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request
from navigator.utils.file import LocalFileManager

from parrot.storage.artifacts import ArtifactStore
from parrot.tools import abstract as abstract_module
from parrot.storage.backends.sqlite import ConversationSQLiteBackend
from parrot.storage.exports import parse_export_key
from parrot.storage.overflow import OverflowStore
from parrot.utils.helpers import RequestContext, _current_ctx

STRIPPED = {
    "output_dir", "output_filename", "overwrite_existing", "filename", "export_csv_path", "parquet_path",
    "pptx_template_path", "stylesheets", "artifact_store",
}
AGENT_ID = uuid4()


@dataclass
class _Caller:
    tenant: str | None = "acme"
    user_id: str = "u1"
    groups: frozenset = frozenset()
    is_superuser: bool = False


@dataclass
class _Agent:
    agent_id: object = AGENT_ID
    name: str = "reporter"
    owner: str | None = "u1"
    tenant: str | None = "acme"
    visibility: str = "private"


@dataclass
class _Scope:
    caller: _Caller = field(default_factory=_Caller)
    agent: _Agent | None = field(default_factory=_Agent)


@contextmanager
def studio_scope(tenant: str | None = "acme", agent: _Agent | None = None):
    scope = _Scope(caller=_Caller(tenant=tenant), agent=agent if agent is not None else _Agent(tenant=tenant))
    token = _current_ctx.set(RequestContext(request=make_mocked_request("POST", "/x"), studio_scope=scope))
    try:
        yield
    finally:
        _current_ctx.reset(token)


@pytest.fixture(autouse=True)
def _store_only_mode():
    """PA-11 is the host's opt-in store-only mode (``app[STUDIO_EXPORTS_STORE_ONLY]``): every test here runs with it ON."""
    import parrot.tools.exports_mode as exports_mode

    exports_mode.configure(True)
    yield
    exports_mode.configure(False)


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """HOME, TMPDIR and the working directory are fresh directories; ``watch`` lists every file under them."""
    home, tmp, cwd, static, tpl = (tmp_path / name for name in ("home", "tmp", "cwd", "static", "templates"))
    out = static / "out"
    for path in (home, tmp, cwd, static, out, tpl):
        path.mkdir()
    monkeypatch.setattr(abstract_module, "STATIC_DIR", static)  # the base every tool output_dir must stay under
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("TMPDIR", str(tmp))
    monkeypatch.setattr(tempfile, "tempdir", str(tmp))
    monkeypatch.chdir(cwd)

    class Box:
        pass

    box = Box()
    box.root, box.out, box.tpl, box.tmp = tmp_path, out, tpl, tmp
    box.roots = (home, tmp, cwd, static, tpl)

    def watch() -> set[str]:
        return {str(p) for root in box.roots for p in root.rglob("*") if p.is_file()}

    box.watch = watch
    return box


@pytest.fixture
def store(tmp_path):
    return ArtifactStore(
        dynamodb=ConversationSQLiteBackend(str(tmp_path / "c.db")),
        s3_overflow=OverflowStore(LocalFileManager(base_path=tmp_path / "files")),
    )


def _rows():
    return [{"city": "Madrid", "n": 1}, {"city": "Lyon", "n": 2}]


def _export_of(result) -> dict:
    """``{url, filename, bytes}`` out of a dict or ``ToolResult`` result."""
    payload = getattr(result, "result", result)
    candidates = [payload, getattr(result, "metadata", None) or {}]
    if isinstance(payload, dict):
        candidates += [payload.get("result") or {}, payload.get("metadata") or {}]
    for item in candidates:
        if isinstance(item, dict) and {"url", "filename", "bytes"} <= set(item):
            return item
    raise AssertionError(f"no export in {result!r}")


def _ok(result) -> bool:
    payload = getattr(result, "result", result)
    inner = payload.get("status") if isinstance(payload, dict) else None
    status = getattr(result, "status", None) or (result.get("status") if isinstance(result, dict) else None)
    return status in ("success", None) and inner != "error" and getattr(result, "success", True) is not False


# -- the tools --------------------------------------------------------------------------------------------------


def _excel(box, store):
    from parrot_tools.excel import ExcelTool

    return ExcelTool(templates_dir=box.tpl, output_dir=box.out, artifact_store=store), {"content": _rows()}


def _df_excel(box, store):
    from parrot_tools.excel import DataFrameToExcelTool

    return DataFrameToExcelTool(templates_dir=box.tpl, output_dir=box.out, artifact_store=store), {"content": _rows()}


def _csv(box, store):
    from parrot_tools.csv_export import CSVExportTool

    return CSVExportTool(output_dir=box.out, artifact_store=store), {"content": _rows()}


def _df_csv(box, store):
    from parrot_tools.csv_export import DataFrameToCSVTool

    return DataFrameToCSVTool(output_dir=box.out, artifact_store=store), {"content": _rows()}


def _word(box, store):
    from parrot_tools.msword import MSWordTool

    return MSWordTool(templates_dir=box.tpl, output_dir=box.out, artifact_store=store), {"content": "# Title\n\nHello"}


def _pptx(box, store):
    from parrot_tools.powerpoint import PowerPointTool

    tool = PowerPointTool(templates_dir=box.tpl, output_dir=box.out, artifact_store=store)
    return tool, {"content": "# Slide\n\n- one\n- two"}


def _pdf(box, store):
    from parrot_tools.pdfprint import PDFPrintTool

    return PDFPrintTool(templates_dir=box.tpl, output_dir=box.out, artifact_store=store), {"text": "# Report\n\nBody"}


def _html(box, store):
    from parrot_tools.dftohtml import DfToHtmlTool

    return DfToHtmlTool(output_dir=box.out, artifact_store=store), {"dataframe": pd.DataFrame(_rows())}


def _chart(box, store):
    from parrot_tools.chart import ChartTool

    tool = ChartTool(output_dir=box.tmp / "parrot_charts", artifact_store=store)
    return tool, {"chart_type": "bar", "title": "Sales", "data": {"categories": ["a", "b"], "values": [1, 2]}}


FACTORIES = {
    "excel": _excel, "data_frame_to_excel": _df_excel, "csv_export": _csv, "data_frame_to_csv": _df_csv,
    "ms_word": _word, "power_point": _pptx, "pdf_print": _pdf, "df_to_html": _html, "chart": _chart,
}


@pytest.mark.parametrize("name", sorted(FACTORIES))
def test_the_llm_schema_has_no_path_overwrite_or_template_path_argument(name, sandbox, store):
    tool, _ = FACTORIES[name](sandbox, store)
    properties = set(tool.get_schema()["parameters"]["properties"])   # what the LLM is actually shown
    assert not properties & STRIPPED, properties & STRIPPED
    assert "artifact_store" in type(tool).server_managed_params


@pytest.mark.parametrize("name", sorted(FACTORIES))
async def test_a_call_writes_only_into_the_store_and_returns_a_url(name, sandbox, store):
    tool, args = FACTORIES[name](sandbox, store)
    before = sandbox.watch()
    with studio_scope("acme"):
        # the LLM tries to choose a destination: it is not in the schema, so it is dropped, never honoured
        result = await tool.execute(**args, output_dir=str(sandbox.root / "evil"), output_filename="../../pwned",
                                    overwrite_existing=True, filename="../../pwned")
    assert _ok(result), result
    exported = _export_of(result)
    assert exported["url"].startswith("/api/v1/astudio/exports/acme/") and exported["bytes"] > 0
    assert sandbox.watch() == before, sorted(sandbox.watch() - before)           # no other file anywhere
    assert not (sandbox.root / "evil").exists() and not any(sandbox.root.glob("pwned*"))
    tenant, agent, _, filename = parse_export_key(exported["url"].removeprefix("/api/v1/astudio/exports/"))
    assert tenant == "acme" and agent == str(AGENT_ID) and filename == exported["filename"]
    key = exported["url"].removeprefix("/api/v1/astudio/exports/")
    stored = await store.get_export(key, tenant="acme")
    assert stored is not None and len(stored.data) == exported["bytes"]
    assert await store.get_export(key, tenant="globex") is None                  # the partition is the tenant's


@pytest.mark.parametrize("name", sorted(FACTORIES))
async def test_a_studio_call_without_a_store_never_writes_a_local_file(name, sandbox, store):
    tool, args = FACTORIES[name](sandbox, None)
    before = sandbox.watch()
    with studio_scope("acme"):
        result = await tool.execute(**args)
    assert not _ok(result), result
    assert "store" in str(getattr(result, "error", None) or result).lower()
    assert sandbox.watch() == before


async def test_df_to_html_ignores_a_traversal_filename(sandbox, store):
    from parrot_tools.dftohtml import DfToHtmlTool

    tool = DfToHtmlTool(output_dir=sandbox.out, artifact_store=store)
    before = sandbox.watch()
    with studio_scope("acme"):
        result = await tool._execute(dataframe=pd.DataFrame(_rows()), filename="../../x")
    assert _export_of(result)["filename"].startswith("table_") and not (sandbox.root / "x.html").exists()
    assert sandbox.watch() == before


@pytest.mark.parametrize(
    "name,field,value",
    [("excel", "template_file", "/etc/passwd"), ("excel", "template_file", "../x.xlsx"),
     ("ms_word", "docx_template", "/abs/t.docx"), ("ms_word", "template_name", "../../evil.html"),
     ("ms_word", "template_name", "/abs/t.html"), ("power_point", "pptx_template", "/abs/t.pptx"),
     ("power_point", "pptx_template", "sub/t.pptx"), ("power_point", "template_name", "../t.html"),
     ("pdf_print", "template_name", "/abs/t.html"), ("pdf_print", "template_name", "../t.html")],
)
async def test_a_template_must_be_a_name_never_a_path(name, field, value, sandbox, store):
    tool, args = FACTORIES[name](sandbox, store)
    before = sandbox.watch()
    with studio_scope("acme"):
        try:
            result = await tool.execute(**args, **{field: value})
        except ValueError:
            result = None                                                         # refused at validation
    assert result is None or not _ok(result), result
    assert sandbox.watch() == before


async def test_a_plain_template_name_still_works(sandbox, store):
    (sandbox.tpl / "memo.html").write_text("<html><body>{{ content }}</body></html>")
    tool, args = _word(sandbox, store)
    with studio_scope("acme"):
        result = await tool.execute(**args, template_name="memo.html")
    assert _ok(result), result


async def test_without_a_store_and_outside_studio_the_legacy_behaviour_remains(sandbox):
    tool, args = _csv(sandbox, None)
    result = await tool.execute(**args)
    assert _ok(result), result
    files = [p for p in sandbox.out.glob("*.csv")]
    assert len(files) == 1                                                        # the tool's own output_dir, server named


# -- Power BI: the real client against a local stand-in for the Power BI API -----------------------------------


async def _powerbi(aiohttp_server, monkeypatch, store, sandbox, fmt):
    from parrot_tools import powerbi

    async def execute(request):
        return web.json_response({"results": [{"tables": [{"rows": [{"a": 1}, {"a": 2}]}]}]})

    app = web.Application()
    app.router.add_post("/datasets/{dataset}/executeQueries", execute)
    server = await aiohttp_server(app)
    monkeypatch.setattr(powerbi, "POWERBI_BASE_URL", str(server.make_url("")).rstrip("/"))
    tool = powerbi.PowerBIQueryTool(artifact_store=store)
    before = sandbox.watch()
    with studio_scope("acme"):
        result = await tool.execute(dataset_id="dataset1", token="t", command="EVALUATE x", output_format=fmt,
                                    export_csv_path="/tmp/evil.csv", parquet_path="/tmp/evil.parquet")
    return tool, result, before


@pytest.mark.parametrize("fmt,ext", [("csv", ".csv"), ("parquet", ".parquet")])
async def test_power_bi_exports_go_to_the_store(fmt, ext, aiohttp_server, monkeypatch, store, sandbox):
    tool, result, before = await _powerbi(aiohttp_server, monkeypatch, store, sandbox, fmt)
    assert _ok(result), result
    exported = _export_of(result)
    assert exported["filename"].endswith(ext) and exported["url"].startswith("/api/v1/astudio/exports/acme/")
    assert sandbox.watch() == before and not Path("/tmp/evil.csv").exists() and not Path("/tmp/evil.parquet").exists()
    props = set(tool.get_schema()["parameters"]["properties"])
    assert not props & {"export_csv_path", "parquet_path"}


async def test_power_bi_table_info_schema_is_clean():
    from parrot_tools.powerbi import PowerBITableInfoTool

    assert not set(PowerBITableInfoTool().get_schema()["parameters"]["properties"]) & STRIPPED
