import pytest
import asyncio
import os
from parrot.tools.cryptoquant import CryptoQuantToolkit
from navconfig import config

@pytest.mark.asyncio
async def test_real_discovery_endpoints():
    """
    Test the CryptoQuant discovery endpoints with a real API call.
    This test requires a valid API key in the environment or config.
    """
    api_key = config.get('CRYPTOQUANT_API_KEY', os.getenv('CRYPTOQUANT_API_KEY'))
    if not api_key:
        pytest.skip("CRYPTOQUANT_API_KEY not found in config or environment")

    toolkit = CryptoQuantToolkit(api_key=api_key)
    
    print(f"Testing with API Key: {api_key[:4]}...")

    try:
        result = await toolkit.cq_discovery_endpoints()
        assert result is not None
        assert "status" in result
        assert result["status"]["code"] == 200
        assert "result" in result
        print("Discovery endpoints fetched successfully.")
    except Exception as e:
        pytest.fail(f"Real API call failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_real_discovery_endpoints())
