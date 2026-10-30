"""CVE lookup, package advisory search and advisory download — OSV + NVD 2.0 + EPSS (FEAT-778 M12)."""

from __future__ import annotations

import asyncio
import hashlib
import json as jsonlib
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Final

import aiohttp

from parrot.knowledge.wiki.store import BaseWikiStore, WikiPageRecord
from parrot.observability.context import current_agent_name
from parrot.tools.toolkit import AbstractToolkit
from parrot_tools.security.cve.models import (
    CVE_ID_RE,
    CVSS,
    OSV_ECOSYSTEMS,
    AffectedPackage,
    CVENotFoundError,
    CVERecord,
    CVESearchResult,
    CVEToolkitError,
    DownloadReceipt,
    severity_from_score,
    validate_cve_id,
)

OSV_VULN_URL: Final[str] = "https://api.osv.dev/v1/vulns/{cve_id}"
OSV_QUERY_URL: Final[str] = "https://api.osv.dev/v1/query"
NVD_CVE_URL: Final[str] = "https://services.nvd.nist.gov/rest/json/cves/2.0?cveId={cve_id}"
EPSS_URL: Final[str] = "https://api.first.org/data/v1/epss?cve={cve_id}"

_CVSS_VERSION_RE: Final[re.Pattern[str]] = re.compile(r"^CVSS:(3\.0|3\.1|4\.0)/")


