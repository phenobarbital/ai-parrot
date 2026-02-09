import asyncio
import sys
import os
from datetime import datetime

# Add project root to path
sys.path.append(os.getcwd())

from parrot.tools.cnn_fear_greed import CNNFearGreedTool

async def main():
    print("--- Starting CNN Fear & Greed Tool Verification ---")
    
    tool = CNNFearGreedTool()
    
    try:
        # Test 1: Simple Score (Default)
        print("\n[Test 1] Fetching latest score (full_dataset=False)...")
        result_simple = await tool._execute(full_dataset=False)
        print("Result Type:", type(result_simple))
        print("Score:", result_simple.score)
        print("Rating:", result_simple.rating)
        print("Timestamp:", result_simple.timestamp)
        
        # Test 2: Full History
        print("\n[Test 2] Fetching full history (full_dataset=True)...")
        result_full = await tool._execute(full_dataset=True, start_date="2023-01-01")
        print("Result Type:", type(result_full))
        print("Current Score from History Object:", result_full.current_score.score)
        print("History Points Count:", len(result_full.history))
        if result_full.history:
            print("First History Point:", result_full.history[0])
            print("Last History Point:", result_full.history[-1])
            
        print("\n--- Verification Completed Successfully ---")
        
    except Exception as e:
        print(f"\n[ERROR] Verification Failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
