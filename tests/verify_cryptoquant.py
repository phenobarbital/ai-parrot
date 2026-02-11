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
        # Print first few items of result to verify structure
        if isinstance(endpoints, dict) and 'result' in endpoints:
             print(f"Discovery Result (first 3 items): {endpoints['result'][:3] if isinstance(endpoints['result'], list) else endpoints['result']}")
        else:
             print(f"Discovery Raw: {endpoints}")
    except Exception as e:
        print(f"Error fetching Discovery: {e}")

    print(f"\n--- Verifying Exchange Flows for {token} on {exchange} ---")
    try:
        # Using 'binance' as exchange, 'netflow' as default flow_type
        flows = await tool.cq_exchange_flows(exchange=exchange, token=token, flow_type="netflow", limit=1)
        print(f"Exchange Flows: {flows}")
    except Exception as e:
        print(f"Error fetching Exchange Flows: {e}")

    print(f"\n--- Verifying Miner Flows for {token} ---")
    try:
        # Using 'all_miner' as default
        miners = await tool.cq_miner_flows(miner="all_miner", token=token, flow_type="netflow", limit=1)
        print(f"Miner Flows: {miners}")
    except Exception as e:
        print(f"Error fetching Miner Flows: {e}")

    print(f"\n--- Verifying Market Indicator (SOPR) for {token} ---")
    try:
        # Using 'sopr' as it was verified in discovery
        sopr = await tool.cq_market_indicator(indicator="sopr", token=token, limit=1)
        print(f"SOPR Indicator: {sopr}")
    except Exception as e:
        print(f"Error fetching SOPR: {e}")

if __name__ == "__main__":
    loop = asyncio.events.new_event_loop()
    loop.run_until_complete(verify_cryptoquant())
