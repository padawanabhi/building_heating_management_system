import datetime
import asyncio
import httpx # For async HTTP requests for weather
import openmeteo_requests
import requests_cache
from retry_requests import retry
from sqlalchemy.orm import Session
import logging # Added logger

from . import models, schemas, control_logic, energy_pricer # Assuming energy_pricer might be used
from .database import SessionLocal # Import SessionLocal factory

# --- Simplified Historical Weather Fetcher (adapted from scripts/historical_weather.py) ---
# Setup the Open-Meteo API client with cache and retry on error
cache_session = requests_cache.CachedSession('.cache', expire_after = 3600)
retry_session = retry(cache_session, retries = 5, backoff_factor = 0.2)
openmeteo = openmeteo_requests.Client(session = retry_session)

async def fetch_historical_weather_for_period(latitude: float, longitude: float, start_date: str, end_date: str) -> list[dict]:
    """
    Fetches hourly historical weather data for a given lat/lon and date range.
    Returns a list of hourly data points, or an empty list on error.
    Each data point is a dict with at least 'date' (timestamp) and 'temperature_2m'.
    """
    url = "https://archive-api.open-meteo.com/v1/archive"
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": start_date,
        "end_date": end_date,
        "hourly": ["temperature_2m", "relative_humidity_2m", "precipitation", "cloud_cover", "wind_speed_10m"],
        "timezone": "UTC"
    }
    try:
        # httpx for async request
        async with httpx.AsyncClient() as client:
            responses = await client.get(url, params=params) # OpenMeteo SDK might not be fully async with httpx directly
            # The openmeteo client itself is synchronous. We need to run it in a thread.
            # For simplicity in this adaptation, let's make this part synchronous for now,
            # or the caller (API endpoint) will wrap this whole simulation in a thread. 
            # For now, synchronous call for weather within the historical simulator logic.
            # To make it truly async, the `openmeteo.Client().weather_api` call would need careful handling.
            
            # Reverting to synchronous for direct call within the historical sim function for now.
            # The overall historical_simulation can be run in a background task by FastAPI.
            response = openmeteo.weather_api(url, params=params) # This is a list of responses
            
            if not response or len(response) == 0:
                print(f"Error: No response from OpenMeteo for {latitude},{longitude} from {start_date} to {end_date}")
                return []

            res = response[0] # Assuming one location
            print(f"Coordinates {res.Latitude()}°N {res.Longitude()}°E")
            print(f"Elevation {res.Elevation()} m asl")
            print(f"Timezone {res.Timezone()} {res.TimezoneAbbreviation()}")
            print(f"Timezone difference to GMT+0 {res.UtcOffsetSeconds()} s")

            hourly = res.Hourly()
            hourly_temperature_2m = hourly.Variables(0).ValuesAsNumpy()
            # Add other variables as needed from params["hourly"]

            hourly_data = []
            start_ts = int(hourly.Time()) 
            end_ts = int(hourly.TimeEnd())
            interval = int(hourly.Interval())

            for i, time_ts in enumerate(range(start_ts, end_ts, interval)):
                # Ensure we don't go out of bounds for the numpy array
                if i < len(hourly_temperature_2m):
                    hourly_data.append({
                        "date": datetime.datetime.fromtimestamp(time_ts, tz=datetime.timezone.utc),
                        "temperature_2m": hourly_temperature_2m[i]
                        # Add other fields here
                    })
                else:
                    break # Should not happen if time range and data align
            return hourly_data

    except Exception as e:
        print(f"Error fetching historical weather for {latitude},{longitude}: {e}")
        return []

