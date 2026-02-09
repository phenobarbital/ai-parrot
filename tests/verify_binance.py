import asyncio
import os
from parrot.tools.binance import BinanceToolkit
from navconfig import config

async def verify_binance():
    # Check for API keys
    api_key = config.get('BINANCE_API_KEY')
    if not api_key:
        print("[WARNING] BINANCE_API_KEY not set. Some endpoints might fail or be rate limited.")
    else:
        print(f"[INFO] Using BINANCE_API_KEY: {api_key[:4]}...{api_key[-4:]}")

    tool = BinanceToolkit()
    symbol = "BTCUSDT"
    
    print(f"\n--- Verifying Spot Data for {symbol} ---")
    try:
        price = await tool.get_spot_price(symbol)
        print(f"Spot Price: {price}")
    except Exception as e:
        print(f"Error fetching Spot Price: {e}")

    try:
        info = await tool.get_exchange_info()
        print(f"Exchange Info (partial): {list(info.keys()) if isinstance(info, dict) else 'Error'}")
    except Exception as e:
        print(f"Error fetching Exchange Info: {e}")

    print(f"\n--- Verifying Futures Data for {symbol} ---")
    try:
        f_price = await tool.get_futures_price(symbol)
        print(f"Futures Price: {f_price}")
    except Exception as e:
        print(f"Error fetching Futures Price: {e}")

    try:
        funding = await tool.get_funding_rate(symbol, limit=2)
        print(f"Funding Rate (last 2): {funding}")
    except Exception as e:
        print(f"Error fetching Funding Rate: {e}")

    try:
        oi = await tool.get_open_interest(symbol)
        print(f"Open Interest: {oi}")
    except Exception as e:
        print(f"Error fetching Open Interest: {e}")

    try:
        ls_ratio = await tool.get_top_long_short_ratio_accounts(symbol, period="1h", limit=1)
        print(f"Top L/S Ratio (Accounts): {ls_ratio}")
    except Exception as e:
        print(f"Error fetching L/S Ratio: {e}")
        
    try:
        taker_vol = await tool.get_taker_volume(symbol, period="1h", limit=1)
        print(f"Taker Volume: {taker_vol}")
    except Exception as e:
        print(f"Error fetching Taker Volume: {e}")

if __name__ == "__main__":
    loop = asyncio.events.new_event_loop()
    loop.run_until_complete(verify_binance())
