"""Unit tests for CVEToolkit (FEAT-778 TASK-4929). No test opens a socket: ``_get_json`` is replaced."""

from __future__ import annotations

import json
import stat
from pathlib import Path
from typing import Any

import pytest

from parrot.knowledge.wiki.file_store import InMemoryWikiStore
from parrot.observability.context import current_agent_name
from parrot_tools.security.cve.models import CVENotFoundError, CVEToolkitError
from parrot_tools.security.cve.toolkit import (
    EPSS_URL,
    NVD_CVE_URL,
    OSV_QUERY_URL,
    OSV_VULN_URL,
    CVEToolkit,
)

FIXTURES = Path(__file__).parent / "fixtures"
CVE = "CVE-2026-98432"


def _fx(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text())


def _install(toolkit: CVEToolkit, routes: dict[str, tuple[int, dict[str, Any]] | Exception]) -> list[dict]:
    calls: list[dict] = []

    async def fake(url: str, *, method: str = "GET", json: dict | None = None, headers: dict | None = None):
        calls.append({"url": url, "method": method, "json": json, "headers": headers})
        result = routes[url]
        if isinstance(result, Exception):
            raise result
        return result

    toolkit._get_json = fake  # type: ignore[method-assign]
    return calls


def _default_routes(nvd: tuple[int, dict] | Exception | None = None) -> dict:
    return {
        OSV_VULN_URL.format(cve_id=CVE): (200, _fx(f"osv_{CVE}.json")),
        NVD_CVE_URL.format(cve_id=CVE): nvd if nvd is not None else (200, _fx(f"nvd_{CVE}.json")),
        EPSS_URL.format(cve_id=CVE): (200, _fx(f"epss_{CVE}.json")),
    }


@pytest.mark.asyncio
async def test_lookup_cve_merges_osv_and_nvd() -> None:
    tk = CVEToolkit(nvd_api_key="k", enrich_epss=True)
    calls = _install(tk, _default_routes())
    rec = await tk.lookup_cve(CVE)
    assert rec["id"] == CVE
    assert rec["severity"].lower() == "medium"
    assert any(c["source"] == "nvd" and c["score"] == 5.3 for c in rec["cvss"])
    assert "CWE-522" in rec["cwe_ids"] and "CWE-200" in rec["cwe_ids"]
    assert rec["affected"][0]["name"] == "requests" and rec["affected"][0]["fixed"] == "2.32.4"
    assert rec["epss"] == pytest.approx(0.00421)
    assert rec["sources"] == ["osv", "nvd", "epss"]
    assert "raw" not in rec
    nvd_call = next(c for c in calls if c["url"].startswith("https://services.nvd"))
    assert nvd_call["headers"] == {"apiKey": "k"}
    with pytest.raises(ValueError):
        await tk.lookup_cve("cve-bad")


@pytest.mark.asyncio
async def test_lookup_cve_nvd_failure_degrades_to_osv(caplog: pytest.LogCaptureFixture, monkeypatch) -> None:
    monkeypatch.delenv("NVD_API_KEY", raising=False)
    tk = CVEToolkit()
    calls = _install(tk, _default_routes(nvd=(429, {})))
    rec = await tk.lookup_cve(CVE)
    assert rec["sources"] == ["osv"]
    assert rec["affected"][0]["fixed"] == "2.32.4"
    assert any("NVD" in r.getMessage() for r in caplog.records)
    assert calls[1]["headers"] is None
    tk2 = CVEToolkit()
    _install(tk2, _default_routes(nvd=TimeoutError()))
    assert (await tk2.lookup_cve(CVE))["sources"] == ["osv"]


@pytest.mark.asyncio
async def test_lookup_cve_not_found() -> None:
    tk = CVEToolkit()
    _install(tk, {OSV_VULN_URL.format(cve_id="CVE-2026-0001"): (404, _fx("osv_404.json"))})
    with pytest.raises(CVENotFoundError):
        await tk.lookup_cve("CVE-2026-0001")


@pytest.mark.asyncio
async def test_search_cves_validates_ecosystem() -> None:
    tk = CVEToolkit()
    with pytest.raises(ValueError):
        await tk.search_cves("requests", "pypi")
    ghsa_only = {"id": "GHSA-aaaa-bbbb-cccc", "aliases": [], "summary": "no cve"}
    calls = _install(tk, {OSV_QUERY_URL: (200, {"vulns": [_fx(f"osv_{CVE}.json"), ghsa_only]})})
    res = await tk.search_cves("requests", "PyPI", version="2.32.3")
    assert calls[0]["method"] == "POST"
    assert calls[0]["json"] == {"package": {"name": "requests", "ecosystem": "PyPI"}, "version": "2.32.3"}
    assert [r["id"] for r in res["records"]] == [CVE]
    assert "raw" not in res["records"][0]


@pytest.mark.asyncio
async def test_download_cve_writes_json_and_wiki_page(tmp_path: Path) -> None:
    store = InMemoryWikiStore(tmp_path / "pages", wiki_name="expert-sec")
    sources = tmp_path / "sources"
    tk = CVEToolkit(store_resolver=lambda name: store, sources_dir=sources, enrich_nvd=True)
    _install(tk, _default_routes())
    token = current_agent_name.set("sec")
    try:
        receipt = await tk.download_cve(CVE)
    finally:
        current_agent_name.reset(token)
    assert receipt["wiki_name"] == "expert-sec"
    assert receipt["concept_id"] == f"expert-sec/cve/{CVE}"
    path = Path(receipt["json_path"])
    assert path == (sources / "cve" / f"{CVE}.json").resolve()
    assert json.loads(path.read_text())["osv"]["aliases"] == [CVE]
    assert stat.S_IMODE(sources.stat().st_mode) == 0o700
    pages = await store.dump_pages()
    assert len(pages) == 1
    page = await store.get_page(receipt["concept_id"])
    assert page["origin"] == "download"
    assert page["body"].startswith(f'# {CVE}\n\n<untrusted_data source="osv,nvd" cve="{CVE}">')


@pytest.mark.asyncio
async def test_download_cve_requires_namespace(tmp_path: Path) -> None:
    tk = CVEToolkit(store_resolver=lambda name: InMemoryWikiStore(tmp_path / "p"), sources_dir=tmp_path)
    _install(tk, _default_routes())
    with pytest.raises(CVEToolkitError):
        await tk.download_cve(CVE)
    assert not (tmp_path / "cve").exists()


@pytest.mark.asyncio
async def test_untrusted_wrapper_keeps_injection_verbatim(tmp_path: Path) -> None:
    store = InMemoryWikiStore(tmp_path / "pages")
    tk = CVEToolkit(store_resolver=lambda name: store, sources_dir=tmp_path / "s", enrich_nvd=False)
    _install(tk, _default_routes())
    receipt = await tk.download_cve(CVE, wiki_name="expert-x")
    body = (await store.get_page(receipt["concept_id"]))["body"]
    start, end = body.index("<untrusted_data"), body.index("</untrusted_data>")
    inside = body[start:end]
    assert "$name" in inside
    assert "IGNORE PREVIOUS INSTRUCTIONS" in inside
    assert "IGNORE PREVIOUS INSTRUCTIONS" not in body[end:]
    assert "```" in body[end:]


@pytest.mark.asyncio
async def test_cve_toolkit_lifecycle() -> None:
    tk = CVEToolkit()
    assert tk.auto_open is True
    await tk._ensure_open()
    session = tk._session
    assert session is not None and not session.closed
    await tk._ensure_open()
    assert tk._session is session
    await tk._close()
    assert session.closed and tk._session is None
