---
type: Wiki Entity
title: OpenWeatherTool
id: class:parrot_tools.openweather.OpenWeatherTool
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Tool to get weather information for specific locations using OpenWeatherMap
  API.
relates_to:
- concept: class:parrot.tools.abstract.AbstractTool
  rel: extends
---

# OpenWeatherTool

Defined in [`parrot_tools.openweather`](../summaries/mod:parrot_tools.openweather.md).

```python
class OpenWeatherTool(AbstractTool)
```

Tool to get weather information for specific locations using OpenWeatherMap API.

This tool provides current weather conditions and weather forecasts for any location
specified by latitude and longitude coordinates. It supports different temperature
units and can be configured for different countries.

Features:
- Current weather conditions
- Weather forecasts (up to 16 days)
- Multiple temperature units (Celsius, Fahrenheit, Kelvin)
- Country-specific formatting
- Comprehensive weather data including temperature, humidity, pressure, wind, etc.

## Methods

- `def execute_sync(self, latitude: float, longitude: float, request_type: str='weather', units: str='imperial', country: str='us', forecast_days: int=3) -> Dict[str, Any]` — Execute weather request synchronously.
- `def get_weather_summary(self, weather_data: ToolResult) -> str` — Generate a human-readable weather summary.
- `def save_weather_data(self, weather_result: ToolResult, filename: Optional[str]=None) -> Dict[str, Any]` — Save weather data to JSON file.
