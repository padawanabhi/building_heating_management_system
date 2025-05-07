import datetime

# Define energy price levels and corresponding costs per kWh
# These are examples and can be adjusted
ENERGY_PRICES = {
    "OFF_PEAK": {"price_per_kwh": 0.10, "currency": "EUR"}, # e.g., Night
    "STANDARD": {"price_per_kwh": 0.18, "currency": "EUR"}, # e.g., Day
    "PEAK":     {"price_per_kwh": 0.25, "currency": "EUR"}, # e.g., Evening
    "SUPER_PEAK":{"price_per_kwh": 0.40, "currency": "EUR"}  # e.g., High demand periods
}

def get_current_energy_price(time_override: datetime.datetime | None = None) -> dict:
    """
    Gets the current simulated energy price level and cost based on the hour of the day.
    Can be overridden by passing a specific datetime object.
    """
    # Use override time if provided, otherwise use current UTC time
    current_time = time_override if time_override else datetime.datetime.now(datetime.timezone.utc)
    current_hour = current_time.hour # Hour (0-23)

    price_level = "STANDARD" # Default level

    # Example time-based pricing (adjust hours as needed)
    if 0 <= current_hour < 7: # Off-peak (e.g., midnight to 7 AM)
        price_level = "OFF_PEAK"
    elif 17 <= current_hour < 21: # Peak (e.g., 5 PM to 9 PM)
        price_level = "PEAK"
    # Add other conditions, e.g., super peak if needed
    # elif current_hour == 19: # Example super peak at 7 PM
    #     price_level = "SUPER_PEAK"
    else:
        price_level = "STANDARD" # Default daytime

    result = ENERGY_PRICES.get(price_level, ENERGY_PRICES["STANDARD"])
    result["level"] = price_level # Add the level name to the returned dict
    result["timestamp_utc"] = current_time.isoformat() # Add timestamp for context
    return result

if __name__ == '__main__':
    # Test the function for different times
    print(f"Current Price: {get_current_energy_price()}")
    
    test_time_offpeak = datetime.datetime(2023, 1, 1, 3, 30, 0, tzinfo=datetime.timezone.utc)
    print(f"Price at {test_time_offpeak}: {get_current_energy_price(time_override=test_time_offpeak)}")

    test_time_standard = datetime.datetime(2023, 1, 1, 11, 0, 0, tzinfo=datetime.timezone.utc)
    print(f"Price at {test_time_standard}: {get_current_energy_price(time_override=test_time_standard)}")

    test_time_peak = datetime.datetime(2023, 1, 1, 18, 0, 0, tzinfo=datetime.timezone.utc)
    print(f"Price at {test_time_peak}: {get_current_energy_price(time_override=test_time_peak)}") 