# --- Main Historical Simulation Function --- 
# Modified to manage its own DB session
def run_historical_simulation_for_zone(
    # db: Session, # Removed db session from arguments
    zone_id: int, 
    run_id: int, # ID of the HistoricalSimulationRun entry
    sim_start_date_str: str, 
    sim_end_date_str: str
):
    """
    Core logic for running a historical simulation for a given zone and period.
    This function will be called in a background task.
    It creates its own DB session, updates the HistoricalSimulationRun status, 
    and populates HistoricalSimulationDataPoint.
    """
    # Create a new session for this background task
    db: Session = SessionLocal()
    logger = logging.getLogger(__name__) # Get a logger
    
    try:
        run_entry = db.query(models.HistoricalSimulationRun).filter(models.HistoricalSimulationRun.id == run_id).first()
        if not run_entry:
            logger.error(f"Historical Run ID {run_id} not found in background task. Aborting.")
            return # Cannot update status if run_entry not found

        zone = db.query(models.Zone).filter(models.Zone.id == zone_id).first()
        if not zone:
            run_entry.status = "FAILED"
            run_entry.status_message = f"Zone ID {zone_id} not found."
            db.commit()
            return

        if not zone.latitude or not zone.longitude:
            run_entry.status = "FAILED"
            run_entry.status_message = f"Zone {zone.name} (ID: {zone_id}) is missing latitude/longitude for historical weather."
            db.commit()
            return

        try:
            run_entry.status = "RUNNING"
            run_entry.status_message = "Fetching historical weather data..."
            db.commit()

            # Fetch weather data (using synchronous approach within the background task)
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            historical_weather_data = loop.run_until_complete(fetch_historical_weather_for_period(
                 zone.latitude, zone.longitude, sim_start_date_str, sim_end_date_str
            ))
            loop.close()

            if not historical_weather_data:
                run_entry.status = "FAILED"
                run_entry.status_message = "Failed to fetch historical weather data."
                db.commit()
                return

            run_entry.status_message = f"Processing {len(historical_weather_data)} hourly weather points..."
            db.commit()

            # Initialize zone's simulated state 
            sim_current_temp = zone.preferences.get('default_occupied_temp', 20.0) 
            sim_heater_on = False # Re-evaluate initial state based on actual initial temp/target?
            # For simplicity start OFF
            
            prefs_data = zone.preferences
            if not isinstance(prefs_data, dict):
                prefs_data = {} 
            preferences = schemas.ZonePreferences(**prefs_data)

            # Refined initial heater state based on initial sim temp and first scheduled/default target
            initial_time = historical_weather_data[0]["date"].time() if historical_weather_data else datetime.time(0, 0)
            initial_target_temp = control_logic.get_active_schedule_setpoint(preferences, initial_time)
            if initial_target_temp is not None and sim_current_temp < initial_target_temp - 0.5: # Use hysteresis lower bound
                sim_heater_on = True
            else:
                sim_heater_on = False
                
            total_energy_kwh = 0.0
            HEATER_POWER_KW = 2.0 # Assume a 2kW heater
            # More realistic: Get heater power from preferences? e.g., prefs.get('heater_power_kw', 2.0)

            for i, weather_hour in enumerate(historical_weather_data):
                current_historical_time_utc = weather_hour["date"]
                outdoor_temp = weather_hour["temperature_2m"]
                if outdoor_temp is None: outdoor_temp = 10.0 # Fallback if weather data is missing

                # Determine simulated occupancy 
                sim_occupancy = False
                if 7 <= current_historical_time_utc.hour < 22 and current_historical_time_utc.weekday() < 5: 
                    sim_occupancy = True

                # Get control decision 
                # Pass the parsed preferences object directly
                # Refactor make_control_decision maybe? For now, pass zone and it re-parses prefs.
                heater_decision, target_temp_decision = control_logic.make_control_decision(
                    db=db,
                    zone=zone, 
                    current_temp=sim_current_temp,
                    current_occupancy=sim_occupancy,
                    current_heater_state_from_modbus=sim_heater_on, 
                    current_time=current_historical_time_utc.time(),
                    current_weather={"temp_c": outdoor_temp}
                )

                # Log this data point
                data_point = models.HistoricalSimulationDataPoint(
                    run_id=run_id,
                    timestamp_utc=current_historical_time_utc,
                    temperature_simulated=round(sim_current_temp, 2),
                    target_temperature_control=round(target_temp_decision, 2) if target_temp_decision is not None else sim_current_temp, 
                    heater_on_simulated=sim_heater_on, 
                    occupancy_simulated=sim_occupancy,
                    outdoor_temp_actual=round(outdoor_temp, 2),
                    # energy_price_level_simulated=energy_pricer.get_energy_price_for_time(current_historical_time_utc).get("level") 
                    # Ensure energy_pricer has get_energy_price_for_time
                    energy_price_level_simulated=energy_pricer.get_current_energy_price(time_override=current_historical_time_utc).get("level") # Pass time override
                )
                db.add(data_point)

                # Update heater state based on decision for the *next* hour
                sim_heater_on = heater_decision

                # Simulate temperature change for the next hour using fixed defaults
                # heating_rate = preferences.heating_rate_degC_per_hour if hasattr(preferences, 'heating_rate_degC_per_hour') and preferences.heating_rate_degC_per_hour is not None else 1.0
                # cooling_factor = preferences.cooling_rate_factor_per_hour if hasattr(preferences, 'cooling_rate_factor_per_hour') and preferences.cooling_rate_factor_per_hour is not None else 0.1
                heating_rate = 1.0 # Fixed default heating rate (°C/hr)
                cooling_factor = 0.1 # Fixed default cooling factor (towards outdoor temp)

                if sim_heater_on:
                    sim_current_temp += heating_rate 
                    total_energy_kwh += HEATER_POWER_KW
                else:
                    sim_current_temp -= (sim_current_temp - outdoor_temp) * cooling_factor
                
                sim_current_temp = max(10.0, min(30.0, sim_current_temp))

                if (i + 1) % 100 == 0: 
                    run_entry.status_message = f"Processed {i+1}/{len(historical_weather_data)} data points..."
                    db.commit() 

            run_entry.status = "COMPLETED"
            run_entry.status_message = f"Simulation completed. Processed {len(historical_weather_data)} data points."
            run_entry.total_simulated_hours = len(historical_weather_data)
            run_entry.calculated_energy_kwh = round(total_energy_kwh, 2)
            db.commit()

        except Exception as e:
            logger.error(f"Error during historical simulation processing for run {run_id}", exc_info=True)
            run_entry.status = "FAILED"
            run_entry.status_message = f"Processing Error: {str(e)}"
            db.commit()
            
    except Exception as e:
        # Catch errors before simulation starts (e.g., initial DB query failure)
        logger.error(f"Outer error during historical simulation setup for run {run_id}", exc_info=True)
        # Cannot update run_entry if it wasn't fetched
        # If run_entry exists, it might have been updated to RUNNING, so update to FAILED
        if 'run_entry' in locals() and run_entry:
            try:
                run_entry.status = "FAILED"
                run_entry.status_message = f"Setup Error: {str(e)}"
                db.commit()
            except Exception as commit_err:
                logger.error(f"Failed to commit FAILED status for run {run_id}: {commit_err}")
                db.rollback()
        else:
             logger.error("Could not update run status to FAILED as run_entry was not found or initial query failed.")
    finally:
        # Ensure the session created for this task is closed
        if db: 
            db.close()
            logger.info(f"DB Session closed for historical simulation run {run_id}.")

