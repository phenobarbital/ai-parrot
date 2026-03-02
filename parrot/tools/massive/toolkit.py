"""
MassiveToolkit — Premium market data enrichment from Massive.com (ex-Polygon.io).

Provides institutional-grade data not available from free APIs:
- Options chains with exchange-computed Greeks and IV
- FINRA short interest and short volume data
- Benzinga earnings with revenue estimates/actuals
- Benzinga analyst ratings with individual analyst actions
"""

import asyncio
import os
from datetime import datetime, timezone
from typing import Any

from navconfig.logging import logging

from ..toolkit import AbstractToolkit
from .cache import MassiveCache
from .client import MassiveClient, MassiveAPIError
from .models import (
    AnalystAction,
    AnalystRatingsDerived,
    AnalystRatingsOutput,
    ConsensusRating,
    EarningsDerived,
    EarningsOutput,
    EarningsRecord,
    GreeksData,
    OptionsChainOutput,
    OptionsContract,
    ShortInterestDerived,
    ShortInterestOutput,
    ShortInterestRecord,
    ShortVolumeDerived,
    ShortVolumeOutput,
    ShortVolumeRecord,
)


class MassiveToolkit(AbstractToolkit):
    """Premium market data enrichment from Massive.com (ex-Polygon.io).

    Provides options chains with Greeks, FINRA short interest/volume,
    Benzinga earnings data, and analyst ratings. All methods implement
    graceful degradation — errors return a structured fallback dict
    instead of raising exceptions.
    """

    name = "massive_toolkit"

    # Maximum concurrent API calls during batch enrichment.
    DEFAULT_MAX_CONCURRENT = 3

    def __init__(
        self,
        api_key: str | None = None,
        max_concurrent: int = DEFAULT_MAX_CONCURRENT,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.logger = logging.getLogger(self.__class__.__name__)
        self.api_key = api_key or os.environ.get("MASSIVE_API_KEY")
        if not self.api_key:
            raise ValueError(
                "MASSIVE_API_KEY required. "
                "Provide it as argument or set the MASSIVE_API_KEY env variable."
            )
        self._client = MassiveClient(api_key=self.api_key)
        self._cache = MassiveCache()
        self._benzinga_available: bool | None = None
        self._max_concurrent = max_concurrent

    # -------------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------------

    async def stop(self):
        """Close connections on shutdown."""
        await self._cache.close()
        # Ensure httpx client is closed if implemented there natively, but in our case,
        # MassiveClient re-news an AsyncClient per method call using `async with httpx.AsyncClient()`.
        # So we just cleanup cache.

    # -------------------------------------------------------------------------
    # Tool Methods — auto-discovered by AbstractToolkit
    # -------------------------------------------------------------------------

    async def get_options_chain_enriched(
        self,
        underlying: str,
        expiration_date_gte: str | None = None,
        expiration_date_lte: str | None = None,
        strike_price_gte: float | None = None,
        strike_price_lte: float | None = None,
        contract_type: str | None = None,
        limit: int = 250,
    ) -> dict:
        """Fetch options chain with pre-computed Greeks and IV.

        Returns market-calibrated Greeks (delta, gamma, theta, vega) from
        OPRA data. Use for portfolio exposure calculations and spread analysis.
        """
        cache_params = dict(
            underlying=underlying,
            expiration_date_gte=expiration_date_gte,
            expiration_date_lte=expiration_date_lte,
            strike_price_gte=strike_price_gte,
            strike_price_lte=strike_price_lte,
            contract_type=contract_type,
            limit=limit,
        )
        try:
            cached = await self._cache.get("options_chain", **cache_params)
            if cached is not None:
                cached["cached"] = True
                return cached

            raw = await self._client.list_snapshot_options_chain(
                underlying,
                expiration_date_gte=expiration_date_gte,
                expiration_date_lte=expiration_date_lte,
                strike_price_gte=strike_price_gte,
                strike_price_lte=strike_price_lte,
                contract_type=contract_type,
                limit=limit,
            )
            result = self._transform_options_chain(raw, underlying)
            await self._cache.set("options_chain", result, **cache_params)
            return result
        except Exception as e:
            self.logger.warning("Massive options chain failed for %s: %s", underlying, e)
            return OptionsChainOutput(
                underlying=underlying,
                error=str(e),
                fallback="use_yfinance_options",
                source="massive_error",
            ).model_dump()

    async def get_short_interest(
        self,
        symbol: str,
        limit: int = 10,
        order: str = "desc",
    ) -> dict:
        """Fetch FINRA short interest data with derived trend metrics.

        Returns bi-monthly settlement data including short interest,
        days to cover, and derived change percentage and trend direction.
        """
        cache_params = dict(symbol=symbol, limit=limit, order=order)
        try:
            cached = await self._cache.get("short_interest", **cache_params)
            if cached is not None:
                cached["cached"] = True
                return cached

            raw = await self._client.list_short_interest(
                symbol, limit=limit, order=order,
            )
            result = self._transform_short_interest(raw, symbol)
            await self._cache.set("short_interest", result, **cache_params)
            return result
        except Exception as e:
            self.logger.warning("Massive short interest failed for %s: %s", symbol, e)
            return ShortInterestOutput(
                symbol=symbol,
                error=str(e),
                fallback="check_finviz_short_data",
                source="massive_error",
            ).model_dump()

    async def get_short_volume(
        self,
        symbol: str,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 30,
    ) -> dict:
        """Fetch daily FINRA short volume data with derived ratios.

        Returns daily short volume, total volume, short ratio,
        and derived 5/20-day averages with trend analysis.
        """
        cache_params = dict(
            symbol=symbol, date_from=date_from, date_to=date_to, limit=limit,
        )
        try:
            cached = await self._cache.get("short_volume", **cache_params)
            if cached is not None:
                cached["cached"] = True
                return cached

            raw = await self._client.list_short_volume(
                symbol, date_from=date_from, date_to=date_to, limit=limit,
            )
            result = self._transform_short_volume(raw, symbol)
            await self._cache.set("short_volume", result, **cache_params)
            return result
        except Exception as e:
            self.logger.warning("Massive short volume failed for %s: %s", symbol, e)
            return ShortVolumeOutput(
                symbol=symbol,
                error=str(e),
                fallback="check_finviz_short_data",
                source="massive_error",
            ).model_dump()

    async def get_earnings_data(
        self,
        symbol: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        importance: int | None = None,
        limit: int = 50,
    ) -> dict:
        """Fetch Benzinga earnings data with revenue surprise metrics.

        Returns historical earnings with EPS/revenue estimates vs actuals,
        and derived beat rate and surprise averages.
        Requires Benzinga add-on in Massive plan.
        """
        if not await self._check_benzinga():
            return EarningsOutput(
                symbol=symbol,
                error="Benzinga endpoints not available in current plan",
                fallback="use_finnhub_earnings",
                source="massive_error",
            ).model_dump()

        cache_params = dict(
            symbol=symbol, date_from=date_from, date_to=date_to,
            importance=importance, limit=limit,
        )
        try:
            cached = await self._cache.get("earnings", **cache_params)
            if cached is not None:
                cached["cached"] = True
                return cached

            raw = await self._client.get_benzinga_earnings(
                symbol=symbol, date_from=date_from, date_to=date_to,
                importance=importance, limit=limit,
            )
            result = self._transform_earnings(raw, symbol)
            await self._cache.set("earnings", result, **cache_params)
            return result
        except Exception as e:
            self.logger.warning("Massive earnings failed for %s: %s", symbol, e)
            return EarningsOutput(
                symbol=symbol,
                error=str(e),
                fallback="use_finnhub_earnings",
                source="massive_error",
            ).model_dump()

    async def get_analyst_ratings(
        self,
        symbol: str,
        action: str | None = None,
        date_from: str | None = None,
        limit: int = 20,
        include_consensus: bool = True,
    ) -> dict:
        """Fetch Benzinga analyst ratings with consensus summary.

        Returns individual analyst actions (upgrades, downgrades, initiations)
        and consensus rating summary with target prices.
        Requires Benzinga add-on in Massive plan.
        """
        if not await self._check_benzinga():
            return AnalystRatingsOutput(
                symbol=symbol,
                error="Benzinga endpoints not available in current plan",
                fallback="use_finnhub_recommendations",
                source="massive_error",
            ).model_dump()

        cache_params = dict(
            symbol=symbol, action=action, date_from=date_from,
            limit=limit, include_consensus=include_consensus,
        )
        try:
            cached = await self._cache.get("analyst_ratings", **cache_params)
            if cached is not None:
                cached["cached"] = True
                return cached

            raw_actions = await self._client.get_benzinga_analyst_ratings(
                symbol=symbol, action=action, date_from=date_from, limit=limit,
            )

            consensus_data = None
            if include_consensus:
                try:
                    consensus_data = await self._client.get_benzinga_consensus_ratings(
                        symbol=symbol,
                    )
                except Exception as exc:
                    self.logger.debug("Consensus ratings failed for %s: %s", symbol, exc)

            result = self._transform_analyst_ratings(raw_actions, consensus_data, symbol)
            await self._cache.set("analyst_ratings", result, **cache_params)
            return result
        except Exception as e:
            self.logger.warning("Massive analyst ratings failed for %s: %s", symbol, e)
            return AnalystRatingsOutput(
                symbol=symbol,
                error=str(e),
                fallback="use_finnhub_recommendations",
                source="massive_error",
            ).model_dump()

    # -------------------------------------------------------------------------
    # Convenience Methods
    # -------------------------------------------------------------------------

    async def enrich_ticker(self, symbol: str) -> dict[str, Any]:
        """Fetch all available data for a single ticker in parallel.

        Returns a dict keyed by endpoint name with each result.
        """
        tasks = {
            "options_chain": self.get_options_chain_enriched(underlying=symbol),
            "short_interest": self.get_short_interest(symbol=symbol),
            "short_volume": self.get_short_volume(symbol=symbol),
            "earnings": self.get_earnings_data(symbol=symbol),
            "analyst_ratings": self.get_analyst_ratings(symbol=symbol),
        }

        results = await asyncio.gather(*tasks.values(), return_exceptions=True)

        enriched: dict[str, Any] = {"symbol": symbol}
        for key, result in zip(tasks.keys(), results):
            if isinstance(result, Exception):
                self.logger.warning("enrich_ticker %s/%s failed: %s", symbol, key, result)
                enriched[key] = {"error": str(result), "source": "massive_error"}
            else:
                enriched[key] = result

        return enriched

    async def enrich_candidates(
        self,
        symbols: list[str],
        endpoints: list[str] | None = None,
        max_concurrent: int | None = None,
    ) -> dict[str, dict]:
        """Enrich multiple tickers with rate-limit-aware concurrency.

        Args:
            symbols: List of ticker symbols to enrich.
            endpoints: Optional list of specific endpoints to call. Defaults to all.
            max_concurrent: Max parallel API calls. Defaults to instance setting.

        Returns:
            Dict keyed by symbol with enrichment results.
        """
        semaphore = asyncio.Semaphore(max_concurrent or self._max_concurrent)

        async def _enrich_one(sym: str) -> tuple[str, dict]:
            async with semaphore:
                if endpoints:
                    result = await self._enrich_ticker_selective(sym, endpoints)
                else:
                    result = await self.enrich_ticker(sym)
                return sym, result

        tasks = [_enrich_one(sym) for sym in symbols]
        completed = await asyncio.gather(*tasks, return_exceptions=True)

        results: dict[str, dict] = {}
        for item in completed:
            if isinstance(item, Exception):
                self.logger.warning("enrich_candidates failed for item: %s", item)
            else:
                sym, data = item
                results[sym] = data

        return results

    async def _enrich_ticker_selective(
        self, symbol: str, endpoints: list[str],
    ) -> dict[str, Any]:
        """Enrich a ticker with only the specified endpoints."""
        endpoint_map = {
            "options_chain": lambda: self.get_options_chain_enriched(underlying=symbol),
            "short_interest": lambda: self.get_short_interest(symbol=symbol),
            "short_volume": lambda: self.get_short_volume(symbol=symbol),
            "earnings": lambda: self.get_earnings_data(symbol=symbol),
            "analyst_ratings": lambda: self.get_analyst_ratings(symbol=symbol),
        }

        tasks = {}
        for ep in endpoints:
            if ep in endpoint_map:
                tasks[ep] = endpoint_map[ep]()

        if not tasks:
            return {"symbol": symbol, "error": f"No valid endpoints: {endpoints}"}

        results = await asyncio.gather(*tasks.values(), return_exceptions=True)

        enriched: dict[str, Any] = {"symbol": symbol}
        for key, result in zip(tasks.keys(), results):
            if isinstance(result, Exception):
                enriched[key] = {"error": str(result), "source": "massive_error"}
            else:
                enriched[key] = result

        return enriched

    # -------------------------------------------------------------------------
    # Benzinga Detection
    # -------------------------------------------------------------------------

    async def _check_benzinga(self) -> bool:
        """Lazy-check if Benzinga endpoints are available in the current plan.

        Makes a minimal probe on the first call; caches the result for the
        lifetime of this toolkit instance.
        """
        if self._benzinga_available is not None:
            return self._benzinga_available

        try:
            # Minimal probe: fetch 1 earning record
            await self._client.get_benzinga_earnings(limit=1)
            self._benzinga_available = True
        except MassiveAPIError as e:
            if e.status_code in (403, 401):
                self.logger.warning(
                    "Benzinga endpoints not available (plan restriction): %s", e
                )
                self._benzinga_available = False
            else:
                # Transient error — don't cache the failure
                self.logger.warning("Benzinga probe failed (transient): %s", e)
                return True  # Optimistic: let the real call attempt it
        except Exception as e:
            self.logger.warning("Benzinga probe failed: %s", e)
            return True  # Optimistic fallback

        return self._benzinga_available

    # -------------------------------------------------------------------------
    # Transform Helpers
    # -------------------------------------------------------------------------

    def _safe_get(self, item: dict, path: str, default=None):
        """Safely extract nested dictionary values using dot notation."""
        if not isinstance(item, dict):
            return default
            
        keys = path.split(".")
        current = item
        for key in keys:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return default
        return current

    def _safe_float(self, val):
        try:
            return float(val) if val is not None else None
        except (ValueError, TypeError):
            return None

    def _transform_options_chain(
        self, raw: list[Any], underlying: str,
    ) -> dict:
        """Transform API options chain response to spec output structure."""
        contracts = []
        underlying_price = None

        for item in raw or []:
            if not isinstance(item, dict):
                item = vars(item) if hasattr(item, "__dict__") else {}
                
            greeks = GreeksData(
                delta=self._safe_float(self._safe_get(item, "greeks.delta")),
                gamma=self._safe_float(self._safe_get(item, "greeks.gamma")),
                theta=self._safe_float(self._safe_get(item, "greeks.theta")),
                vega=self._safe_float(self._safe_get(item, "greeks.vega")),
            )

            bid = self._safe_float(self._safe_get(item, "last_quote.bid") or item.get("bid"))
            ask = self._safe_float(self._safe_get(item, "last_quote.ask") or item.get("ask"))
            midpoint = None
            if bid is not None and ask is not None:
                midpoint = round((bid + ask) / 2, 4)

            contract = OptionsContract(
                ticker=item.get("ticker", "") or self._safe_get(item, "details.ticker", ""),
                strike=self._safe_float(item.get("strike_price") or self._safe_get(item, "details.strike_price", 0.0)),
                expiration=item.get("expiration_date", "") or self._safe_get(item, "details.expiration_date", ""),
                contract_type=item.get("contract_type", "") or self._safe_get(item, "details.contract_type", ""),
                greeks=greeks,
                implied_volatility=self._safe_float(item.get("implied_volatility")),
                open_interest=item.get("open_interest"),
                volume=item.get("volume") or self._safe_get(item, "day.volume"),
                bid=bid,
                ask=ask,
                midpoint=midpoint,
                last_trade_price=self._safe_float(self._safe_get(item, "last_trade.price")),
                break_even_price=self._safe_float(item.get("break_even_price")),
            )
            contracts.append(contract)

            # Extract underlying price from first contract's underlying snapshot if available
            if underlying_price is None:
                underlying_price = self._safe_float(self._safe_get(item, "underlying_asset.price"))

        output = OptionsChainOutput(
            underlying=underlying,
            underlying_price=underlying_price,
            timestamp=datetime.now(timezone.utc).isoformat(),
            contracts_count=len(contracts),
            contracts=contracts,
            source="massive",
            cached=False,
        )
        return output.model_dump()

    def _transform_short_interest(
        self, raw: list[Any], symbol: str,
    ) -> dict:
        """Transform API short interest response to spec output structure."""
        records = []
        for item in raw or []:
            if not isinstance(item, dict):
                item = vars(item) if hasattr(item, "__dict__") else {}
                
            record = ShortInterestRecord(
                settlement_date=item.get("settlement_date", "") or str(item.get("date", "")),
                short_interest=item.get("short_volume", 0) or item.get("short_interest", 0),
                avg_daily_volume=item.get("avg_daily_volume"),
                days_to_cover=self._safe_float(item.get("days_to_cover")),
            )
            records.append(record)

        derived = self._compute_short_interest_derived(records)
        latest = records[0] if records else None

        output = ShortInterestOutput(
            symbol=symbol,
            latest=latest,
            history=records,
            derived=derived,
            source="massive",
            cached=False,
        )
        return output.model_dump()

    def _compute_short_interest_derived(
        self, records: list[ShortInterestRecord],
    ) -> ShortInterestDerived:
        """Compute derived metrics from short interest records."""
        if len(records) < 2:
            return ShortInterestDerived()

        latest_si = records[0].short_interest
        prev_si = records[1].short_interest

        change_pct = None
        if prev_si and prev_si > 0:
            change_pct = round(((latest_si - prev_si) / prev_si) * 100, 2)

        trend = None
        if change_pct is not None:
            if change_pct > 5:
                trend = "increasing"
            elif change_pct < -5:
                trend = "decreasing"
            else:
                trend = "stable"

        # Days to cover z-score (simplified: compare to mean of all periods)
        dtc_values = [r.days_to_cover for r in records if r.days_to_cover is not None]
        dtc_zscore = None
        if len(dtc_values) >= 3 and dtc_values[0] is not None:
            mean_dtc = sum(dtc_values) / len(dtc_values)
            variance = sum((v - mean_dtc) ** 2 for v in dtc_values) / len(dtc_values)
            std_dtc = variance ** 0.5
            if std_dtc > 0:
                dtc_zscore = round((dtc_values[0] - mean_dtc) / std_dtc, 2)

        return ShortInterestDerived(
            short_interest_change_pct=change_pct,
            trend=trend,
            days_to_cover_zscore=dtc_zscore,
        )

    def _transform_short_volume(
        self, raw: list[Any], symbol: str,
    ) -> dict:
        """Transform API short volume response to spec output structure."""
        records = []
        for item in raw or []:
            if not isinstance(item, dict):
                item = vars(item) if hasattr(item, "__dict__") else {}
                
            short_vol = item.get("short_volume", 0) or 0
            total_vol = item.get("total_volume", 0) or item.get("volume", 0) or 1
            short_exempt = item.get("short_exempt_volume")

            ratio = round(short_vol / total_vol, 4) if total_vol > 0 else 0.0

            record = ShortVolumeRecord(
                date=item.get("date", "") or str(item.get("timestamp", "")),
                short_volume=short_vol,
                short_exempt_volume=short_exempt,
                total_volume=total_vol,
                short_volume_ratio=ratio,
            )
            records.append(record)

        derived = self._compute_short_volume_derived(records)

        output = ShortVolumeOutput(
            symbol=symbol,
            data=records,
            derived=derived,
            source="massive",
            cached=False,
        )
        return output.model_dump()

    def _compute_short_volume_derived(
        self, records: list[ShortVolumeRecord],
    ) -> ShortVolumeDerived:
        """Compute derived metrics from short volume records."""
        if not records:
            return ShortVolumeDerived()

        ratios = [r.short_volume_ratio for r in records]

        avg_5d = round(sum(ratios[:5]) / min(len(ratios), 5), 4) if ratios else None
        avg_20d = round(sum(ratios[:20]) / min(len(ratios), 20), 4) if ratios else None

        current_vs_20d = None
        if avg_20d is not None and ratios:
            diff = ratios[0] - avg_20d
            if diff > 0.05:
                current_vs_20d = "above_average"
            elif diff < -0.05:
                current_vs_20d = "below_average"
            else:
                current_vs_20d = "normal"

        trend_5d = None
        if len(ratios) >= 5:
            first_half = sum(ratios[:2]) / 2
            second_half = sum(ratios[2:5]) / 3
            diff = first_half - second_half
            if diff > 0.02:
                trend_5d = "increasing"
            elif diff < -0.02:
                trend_5d = "decreasing"
            else:
                trend_5d = "stable"

        return ShortVolumeDerived(
            avg_short_ratio_5d=avg_5d,
            avg_short_ratio_20d=avg_20d,
            current_vs_20d=current_vs_20d,
            trend_5d=trend_5d,
        )

    def _transform_earnings(
        self, raw: list[Any], symbol: str | None,
    ) -> dict:
        """Transform API earnings response to spec output structure."""
        records = []
        for item in raw or []:
            if not isinstance(item, dict):
                item = vars(item) if hasattr(item, "__dict__") else {}
                
            eps_estimate = self._safe_float(item.get("eps_estimate"))
            eps_actual = self._safe_float(item.get("eps_actual"))
            rev_estimate = self._safe_float(item.get("revenue_estimate"))
            rev_actual = self._safe_float(item.get("revenue_actual"))

            eps_surprise = None
            if eps_estimate and eps_actual and eps_estimate != 0:
                eps_surprise = round(((eps_actual - eps_estimate) / abs(eps_estimate)) * 100, 2)

            rev_surprise = None
            if rev_estimate and rev_actual and rev_estimate != 0:
                rev_surprise = round(((rev_actual - rev_estimate) / abs(rev_estimate)) * 100, 2)

            record = EarningsRecord(
                date=item.get("date", "") or str(item.get("date_reported", "")),
                time=item.get("time") or item.get("timing"),
                period=item.get("period") or item.get("fiscal_period"),
                eps_estimate=eps_estimate,
                eps_actual=eps_actual,
                eps_surprise_pct=eps_surprise,
                revenue_estimate=rev_estimate,
                revenue_actual=rev_actual,
                revenue_surprise_pct=rev_surprise,
            )
            records.append(record)

        derived = self._compute_earnings_derived(records)

        output = EarningsOutput(
            symbol=symbol,
            earnings=records,
            derived=derived,
            source="massive_benzinga",
            cached=False,
        )
        return output.model_dump()

    def _compute_earnings_derived(
        self, records: list[EarningsRecord],
    ) -> EarningsDerived:
        """Compute derived metrics from earnings records."""
        if not records:
            return EarningsDerived()

        # Look at last 4 quarters (or less)
        recent = records[:4]

        beats = 0
        eps_surprises = []
        rev_surprises = []

        for rec in recent:
            if rec.eps_surprise_pct is not None:
                eps_surprises.append(rec.eps_surprise_pct)
                if rec.eps_surprise_pct > 0:
                    beats += 1
            if rec.revenue_surprise_pct is not None:
                rev_surprises.append(rec.revenue_surprise_pct)

        total = len(eps_surprises)
        beat_rate = round(beats / total, 2) if total > 0 else None

        avg_eps = round(sum(eps_surprises) / len(eps_surprises), 2) if eps_surprises else None
        avg_rev = round(sum(rev_surprises) / len(rev_surprises), 2) if rev_surprises else None

        trend = None
        if beat_rate is not None:
            if beat_rate >= 0.75:
                trend = "consistent_beater"
            elif beat_rate <= 0.25:
                trend = "consistent_misser"
            else:
                trend = "mixed"

        return EarningsDerived(
            beat_rate_4q=beat_rate,
            avg_eps_surprise_4q=avg_eps,
            avg_revenue_surprise_4q=avg_rev,
            trend=trend,
        )

    def _transform_analyst_ratings(
        self,
        raw_actions: list[Any],
        consensus_data: Any,
        symbol: str,
    ) -> dict:
        """Transform API analyst ratings to spec output structure."""
        actions = []
        for item in raw_actions or []:
            if not isinstance(item, dict):
                item = vars(item) if hasattr(item, "__dict__") else {}
                
            action = AnalystAction(
                date=item.get("date", "") or str(item.get("action_date", "")),
                analyst=item.get("analyst") or item.get("analyst_name"),
                firm=item.get("analyst_firm", "") or item.get("firm", ""),
                action=item.get("action_type", "") or item.get("rating_action", ""),
                rating_prior=item.get("rating_prior") or item.get("pt_prior"),
                rating_current=item.get("rating_current", "") or item.get("rating", ""),
                price_target_prior=self._safe_float(
                    item.get("pt_prior") or item.get("price_target_prior")
                ),
                price_target_current=self._safe_float(
                    item.get("pt_current") or item.get("price_target")
                ),
            )
            actions.append(action)

        consensus = self._transform_consensus(consensus_data) if consensus_data else None
        derived = self._compute_analyst_derived(actions)

        output = AnalystRatingsOutput(
            symbol=symbol,
            recent_actions=actions,
            consensus=consensus,
            derived=derived,
            source="massive_benzinga",
            cached=False,
        )
        return output.model_dump()

    def _transform_consensus(self, raw: Any) -> ConsensusRating | None:
        """Transform consensus rating data."""
        if raw is None:
            return None

        if isinstance(raw, dict):
            # Often it's wrapped in `{"results": {...}}` at the client level, 
            # but we assume the client unwraps it if it can. If not, handle here
            data = raw.get("results", raw) if "results" in raw else raw
        elif isinstance(raw, list) and raw:
            data = raw[0] if isinstance(raw[0], dict) else vars(raw[0]) if hasattr(raw[0], "__dict__") else {}
        elif hasattr(raw, "__dict__"):
            data = vars(raw)
        else:
            return None

        return ConsensusRating(
            buy=data.get("buy", 0) or 0,
            hold=data.get("hold", 0) or 0,
            sell=data.get("sell", 0) or 0,
            strong_buy=data.get("strongBuy", 0) or data.get("strong_buy", 0) or 0,
            strong_sell=data.get("strongSell", 0) or data.get("strong_sell", 0) or 0,
            mean_target=self._safe_float(data.get("targetMean") or data.get("mean_target")),
            high_target=self._safe_float(data.get("targetHigh") or data.get("high_target")),
            low_target=self._safe_float(data.get("targetLow") or data.get("low_target")),
            consensus_rating=data.get("consensus", None) or data.get("consensus_rating", None),
        )

    def _compute_analyst_derived(
        self, actions: list[AnalystAction],
    ) -> AnalystRatingsDerived:
        """Compute derived metrics from analyst actions."""
        if not actions:
            return AnalystRatingsDerived()

        now = datetime.now(timezone.utc)
        upgrades_30d = 0
        downgrades_30d = 0

        for act in actions:
            try:
                act_date = datetime.strptime(act.date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                days_ago = (now - act_date).days
                if days_ago <= 30:
                    action_lower = act.action.lower()
                    if "upgrade" in action_lower:
                        upgrades_30d += 1
                    elif "downgrade" in action_lower:
                        downgrades_30d += 1
            except (ValueError, TypeError):
                continue

        net_sentiment = None
        total = upgrades_30d + downgrades_30d
        if total > 0:
            ratio = upgrades_30d / total
            if ratio >= 0.6:
                net_sentiment = "positive"
            elif ratio <= 0.4:
                net_sentiment = "negative"
            else:
                net_sentiment = "neutral"

        # Recent momentum from all actions (not just 30d)
        recent_momentum = None
        if len(actions) >= 3:
            recent_actions_lower = [a.action.lower() for a in actions[:5]]
            upgrades = sum(1 for a in recent_actions_lower if "upgrade" in a or "initiate" in a)
            downgrades = sum(1 for a in recent_actions_lower if "downgrade" in a)
            if upgrades > downgrades:
                recent_momentum = "improving"
            elif downgrades > upgrades:
                recent_momentum = "deteriorating"
            else:
                recent_momentum = "stable"

        return AnalystRatingsDerived(
            upgrades_30d=upgrades_30d,
            downgrades_30d=downgrades_30d,
            net_sentiment=net_sentiment,
            recent_momentum=recent_momentum,
        )


# =============================================================================
# Module-level helpers
# =============================================================================


def _safe_getattr(obj: Any, path: str, default: Any = None) -> Any:
    """Safely traverse nested attributes using dot notation."""
    current = obj
    for attr in path.split("."):
        if current is None:
            return default
        current = getattr(current, attr, None)
    return current if current is not None else default


def _safe_float(value: Any) -> float | None:
    """Convert value to float or return None."""
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None
