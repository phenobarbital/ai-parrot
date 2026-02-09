"""
Technical Analysis Tool
"""
from typing import Dict, Any, List, Optional, Union
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pydantic import BaseModel, Field

# Local Imports
from navconfig.logging import logging
from .toolkit import AbstractToolkit
from .alpaca import AlpacaMarketsToolkit
from .coingecko import CoingeckoToolkit
from .cryptoquant import CryptoQuantToolkit


class TechnicalAnalysisInput(BaseModel):
    symbol: str = Field(..., description="Symbol to analyze (e.g., 'AAPL', 'bitcoin').")
    asset_type: str = Field(..., description="Type of asset: 'stock' or 'crypto'.")
    source: str = Field('alpaca', description="Source for data: 'alpaca', 'coingecko', 'cryptoquant'.")
    interval: str = Field('1d', description="Time interval: '1d', '1h'. Default '1d'.")
    lookback_days: int = Field(365, description="Days of historical data to fetch for calculation. Default 365.")


class TechnicalAnalysisTool(AbstractToolkit):
    """
    Tool for performing Technical Analysis on stocks and crypto.
    Calculates SMA, RSI, MACD, Bollinger Bands from OHLCV data fetched via other toolkits.
    """
    name = "technical_analysis"
    description = "Calculates technical indicators (SMA, RSI, MACD, BBands) for stocks and crypto."
    args_schema = TechnicalAnalysisInput

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.logger = logging.getLogger(self.__class__.__name__)
        # Initialize sub-toolkits
        # Note: We initialize them with default config credentials
        self.alpaca = AlpacaMarketsToolkit()
        self.coingecko = CoingeckoToolkit()
        self.cryptoquant = CryptoQuantToolkit()

    def _calculate_rsi(self, series: pd.Series, period: int = 14) -> pd.Series:
        delta = series.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))

    def _calculate_macd(self, series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
        exp1 = series.ewm(span=fast, adjust=False).mean()
        exp2 = series.ewm(span=slow, adjust=False).mean()
        macd = exp1 - exp2
        signal_line = macd.ewm(span=signal, adjust=False).mean()
        return macd, signal_line

    def _calculate_bollinger_bands(self, series: pd.Series, window: int = 20, num_std: int = 2):
        sma = series.rolling(window=window).mean()
        std = series.rolling(window=window).std()
        upper = sma + (std * num_std)
        lower = sma - (std * num_std)
        return upper, lower, sma

    async def _execute(self, symbol: str, asset_type: str, source: str = 'alpaca', interval: str = '1d', lookback_days: int = 365) -> Dict[str, Any]:
        """
        Execute the technical analysis.
        """
        df = pd.DataFrame()
        
        try:
            # 1. Fetch Data
            if asset_type == 'stock':
                if source != 'alpaca':
                    # Fallback or error? For stocks, only Alpaca is supported currently.
                    source = 'alpaca'
                
                end_dt = datetime.now()
                start_dt = end_dt - timedelta(days=lookback_days)
                
                # Check Alpaca timeframes
                tf = "1Day"
                if interval in ['1h', '1Hour']:
                    tf = "1Hour"
                elif interval in ['15m', '15Min']:
                    tf = "15Min"
                
                data = await self.alpaca.get_stock_bars(
                    symbol=symbol, 
                    timeframe=tf, 
                    start=start_dt.strftime('%Y-%m-%d'),
                    end=end_dt.strftime('%Y-%m-%d'),
                    limit=1000
                )
                
                if 'bars' in data and data['bars']:
                    # Alpaca returns list of dicts: [{'t': '...', 'o': ..., 'c': ...}] unless it was normalized by wrapper
                    # The wrapper I checked returns: "bars": data (list of records)
                    # Keys: timestamp, open, high, low, close, volume, trade_count, vwap
                    df = pd.DataFrame(data['bars'])
                    # Rename columns if needed, but wrapper seems to use lower case full names
                    # Make sure 'close' exists
                    if 'close' not in df.columns and 'c' in df.columns:
                        df.rename(columns={'c': 'close', 'o': 'open', 'h': 'high', 'l': 'low', 'v': 'volume', 't': 'timestamp'}, inplace=True)

            elif asset_type == 'crypto':
                if source == 'coingecko':
                    # Coingecko doesn't support 'interval' freely. 
                    # days=1/7/14/30 etc determines granularity.
                    # 1 day = 5 min interval, 7-14 days = hourly, >30 days = daily.
                    # We want 'daily' usually for SMA50/200.
                    days_param = str(lookback_days)
                    if lookback_days > 30:
                        # Ensures daily resolution
                        pass 
                    else:
                        # If user wants hourly, we might get 5-min data if days=1.
                        # Simple rule: if lookback > 30, it is daily.
                        pass

                    ohlc = await self.coingecko.cg_coins_ohlc(
                        coin_id=symbol, # User must pass coin_id (e.g. bitcoin) not ticker (BTC)
                        vs_currency='usd',
                        days=days_param
                    )
                    # result is list of [time, o, h, l, c]
                    df = pd.DataFrame(ohlc, columns=['timestamp', 'open', 'high', 'low', 'close'])
                    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')

                elif source == 'cryptoquant':
                    # cq_price_ohlcv returns Dict.
                    # Example assumption: { "result": { "data": [...] } }
                    data = await self.cryptoquant.cq_price_ohlcv(
                        token=symbol,
                        window='day', # Fixed to day for now or map interval
                        limit=lookback_days
                    )
                    # TODO: Parse data structure based on actual API response
                    # For now, return error if not mocked/known
                    # Assuming data is in data['result']['data'] or similar
                    if 'result' in data and 'data' in data['result']:
                         df = pd.DataFrame(data['result']['data'])
                    else:
                         return {"error": f"Unknown CryptoQuant response format: {data.keys()}"}

            if df.empty:
                return {"error": f"No data found for {symbol} from {source}"}

            # 2. Prepare DataFrame
            # Ensure 'close' is numeric
            for col in ['open', 'high', 'low', 'close']:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
            
            if 'volume' in df.columns:
                df['volume'] = pd.to_numeric(df['volume'], errors='coerce')

            # Sort by date
            if 'timestamp' in df.columns:
                df['timestamp'] = pd.to_datetime(df['timestamp'])
                df.sort_values('timestamp', inplace=True)

            # 3. Calculate Indicators
            results = {}
            
            # SMA
            df['SMA_50'] = df['close'].rolling(window=50).mean()
            df['SMA_200'] = df['close'].rolling(window=200).mean()
            
            # RSI
            # RSI Calculation formula often uses EMA for gain/loss
            # My simple implementation used Simple Moving Average. 
            # Standard RSI uses Wilder's Smoothing (EMA-like).
            # Implementing Wilder's RSI:
            delta = df['close'].diff()
            gain = delta.where(delta > 0, 0)
            loss = -delta.where(delta < 0, 0)
            
            # Wilder's Smoothing
            avg_gain = gain.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
            avg_loss = loss.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
            rs = avg_gain / avg_loss
            df['RSI_14'] = 100 - (100 / (1 + rs))

            # MACD (12, 26, 9)
            exp1 = df['close'].ewm(span=12, adjust=False).mean()
            exp2 = df['close'].ewm(span=26, adjust=False).mean()
            df['MACD'] = exp1 - exp2
            df['MACD_Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
            df['MACD_Hist'] = df['MACD'] - df['MACD_Signal']
            
            # Bollinger Bands (20, 2)
            sma20 = df['close'].rolling(window=20).mean()
            std20 = df['close'].rolling(window=20).std()
            df['BB_Upper'] = sma20 + (std20 * 2)
            df['BB_Lower'] = sma20 - (std20 * 2)
            df['BB_Mid'] = sma20

            # 4. Extract Latest Values
            last = df.iloc[-1]
            
            summary = {
                "symbol": symbol,
                "timestamp": str(last['timestamp']),
                "price": float(last['close']),
                "indicators": {
                    "SMA_50": float(last['SMA_50']) if not pd.isna(last['SMA_50']) else None,
                    "SMA_200": float(last['SMA_200']) if not pd.isna(last['SMA_200']) else None,
                    "RSI_14": float(last['RSI_14']) if not pd.isna(last['RSI_14']) else None,
                    "MACD": {
                        "value": float(last['MACD']) if not pd.isna(last['MACD']) else None,
                        "signal": float(last['MACD_Signal']) if not pd.isna(last['MACD_Signal']) else None,
                        "hist": float(last['MACD_Hist']) if not pd.isna(last['MACD_Hist']) else None,
                    },
                    "BBands": {
                        "upper": float(last['BB_Upper']) if not pd.isna(last['BB_Upper']) else None,
                        "lower": float(last['BB_Lower']) if not pd.isna(last['BB_Lower']) else None,
                        "mid": float(last['BB_Mid']) if not pd.isna(last['BB_Mid']) else None,
                    }
                }
            }

            # Generate Signals
            signals = []
            if summary['indicators']['SMA_200']:
                if summary['price'] > summary['indicators']['SMA_200']:
                    signals.append("Bullish Trend (Price > SMA200)")
                else:
                    signals.append("Bearish Trend (Price < SMA200)")
            
            if summary['indicators']['RSI_14']:
                if summary['indicators']['RSI_14'] > 70:
                    signals.append("Overbought (RSI > 70)")
                elif summary['indicators']['RSI_14'] < 30:
                    signals.append("Oversold (RSI < 30)")

            summary['signals'] = signals
            
            # Add Volume if available
            if 'volume' in df.columns:
                vol = float(last['volume']) if not pd.isna(last['volume']) else 0
                summary['volume'] = vol
                # Avg Volume
                df['Vol_Avg_20'] = df['volume'].rolling(window=20).mean()
                avg_vol = float(df.iloc[-1]['Vol_Avg_20']) if not pd.isna(df.iloc[-1]['Vol_Avg_20']) else 0
                summary['indicators']['Avg_Volume_20d'] = avg_vol
                
                if avg_vol > 0 and vol > (avg_vol * 1.5):
                    signals.append("High Volume (> 1.5x Avg)")

            return summary

        except Exception as e:
            self.logger.error(f"Error in TechnicalAnalysisTool: {e}")
            raise e
