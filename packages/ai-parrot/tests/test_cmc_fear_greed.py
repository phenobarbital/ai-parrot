import unittest
from unittest.mock import MagicMock, AsyncMock, patch
from parrot.tools.cmc_fear_greed import CMCFearGreedTool, CMCFearGreedData

class TestCMCFearGreedTool(unittest.IsolatedAsyncioTestCase):
    async def test_execute_success(self):
        # Mock HTTPService
        with patch('parrot.tools.cmc_fear_greed.HTTPService') as MockHTTPService:
            mock_service = MockHTTPService.return_value
            mock_service._logger = MagicMock() # Mock the logger since it's used
            
            # Mock async_request
            mock_response = {
                "status": {
                    "timestamp": "2024-09-03T12:00:00.000Z",
                    "error_code": 0,
                    "error_message": None,
                    "elapsed": 15,
                    "credit_count": 1,
                    "total_count": 2
                },
                "data": [
                    {
                        "timestamp": "2024-09-02T12:00:00.000Z",
                        "value": 50,
                        "value_classification": "Neutral"
                    },
                    {
                        "timestamp": "2024-09-01T12:00:00.000Z",
                        "value": 35,
                        "value_classification": "Fear"
                    }
                ]
            }
            mock_service.async_request = AsyncMock(return_value=(mock_response, None))

            tool = CMCFearGreedTool(api_key="test_key")
            result = await tool.execute(limit=2)

            # Verification
            self.assertIsInstance(result.result, CMCFearGreedData)
            self.assertEqual(len(result.result.data), 2)
            self.assertEqual(result.result.data[0].value, 50)
            self.assertEqual(result.result.data[0].value_classification, "Neutral")
            
            # Verify API call arguments
            mock_service.async_request.assert_called_once()
            call_args = mock_service.async_request.call_args
            self.assertIn("url", call_args.kwargs)
            self.assertIn("limit=2", call_args.kwargs["url"])

    async def test_execute_error(self):
        with patch('parrot.tools.cmc_fear_greed.HTTPService') as MockHTTPService:
            mock_service = MockHTTPService.return_value
            mock_service._logger = MagicMock()
            
            # Mock error
            mock_service.async_request = AsyncMock(return_value=(None, "API Error"))

            tool = CMCFearGreedTool(api_key="test_key")
            
            # Expect exception or error result
            result = await tool.execute(limit=2)
            self.assertEqual(result.status, "error")
            self.assertIn("API Error", result.error)

if __name__ == '__main__':
    unittest.main()
