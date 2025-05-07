# scripts/run_historical_simulation.py

import sys
import os
import json
import datetime
import time
import pandas as pd
import openmeteo_requests
from sqlalchemy.orm import Session
import requests_cache # Optional: For caching API calls
from retry_requests import retry # Optional: For retrying failed API calls
from openmeteo_sdk.Variable import Variable # To specify weather variables
import argparse # To accept optional zone ID from command line

# Adjust path to import from src
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.database import SessionLocal
from src.models import Zone as ZoneModel
from src.schemas import ZonePreferences
from src.energy_pricer import get_current_energy_price
# We will need to import or replicate the core control logic and zone physics
# from src.server import apply_control_logic_job # Need refactoring
# from src.zone_simulator import _calculate_new_temperature # Need refactoring

# --- Simulation Configuration (Defaults) ---
SIMULATION_START_OFFSET_DAYS = 2 # How many days ago to start
SIMULATION_DURATION_HOURS = 48   # How long to simulate
SIMULATION_TIME_STEP_MINUTES = 15 # Simulation time resolution
INITIAL_ZONE_TEMP = 18.0        # Starting internal temperature for all zones
# Note: Physics constants are now primarily read from ZonePreferences
RESULTS_FILE_TEMPLATE = "simulation_results_zone_{zone_id}.csv" # Template for output file

# Placeholder for refactored control logic function
def calculate_ideal_target(sim_time: datetime.datetime, zone_prefs: ZonePreferences, current_internal_temp: float, is_occupied: bool, 
                             current_outside_temp: float, hourly_forecast_data: list, energy_price_info: dict):
    """
    Calculates the ideal target temperature based on schedule, occupancy, 
    predictive logic, energy prices, and outdoor temperature overrides.
    Adapted from apply_control_logic_job in server.py.
    
    Args:
        sim_time: The current simulated datetime (timezone aware, ideally UTC).
        zone_prefs: The ZonePreferences Pydantic model for the zone.
        current_internal_temp: The current simulated internal temperature of the zone.
        is_occupied: Boolean indicating current simulated occupancy.
        current_outside_temp: The current (historical) outside temperature.
        hourly_forecast_data: List of hourly data points for the forecast window 
                              (extracted from historical data). Each entry should be a dict 
                              like {'time': 'HH:MM', 'temp_c': float}.
        energy_price_info: Dict with energy price level and cost.

    Returns:
        The calculated ideal target temperature (float).
    """

    # --- Schedule Logic --- 
    # Helper to get scheduled setpoints for a given time object
    def _get_setpoints_for_time(time_to_check: datetime.time, schedule_entries: list, default_occ_temp: float, default_unocc_temp: float) -> dict:
        active_sch_occ_temp = default_occ_temp
        active_sch_unocc_temp = default_unocc_temp
        is_scheduled_period = False
        schedule_active_at_time = None
        for entry in reversed(schedule_entries): # Assumes schedule_entries is sorted by time_obj
            if time_to_check >= entry["time_obj"]:
                schedule_active_at_time = entry
                break
        if schedule_active_at_time:
            active_sch_occ_temp = schedule_active_at_time["occupied_temp"]
            active_sch_unocc_temp = schedule_active_at_time["unoccupied_temp"]
            is_scheduled_period = True
        return {"occupied_temp": active_sch_occ_temp, "unoccupied_temp": active_sch_unocc_temp, "is_scheduled": is_scheduled_period}

    parsed_schedule_entries = []
    if zone_prefs.schedule:
        for entry_data in zone_prefs.schedule:
            try:
                schedule_time = datetime.datetime.strptime(entry_data.time, "%H:%M").time()
                parsed_schedule_entries.append({
                    "time_obj": schedule_time,
                    "occupied_temp": entry_data.occupied_temp,
                    "unoccupied_temp": entry_data.unoccupied_temp
                })
            except ValueError:
                pass 
        parsed_schedule_entries.sort(key=lambda x: x["time_obj"])

    current_time_setpoints = _get_setpoints_for_time(sim_time.time(), parsed_schedule_entries, zone_prefs.default_occupied_temp, zone_prefs.default_unoccupied_temp)
    active_occupied_setpoint = current_time_setpoints["occupied_temp"]
    active_unoccupied_setpoint = current_time_setpoints["unoccupied_temp"]
    ideal_target_temp = active_unoccupied_setpoint
    if is_occupied:
        ideal_target_temp = active_occupied_setpoint

    energy_price_level = energy_price_info.get("level")
    if zone_prefs.allow_predictive_control and hourly_forecast_data and current_outside_temp is not None:
        window_hours = zone_prefs.predictive_window_hours
        for i in range(1, window_hours + 1):
            if i > len(hourly_forecast_data):
                 break
            future_hour_data = hourly_forecast_data[i-1]
            future_temp_c = future_hour_data.get('temp_c')
            future_time_str = future_hour_data.get('time')
            if future_temp_c is None or not future_time_str:
                 continue
            try:
                 future_time_obj = datetime.datetime.strptime(future_time_str, "%H:%M").time()
            except ValueError:
                 continue
            future_schedule_setpoints = _get_setpoints_for_time(future_time_obj, parsed_schedule_entries, zone_prefs.default_occupied_temp, zone_prefs.default_unoccupied_temp)
            predicted_significant_drop = (current_outside_temp - future_temp_c) > zone_prefs.predictive_temp_drop_threshold
            energy_ok_for_preheat = (energy_price_level not in ["super_peak"] and (energy_price_level != "peak" or zone_prefs.prioritize_comfort_over_peak_cost))
            if predicted_significant_drop and energy_ok_for_preheat:
                if is_occupied:
                    increase = zone_prefs.predictive_preheat_increase
                    ideal_target_temp += increase
                    break
                elif future_schedule_setpoints["is_scheduled"]:
                    future_target_occupied_for_schedule = future_schedule_setpoints["occupied_temp"]
                    if future_temp_c < future_target_occupied_for_schedule and current_internal_temp < future_target_occupied_for_schedule:
                        increase = zone_prefs.predictive_preheat_increase
                        ideal_target_temp = future_target_occupied_for_schedule + increase
                        break
            predicted_significant_rise = (future_temp_c - current_outside_temp) > zone_prefs.predictive_temp_rise_threshold
            if predicted_significant_rise and is_occupied:
                 reduction = zone_prefs.predictive_avoid_overheat_reduction
                 ideal_target_temp -= reduction
                 break
    base_occupied_setpoint_for_cap = active_occupied_setpoint
    max_allowed_temp_after_boost = base_occupied_setpoint_for_cap + zone_prefs.max_combined_preheat_boost
    if is_occupied or (not is_occupied and ideal_target_temp > active_unoccupied_setpoint):
        if ideal_target_temp > max_allowed_temp_after_boost:
            ideal_target_temp = max_allowed_temp_after_boost
    if is_occupied:
        if energy_price_level == "peak":
            reduction = zone_prefs.peak_occupied_temp_reduction
            ideal_target_temp -= reduction
        elif energy_price_level == "super_peak":
            reduction = zone_prefs.super_peak_occupied_temp_reduction
            ideal_target_temp -= reduction
        elif energy_price_level == "off_peak" and zone_prefs.allow_off_peak_preconditioning:
            increase = zone_prefs.off_peak_occupied_temp_increase
            ideal_target_temp += increase
            if ideal_target_temp > max_allowed_temp_after_boost:
                ideal_target_temp = max_allowed_temp_after_boost
    if is_occupied and current_outside_temp is not None and current_outside_temp > zone_prefs.high_outside_temp_threshold:
        ideal_target_temp -= zone_prefs.occupied_temp_reduction_high_outside
    ideal_target_temp = max(zone_prefs.min_target_temp, min(zone_prefs.max_target_temp, ideal_target_temp))
    ideal_target_temp = round(ideal_target_temp, 1)
    return ideal_target_temp