# Ensure energy_pricer has a compatible function
# Example modification to energy_pricer.py:
# def get_current_energy_price(time_override: datetime.datetime | None = None) -> dict:
#     current_time = time_override if time_override else datetime.datetime.now(datetime.timezone.utc)
#     current_hour = current_time.hour
#     # ... rest of the logic ...

# We also need heating_rate_degC_per_hour and cooling_rate_factor_per_hour in preferences
# Add them back to ZonePreferences in schemas.py if needed for simulation accuracy
# (They were removed earlier as not needed for *live* control preferences)
# Using fixed defaults for now instead.

if __name__ == '__main__':
    # For testing this module directly (requires DB setup and a Zone)
    print("Testing historical_simulator.py...")
    # Example:
    # db_test_session = SessionLocal()
    # test_zone_id = 1 
    # test_run = models.HistoricalSimulationRun(
    #     zone_id=test_zone_id, 
    #     sim_period_start="2023-01-01", 
    #     sim_period_end="2023-01-02",
    #     status="PENDING"
    # )
    # db_test_session.add(test_run)
    # db_test_session.commit()
    # db_test_session.refresh(test_run)
    # print(f"Created test run ID: {test_run.id}")

    # run_historical_simulation_for_zone(
    #     db=db_test_session, 
    #     zone_id=test_zone_id, 
    #     run_id=test_run.id,
    #     sim_start_date_str="2023-01-01", 
    #     sim_end_date_str="2023-01-02"
    # )
    # db_test_session.close()
    print("Test complete (manual setup required for full run).") 