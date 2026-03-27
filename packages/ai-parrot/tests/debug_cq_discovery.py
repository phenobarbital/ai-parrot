import asyncio
import os
from parrot.tools.cryptoquant import CryptoQuantToolkit
from navconfig import config

async def debug_discovery():
    tool = CryptoQuantToolkit()
    try:
        endpoints = await tool.cq_discovery_endpoints()
        if isinstance(endpoints, dict) and 'result' in endpoints:
             data = endpoints['result'].get('data', [])
             targets = ['/v1/btc/miner-flows/netflow']
             for item in data:
                 if item.get('path') in targets:
                     print(f"PATH: {item['path']}")
                     print(f"PARAMS: {item.get('parameters')}")
                     print(f"REQUIRED: {item.get('required_parameters')}")
                     print("-" * 20)
        else:
             print(endpoints)
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    loop = asyncio.events.new_event_loop()
    loop.run_until_complete(debug_discovery())
