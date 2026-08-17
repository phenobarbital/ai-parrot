"""
OpenDataToolkit — direct access to free, no-auth open-data REST APIs
(FEAT-426 Module 2: World Bank Open Data, EU Open Data Portal, OECD SDMX).

World Bank has **no server-side keyword search**: indicators are looked up
by code or resolved from `query` via indicator metadata, then time-series
observations are fetched. The EU Open Data Portal (piveau/DCAT-AP), by
contrast, supports genuine server-side full-text search. OECD's SDMX 3.0
API has no keyword search either — its ~1,500-dataflow catalog is listed
and filtered client-side, and its DSD (Data Structure Definition) must be
fetched before a data query can be built, since dimension order is
positional and dataflow-specific. See spec §3 Module 2 and §7 "Known
Risks".
"""
from urllib.parse import quote

import backoff
from parrot.tools.toolkit import AbstractToolkit

from .base import BaseResearchToolkit
from .models import DatasetResult, IndicatorValue, ResearchResult

try:
    import wbgapi as wb
except ImportError:
    wb = None

try:
    # PyPI distribution is `sdmx1`; the importable module is `sdmx`.
    import sdmx
except ImportError:
    sdmx = None

_WB_SOURCE_NAME = "World Bank Open Data"
_WB_LICENSE = "CC BY-4.0"
_WB_MISSING_MESSAGE = (
    "World Bank support requires: pip install 'ai-parrot-tools[research]'"
)

# EU Open Data Portal — piveau platform (NOT CKAN). Full-text search over
# an Elasticsearch/DCAT-AP index. `limit` caps at 1000 (plain-text HTTP 400
# above it); `page` is 0-indexed.
EU_SEARCH_URL = "https://data.europa.eu/api/hub/search/search"
_EU_SOURCE_NAME = "EU Open Data Portal"
_EU_LIMIT_CAP = 1000

# OECD SDMX 3.0. `OECD3` is the v2/SDMX-3.0 `sdmx1` source id — `OECD` is
# the older v1 entry and must not be used. Data queries are unpaginated
# and can reach tens of MB, so every query is bounded by a dimension key
# and a starting period; rows mapped into IndicatorValue are also capped.
_OECD_SOURCE_ID = "OECD3"
_OECD_SOURCE_NAME = "OECD SDMX"
_OECD_MISSING_MESSAGE = (
    "OECD support requires: pip install 'ai-parrot-tools[research]'"
)
_OECD_DEFAULT_START_PERIOD = "2015"
_OECD_MAX_OBSERVATIONS = 500


