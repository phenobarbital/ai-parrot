import asyncio
from parrot.tools.fear_greed import FearGreedTool

async def main():
    tool = FearGreedTool()
    print("Testing Fear & Greed Tool...")
    
    try:
        result = await tool._execute(limit=2)
        print("Result:")
        import json
        print(json.dumps(result, indent=2))
        
        # Verify structure
        if "data" in result and len(result["data"]) > 0:
            print("\nVerification Successful: Data retrieved.")
        else:
            print("\nVerification Failed: No data retrieved.")
            
    except Exception as e:
        print(f"\nVerification Failed with error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
