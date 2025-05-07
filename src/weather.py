import requests
from .config import WEATHERAPI_KEY

WEATHERAPI_BASE_URL = "http://api.weatherapi.com/v1"

def get_weather_forecast(location: str, days: int = 1) -> dict:
    """
    Fetches the weather forecast for a given location and number of days.

    Args:
        location: The location query (e.g., "London", "90210", "48.8567,2.3508").
        days: Number of days for the forecast (1 to 14).

    Returns:
        A dictionary containing the forecast data or an error message.
    """
    if not WEATHERAPI_KEY:
        return {"error": "WeatherAPI key not configured."}

    if not 1 <= days <= 14:
        # According to WeatherAPI docs, 'days' parameter value ranges between 1 and 14
        # For future API, it's different, but for standard forecast this is the range.
        return {"error": "Number of forecast days must be between 1 and 14."}

    params = {
        "key": WEATHERAPI_KEY,
        "q": location,
        "days": days,
        "aqi": "no",  # Air Quality Data - can be 'yes' or 'no'
        "alerts": "no" # Weather Alerts - can be 'yes' or 'no'
    }

    try:
        response = requests.get(f"{WEATHERAPI_BASE_URL}/forecast.json", params=params)
        response.raise_for_status()  # Raises an HTTPError for bad responses (4XX or 5XX)
        return response.json()
    except requests.exceptions.RequestException as e:
        return {"error": f"Error fetching weather data: {e}"}
    except Exception as e:
        return {"error": f"An unexpected error occurred: {e}"}

if __name__ == '__main__':
    # Example usage (for testing purposes)
    # Make sure your .env file is in the project root when running this directly
    # or that WEATHERAPI_KEY is an environment variable.
    print("Testing Weather API integration...")
    # You might need to adjust path for config if running this file directly
    # For now, assume it's run as part of the larger application context
    # or WEATHERAPI_KEY is already loaded.

    # Test with a city name
    london_forecast = get_weather_forecast(location="London", days=3)
    if "error" in london_forecast:
        print(f"Error for London: {london_forecast['error']}")
    else:
        print("Forecast for London:")
        # print(london_forecast) # Full dump
        if london_forecast and 'forecast' in london_forecast and 'forecastday' in london_forecast['forecast']:
            for day_data in london_forecast['forecast']['forecastday']:
                print(f"  Date: {day_data['date']}, Max Temp: {day_data['day']['maxtemp_c']}C, Min Temp: {day_data['day']['mintemp_c']}C, Condition: {day_data['day']['condition']['text']}")
        else:
            print("Could not parse London forecast data as expected.")

    # Test with a zip code
    zip_forecast = get_weather_forecast(location="90210", days=1)
    if "error" in zip_forecast:
        print(f"\nError for 90210: {zip_forecast['error']}")
    else:
        print("\nForecast for 90210:")
        if zip_forecast and 'forecast' in zip_forecast and 'forecastday' in zip_forecast['forecast']:
            day_data = zip_forecast['forecast']['forecastday'][0]
            print(f"  Date: {day_data['date']}, Max Temp: {day_data['day']['maxtemp_c']}C, Condition: {day_data['day']['condition']['text']}")
        else:
            print("Could not parse 90210 forecast data as expected.")

    # Test error case for API key (if key is not set)
    # To test this, temporarily remove or invalidate your WEATHERAPI_KEY
    # original_key = WEATHERAPI_KEY
    # WEATHERAPI_KEY = None # This won't work as it's module level, config is already loaded
    # print(get_weather_forecast(location="Paris", days=1))
    # WEATHERAPI_KEY = original_key 