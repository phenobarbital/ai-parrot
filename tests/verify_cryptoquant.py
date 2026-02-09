import asyncio
import os
from parrot.tools.cryptoquant import CryptoQuantToolkit
from navconfig import config

async def verify_cryptoquant():
    # Check for API keys
    api_key = config.get('CRYPTOQUANT_API_KEY')
    if not api_key:
        print("[WARNING] CRYPTOQUANT_API_KEY not set. Expecting authentication errors.")
    else:
        print(f"[INFO] Using CRYPTOQUANT_API_KEY: {api_key[:4]}...{api_key[-4:]}")

    tool = CryptoQuantToolkit()
    token = "btc"
    exchange = "binance"
    
    print(f"\n--- Verifying Discovery ---")
    try:
        endpoints = await tool.cq_discovery_endpoints()
        print(f"Discovery Endpoints (keys): {list(endpoints.keys()) if isinstance(endpoints, dict) else 'Error'}")
    except Exception as e:
        print(f"Error fetching Discovery: {e}")

    print(f"\n--- Verifying Exchange Flows for {token} on {exchange} ---")
    try:
        # Note: 'binance' might need specific exchange ID in CQ API, but let's try 'binance' first or 'all_exchanges' if supported
        flows = await tool.cq_exchange_flows(exchange=exchange, token=token, limit=1)
        print(f"Exchange Flows: {flows}")
    except Exception as e:
        print(f"Error fetching Exchange Flows: {e}")

    print(f"\n--- Verifying Miner Flows for {token} ---")
    try:
        miners = await tool.cq_miner_flows(token=token, limit=1)
        print(f"Miner Flows: {miners}")
    except Exception as e:
        print(f"Error fetching Miner Flows: {e}")

    print(f"\n--- Verifying Market Indicator (MVRV) for {token} ---")
    try:
        # 'mvrv' is a common indicator, let's see if this generic endpoint works or needs adjustment
        mvrv = await tool.cq_market_indicator(indicator="mvrv", token=token, limit=1)
        print(f"MVRV Indicator: {mvrv}")
    except Exception as e:
        print(f"Error fetching MVRV: {e}")

if __name__ == "__main__":
    loop = asyncio.events.new_event_loop()
    loop.run_until_complete(verify_cryptoquant())
