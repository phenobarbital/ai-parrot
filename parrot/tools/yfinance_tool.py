"""YFinance tool for retrieving market data via Yahoo Finance."""
from __future__ import annotations
import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Literal, Union
import numpy as np
import pandas as pd
import yfinance as yf
from pydantic import Field, field_validator

from .abstract import AbstractTool, AbstractToolArgsSchema, ToolResult


class YFinanceArgs(AbstractToolArgsSchema):
    """Argument schema for :class:`YFinanceTool`."""

    ticker: str = Field(
        ...,
        description="Ticker symbol to query (for example: AAPL, MSFT, TSLA).",
        min_length=1,
        max_length=32,
    )
    action: Literal["quote", "info", "history", "financials"] = Field(
        "quote",
        description=(
            "Type of data to retrieve. "
            "'quote' returns the latest market quote, 'info' returns company details, "
            "'history' returns historical price data, and 'financials' returns financial statements."
        ),
    )
    period: Optional[str] = Field(
        "1mo",
        description=(
            "Period for historical data (used when action='history'). Examples: '1d', '5d', '1mo', "
            "'3mo', '6mo', '1y', '5y', '10y', 'ytd', 'max'."
        ),
    )
    interval: Optional[str] = Field(
        "1d",
        description=(
            "Data interval for historical data (used when action='history'). Examples: '1m', '5m', '15m', "
            "'1h', '1d', '1wk', '1mo'."
        ),
    )
    start: Optional[Union[datetime, str]] = Field(
        None,
        description=(
            "Optional start date for historical data. Accepts ISO formatted strings or datetime objects."
        ),
    )
    end: Optional[Union[datetime, str]] = Field(
        None,
        description=(
            "Optional end date for historical data. Accepts ISO formatted strings or datetime objects."
        ),
    )
    auto_adjust: bool = Field(
        True,
        description="Adjust historical data for dividends and splits (used when action='history').",
    )
    include_actions: bool = Field(
        False,
        description="Include dividends and splits columns in historical results (action='history').",
    )

    @field_validator("ticker")
    @classmethod
    def normalize_ticker(cls, value: str) -> str:
        if (ticker := value.strip().upper()):
            return ticker
        raise ValueError("Ticker symbol cannot be empty")



