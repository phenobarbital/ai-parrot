import asyncio
import logging
import os
from dataclasses import dataclass, field

from parrot.finance.schemas import ResearchBriefing, ResearchItem

@dataclass
class CandidateTicker:
    symbol: str
    asset_class: str
    mention_count: int = 0
    max_relevance: float = 0.0
    mentioned_by: list[str] = field(default_factory=list)
    data_needs: set[str] = field(default_factory=set)


def _infer_asset_class(symbol: str) -> str:
    """Classify a symbol as 'equity', 'crypto', 'etf', or 'index'."""
    symbol = symbol.upper()
    crypto_symbols = {"BTC", "ETH", "SOL", "ADA", "XRP", "DOGE", "DOT", "LTC", "LINK"}
    etf_symbols = {"SPY", "QQQ", "IWM", "DIA", "VTI", "VOO", "ARKK", "KRE", "XLF", "XLE"}
    if symbol in crypto_symbols or symbol.endswith("USDT") or symbol.endswith("USD") and len(symbol) > 4:
        return "crypto"
    if symbol in etf_symbols:
        return "etf"
    return "equity"


def _infer_data_needs(crew_id: str, _item: ResearchItem) -> set[str]:
    """Map crew context to required Massive endpoints."""
    needs = set()
    if crew_id == "equity":
        needs.update({"options", "earnings", "analyst_ratings"})
    elif crew_id == "sentiment":
        needs.update({"short_interest", "short_volume"})
    return needs


def _extract_candidates(
    briefings: dict[str, ResearchBriefing],
    max_candidates: int | None = None
) -> list[CandidateTicker]:
    """Scan all briefings, build priority-ranked list of candidates."""
    if max_candidates is None:
        max_candidates = int(os.getenv("MASSIVE_MAX_CANDIDATES", "15"))

    candidates_map: dict[str, CandidateTicker] = {}

    for crew_id, briefing in briefings.items():
        for item in briefing.research_items:
            for symbol in item.assets_mentioned:
                symbol = symbol.upper()
                if symbol not in candidates_map:
                    asset_class = _infer_asset_class(symbol)
                    candidates_map[symbol] = CandidateTicker(
                        symbol=symbol,
                        asset_class=asset_class
                    )
                
                candidate = candidates_map[symbol]
                candidate.mention_count += 1
                if item.relevance_score > candidate.max_relevance:
                    candidate.max_relevance = item.relevance_score
                
                if crew_id not in candidate.mentioned_by:
                    candidate.mentioned_by.append(crew_id)
                
                # Update data needs based on crew
                needs = _infer_data_needs(crew_id, item)
                candidate.data_needs.update(needs)

    # Apply constraints after aggregation
    for candidate in candidates_map.values():
        if candidate.asset_class == "crypto":
            candidate.data_needs.clear()
        elif candidate.asset_class == "etf":
            # ETFs only get options, filter out the rest
            candidate.data_needs &= {"options"}

    # Rank: mention_count desc, then max_relevance desc
    ranked_candidates = sorted(
        candidates_map.values(),
        key=lambda c: (c.mention_count, c.max_relevance),
        reverse=True
    )

    return ranked_candidates[:max_candidates]

