---
type: Wiki Summary
title: parrot_tools.openweather
id: mod:parrot_tools.openweather
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: OpenWeather Tool migrated to use AbstractTool framework with aiohttp.
relates_to:
- concept: class:parrot_tools.openweather.OpenWeatherArgs
  rel: defines
- concept: class:parrot_tools.openweather.OpenWeatherTool
  rel: defines
- concept: mod:parrot_tools.abstract
  rel: references
---

# `parrot_tools.openweather`

OpenWeather Tool migrated to use AbstractTool framework with aiohttp.

## Classes

- **`OpenWeatherArgs(BaseModel)`** — Arguments schema for OpenWeatherTool.
- **`OpenWeatherTool(AbstractTool)`** — Tool to get weather information for specific locations using OpenWeatherMap API.