class YFinanceTool(AbstractTool):
    """Retrieve quotes, company information, and financial statements via Yahoo Finance."""

    name = "yfinance_tool"
    description = (
        "Access Yahoo Finance market data including latest quotes, company information, "
        "historical prices, and financial statements for a given ticker symbol."
    )
    args_schema = YFinanceArgs

    async def _execute(self, **kwargs: Any) -> ToolResult:
        args = self.args_schema(**kwargs)
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._run, args)

    def _run(self, args: YFinanceArgs) -> ToolResult:
        ticker = yf.Ticker(args.ticker)
        action = args.action

        retrieved_at = datetime.now(tz=timezone.utc).isoformat() + "Z"

        if action == "quote":
            payload = self._get_quote(ticker, args, retrieved_at)
        elif action == "info":
            payload = self._get_info(ticker, args, retrieved_at)
        elif action == "history":
            payload = self._get_history(ticker, args, retrieved_at)
        elif action == "financials":
            payload = self._get_financials(ticker, args, retrieved_at)
        else:
            raise ValueError(f"Unsupported action: {action}")

        return ToolResult(
            status="success",
            result=payload,
            metadata={
                "symbol": args.ticker,
                "action": action,
                "source": "yfinance",
                "retrieved_at": retrieved_at,
            },
        )

    def _get_quote(
        self, ticker: yf.Ticker, args: YFinanceArgs, retrieved_at: str
    ) -> Dict[str, Any]:
        fast_info: Dict[str, Any] = {}
        info: Dict[str, Any] = {}

        try:
            fast_info = dict(getattr(ticker, "fast_info", {}) or {})
        except Exception as exc:  # pragma: no cover - defensive
            self.logger.warning("Unable to retrieve fast_info for %s: %s", args.ticker, exc)

        try:
            info = ticker.get_info() or {}
        except Exception as exc:  # pragma: no cover - defensive
            self.logger.warning("Unable to retrieve info for %s: %s", args.ticker, exc)

        def _extract_price() -> Optional[float]:
            candidates = [
                fast_info.get("lastPrice"),
                fast_info.get("last_price"),
                fast_info.get("regularMarketPrice"),
                info.get("regularMarketPrice"),
            ]
            for candidate in candidates:
                if candidate is not None:
                    return self._to_native_number(candidate)
            return None

        summary = {
            "last_price": _extract_price(),
            "currency": fast_info.get("currency") or info.get("currency"),
            "previous_close": self._to_native_number(
                fast_info.get("previousClose") or fast_info.get("previous_close") or info.get("previousClose")
            ),
            "open": self._to_native_number(fast_info.get("open") or info.get("open")),
            "day_range": {
                "low": self._to_native_number(
                    fast_info.get("dayLow") or fast_info.get("day_low") or info.get("dayLow")
                ),
                "high": self._to_native_number(
                    fast_info.get("dayHigh") or fast_info.get("day_high") or info.get("dayHigh")
                ),
            },
            "volume": self._to_native_number(fast_info.get("volume") or info.get("volume")),
            "market_cap": self._to_native_number(
                fast_info.get("marketCap") or fast_info.get("market_cap") or info.get("marketCap")
            ),
            "exchange": info.get("exchange") or info.get("fullExchangeName"),
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }

        return {
            "ticker": args.ticker,
            "retrieved_at": retrieved_at,
            "quote": summary,
            "fast_info": self._clean_nested(fast_info),
            "info_excerpt": {
                k: info.get(k)
                for k in ("longName", "shortName", "quoteType", "sector", "industry")
                if k in info
            },
        }

    def _get_info(
        self, ticker: yf.Ticker, args: YFinanceArgs, retrieved_at: str
    ) -> Dict[str, Any]:
        try:
            info = ticker.get_info() or {}
        except Exception as exc:
            raise ValueError(f"Unable to retrieve company info for {args.ticker}: {exc}") from exc

        return {
            "ticker": args.ticker,
            "retrieved_at": retrieved_at,
            "info": self._clean_nested(info),
        }

    def _get_history(
        self, ticker: yf.Ticker, args: YFinanceArgs, retrieved_at: str
    ) -> Dict[str, Any]:
        history_df = ticker.history(
            period=args.period,
            interval=args.interval,
            start=args.start,
            end=args.end,
            auto_adjust=args.auto_adjust,
            actions=args.include_actions,
        )

        records = []
        if not history_df.empty:
            history_df = history_df.reset_index()
            for row in history_df.to_dict(orient="records"):
                cleaned_row = {
                    key: (
                        value.isoformat()
                        if isinstance(value, (pd.Timestamp, datetime))
                        else self._clean_value(value)
                    )
                    for key, value in row.items()
                }
                records.append(cleaned_row)

        return {
            "ticker": args.ticker,
            "retrieved_at": retrieved_at,
            "parameters": {
                "period": args.period,
                "interval": args.interval,
                "start": self._format_datetime(args.start),
                "end": self._format_datetime(args.end),
                "auto_adjust": args.auto_adjust,
                "include_actions": args.include_actions,
            },
            "records": records,
        }

    def _get_financials(
        self, ticker: yf.Ticker, args: YFinanceArgs, retrieved_at: str
    ) -> Dict[str, Any]:
        datasets = {
            "financials": getattr(ticker, "financials", None),
            "quarterly_financials": getattr(ticker, "quarterly_financials", None),
            "balance_sheet": getattr(ticker, "balance_sheet", None),
            "quarterly_balance_sheet": getattr(ticker, "quarterly_balance_sheet", None),
            "cashflow": getattr(ticker, "cashflow", None),
            "quarterly_cashflow": getattr(ticker, "quarterly_cashflow", None),
        }

        serialized = {
            name: (
                self._serialize_dataframe(df)
                if df is not None and not df.empty
                else {}
            )
            for name, df in datasets.items()
        }

        return {
            "ticker": args.ticker,
            "retrieved_at": retrieved_at,
            "financials": serialized,
        }

    @staticmethod
    def _format_datetime(value: Optional[Union[datetime, str]]) -> Optional[str]:
        if value is None:
            return None
        return value.isoformat() if isinstance(value, datetime) else str(value)

    @staticmethod
    def _to_native_number(value: Any) -> Optional[float]:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, np.generic):
            return float(value.item())
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _clean_value(self, value: Any) -> Any:
        if isinstance(value, np.generic):
            return value.item()
        if isinstance(value, (pd.Timestamp, datetime)):
            return value.isoformat()
        if isinstance(value, (bytes, bytearray)):
            return value.decode("utf-8", errors="ignore")
        if isinstance(value, (list, tuple)):
            return [self._clean_value(item) for item in value]
        if isinstance(value, dict):
            return {str(k): self._clean_value(v) for k, v in value.items()}
        return value

    def _clean_nested(self, data: Dict[str, Any]) -> Dict[str, Any]:
        return {str(k): self._clean_value(v) for k, v in data.items()}

    def _serialize_dataframe(self, df: pd.DataFrame) -> Dict[str, Dict[str, Any]]:
        cleaned_df = df.copy()
        cleaned_df.index = cleaned_df.index.map(self._clean_value)
        cleaned_df.columns = [self._clean_value(col) for col in cleaned_df.columns]
        cleaned_df = cleaned_df.applymap(self._clean_value)
        result: Dict[str, Dict[str, Any]] = {
            str(column): {str(idx): val for idx, val in values.items()}
            for column, values in cleaned_df.to_dict().items()
        }
        return result
