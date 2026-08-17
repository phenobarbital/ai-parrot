"""
OpenDataToolkit — direct access to free, no-auth open-data REST APIs
(FEAT-426 Module 2: World Bank Open Data; Module 2 tail tasks add EU Open
Data Portal and OECD SDMX).

World Bank has **no server-side keyword search**: indicators are looked up
by code or resolved from `query` via indicator metadata, then time-series
observations are fetched. See spec §3 Module 2 and §7 "Known Risks".
"""
import backoff
from parrot.tools.toolkit import AbstractToolkit

from .base import BaseResearchToolkit
from .models import IndicatorValue, ResearchResult

try:
    import wbgapi as wb
except ImportError:
    wb = None

_WB_SOURCE_NAME = "World Bank Open Data"
_WB_LICENSE = "CC BY-4.0"
_WB_MISSING_MESSAGE = (
    "World Bank support requires: pip install 'ai-parrot-tools[research]'"
)


class OpenDataToolkit(BaseResearchToolkit, AbstractToolkit):
    """Direct, structured access to authoritative open-data sources.

    Currently covers World Bank Open Data (indicator/time-series lookup).
    EU Open Data Portal and OECD SDMX methods are added by later tasks in
    this same module (spec §3 Module 2).
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
