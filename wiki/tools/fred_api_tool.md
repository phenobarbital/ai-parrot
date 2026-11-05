# FredAPITool Documentation

## Overview

The `FredAPITool` allows `ai-parrot` agents to interact with the Federal Reserve Economic Data (FRED) API. It provides access to a vast repository of economic data series, including interest rates, inflation metrics, employment numbers, and more.

## Prerequisites

- **API Key**: You must have a valid FRED API Key.
    - Set the environment variable `FRED_API_KEY`.
    - Alternatively, pass `api_key` as an argument to the tool.

## Usage

### Basic Usage

To fetch the most recent observation for a specific series (e.g., Federal Funds Rate `FEDFUNDS`):

```python
from parrot.tools.fred_api import FredAPITool

tool = FredAPITool()
result = await tool.run(series_id="FEDFUNDS", limit=1)

if result.success:
    print(result.result)
    # Output: {'realtime_start': '...', 'realtime_end': '...', 'observation_start': '...', 'observation_end': '...', 'units': 'lin', 'output_type': 1, 'file_type': 'json', 'order_by': 'observation_date', 'sort_order': 'asc', 'count': 1, 'offset': 0, 'limit': 1, 'observations': [{'realtime_start': '...', 'realtime_end': '...', 'date': '2023-12-01', 'value': '5.33'}]}
```

### Fetching a Date Range

```python
result = await tool.run(
    series_id="GDP",
    start_date="2023-01-01",
    end_date="2023-12-31"
)
```

## Supported KPIs and Series IDs

The following tables list key economic indicators supported by this tool, categorized by their economic function.

### Tasas de Interés y Política Monetaria

| KPI | Serie FRED | Frecuencia | Qué indica |
|-----|-----------|------------|------------|
| Federal Funds Rate | `FEDFUNDS` | Mensual | Costo del dinero. Sube → activos riesgo bajan |
| 10-Year Treasury Yield | `DGS10` | Diaria | "Risk-free rate". Benchmark para todo |
| 2-Year Treasury Yield | `DGS2` | Diaria | Expectativa de tasas a corto plazo |
| Yield Curve (10Y-2Y) | `T10Y2Y` | Diaria | Negativa = recesión probable (históricamente) |
| Fed Balance Sheet | `WALCL` | Semanal | Liquidez del sistema. Se expande → bullish |

### Inflación

| KPI | Serie FRED | Frecuencia | Qué indica |
|-----|-----------|------------|------------|
| CPI (Consumer Price Index) | `CPIAUCSL` | Mensual | Inflación al consumidor. Alta → Fed sube tasas |
| Core CPI (sin alimentos/energía) | `CPILFESL` | Mensual | Inflación "subyacente", más estable |
| PCE Price Index | `PCEPI` | Mensual | La medida de inflación preferida por la Fed |
| Inflation Expectations 5Y | `T5YIE` | Diaria | Lo que el mercado espera de inflación |

### Empleo y Actividad

| KPI | Serie FRED | Frecuencia | Qué indica |
|-----|-----------|------------|------------|
| Unemployment Rate | `UNRATE` | Mensual | Salud del mercado laboral |
| Nonfarm Payrolls | `PAYEMS` | Mensual | Empleos creados. Fuerte → economía sana |
| Initial Jobless Claims | `ICSA` | Semanal | Despidos recientes. Sube → problemas |
| GDP Growth Rate | `A191RL1Q225SBEA` | Trimestral | Crecimiento económico real |
| ISM Manufacturing PMI | `MANEMP` | Mensual | >50 = expansión, <50 = contracción |

### Condiciones Financieras

| KPI | Serie FRED | Frecuencia | Qué indica |
|-----|-----------|------------|------------|
| VIX (Volatility Index) | `VIXCLS` | Diaria | "Índice del miedo". >30 = pánico |
| Dollar Index (DXY proxy) | `DTWEXBGS` | Diaria | Dólar fuerte → presión a activos riesgo |
| M2 Money Supply | `M2SL` | Mensual | Liquidez total. Crece → bullish para activos |
| Financial Stress Index | `STLFSI2` | Semanal | Estrés financiero sistémico |

## Complementary Data Sources

While FRED provides extensive historical data, other sources are useful for impactful event scheduling:

### Trading Economics API
- **URL**: [https://tradingeconomics.com/api/](https://tradingeconomics.com/api/)
- **Use Case**: Economic Calendar (report release dates, central bank decisions).
- **Why it matters**: Knowing *when* data is released is often as critical as the data itself.