class EnrichmentService:
    """Core orchestration service for the enrichment pipeline.
    
    Extracts CandidateTicker needs from briefings, fetches premium data 
    from MassiveToolkit efficiently using concurrent calls, computes derived 
    options and short analytics, and merges results back into the briefings.
    """
    
    def __init__(
        self,
        massive_toolkit,
        redis_client,
        options_toolkit=None,
        quant_toolkit=None,
    ):
        self.massive = massive_toolkit
        self.redis = redis_client
        self.options = options_toolkit
        self.quant = quant_toolkit
        self.logger = logging.getLogger(self.__class__.__name__)

    async def enrich_briefings(self, briefings: dict[str, ResearchBriefing]) -> dict[str, ResearchBriefing]:
        """Main entry point for enriching briefings."""
        candidates = _extract_candidates(briefings)
        
        # Filter crypto and items that have no data_needs
        valid_candidates = [c for c in candidates if c.asset_class != "crypto" and c.data_needs]
        
        if not valid_candidates:
            return briefings
            
        enrichment_data = await self._fetch_enrichment(valid_candidates)
        enrichment_data = await self._compute_derived(enrichment_data)
        enriched_briefings = await self._merge_into_briefings(briefings, enrichment_data)
        
        return enriched_briefings

    async def _fetch_enrichment(self, candidates: list[CandidateTicker]) -> dict[str, dict]:
        """Fetch enrichment data for all candidates concurrently."""
        results = {}
        
        max_concurrent = getattr(self.massive, "DEFAULT_MAX_CONCURRENT", 3)
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def _fetch(c: CandidateTicker):
            async with semaphore:
                res = {}
                for ep in c.data_needs:
                    try:
                        # Check cache (pseudo cache integration for the spec)
                        cache_key = f"massive:{ep}:{c.symbol}"
                        cached = self.redis.get(cache_key) if self.redis else None
                        
                        if cached:
                            res[ep] = cached
                            continue
                            
                        # If not cached, fetch from MassiveToolkit
                        if ep == "options":
                            res["options"] = await self.massive.get_options_chain_enriched(c.symbol)
                        elif ep == "earnings":
                            res["earnings"] = await self.massive.get_earnings_data(c.symbol)
                        elif ep == "analyst_ratings":
                            res["analyst_ratings"] = await self.massive.get_analyst_ratings(c.symbol)
                        elif ep == "short_interest":
                            res["short_interest"] = await self.massive.get_short_interest(c.symbol)
                        elif ep == "short_volume":
                            res["short_volume"] = await self.massive.get_short_volume(c.symbol)
                            
                        # Set cache (simplified TTLs)
                        if self.redis and ep in res and "error" not in res[ep]:
                            self.redis.set(cache_key, res[ep], ex="900" if ep == "options" else "14400")
                            
                    except Exception as e:
                        self.logger.warning(f"Error fetching {ep} for {c.symbol}: {e}")
                        res[ep] = {"error": str(e)}
                        
                return c.symbol, res
        
        tasks = [_fetch(c) for c in candidates]
        completed = await asyncio.gather(*tasks, return_exceptions=True)
        
        for item in completed:
            if isinstance(item, Exception):
                self.logger.error(f"Enrichment task failed: {item}")
            else:
                sym, data = item
                results[sym] = data
                
        return results

    async def _compute_derived(self, enrichment: dict[str, dict]) -> dict[str, dict]:
        """Compute derived metrics from raw massive data."""
        for symbol, data in enrichment.items():
            # Derived Options: Put/Call OI ratio
            options_data = data.get("options")
            if options_data and "error" not in options_data:
                try:
                    contracts = options_data.get("contracts", [])
                    puts = [c for c in contracts if c.get("contract_type") == "put"]
                    calls = [c for c in contracts if c.get("contract_type") == "call"]
                    
                    put_oi = sum(c.get("open_interest") or 0 for c in puts)
                    call_oi = sum(c.get("open_interest") or 0 for c in calls)
                    put_call_oi_ratio = put_oi / call_oi if call_oi > 0 else 0
                    
                    data["derived_options"] = {
                        "put_call_oi_ratio": round(put_call_oi_ratio, 2)
                    }
                except Exception as e:
                    self.logger.warning(f"Error computing derived options for {symbol}: {e}")
            
            # Derived Short: Squeeze Score
            si_data = data.get("short_interest")
            sv_data = data.get("short_volume")
            if si_data and "error" not in si_data and sv_data and "error" not in sv_data:
                try:
                    si_derived = si_data.get("derived", {})
                    si_trend = si_derived.get("trend")
                    dtc_z = si_derived.get("days_to_cover_zscore") or 0
                    
                    sv_derived = sv_data.get("derived", {})
                    sv_trend = sv_derived.get("trend_5d")
                    
                    score = 0
                    if si_trend == "increasing": 
                        score += 20
                    if dtc_z > 1.5: 
                        score += 30
                    if sv_trend == "increasing": 
                        score += 20
                        
                    data["derived_short"] = {
                        "squeeze_score": score,
                        "squeeze_risk": "high" if score > 50 else "moderate" if score > 30 else "low"
                    }
                except Exception as e:
                    self.logger.warning(f"Error computing derived short for {symbol}: {e}")

        return enrichment

    async def _merge_into_briefings(self, briefings: dict[str, ResearchBriefing], enrichment: dict[str, dict]) -> dict[str, ResearchBriefing]:
        """Merge enrichment properties back into briefings based on mapping rules."""
        for symbol, data in enrichment.items():
            for ep, dataset in data.items():
                if "error" in dataset:
                    continue
                
                item = ResearchItem(
                    source=f"massive:{ep}",
                    assets_mentioned=[symbol],
                    relevance_score=1.0,
                    raw_data={symbol: dataset}
                )
                
                if ep in ["options", "earnings", "analyst_ratings"]:
                    if "equity" in briefings:
                        briefings["equity"].research_items.append(item)
                elif ep in ["short_interest", "short_volume", "derived_short"]:
                    if "sentiment" in briefings:
                        briefings["sentiment"].research_items.append(item)
                elif ep == "derived_options":
                    if "risk" in briefings:
                        briefings["risk"].research_items.append(item)
                    elif "sentiment" in briefings:
                        briefings["sentiment"].research_items.append(item)
                        
        return briefings

