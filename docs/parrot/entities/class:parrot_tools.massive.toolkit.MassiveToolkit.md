---
type: Wiki Entity
title: MassiveToolkit
id: class:parrot_tools.massive.toolkit.MassiveToolkit
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Premium market data enrichment from Massive.com (ex-Polygon.io).
relates_to:
- concept: class:parrot.tools.toolkit.AbstractToolkit
  rel: extends
---

# MassiveToolkit

Defined in [`parrot_tools.massive.toolkit`](../summaries/mod:parrot_tools.massive.toolkit.md).

```python
class MassiveToolkit(AbstractToolkit)
```

Premium market data enrichment from Massive.com (ex-Polygon.io).

Provides options chains with Greeks, FINRA short interest/volume,
Benzinga earnings data, and analyst ratings. All methods implement
graceful degradation — errors return a structured fallback dict
instead of raising exceptions.

## Methods

- `async def stop(self)` — Close connections on shutdown.
- `async def get_options_chain_enriched(self, underlying: str, expiration_date_gte: str | None=None, expiration_date_lte: str | None=None, strike_price_gte: float | None=None, strike_price_lte: float | None=None, contract_type: str | None=None, limit: int=250) -> dict` — Fetch options chain with pre-computed Greeks and IV.
- `async def get_short_interest(self, symbol: str, limit: int=10, order: str='desc') -> dict` — Fetch FINRA short interest data with derived trend metrics.
- `async def get_short_volume(self, symbol: str, date_from: str | None=None, date_to: str | None=None, limit: int=30) -> dict` — Fetch daily FINRA short volume data with derived ratios.
- `async def get_earnings_data(self, symbol: str | None=None, date_from: str | None=None, date_to: str | None=None, importance: int | None=None, limit: int=50) -> dict` — Fetch Benzinga earnings data with revenue surprise metrics.
- `async def get_analyst_ratings(self, symbol: str, action: str | None=None, date_from: str | None=None, limit: int=20, include_consensus: bool=True) -> dict` — Fetch Benzinga analyst ratings with consensus summary.
- `async def enrich_ticker(self, symbol: str) -> dict[str, Any]` — Fetch all available data for a single ticker in parallel.
- `async def enrich_candidates(self, symbols: list[str], endpoints: list[str] | None=None, max_concurrent: int | None=None) -> dict[str, dict]` — Enrich multiple tickers with rate-limit-aware concurrency.
