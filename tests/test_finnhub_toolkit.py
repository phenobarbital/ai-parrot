import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import os
from parrot.tools.finnhub import FinnhubToolkit, FinnhubQuoteResponse, FinnhubEarningsCalendarResponse, FinnhubInsiderSentimentResponse, FinnhubCompanyProfileResponse

class TestFinnhubToolkit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.api_key = "test_api_key"
        self.toolkit = FinnhubToolkit(api_key=self.api_key)
        self.toolkit.http_service = AsyncMock()

    async def test_finnhub_get_quote(self):
        mock_response = {
            "c": 150.0,
            "d": 2.5,
            "dp": 1.6,
            "h": 155.0,
            "l": 149.0,
            "o": 149.5,
            "pc": 147.5
        }
        self.toolkit.http_service.async_request.return_value = (mock_response, None)

        result = await self.toolkit.finnhub_get_quote("AAPL")
        
        self.assertIsInstance(result, FinnhubQuoteResponse)
        self.assertEqual(result.c, 150.0)
        
        # Verify call
        expected_url = f"https://finnhub.io/api/v1/quote"
        # The exact call arguments might depend on how dict equality works for 'data'
        args, kwargs = self.toolkit.http_service.async_request.call_args
        self.assertEqual(kwargs['url'], expected_url)
        self.assertEqual(kwargs['method'], "GET")
        self.assertEqual(kwargs['data'], {"symbol": "AAPL", "token": self.api_key})

    async def test_finnhub_earnings_calendar(self):
        mock_response = {
            "earningsCalendar": [
                {
                    "date": "2023-01-01",
                    "epsActual": 1.2,
                    "epsEstimate": 1.1,
                    "hour": "bmo",
                    "quarter": 1,
                    "revenueActual": 1000000,
                    "revenueEstimate": 900000,
                    "symbol": "AAPL",
                    "year": 2023
                }
            ]
        }
        self.toolkit.http_service.async_request.return_value = (mock_response, None)

        result = await self.toolkit.finnhub_earnings_calendar("2023-01-01", "2023-01-31")
        
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], FinnhubEarningsCalendarResponse)
        self.assertEqual(result[0].symbol, "AAPL")

        # Verify URL construction
        args, kwargs = self.toolkit.http_service.async_request.call_args
        self.assertIn("calendar/earnings", kwargs['url'])
        self.assertIn("from=2023-01-01", kwargs['url'])
        self.assertIn("to=2023-01-31", kwargs['url'])

    async def test_finnhub_insider_sentiment(self):
        mock_response = {
            "data": [
                {
                    "symbol": "TSLA",
                    "year": 2023,
                    "month": 1,
                    "change": 5000,
                    "mspr": 1.5
                }
            ],
            "symbol": "TSLA"
        }
        self.toolkit.http_service.async_request.return_value = (mock_response, None)
        
        result = await self.toolkit.finnhub_insider_sentiment("TSLA", "2023-01-01", "2023-03-01")
        
        self.assertIsInstance(result, FinnhubInsiderSentimentResponse)
        self.assertEqual(result.symbol, "TSLA")
        self.assertEqual(len(result.data), 1)
        
    async def test_finnhub_company_profile(self):
        mock_response = {
            "country": "US",
            "currency": "USD",
            "exchange": "NASDAQ",
            "ipo": "1980-12-12",
            "marketCapitalization": 2000000,
            "name": "Apple Inc",
            "phone": "1234567890",
            "shareOutstanding": 16000,
            "ticker": "AAPL",
            "weburl": "https://www.apple.com",
            "logo": "https://logo.com",
            "finnhubIndustry": "Technology"
        }
        self.toolkit.http_service.async_request.return_value = (mock_response, None)
        
        result = await self.toolkit.finnhub_company_profile("AAPL")
        
        self.assertIsInstance(result, FinnhubCompanyProfileResponse)
        self.assertEqual(result.name, "Apple Inc")

if __name__ == '__main__':
    unittest.main()