# Placeholder for refactored zone physics
def calculate_new_zone_temp(current_temp, target_temp, outside_temp, heater_on, time_step_minutes, zone_prefs: ZonePreferences):
    """
    Calculates the new zone temperature based on simple physics.
    Adapted from ZoneSimulator._calculate_new_temperature.
    Uses rates defined in ZonePreferences.
    """
    # Convert per-hour rates from preferences to per-minute rates
    heating_rate_per_minute = zone_prefs.heating_rate_degC_per_hour / 60.0
    cooling_rate_factor_per_minute = zone_prefs.cooling_rate_factor_per_hour / 60.0
    
    delta_temp = 0.0

    # Heating effect
    if heater_on:
         delta_temp += heating_rate_per_minute * time_step_minutes

    # Cooling/Heating effect towards outside temperature (Newton's Law of Cooling approximation)
    temp_difference = outside_temp - current_temp
    delta_temp += temp_difference * cooling_rate_factor_per_minute * time_step_minutes

    new_temp = current_temp + delta_temp

    # Add some noise/randomness? Optional.
    # import random
    # noise = random.uniform(-0.05, 0.05)
    # new_temp += noise

    return new_temp

# --- Main Simulation Function (for a single zone) ---
def run_simulation_for_zone(zone_id: int, 
                           start_offset_days: int = SIMULATION_START_OFFSET_DAYS,
                           duration_hours: int = SIMULATION_DURATION_HOURS,
                           time_step_minutes: int = SIMULATION_TIME_STEP_MINUTES) -> pd.DataFrame | None:
    """
    Runs the historical simulation for a single specified zone ID.
    Fetches weather data, simulates step-by-step, returns results.
    """
    print(f"Starting historical simulation for Zone ID: {zone_id}...")
    
    # --- 1. Load Specific Zone Configuration ---
    db: Session = SessionLocal()
    zone_config = None
    try:
        db_zone = db.query(ZoneModel).filter(ZoneModel.id == zone_id).first()
        if not db_zone:
            print(f"Error: Zone ID {zone_id} not found in database.")
            return None
        if db_zone.latitude is None or db_zone.longitude is None:
             print(f"Error: Zone ID {zone_id} ('{db_zone.name}') is missing coordinates. Cannot simulate.")
             return None

        # Validate preferences
        validated_prefs = ZonePreferences.model_validate(db_zone.preferences or {})
        zone_config = {
            "id": db_zone.id,
            "name": db_zone.name,
            "latitude": db_zone.latitude,
            "longitude": db_zone.longitude,
            "weather_location": db_zone.weather_location, # For info
            "preferences": validated_prefs # Store the validated Pydantic model
        }
    finally:
        db.close()

    print(f"Loaded configuration for zone: {zone_config['name']}")

    # --- 2. Define Simulation Time Range ---
    end_time = datetime.datetime.now(datetime.timezone.utc)
    start_time = end_time - datetime.timedelta(days=start_offset_days)
    simulation_duration = datetime.timedelta(hours=duration_hours)
    actual_end_time = min(start_time + simulation_duration, end_time)
    
    print(f"Simulation period: {start_time.strftime('%Y-%m-%d %H:%M')} to {actual_end_time.strftime('%Y-%m-%d %H:%M')} UTC")
    print(f"Time step: {time_step_minutes} minutes")

    # --- 3. Fetch Historical Weather Data for this Zone --- 
    print(f"Fetching historical weather data for ({zone_config['latitude']:.2f}, {zone_config['longitude']:.2f})...")
    om = openmeteo_requests.Client()
    params = {
        "latitude": [zone_config["latitude"]],
        "longitude": [zone_config["longitude"]],
        "start_date": start_time.strftime("%Y-%m-%d"),
        "end_date": actual_end_time.strftime("%Y-%m-%d"),
        "hourly": ["temperature_2m"],
        "timezone": "UTC"
    }
    weather_df = None
    try:
        responses = om.weather_api("https://archive-api.open-meteo.com/v1/archive", params=params)
        if not responses:
             print("Error: No response received from Open-Meteo API.")
             return None
        response = responses[0]
        hourly = response.Hourly()
        if not hourly:
             print("Error: No hourly data in API response.")
             return None
        hourly_temp_variable = next((v for v in map(lambda i: hourly.Variables(i), range(hourly.VariablesLength())) if v.Variable() == Variable.temperature and v.Altitude() == 2), None)
        if hourly_temp_variable is None:
             print("Error: temperature_2m variable not found in API response.")
             return None

        hourly_temperature_2m = hourly_temp_variable.ValuesAsNumpy()
        time_index = pd.to_datetime(range(hourly.Time(), hourly.TimeEnd(), hourly.Interval()), unit="s", utc=True)
        weather_df = pd.DataFrame({"temperature_2m": hourly_temperature_2m}, index=time_index)
        weather_df = weather_df.sort_index() # Ensure sorted
        print(f"Successfully fetched and processed {len(weather_df)} hourly weather records.")

    except Exception as e:
        print(f"Error fetching or processing historical weather data: {e}")
        return None

    # --- 4. Initialize Simulation State ---
    state = {
        "current_temp": INITIAL_ZONE_TEMP,
        "target_temp": INITIAL_ZONE_TEMP,
        "occupancy": False,
        "heater_on": False,
        "last_known_outside_temp": weather_df.iloc[0]['temperature_2m'] if not weather_df.empty else 10.0 # Initial fallback
    }
    zone_prefs = zone_config["preferences"]
    results_log = []
    current_sim_time = start_time
    total_steps = (actual_end_time - start_time) // datetime.timedelta(minutes=time_step_minutes)
    step_count = 0

    # --- 5. Simulation Loop ---
    print("Starting simulation loop...")
    loop_start_time = time.time()
    while current_sim_time < actual_end_time:
        step_count += 1
        if step_count % (60 // time_step_minutes * 4) == 0: # Print progress every ~4 simulated hours
             progress = (current_sim_time - start_time) / (actual_end_time - start_time) * 100
             print(f"  Simulating: {current_sim_time.strftime('%Y-%m-%d %H:%M')} UTC ({progress:.1f}% complete)")

        energy_price_info = get_current_energy_price(current_sim_time)

        # --- Get historical weather & simulated forecast ---
        current_outside_temp = state["last_known_outside_temp"] # Start with fallback
        hourly_forecast_data = []
        try:
            current_weather_row = weather_df.iloc[weather_df.index.get_indexer([current_sim_time], method='ffill')[0]]
            current_outside_temp = current_weather_row['temperature_2m']
            state["last_known_outside_temp"] = current_outside_temp
            forecast_window = zone_prefs.predictive_window_hours
            forecast_start_time = current_sim_time + datetime.timedelta(hours=1)
            forecast_end_time = forecast_start_time + datetime.timedelta(hours=forecast_window - 1)
            sim_forecast_df = weather_df[(weather_df.index >= forecast_start_time) & (weather_df.index <= forecast_end_time)]
            for timestamp, row in sim_forecast_df.iterrows():
                hourly_forecast_data.append({'time': timestamp.strftime('%H:%M'), 'temp_c': row['temperature_2m']})
        except Exception as e:
            # Use fallback temp, forecast remains empty
            print(f"  Warning: Error looking up weather/forecast at {current_sim_time}: {e}. Using last known outside temp: {current_outside_temp}")
            pass 
        if current_outside_temp is None: # Should not happen if fallback works
            current_outside_temp = state["current_temp"]

        # --- Determine Occupancy ---
        sim_time_local = current_sim_time
        parsed_schedule_entries_for_zone = []
        if zone_prefs.schedule:
            for entry_data in zone_prefs.schedule:
                try:
                    schedule_time = datetime.datetime.strptime(entry_data.time, "%H:%M").time()
                    parsed_schedule_entries_for_zone.append({"time_obj": schedule_time, "occupied_temp": entry_data.occupied_temp, "unoccupied_temp": entry_data.unoccupied_temp})
                except ValueError:
                    pass
            parsed_schedule_entries_for_zone.sort(key=lambda x: x["time_obj"])
        is_occupied = False
        active_schedule_entry = None
        for entry in reversed(parsed_schedule_entries_for_zone):
            if sim_time_local.time() >= entry["time_obj"]:
                active_schedule_entry = entry
                break
        if active_schedule_entry is not None:
            is_occupied = True
        state["occupancy"] = is_occupied

        # --- Calculate Target --- 
        ideal_target = calculate_ideal_target(current_sim_time, zone_prefs, state["current_temp"], is_occupied, current_outside_temp, hourly_forecast_data, energy_price_info)
        state["target_temp"] = ideal_target

        # --- Determine Heater State --- 
        state["heater_on"] = state["current_temp"] < state["target_temp"]

        # --- Calculate Next Internal Temp --- 
        state["current_temp"] = calculate_new_zone_temp(state["current_temp"], state["target_temp"], current_outside_temp, state["heater_on"], time_step_minutes, zone_prefs)

        # --- Log Results --- 
        results_log.append({
            "timestamp": current_sim_time.isoformat(),
            "zone_id": zone_id,
            "zone_name": zone_config["name"],
            "internal_temp_c": round(state["current_temp"], 2),
            "target_temp_c": round(state["target_temp"], 2),
            "occupancy": state["occupancy"],
            "heater_on": state["heater_on"],
            "outside_temp_c": round(current_outside_temp, 2),
            "energy_price_level": energy_price_info.get("level", "N/A"),
            "energy_price_kwh": energy_price_info.get("price_per_kwh", None)
        })

        current_sim_time += datetime.timedelta(minutes=time_step_minutes)

    loop_end_time = time.time()
    print(f"Simulation loop finished in {loop_end_time - loop_start_time:.2f} seconds.")

    # --- 6. Return Results --- 
    results_df = None
    if results_log:
        results_df = pd.DataFrame(results_log)
        results_df['timestamp'] = pd.to_datetime(results_df['timestamp'])
        # Optionally save to CSV as well
        output_filename = RESULTS_FILE_TEMPLATE.format(zone_id=zone_id)
        results_df.to_csv(output_filename, index=False)
        print(f"Saved {len(results_df)} records to {output_filename}")
    else:
        print("No results were logged.")

    return results_df


# --- Command Line Execution --- 
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run historical heating simulation.")
    parser.add_argument("--zone-id", type=int, help="Specify a single zone ID to simulate.")
    args = parser.parse_args()

    if args.zone_id:
        run_simulation_for_zone(args.zone_id)
    else:
        print("Running simulation for all zones found in database...")
        db = SessionLocal()
        try:
            all_zone_ids = [z.id for z in db.query(ZoneModel.id).all()]
        finally:
            db.close()
        
        if not all_zone_ids:
            print("No zones found in DB to simulate.")
        else:
            print(f"Found zones: {all_zone_ids}")
            for zid in all_zone_ids:
                 run_simulation_for_zone(zid)
                 print("---") # Separator
            print("Finished simulating all zones.") 