def _parse_dt(value: Any) -> datetime | None:
    """Parse an ISO-8601 timestamp, returning None when absent or malformed."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class CVEToolkit(AbstractToolkit):
    """Look up CVEs, search advisories for a package version, and download an advisory into expert knowledge."""

    auto_open: bool = True

    def __init__(
        self,
        *,
        store_resolver: Callable[[str], BaseWikiStore] | None = None,
        sources_dir: Path | None = None,
        nvd_api_key: str | None = None,
        enrich_nvd: bool = True,
        enrich_epss: bool = False,
        timeout_seconds: float = 20.0,
        **kwargs: Any,
    ) -> None:
        """Initialise the toolkit.

        Args:
            store_resolver: Maps a wiki name to its store (needed by ``download_cve``).
            sources_dir: Confined directory for raw JSON downloads.
            nvd_api_key: NVD API key; falls back to ``NVD_API_KEY``.
            enrich_nvd: Enrich OSV records with NVD 2.0 data.
            enrich_epss: Add the EPSS probability.
            timeout_seconds: Total HTTP timeout per request.
            **kwargs: Forwarded to ``AbstractToolkit``.
        """
        super().__init__(**kwargs)
        self._store_resolver = store_resolver
        self._sources_dir = sources_dir
        self._nvd_api_key = nvd_api_key or os.getenv("NVD_API_KEY")
        self._enrich_nvd = enrich_nvd
        self._enrich_epss = enrich_epss
        self._timeout = timeout_seconds
        self._nvd_lock = asyncio.Lock()
        self._session: aiohttp.ClientSession | None = None

    async def _open(self) -> None:
        """Create the shared HTTP session."""
        self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self._timeout))

    async def _close(self) -> None:
        """Close the shared HTTP session."""
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def _get_json(
        self,
        url: str,
        *,
        method: str = "GET",
        json: dict | None = None,
        headers: dict | None = None,
    ) -> tuple[int, dict[str, Any]]:
        """The single network seam: (status, body). Tests monkeypatch this method."""
        await self._ensure_open()
        assert self._session is not None
        async with self._session.request(method, url, json=json, headers=headers) as response:
            body = await response.json(content_type=None) if response.status != 204 else {}
            return response.status, body or {}

    # ------------------------------------------------------------------ tools

    async def lookup_cve(self, cve_id: str) -> dict[str, Any]:
        """Look up one CVE by id (e.g. CVE-2026-98432): severity, CVSS, CWE, affected packages and fixed versions, references."""
        record = await self._lookup(validate_cve_id(cve_id))
        return record.model_dump(mode="json", exclude={"raw"})

    async def search_cves(
        self, package: str, ecosystem: str, version: str | None = None, limit: int = 20
    ) -> dict[str, Any]:
        """List known CVEs for a package (ecosystem: PyPI, npm, crates.io, Go, Maven, …), optionally for one version."""
        if ecosystem not in OSV_ECOSYSTEMS:
            raise ValueError(f"unknown ecosystem {ecosystem!r}; expected one of {OSV_ECOSYSTEMS}")
        payload: dict[str, Any] = {"package": {"name": package, "ecosystem": ecosystem}}
        if version:
            payload["version"] = version
        status, body = await self._get_json(OSV_QUERY_URL, method="POST", json=payload)
        if status >= 400:
            raise CVEToolkitError(f"OSV query failed with HTTP {status}")
        records: list[CVERecord] = []
        for vuln in body.get("vulns") or []:
            if not isinstance(vuln, dict):
                continue
            ids = [vuln.get("id", "")] + list(vuln.get("aliases") or [])
            cve = next((i for i in ids if isinstance(i, str) and CVE_ID_RE.match(i)), None)
            if cve is None:
                continue
            records.append(self._parse_osv(vuln, cve))
            if len(records) >= max(limit, 0):
                break
        return CVESearchResult(package=package, ecosystem=ecosystem, version=version, records=records).model_dump(
            mode="json", exclude={"records": {"__all__": {"raw"}}}
        )

    async def download_cve(self, cve_id: str, wiki_name: str | None = None) -> dict[str, Any]:
        """Download a CVE advisory into your knowledge (wiki) so later answers can cite it."""
        cve_id = validate_cve_id(cve_id)
        agent = current_agent_name.get()
        wiki_name = wiki_name or (f"expert-{agent}" if agent else None)
        if wiki_name is None or self._store_resolver is None:
            raise CVEToolkitError("download_cve needs an active expert or an explicit wiki_name, and a store")
        if self._sources_dir is None:
            raise CVEToolkitError("download_cve needs a sources_dir")
        record = await self._lookup(cve_id)

        json_path = await asyncio.to_thread(self._write_raw, cve_id, record.raw)
        body = self._render_markdown(record)
        content_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
        concept_id = f"{wiki_name}/cve/{cve_id}"
        page = WikiPageRecord(
            concept_id=concept_id,
            title=cve_id,
            category="advisory",
            summary=(record.summary or cve_id)[:500],
            body=body,
            origin="download",
            asserted_by=f"tool:cve:{agent or 'none'}",
            content_hash=content_hash,
        )
        store = self._store_resolver(wiki_name)
        await store.upsert_pages([page])
        return DownloadReceipt(
            cve_id=cve_id,
            wiki_name=wiki_name,
            concept_id=concept_id,
            json_path=str(json_path),
            content_hash=content_hash,
        ).model_dump(mode="json")

    # ------------------------------------------------------------------ internals

    def _write_raw(self, cve_id: str, raw: dict[str, Any]) -> Path:
        """Write the raw JSON under ``sources_dir/cve`` (0o700), refusing paths outside the confined dir."""
        assert self._sources_dir is not None
        root = Path(self._sources_dir)
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(root, 0o700)
        root = root.resolve()
        target = (root / "cve" / f"{cve_id}.json").resolve()
        if not target.is_relative_to(root):
            raise CVEToolkitError(f"refusing to write outside {root}: {target}")
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        target.write_text(jsonlib.dumps(raw, indent=2, sort_keys=True), encoding="utf-8")
        return target

    @staticmethod
    def _render_markdown(record: CVERecord) -> str:
        """Render the advisory: untrusted provider text wrapped, metadata block outside the wrapper."""
        sources = ",".join(s for s in record.sources if s != "epss") or "osv"
        refs = "\n".join(record.references)
        untrusted = (
            f'<untrusted_data source="{sources}" cve="{record.id}">\n'
            f"{record.summary}\n\n{record.details}\n"
            f"{refs}\n"
            f"</untrusted_data>"
        )
        meta_lines = [f"severity: {record.severity.value if hasattr(record.severity, 'value') else record.severity}"]
        for c in record.cvss:
            meta_lines.append(f"cvss: {c.version} {c.score} {c.vector} ({c.source})")
        if record.epss is not None:
            meta_lines.append(f"epss: {record.epss}")
        if record.cwe_ids:
            meta_lines.append(f"cwe: {', '.join(record.cwe_ids)}")
        for a in record.affected:
            meta_lines.append(f"affected: {a.ecosystem}/{a.name} introduced={a.introduced} fixed={a.fixed}")
        for r in record.references:
            meta_lines.append(f"reference: {r}")
        meta = "```yaml\n" + "\n".join(meta_lines) + "\n```"
        return f"# {record.id}\n\n{untrusted}\n\n{meta}\n"

    async def _lookup(self, cve_id: str) -> CVERecord:
        """OSV (404 → CVENotFoundError) + optional NVD (lock, degrade on failure) + optional EPSS; severity from max score."""
        status, body = await self._get_json(OSV_VULN_URL.format(cve_id=cve_id))
        if status == 404:
            raise CVENotFoundError(f"{cve_id} not found in OSV")
        if status >= 400:
            raise CVEToolkitError(f"OSV lookup failed with HTTP {status}")
        record = self._parse_osv(body, cve_id)
        if self._enrich_nvd:
            await self._merge_nvd(record, cve_id)
        if self._enrich_epss:
            await self._merge_epss(record, cve_id)
        scores = [c.score for c in record.cvss if c.score is not None and c.score > 0]
        record.severity = severity_from_score(max(scores) if scores else None)
        return record

    @staticmethod
    def _parse_osv(vuln: dict[str, Any], cve_id: str) -> CVERecord:
        """Map an OSV vulnerability object to a ``CVERecord``."""
        affected: list[AffectedPackage] = []
        for item in vuln.get("affected") or []:
            pkg = item.get("package") or {}
            introduced = fixed = None
            for rng in item.get("ranges") or []:
                for ev in rng.get("events") or []:
                    if "introduced" in ev and introduced is None:
                        introduced = ev["introduced"]
                    if "fixed" in ev and fixed is None:
                        fixed = ev["fixed"]
            affected.append(
                AffectedPackage(
                    ecosystem=pkg.get("ecosystem", ""),
                    name=pkg.get("name", ""),
                    introduced=introduced,
                    fixed=fixed,
                    versions=list(item.get("versions") or []),
                )
            )
        cvss: list[CVSS] = []
        for sev in vuln.get("severity") or []:
            vector = sev.get("score", "")
            m = _CVSS_VERSION_RE.match(vector or "")
            if m:
                cvss.append(CVSS(version=m.group(1), score=0.0, vector=vector, source="osv"))
        aliases = [a for a in (vuln.get("aliases") or []) if a != cve_id]
        if vuln.get("id") and vuln.get("id") != cve_id:
            aliases.insert(0, vuln["id"])
        cwes = list((vuln.get("database_specific") or {}).get("cwe_ids") or [])
        return CVERecord(
            id=cve_id,
            aliases=aliases,
            summary=vuln.get("summary", "") or "",
            details=vuln.get("details", "") or "",
            cvss=cvss,
            cwe_ids=cwes,
            affected=affected,
            references=[r.get("url") for r in vuln.get("references") or [] if r.get("url")],
            published=_parse_dt(vuln.get("published")),
            modified=_parse_dt(vuln.get("modified")),
            sources=["osv"],
            raw={"osv": vuln},
        )

    async def _merge_nvd(self, record: CVERecord, cve_id: str) -> None:
        """Enrich with NVD 2.0 data; any failure degrades to OSV-only with a warning."""
        headers = {"apiKey": self._nvd_api_key} if self._nvd_api_key else None
        try:
            async with self._nvd_lock:
                status, body = await self._get_json(NVD_CVE_URL.format(cve_id=cve_id), headers=headers)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
            self.logger.warning("NVD enrichment failed for %s: %s; using OSV only", cve_id, exc)
            return
        if status != 200:
            self.logger.warning("NVD enrichment failed for %s: HTTP %s; using OSV only", cve_id, status)
            return
        vulns = body.get("vulnerabilities") or []
        if not vulns:
            return
        cve = vulns[0].get("cve") or {}
        metrics = cve.get("metrics") or {}
        nvd_cvss: list[CVSS] = []
        for key in ("cvssMetricV40", "cvssMetricV31", "cvssMetricV30"):
            for metric in metrics.get(key) or []:
                data = metric.get("cvssData") or {}
                version = str(data.get("version", ""))
                if version in ("3.0", "3.1", "4.0") and data.get("vectorString"):
                    nvd_cvss.append(
                        CVSS(
                            version=version,
                            score=float(data.get("baseScore", 0.0)),
                            vector=data["vectorString"],
                            source="nvd",
                        )
                    )
        nvd_vectors = {c.vector for c in nvd_cvss}
        record.cvss = [c for c in record.cvss if c.vector not in nvd_vectors] + nvd_cvss
        for weakness in cve.get("weaknesses") or []:
            for desc in weakness.get("description") or []:
                value = desc.get("value", "")
                if value.startswith("CWE-") and value not in record.cwe_ids:
                    record.cwe_ids.append(value)
        for ref in cve.get("references") or []:
            url = ref.get("url")
            if url and url not in record.references:
                record.references.append(url)
        record.published = record.published or _parse_dt(cve.get("published"))
        record.modified = record.modified or _parse_dt(cve.get("lastModified"))
        if not record.details:
            for desc in cve.get("descriptions") or []:
                if desc.get("lang") == "en":
                    record.details = desc.get("value", "")
                    break
        record.sources.append("nvd")
        record.raw["nvd"] = body

    async def _merge_epss(self, record: CVERecord, cve_id: str) -> None:
        """Add the EPSS probability; failures are logged and ignored."""
        try:
            status, body = await self._get_json(EPSS_URL.format(cve_id=cve_id))
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
            self.logger.warning("EPSS lookup failed for %s: %s", cve_id, exc)
            return
        if status != 200:
            self.logger.warning("EPSS lookup failed for %s: HTTP %s", cve_id, status)
            return
        data = body.get("data") or []
        if data:
            try:
                record.epss = float(data[0].get("epss"))
            except (TypeError, ValueError):
                return
            record.sources.append("epss")
            record.raw["epss"] = body