class OpenDataToolkit(BaseResearchToolkit, AbstractToolkit):
    """Direct, structured access to authoritative open-data sources.

    Covers World Bank Open Data (indicator/time-series lookup), the EU
    Open Data Portal (piveau full-text search), and OECD SDMX 3.0 (dataflow
    catalog browsing + bounded data queries). See spec §3 Module 2.
    """

    def _time_kwargs(
        self, year: str | None = None, date_range: str | None = None
    ) -> dict:
        """Build the `time`/`mrv` kwarg for `wbgapi` calls.

        Args:
            year: A single year, e.g. "2020".
            date_range: A `wbgapi`-style range, e.g. "2015:2020".

        Returns:
            A single-key dict suitable for `**kwargs` into `wb.data.fetch`.
        """
        if date_range:
            return {"time": date_range}
        if year:
            return {"time": f"YR{year}"}
        # No explicit period requested: return the 5 most recent values.
        return {"mrv": 5}

    async def search_world_bank(
        self,
        query: str,
        indicator: str | None = None,
        country: str | None = None,
        date_range: str | None = None,
        max_results: int = 10,
    ) -> ResearchResult:
        """Search World Bank economic/statistical indicators.

        World Bank's v2 API has no server-side full-text search — this
        method resolves `query` against indicator metadata (or uses an
        explicit `indicator` code, which is far more reliable) and returns
        matching observations. For best results, prefer a known World Bank
        indicator code (e.g. "NY.GDP.MKTP.KD.ZG") over free-text prose.

        Args:
            query: Free-text description or a World Bank indicator code.
            indicator: Explicit indicator code — skips metadata search.
            country: ISO-3166 country code to filter observations.
            date_range: `wbgapi`-style time range, e.g. "2015:2020".
            max_results: Maximum number of indicator matches to fetch.

        Returns:
            A `ResearchResult` with `result_type="indicators"`.
        """
        source = "open_data.search_world_bank"
        if wb is None:
            return self._failure(
                query, source, "indicators", "error", _WB_MISSING_MESSAGE
            )

        cache_params = {
            "query": query, "indicator": indicator, "country": country,
            "date_range": date_range, "max_results": max_results,
        }
        cached = await self._cache.get(
            "open_data", "search_world_bank", **cache_params
        )
        if cached is not None:
            return ResearchResult(**cached)

        indicator_ids = [indicator] if indicator else None
        if not indicator_ids:
            try:
                matches = await self._search_indicator_metadata(query)
            except Exception as e:  # noqa: BLE001 — never raise into the agent loop
                self.logger.error("World Bank series search failed: %s", e)
                return self._failure(
                    query, source, "indicators", "error",
                    f"World Bank series lookup failed: {e}",
                )
            indicator_ids = [m.id for m in matches[:max_results]] if matches else []

        if not indicator_ids:
            return self._failure(
                query, source, "indicators", "no_data",
                f"No World Bank indicators matched '{query}'",
            )

        try:
            rows = await self._fetch_observations(indicator_ids, country, date_range)
        except Exception as e:  # noqa: BLE001 — never raise into the agent loop
            self.logger.error("World Bank data fetch failed: %s", e)
            return self._failure(
                query, source, "indicators", "error",
                f"World Bank data fetch failed: {e}",
            )

        if not rows:
            return self._failure(
                query, source, "indicators", "no_data",
                f"No observations found for '{query}'",
            )

        indicators = [
            self._row_to_indicator(row, country) for row in rows[:max_results]
        ]
        citation = self._build_citation(
            source_name=_WB_SOURCE_NAME,
            source_url="https://data.worldbank.org/indicator",
            license=_WB_LICENSE,
        )
        result = ResearchResult(
            query=query, source=source, result_type="indicators",
            status="success", total_results=len(indicators),
            indicators=indicators, citation=citation,
        )
        await self._cache.set(
            "open_data", "search_world_bank", result.model_dump(),
            ttl=3600, **cache_params,
        )
        return result

    async def get_world_bank_indicator(
        self,
        indicator_id: str,
        country: str,
        year: str | None = None,
        date_range: str | None = None,
    ) -> ResearchResult:
        """Fetch a World Bank indicator time series for a country.

        Args:
            indicator_id: World Bank indicator code, e.g. "NY.GDP.MKTP.KD.ZG".
            country: ISO-3166 country code, e.g. "BRA".
            year: A single year to fetch, e.g. "2020".
            date_range: A `wbgapi`-style range, e.g. "2015:2020". Takes
                precedence over `year` when both are supplied.

        Returns:
            A `ResearchResult` with `result_type="indicators"`.
        """
        source = "open_data.get_world_bank_indicator"
        if wb is None:
            return self._failure(
                indicator_id, source, "indicators", "error", _WB_MISSING_MESSAGE
            )

        cache_params = {
            "indicator_id": indicator_id, "country": country,
            "year": year, "date_range": date_range,
        }
        cached = await self._cache.get(
            "open_data", "get_world_bank_indicator", **cache_params
        )
        if cached is not None:
            return ResearchResult(**cached)

        try:
            rows = await self._fetch_observations(
                [indicator_id], country, date_range, year
            )
        except Exception as e:  # noqa: BLE001 — never raise into the agent loop
            self.logger.error("World Bank fetch failed: %s", e)
            return self._failure(
                indicator_id, source, "indicators", "error",
                f"World Bank request failed: {e}",
            )

        if not rows:
            return self._failure(
                indicator_id, source, "indicators", "no_data",
                f"No observations found for {indicator_id}/{country}",
            )

        indicators = [self._row_to_indicator(row, country) for row in rows]
        citation = self._build_citation(
            source_name=_WB_SOURCE_NAME,
            source_url=(
                f"https://data.worldbank.org/indicator/{indicator_id}"
                f"?locations={country}"
            ),
            license=_WB_LICENSE,
        )
        result = ResearchResult(
            query=indicator_id, source=source, result_type="indicators",
            status="success", total_results=len(indicators),
            indicators=indicators, citation=citation,
        )
        await self._cache.set(
            "open_data", "get_world_bank_indicator", result.model_dump(),
            ttl=3600, **cache_params,
        )
        return result

    async def search_eu_open_data(
        self,
        query: str,
        dataset_type: str | None = None,
        publisher: str | None = None,
        max_results: int = 10,
    ) -> ResearchResult:
        """Search the EU Open Data Portal (piveau/DCAT-AP full-text search).

        Unlike World Bank, this source has genuine server-side full-text
        search — natural-language queries work well here.

        Args:
            query: Full-text search query.
            dataset_type: Optional dataset type/category filter.
            publisher: Optional publisher name filter.
            max_results: Maximum number of datasets to return. The portal
                caps its own `limit` parameter at 1000 (returning a
                plain-text HTTP 400 above that), so values are clamped.

        Returns:
            A `ResearchResult` with `result_type="datasets"`.
        """
        source = "open_data.search_eu_open_data"
        limit = min(max_results, _EU_LIMIT_CAP)

        cache_params = {
            "query": query, "dataset_type": dataset_type,
            "publisher": publisher, "max_results": max_results,
        }
        cached = await self._cache.get(
            "open_data", "search_eu_open_data", **cache_params
        )
        if cached is not None:
            return ResearchResult(**cached)

        params = {"q": query, "limit": limit, "page": 0}
        if dataset_type:
            params["filter"] = dataset_type
        if publisher:
            params["publisher"] = publisher

        payload, err = await self._make_api_request(EU_SEARCH_URL, params=params)
        if err:
            return self._failure(query, source, "datasets", "error", err)

        hits = (payload or {}).get("result", {}).get("results", [])
        if not hits:
            return self._failure(
                query, source, "datasets", "no_data",
                f"No EU Open Data datasets matched '{query}'",
            )

        datasets = [self._dataset_from_hit(hit) for hit in hits[:max_results]]
        citation = self._build_citation(
            source_name=_EU_SOURCE_NAME,
            source_url=f"{EU_SEARCH_URL}?q={quote(query)}",
        )
        result = ResearchResult(
            query=query, source=source, result_type="datasets",
            status="success", total_results=len(datasets),
            datasets=datasets, citation=citation,
        )
        await self._cache.set(
            "open_data", "search_eu_open_data", result.model_dump(),
            ttl=3600, **cache_params,
        )
        return result

    @staticmethod
    def _pick_lang(value, preferred: str = "en") -> str:
        """Return `preferred` language, else the first available, else ''.

        EU Open Data Portal metadata (`title`, `description`, ...) arrives
        as a language-keyed dict; English is not guaranteed to be present.
        """
        if isinstance(value, str):
            return value
        if isinstance(value, dict) and value:
            return value.get(preferred) or next(iter(value.values()))
        return ""

    def _dataset_from_hit(self, hit: dict) -> DatasetResult:
        """Convert a raw EU Open Data Portal search hit into a `DatasetResult`."""
        dataset_id = hit.get("id", "")
        title = self._pick_lang(hit.get("title")) or "Untitled dataset"
        description = self._pick_lang(hit.get("description")) or None

        publisher = hit.get("publisher")
        if isinstance(publisher, dict):
            publisher_name = self._pick_lang(publisher.get("name")) or None
        else:
            publisher_name = publisher or None

        keywords = hit.get("keywords")
        if isinstance(keywords, dict):
            keywords = keywords.get("en") or next(iter(keywords.values()), None)

        distributions = hit.get("distributions") or []
        fmt = None
        if distributions:
            fmt_field = distributions[0].get("format")
            fmt = fmt_field.get("label") if isinstance(fmt_field, dict) else fmt_field

        url = hit.get("landing_page") or (
            f"https://data.europa.eu/data/datasets/{dataset_id}"
            if dataset_id else None
        )

        return DatasetResult(
            title=title,
            description=description,
            publisher=publisher_name,
            url=url,
            keywords=keywords,
            format=fmt,
            last_modified=hit.get("modified"),
            source="eu_open_data",
        )

    async def search_oecd_data(
        self,
        query: str,
        dataset: str | None = None,
        country: str | None = None,
        max_results: int = 10,
    ) -> ResearchResult:
        """Browse the OECD SDMX 3.0 dataflow catalog and filter client-side.

        OECD has no server-side keyword search over its ~1,500 dataflows;
        this method lists the catalog (cached 24h — it changes rarely) and
        filters dataflow ids/names against `query`. Use the resulting
        dataflow id with `get_oecd_indicator` to fetch actual data.

        Args:
            query: Free-text filter matched against dataflow id/name.
            dataset: Optional exact dataflow id — skips catalog filtering.
            country: Unused for catalog search; accepted for symmetry with
                `get_oecd_indicator`.
            max_results: Maximum number of dataflows to return.

        Returns:
            A `ResearchResult` with `result_type="datasets"`.
        """
        source = "open_data.search_oecd_data"
        if sdmx is None:
            return self._failure(
                query, source, "datasets", "error", _OECD_MISSING_MESSAGE
            )

        cache_params = {
            "query": query, "dataset": dataset,
            "country": country, "max_results": max_results,
        }
        cached = await self._cache.get(
            "open_data", "search_oecd_data", **cache_params
        )
        if cached is not None:
            return ResearchResult(**cached)

        try:
            flows = await self._fetch_oecd_catalog()
        except Exception as e:  # noqa: BLE001 — never raise into the agent loop
            self.logger.error("OECD catalog fetch failed: %s", e)
            return self._failure(
                query, source, "datasets", "error",
                f"OECD catalog fetch failed: {e}",
            )

        if dataset:
            flows = [f for f in flows if f.get("id") == dataset]
        elif query:
            q = query.lower()
            flows = [
                f for f in flows
                if q in f.get("id", "").lower() or q in f.get("name", "").lower()
            ]

        if not flows:
            return self._failure(
                query, source, "datasets", "no_data",
                f"No OECD dataflows matched '{query}'",
            )

        datasets = [
            DatasetResult(
                title=f.get("name") or f.get("id", ""),
                publisher="OECD",
                url=f"https://sdmx.oecd.org/public/rest/v2/dataflow/{f.get('id', '')}",
                source="oecd",
            )
            for f in flows[:max_results]
        ]
        citation = self._build_citation(
            source_name=_OECD_SOURCE_NAME,
            source_url="https://sdmx.oecd.org/public/rest/v2/dataflow",
        )
        result = ResearchResult(
            query=query, source=source, result_type="datasets",
            status="success", total_results=len(datasets),
            datasets=datasets, citation=citation,
        )
        await self._cache.set(
            "open_data", "search_oecd_data", result.model_dump(),
            ttl=86400, **cache_params,
        )
        return result

    async def get_oecd_indicator(
        self,
        dataset_id: str,
        country: str,
        frequency: str | None = None,
    ) -> ResearchResult:
        """Fetch an OECD SDMX 3.0 data series for a dataflow + country.

        Requires a dataflow id (found via `search_oecd_data`), e.g.
        "DSD_FUA_CLIM@DF_TEMPERATURES" — agency ids may be dotted and
        dataflow ids `@`-joined; pass them through verbatim. Fetches the
        Data Structure Definition first, since dimension order is
        positional and dataflow-specific, then bounds the data query by
        country and a starting period (OECD data responses are
        unpaginated and can reach tens of MB).

        Args:
            dataset_id: OECD dataflow id, e.g. "DSD_FUA_CLIM@DF_TEMPERATURES".
            country: ISO country code used as the REF_AREA dimension key.
            frequency: Optional frequency filter (e.g. "A", "M", "Q").

        Returns:
            A `ResearchResult` with `result_type="indicators"`.
        """
        source = "open_data.get_oecd_indicator"
        if sdmx is None:
            return self._failure(
                dataset_id, source, "indicators", "error", _OECD_MISSING_MESSAGE
            )

        cache_params = {
            "dataset_id": dataset_id, "country": country, "frequency": frequency,
        }
        cached = await self._cache.get(
            "open_data", "get_oecd_indicator", **cache_params
        )
        if cached is not None:
            return ResearchResult(**cached)

        try:
            rows = await self._fetch_oecd_series(dataset_id, country, frequency)
        except Exception as e:  # noqa: BLE001 — never raise into the agent loop
            self.logger.error("OECD series fetch failed: %s", e)
            return self._failure(
                dataset_id, source, "indicators", "error",
                f"OECD series fetch failed: {e}",
            )

        if not rows:
            return self._failure(
                dataset_id, source, "indicators", "no_data",
                f"No OECD observations found for {dataset_id}/{country}",
            )

        truncated = len(rows) > _OECD_MAX_OBSERVATIONS
        indicators = [
            IndicatorValue(
                indicator_id=dataset_id,
                indicator_name=row.get("series_name", dataset_id),
                country=row.get("country", country),
                country_name=row.get("country_name", row.get("country", country)),
                year=str(row.get("period", "")),
                value=row.get("value"),
            )
            for row in rows[:_OECD_MAX_OBSERVATIONS]
        ]
        citation = self._build_citation(
            source_name=_OECD_SOURCE_NAME,
            source_url=f"https://sdmx.oecd.org/public/rest/v2/data/{dataset_id}",
        )
        result = ResearchResult(
            query=dataset_id, source=source, result_type="indicators",
            status="success", total_results=len(indicators),
            indicators=indicators, citation=citation,
            raw_metadata={"truncated": truncated} if truncated else None,
        )
        await self._cache.set(
            "open_data", "get_oecd_indicator", result.model_dump(),
            ttl=3600, **cache_params,
        )
        return result

    async def _search_indicator_metadata(self, query: str) -> list:
        """Resolve free-text `query` against World Bank indicator metadata."""

        @backoff.on_exception(backoff.expo, Exception, max_tries=3)
        def _search():
            return list(wb.series.info(q=query))

        return await self._run_sync_in_executor(_search)

    async def _fetch_observations(
        self,
        indicator_ids: list,
        country: str | None,
        date_range: str | None,
        year: str | None = None,
    ) -> list:
        """Fetch raw `wbgapi` observation rows for one or more indicators."""
        time_kwargs = self._time_kwargs(year=year, date_range=date_range)

        @backoff.on_exception(backoff.expo, Exception, max_tries=3)
        def _fetch():
            rows = []
            for indicator_id in indicator_ids:
                rows.extend(
                    wb.data.fetch(indicator_id, economy=country, **time_kwargs)
                )
            return rows

        return await self._run_sync_in_executor(_fetch)

    def _row_to_indicator(self, row: dict, country: str | None) -> IndicatorValue:
        """Convert a raw `wbgapi` observation row into an `IndicatorValue`."""
        economy = row.get("economy", country or "")
        return IndicatorValue(
            indicator_id=row.get("series", ""),
            indicator_name=row.get("seriesName", row.get("series", "")),
            country=economy,
            country_name=row.get("economyName", economy),
            year=str(row.get("time", "")).lstrip("YR"),
            value=row.get("value"),
        )

    async def _fetch_oecd_catalog(self) -> list:
        """List OECD dataflows via the SDMX 3.0 (`OECD3`) source.

        Cached 24h under its own key — the catalog is large (~1,500
        dataflows) and slow-changing, so it is fetched at most once a day
        regardless of the query parameters callers pass.
        """
        cached = await self._cache.get("open_data", "_oecd_catalog")
        if cached is not None:
            return cached

        @backoff.on_exception(backoff.expo, Exception, max_tries=3)
        def _fetch():
            client = sdmx.Client(_OECD_SOURCE_ID)
            flow_msg = client.dataflow()
            return [
                {"id": flow_id, "name": str(getattr(flow, "name", flow_id))}
                for flow_id, flow in flow_msg.dataflow.items()
            ]

        flows = await self._run_sync_in_executor(_fetch)
        await self._cache.set("open_data", "_oecd_catalog", flows, ttl=86400)
        return flows

    async def _fetch_oecd_series(
        self,
        dataset_id: str,
        country: str,
        frequency: str | None,
    ) -> list:
        """Fetch the DSD, then a bounded data query, for one OECD dataflow.

        The DSD (`client.dataflow(dataset_id)`) is always fetched before
        the data query, since dimension order is positional and
        dataflow-specific. The data query itself is bounded by a
        `REF_AREA` (+ optional `FREQ`) dimension key and a `startPeriod`
        param — OECD data responses are unpaginated and can reach tens of
        MB, so a bare all-dimensions query is never issued.
        """

        @backoff.on_exception(backoff.expo, Exception, max_tries=3)
        def _fetch():
            client = sdmx.Client(_OECD_SOURCE_ID)
            client.dataflow(dataset_id)  # DSD — resolves dimension order first

            key = {"REF_AREA": country}
            if frequency:
                key["FREQ"] = frequency
            params = {"startPeriod": _OECD_DEFAULT_START_PERIOD}

            data_msg = client.data(dataset_id, key=key, params=params)
            return self._rows_from_oecd_message(data_msg)

        return await self._run_sync_in_executor(_fetch)

    def _rows_from_oecd_message(self, data_msg) -> list:
        """Normalize an `sdmx1` data message into plain observation dicts.

        `sdmx1` typically requires `sdmx.to_pandas(data_msg)` to turn a
        parsed data message into a pandas Series/DataFrame. This helper
        prefers an already-normalized `.observations` list (used by
        offline tests, spec goal G6) and falls back to `sdmx.to_pandas()`
        for a real message when available.
        """
        if hasattr(data_msg, "observations"):
            return list(data_msg.observations)

        if sdmx is not None and hasattr(sdmx, "to_pandas"):
            try:
                series = sdmx.to_pandas(data_msg)
            except Exception as e:  # noqa: BLE001 — surfaced by the caller
                self.logger.warning("sdmx.to_pandas() conversion failed: %s", e)
                return []
            rows = []
            for idx, value in series.items():
                row = dict(zip(series.index.names, idx)) if isinstance(idx, tuple) else {}
                row["value"] = value
                rows.append(row)
            return rows

        return []
