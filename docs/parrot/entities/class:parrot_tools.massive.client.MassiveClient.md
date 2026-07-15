---
type: Wiki Entity
title: MassiveClient
id: class:parrot_tools.massive.client.MassiveClient
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Async REST client for Massive API with retry and rate limit handling.
---

# MassiveClient

Defined in [`parrot_tools.massive.client`](../summaries/mod:parrot_tools.massive.client.md).

```python
class MassiveClient
```

Async REST client for Massive API with retry and rate limit handling.

Usage:
    client = MassiveClient(api_key="your-key")
    chain = await client.list_snapshot_options_chain("AAPL")

## Methods

- `async def list_snapshot_options_chain(self, underlying: str, expiration_date_gte: str | None=None, expiration_date_lte: str | None=None, strike_price_gte: float | None=None, strike_price_lte: float | None=None, contract_type: str | None=None, limit: int=250) -> list[Any]` — Fetch options chain snapshot with Greeks and IV.
- `async def list_short_interest(self, symbol: str, limit: int=10, order: str='desc') -> list[Any]` — Fetch FINRA short interest data.
- `async def list_short_volume(self, symbol: str, date_from: str | None=None, date_to: str | None=None, limit: int=30) -> list[Any]` — Fetch daily FINRA short volume data.
- `async def get_benzinga_earnings(self, symbol: str | None=None, date_from: str | None=None, date_to: str | None=None, importance: int | None=None, limit: int=50) -> list[Any]` — Fetch Benzinga earnings data.
- `async def get_benzinga_analyst_ratings(self, symbol: str, action: str | None=None, date_from: str | None=None, limit: int=20) -> list[Any]` — Fetch Benzinga analyst ratings.
- `async def get_benzinga_consensus_ratings(self, symbol: str) -> dict[str, Any]` — Fetch Benzinga consensus ratings.
