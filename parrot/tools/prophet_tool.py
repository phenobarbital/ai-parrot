"""
ProphetForecastTool for time series forecasting using Facebook Prophet.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd
from pydantic import Field, field_validator
from prophet import Prophet

from .abstract import AbstractTool, AbstractToolArgsSchema, ToolResult


class ProphetForecastArgs(AbstractToolArgsSchema):
    """Arguments for :class:`ProphetForecastTool`."""

    dataframe: str = Field(
        ..., description="Name or alias of the DataFrame containing the time series"
    )
    ds_column: str = Field(
        ..., description="Column with datestamp values (will be converted to datetime)"
    )
    y_column: str = Field(
        ..., description="Numeric column to forecast"
    )
    periods: int = Field(
        365,
        description="Number of future periods to forecast",
        ge=1,
    )
    freq: str = Field(
        "D",
        description="Pandas frequency string for future periods (e.g., 'D', 'W', 'M')",
        min_length=1,
    )
    include_history: bool = Field(
        default=True,
        description="Whether to include the historical dates in the forecast output",
    )

    @field_validator("periods")
    @classmethod
    def validate_periods(cls, value: int) -> int:
        if value < 1:
            raise ValueError("periods must be a positive integer")
        return value


class ProphetForecastTool(AbstractTool):
    """Generate time series forecasts with Facebook Prophet and return plots."""

    name = "prophet_forecast"
    description = (
        "Fit a Facebook Prophet model on a DataFrame and generate future forecasts "
        "with corresponding forecast plot image."
    )
    args_schema = ProphetForecastArgs

    def __init__(
        self,
        dataframes: Optional[Dict[str, pd.DataFrame]] = None,
        alias_map: Optional[Dict[str, str]] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.dataframes: Dict[str, pd.DataFrame] = dataframes or {}
        self.alias_map: Dict[str, str] = alias_map or {}

    def _default_output_dir(self) -> Path:
        return self.static_dir / "reports" / "prophet_forecast"

    def update_context(
        self, dataframes: Dict[str, pd.DataFrame], alias_map: Optional[Dict[str, str]] = None
    ) -> None:
        """Update internal references to available DataFrames and aliases."""

        self.dataframes = dataframes
        if alias_map is not None:
            self.alias_map = alias_map

    async def _execute(self, **kwargs: Any) -> ToolResult:
        args = self.args_schema(**kwargs)
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._run_forecast, args)

    def _run_forecast(self, args: ProphetForecastArgs) -> ToolResult:
        dataframe = self._resolve_dataframe(args.dataframe)
        cleaned_df = self._prepare_dataframe(dataframe, args)

        model = Prophet()
        model.fit(cleaned_df)

        future = model.make_future_dataframe(
            periods=args.periods, freq=args.freq, include_history=args.include_history
        )
        forecast = model.predict(future)

        plot_path = self._save_forecast_plot(model, forecast, args.dataframe)

        return ToolResult(
            status="success",
            result={
                "forecast": forecast.to_dict(orient="records"),
                "forecast_columns": list(forecast.columns),
                "future_dataframe": future.to_dict(orient="records"),
                "figure_path": str(plot_path),
                "figure_url": self.to_static_url(plot_path),
            },
            metadata={
                "dataframe": args.dataframe,
                "ds_column": args.ds_column,
                "y_column": args.y_column,
                "periods": args.periods,
                "freq": args.freq,
            },
        )

    def _resolve_dataframe(self, name: str) -> pd.DataFrame:
        if name in self.dataframes:
            return self.dataframes[name]

        # Accept alias names (df1, df2, etc.)
        for df_name, alias in self.alias_map.items():
            if name == alias and df_name in self.dataframes:
                return self.dataframes[df_name]

        raise ValueError(
            f"DataFrame '{name}' not found. Available: {list(self.dataframes.keys())}"
        )

    def _prepare_dataframe(
        self, dataframe: pd.DataFrame, args: ProphetForecastArgs
    ) -> pd.DataFrame:
        if args.ds_column not in dataframe.columns:
            raise ValueError(
                f"Date column '{args.ds_column}' not found. Columns: {list(dataframe.columns)}"
            )
        if args.y_column not in dataframe.columns:
            raise ValueError(
                f"Target column '{args.y_column}' not found. Columns: {list(dataframe.columns)}"
            )

        df = dataframe.copy()
        df[args.ds_column] = pd.to_datetime(df[args.ds_column], errors="coerce")
        df[args.y_column] = pd.to_numeric(df[args.y_column], errors="coerce")

        df = df.dropna(subset=[args.ds_column, args.y_column])
        if df.empty:
            raise ValueError("No valid rows available after cleaning for Prophet forecast")

        df = df[[args.ds_column, args.y_column]].rename(
            columns={args.ds_column: "ds", args.y_column: "y"}
        )
        return df

    def _save_forecast_plot(
        self, model: Prophet, forecast: pd.DataFrame, dataframe_name: str
    ) -> Path:
        plot_dir = self.output_dir
        plot_dir.mkdir(parents=True, exist_ok=True)

        fig = model.plot(forecast)
        filename = f"prophet_forecast_{dataframe_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        file_path = plot_dir / filename
        fig.savefig(file_path, bbox_inches="tight")
        return file_path
