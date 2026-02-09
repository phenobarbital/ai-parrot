import pytest
from parrot.tools.coingecko import CoingeckoToolkit

@pytest.mark.asyncio
async def test_ping():
    toolkit = CoingeckoToolkit(demo=True)
    res = await toolkit.ping()
    assert "gecko_says" in res

@pytest.mark.asyncio
async def test_simple_price():
    toolkit = CoingeckoToolkit(demo=True)
    res = await toolkit.cg_simple_price(ids="bitcoin", vs_currencies="usd")
    assert "bitcoin" in res
    assert "usd" in res["bitcoin"]

@pytest.mark.asyncio
async def test_coins_list():
    toolkit = CoingeckoToolkit(demo=True)
    res = await toolkit.cg_coins_list()
    assert isinstance(res, list)
    assert len(res) > 0
    assert "id" in res[0]
    assert "symbol" in res[0]
    assert "name" in res[0]

@pytest.mark.asyncio
async def test_coins_markets():
    toolkit = CoingeckoToolkit(demo=True)
    res = await toolkit.cg_coins_markets(vs_currency="usd", ids="bitcoin", per_page=1)
    assert isinstance(res, list)
    assert len(res) == 1
    assert res[0]["id"] == "bitcoin"

@pytest.mark.asyncio
async def test_search_trending():
    toolkit = CoingeckoToolkit(demo=True)
    res = await toolkit.cg_search_trending()
    assert "coins" in res
    assert "nfts" in res
    assert "categories" in res
