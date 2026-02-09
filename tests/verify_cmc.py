import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from parrot.tools.cmc_fear_greed import CMCFearGreedTool

async def main():
    print("Initializing CMC Fear & Greed Tool...")
    tool = CMCFearGreedTool()
    
    print("\nTest 1: Fetch latest 10 records (default)")
    try:
        result = await tool.execute(limit=10)
        print(f"Success! Retrieved {result.result.total_count} records.")
        print("Data sample:")
        for item in result.result.data[:3]:
            print(f"  {item.timestamp}: {item.value} ({item.value_classification})")
    except Exception as e:
        print(f"Error in Test 1: {e}")

    print("\nTest 2: Fetch with start parameter")
    try:
        # Start from index 10 (older records)
        result = await tool.execute(limit=5, start=10)
        print(f"Success! Retrieved {len(result.result.data)} records (requested 5).")
        print("Data sample:")
        for item in result.result.data:
            print(f"  {item.timestamp}: {item.value} ({item.value_classification})")
    except Exception as e:
        print(f"Error in Test 2: {e}")

if __name__ == "__main__":
    asyncio.run(main())
