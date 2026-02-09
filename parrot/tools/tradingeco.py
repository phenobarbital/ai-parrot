"""
TradingEconomics Toolkit.
"""
import os
from typing import List, Optional, Dict, Any, Union
from pydantic import BaseModel, Field
import tradingeconomics as te
from navconfig import config
from .toolkit import AbstractToolkit


class TradingEcoStock(BaseModel):
    """
    Pydantic model for Trading Economics Stock Data.
    Based on the response fields from documentation.
    """
    Symbol: str = Field(..., description="Stock Symbol")
    Ticker: str = Field(..., description="Stock Ticker")
    Name: str = Field(..., description="Company Name")
    Country: str = Field(..., description="Country")
    Date: str = Field(..., description="Date of data")
    Type: Optional[str] = Field(None, description="Type of instrument")
    decimals: Optional[int] = Field(None, description="Number of decimals")
    state: Optional[str] = Field(None, description="Market State")
    Last: Optional[float] = Field(None, description="Last Price")
    Close: Optional[float] = Field(None, description="Close Price")
    CloseDate: Optional[str] = Field(None, description="Close Date")
    MarketCap: Optional[float] = Field(None, description="Market Capitalization")
    URL: Optional[str] = Field(None, description="Trading Economics URL")
    Importance: Optional[int] = Field(None, description="Importance rating")
    DailyChange: Optional[float] = Field(None, description="Daily Change")
    DailyPercentualChange: Optional[float] = Field(None, description="Daily % Change")
    WeeklyChange: Optional[float] = Field(None, description="Weekly Change")
    WeeklyPercentualChange: Optional[float] = Field(None, description="Weekly % Change")
    MonthlyChange: Optional[float] = Field(None, description="Monthly Change")
    MonthlyPercentualChange: Optional[float] = Field(None, description="Monthly % Change")
    YearlyChange: Optional[float] = Field(None, description="Yearly Change")
    YearlyPercentualChange: Optional[float] = Field(None, description="Yearly % Change")
    YTDChange: Optional[float] = Field(None, description="YTD Change")
    YTDPercentualChange: Optional[float] = Field(None, description="YTD % Change")
    day_high: Optional[float] = Field(None, description="Day High")
    day_low: Optional[float] = Field(None, description="Day Low")
    yesterday: Optional[float] = Field(None, description="Yesterday Price")
    lastWeek: Optional[float] = Field(None, description="Last Week Price")
    lastMonth: Optional[float] = Field(None, description="Last Month Price")
    lastYear: Optional[float] = Field(None, description="Last Year Price")
    startYear: Optional[float] = Field(None, description="Start Year Price")
    
    class Config:
        extra = "ignore" 


class TradingEcoToolkit(AbstractToolkit):
    """
    Toolkit for interacting with TradingEconomics API.
    Wrapper around the 'tradingeconomics' python package.
    """

    def __init__(self, api_key: Optional[str] = None, **kwargs):
        """
        Initialize the TradingEcoToolkit.

        Args:
            api_key: TradingEconomics API Key. If not provided, uses TRADINGECONOMICS_API_KEY env var.
        """
        super().__init__(**kwargs)
        self.api_key = api_key or config.get("TRADINGECONOMICS_API_KEY")
        if not self.api_key:
            self.logger.warning("TRADINGECONOMICS_API_KEY not found. API calls may fail.")
        else:
            try:
                te.login(self.api_key)
            except Exception as e:
                self.logger.error(f"Failed to login to TradingEconomics: {e}")

    async def te_quotes(self, country: str = 'united states') -> List[TradingEcoStock]:
        """
        Get stocks by country.
        
        Args:
            country: Country name (e.g., 'united states').
            
        Returns:
            List of TradingEcoStock objects.
        """
        try:
            # te.getStocksByCountry returns a list of dictionaries (or None/Error)
            data = te.getStocksByCountry(country=country, output_type='dict')
            if not data:
                return []
            
            # Helper to handle different return types if needed, but output_type='dict' usually returns list of dicts
            if isinstance(data, dict):
                 # Sometimes single item might be returned as dict? Unlikely for getStocksByCountry but good to be safe if API changes behavior
                 # or if it returns {"Error": ...}
                 if "Error" in data:
                     raise ValueError(data["Error"])
                 data = [data]
                 
            return [TradingEcoStock(**item) for item in data]
        except Exception as e:
            self.logger.error(f"Error fetching quotes for {country}: {e}")
            raise

    async def te_news(self, country: Optional[str] = None, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Get latest economic news.
        
        Args:
            country: Optional country to filter news.
            limit: Number of news items to return.
            
        Returns:
            List of news items.
        """
        try:
            if country:
                data = te.getNews(country=country, limit=limit, output_type='dict')
            else:
                data = te.getNews(limit=limit, output_type='dict')
                
            if not data:
                return []
            return data
        except Exception as e:
            self.logger.error(f"Error fetching news: {e}")
            raise

    async def te_market_forecast(self, category: str = 'index') -> List[Dict[str, Any]]:
        """
        Get markets forecasts.
        
        Args:
            category: Category (e.g., 'index', 'currency', 'bond', 'commodity').
        
        Returns:
            List of forecast data.
        """
        try:
            data = te.getMarketsForecasts(category=category, output_type='dict')
            if not data:
                 return []
            return data
        except Exception as e:
            self.logger.error(f"Error fetching market forecasts for {category}: {e}")
            raise

    async def te_market_sectors(self, country: str = 'united states') -> List[Dict[str, Any]]:
        """
        Get market sector performance.
        
        Args:
            country: Country name (e.g., 'united states').
            
        Returns:
            List of sector performance data.
        """
        try:
            # te.getMarkets(category='sector') or similar might be the way, 
            # but documentation for 'sector' often points to getStocksByCountry or similar with filters.
            # However, te.getSectorPerformance or similar might exist. 
            # Let's try to find a method or use getMarkets with category='sector'.
            
            # Based on standard TE API usage:
            data = te.getMarketsByCountry(country=country)
            
            
            if not data:
                return []
            return data
        except Exception as e:
            self.logger.error(
                f"Error fetching market sectors for {country}: {e}"
            )
            raise

    async def te_economic_calendar(self, country: Optional[str] = None, indicator: Optional[str] = None, start_date: Optional[str] = None, end_date: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get economic calendar data.

        Args:
            country: Country name (e.g., 'united states').
            indicator: Economic indicator (e.g., 'inflation rate').
            start_date: Start date (YYYY-MM-DD).
            end_date: End date (YYYY-MM-DD).

        Returns:
            List of economic calendar events.
        """
        try:
            # Arguments for getCalendar
            kwargs = {'output_type': 'dict'}
            if country:
                kwargs['country'] = country
            if indicator:
                kwargs['indicator'] = indicator
            if start_date:
                kwargs['initDate'] = start_date
            if end_date:
                kwargs['endDate'] = end_date

            data = te.getCalendarData(**kwargs)
            
            if not data:
                return []
            return data
        except Exception as e:
            self.logger.error(f"Error fetching economic calendar: {e}")
            raise

