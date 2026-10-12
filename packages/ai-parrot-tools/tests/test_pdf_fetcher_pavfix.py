"""PA-V2 review fix 4: the PDF export never lets LLM-controlled HTML read local files or reach the network.

Real ``PDFPrintTool`` + real WeasyPrint + a real local HTTP server; the tool is built the way a host builds it
(artifact store), so the restricted fetcher is on. A canary file and a canary server record every fetch.
"""
from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

pytest.importorskip("weasyprint")

from navigator.utils.file import LocalFileManager  # noqa: E402

from parrot.tools import abstract as abstract_module  # noqa: E402
from parrot.storage.artifacts import ArtifactStore  # noqa: E402
from parrot.storage.backends.sqlite import ConversationSQLiteBackend  # noqa: E402
from parrot.storage.overflow import OverflowStore  # noqa: E402
from parrot_tools.pdfprint import PDFPrintTool  # noqa: E402

PNG = (  # a 1x1 png
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xa7\x9a\xa0\xa0\x00\x00\x00\x00IEND\xaeB`\x82"
)


@pytest.fixture
def canary_server():
    hits: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            hits.append(self.path)
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.end_headers()
            self.wfile.write(PNG)

        def log_message(self, *args):  # noqa: D102
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}", hits
    server.shutdown()


@pytest.fixture(autouse=True)
def _static(tmp_path, monkeypatch):
    (tmp_path / "static" / "out").mkdir(parents=True)
    monkeypatch.setattr(abstract_module, "STATIC_DIR", tmp_path / "static")  # the base every output_dir stays under


def _tool(tmp_path, with_store=True):
    store = ArtifactStore(
        dynamodb=ConversationSQLiteBackend(str(tmp_path / "c.db")),
        s3_overflow=OverflowStore(LocalFileManager(base_path=tmp_path / "files")),
    ) if with_store else None
    tpl = tmp_path / "templates"
    tpl.mkdir(exist_ok=True)
    return PDFPrintTool(templates_dir=tpl, output_dir=tmp_path / "static" / "out", artifact_store=store), store


def _spy_on_files(monkeypatch):
    """Record every ``file:`` URL WeasyPrint's real fetcher is asked to open."""
    from weasyprint import URLFetcher

    opened: list[str] = []
    real = URLFetcher.fetch

    def fetch(self, url, headers=None):
        opened.append(str(url))
        return real(self, url, headers)

    monkeypatch.setattr(URLFetcher, "fetch", fetch)
    return opened


async def test_file_and_network_urls_in_the_html_are_never_fetched(tmp_path, canary_server, monkeypatch):
    base, hits = canary_server
    secret = tmp_path / "secret.png"
    secret.write_bytes(PNG)
    opened = _spy_on_files(monkeypatch)
    tool, _ = _tool(tmp_path)
    html = (
        f'<img src="file://{secret}"><img src="{base}/x.png"><img src="http://169.254.169.254/latest/meta-data/">'
        f'<link rel="attachment" href="file:///etc/hostname"><style>@import url("{base}/css");</style><p>ok</p>'
    )
    result = await tool._execute(text=html, auto_detect_markdown=False)
    assert result["bytes"] > 0
    assert hits == []                                                     # the canary server was never contacted
    assert not [u for u in opened if "secret.png" in u or "hostname" in u or "169.254" in u]  # nor opened


async def test_data_uris_and_template_assets_still_render(tmp_path, monkeypatch):
    tool, _ = _tool(tmp_path)
    (tool.templates_dir / "logo.png").write_bytes(PNG)
    opened = _spy_on_files(monkeypatch)
    import base64

    data_uri = "data:image/png;base64," + base64.b64encode(PNG).decode()
    result = await tool._execute(text=f'<img src="{data_uri}"><img src="logo.png"><p>ok</p>', auto_detect_markdown=False)
    assert result["bytes"] > 0
    assert any(u.endswith("/templates/logo.png") for u in opened)          # a server-owned asset is allowed


async def test_a_host_without_a_store_or_guard_is_unchanged(tmp_path, canary_server):
    base, hits = canary_server
    tool, _ = _tool(tmp_path, with_store=False)
    await tool._execute(text=f'<img src="{base}/x.png"><p>ok</p>', auto_detect_markdown=False)
    assert hits == ["/x.png"]                                             # legacy behaviour: no host switch, no change
