import asyncio
from parrot.tools.openweather import OpenWeatherTool


async def example_usage():
    # Create tool instance
    weather_tool = OpenWeatherTool()

    # Get current weather
    current_weather = await weather_tool.execute(
        latitude=37.7749,
        longitude=-122.4194,
        request_type="weather",
        units="metric"
    )

    # Get weather forecast
    forecast = await weather_tool.execute(
        latitude=40.7128,
        longitude=-74.0060,
        request_type="forecast",
        units="imperial",
        forecast_days=5
    )

    # Generate summary
    summary = weather_tool.get_weather_summary(current_weather)
    print(summary)

    # Save data
    file_info = weather_tool.save_weather_data(forecast, "nyc_forecast")
    print(f"Saved to: {file_info['file_url']}")


if __name__ == "__main__":
    asyncio.run(example_usage())
