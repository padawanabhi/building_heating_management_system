import datetime
import json
import asyncio
from sqlalchemy.orm import Session
from sqlalchemy import desc
from . import models, schemas, weather, modbus_client, database

# Constants for control logic (can be moved to config or preferences later)
OCCUPANCY_SETBACK_DEGREES = 2.0  # Degrees to lower setpoint when unoccupied
HEATING_LOWER_THRESHOLD_OFFSET = 0.5 # Degrees below target to turn on heater
HEATING_UPPER_THRESHOLD_OFFSET = 0.2 # Degrees above target to turn off heater

def get_active_schedule_setpoint(preferences: schemas.ZonePreferences, current_time_dt: datetime.time) -> float | None:
    """
    Determines the target setpoint based on the active schedule for occupied state.
    Returns None if no schedule is active or applicable, then a default should be used.
    """
    if not preferences.schedule:
        return preferences.default_occupied_temp # Fallback to default occupied if no schedule

    # Sort schedules by start time to ensure consistent behavior
    sorted_schedules = sorted(preferences.schedule, key=lambda s: datetime.time.fromisoformat(s.time))

    active_entry = None
    for entry in sorted_schedules:
        entry_time = datetime.time.fromisoformat(entry.time)
        if entry_time <= current_time_dt:
            active_entry = entry # This entry is potentially active
        else:
            # Since schedules are sorted, if this entry's time is past current_time,
            # the previous one (active_entry) is the correct one.
            break 
            
    if active_entry:
        return active_entry.occupied_temp # Use the occupied_temp from the schedule
    
    # If current_time_dt is before the first scheduled time, or no schedule matched
    # (though the loop logic should find the latest one before current time)
    # Fallback to the default occupied temperature from preferences
    # If there's a schedule, but no entry is "active" yet (e.g., current time is before first schedule time),
    # one might argue for default_unoccupied_temp, but control logic later handles actual occupancy.
    # So, for "what the schedule SAYS the occupied temp should be", this is the fallback.
    return preferences.default_occupied_temp

def make_control_decision(
    db: Session,
    zone: models.Zone,
    current_temp: float,
    current_occupancy: bool,
    current_heater_state_from_modbus: bool,
    current_time: datetime.time,
    current_weather: dict | None
) -> tuple[bool, float | None]:
    """
    Makes a control decision for a given zone.
    Returns a tuple: (heater_on, target_setpoint_used)
    """
    try:
        prefs_data = json.loads(zone.preferences) if isinstance(zone.preferences, str) else zone.preferences
        if not isinstance(prefs_data, dict):
            raise ValueError("Preferences is not a dictionary after loading.")
        preferences = schemas.ZonePreferences(**prefs_data)
    except (json.JSONDecodeError, ValueError, TypeError) as e:
        print(f"Error decoding preferences for zone {zone.id}: {e}. Using default behavior.")
        # Fallback: if preferences are malformed, maybe turn off heating or use a safe default.
        # For now, let's assume it means no heating and no specific target.
        return False, None 

    target_setpoint = get_active_schedule_setpoint(preferences, current_time)

    if target_setpoint is None: # Should not happen if default_setpoint is mandatory
        print(f"Warning: No target setpoint could be determined for zone {zone.id}. Turning heater off.")
        return False, None

    # Adjust for occupancy if applicable
    if preferences.use_occupancy_for_heating and not current_occupancy:
        # If unoccupied and occupancy is used, target the setback temperature
        # Ensure setback_setpoint is not None, otherwise, maintain scheduled/default setpoint
        if preferences.setback_setpoint is not None:
            target_setpoint = preferences.setback_setpoint
            print(f"Zone {zone.id} unoccupied, using setback temperature: {target_setpoint}°C")
        else:
            print(f"Zone {zone.id} unoccupied but no setback temperature defined. Using: {target_setpoint}°C")
    
    # Basic hysteresis logic
    # If current temperature is below target - lower_hysteresis_delta, turn heater on.
    # If current temperature is above target + upper_hysteresis_delta, turn heater off.
    # Otherwise, maintain current heater state (implies we need to know current state, or just decide based on thresholds).
    
    # For simplicity, let's assume we decide ON/OFF directly without knowing previous state.
    # This means the heater might cycle if temp hovers around target_setpoint.
    # A better approach would be: if OFF and temp < target - delta_low -> ON
    #                             if ON  and temp > target + delta_high -> OFF
    # This requires knowing the current heater state. For now, a simpler threshold:
    
    heater_on = False
    # Ensure min/max setpoints are respected if defined
    if preferences.min_target_temp is not None:
        target_setpoint = max(target_setpoint, preferences.min_target_temp)
    if preferences.max_target_temp is not None:
        target_setpoint = min(target_setpoint, preferences.max_target_temp)

    # Weather-based adjustment (before final hysteresis)
    # This is a simplified example. Real adjustments might be more complex
    # and use parameters from ZonePreferences.
    if current_weather and preferences.allow_weather_adjustment: # Check a hypothetical preference flag
        outdoor_temp = current_weather.get('temp_c')
        if outdoor_temp is not None:
            # Example: Boost target if very cold
            # These thresholds and boosts could come from preferences.ZoneWeatherAdjustmentConfig if defined
            freezing_threshold_weather = getattr(preferences, 'weather_adjustment_freezing_threshold', 0.0)
            boost_degrees_weather = getattr(preferences, 'weather_adjustment_cold_boost_degrees', 0.5)
            mild_threshold_weather = getattr(preferences, 'weather_adjustment_mild_threshold', 15.0)
            reduction_degrees_weather = getattr(preferences, 'weather_adjustment_mild_reduction_degrees', 0.0) # Default no reduction

            if outdoor_temp < freezing_threshold_weather:
                original_target = target_setpoint
                target_setpoint += boost_degrees_weather
                print(f"Zone {zone.id}: Weather adjustment - Outdoor temp {outdoor_temp}°C < {freezing_threshold_weather}°C. Boosting target by {boost_degrees_weather}°C from {original_target}°C to {target_setpoint}°C")
            elif outdoor_temp > mild_threshold_weather and reduction_degrees_weather > 0:
                # Example: Slight reduction if mild outside (and if a reduction is configured)
                original_target = target_setpoint
                target_setpoint -= reduction_degrees_weather
                print(f"Zone {zone.id}: Weather adjustment - Outdoor temp {outdoor_temp}°C > {mild_threshold_weather}°C. Reducing target by {reduction_degrees_weather}°C from {original_target}°C to {target_setpoint}°C")
            
            # Re-apply min/max clamps after weather adjustment
            if preferences.min_target_temp is not None:
                target_setpoint = max(target_setpoint, preferences.min_target_temp)
            if preferences.max_target_temp is not None:
                target_setpoint = min(target_setpoint, preferences.max_target_temp)

    # Simplified decision: if significantly cold, turn on. If warm enough, turn off.
    # Using a small fixed deadband around the target for this example.
    # In a real scenario, hysteresis values would come from preferences.
    LOWER_THRESHOLD_OFFSET = 0.5 # Turn ON if temp is 0.5C below target
    UPPER_THRESHOLD_OFFSET = 0.2 # Turn OFF if temp is 0.2C above target

    if current_temp < (target_setpoint - LOWER_THRESHOLD_OFFSET):
        heater_on = True
    elif current_temp > (target_setpoint + UPPER_THRESHOLD_OFFSET):
        heater_on = False
    else:
        # If in the deadband, maintain the current heater state
        heater_on = current_heater_state_from_modbus 

    # TODO: Adjust setpoint based on weather (e.g., outdoor temperature compensation)
    # This is a placeholder for future enhancement.
    if current_weather:
        # Example: if it's very cold outside, slightly increase the target_setpoint
        # outdoor_temp = current_weather.get('temp_c') # Assuming weather dict has temp_c
        # if outdoor_temp is not None and outdoor_temp < 0:
        #     target_setpoint += 1 # Boost by 1 degree if freezing outside
        pass

    print(f"Zone {zone.id}: Current Temp: {current_temp}°C, Target: {target_setpoint}°C, Heater: {'ON' if heater_on else 'OFF'}")
    return heater_on, target_setpoint

async def run_zone_control_logic(db: Session, zone_id: int):
    """
    Runs the full control logic for a single zone.
    1. Fetches zone data, preferences, current temperature, occupancy, and weather.
    2. Makes a control decision.
    3. Sends command to Modbus if necessary and if state changed.
    4. Logs the command.
    """
    zone = db.query(models.Zone).filter(models.Zone.id == zone_id).first()
    if not zone:
        print(f"Control Logic: Zone {zone_id} not found.")
        return

    if not zone.modbus_host or zone.modbus_port is None:
        print(f"Control Logic: Zone {zone_id} does not have Modbus configuration. Skipping control.")
        return

    # Fetch latest sensor data for current temperature and occupancy
    latest_sensor_data = (
        db.query(models.SensorData)
        .filter(models.SensorData.zone_id == zone_id)
        .order_by(desc(models.SensorData.timestamp))
        .first()
    )

    if not latest_sensor_data:
        print(f"Control Logic: No sensor data found for zone {zone_id}. Skipping control.")
        return
    
    current_temp = latest_sensor_data.temperature
    # Assuming occupancy is also part of SensorData or read directly from Modbus
    # For now, let's assume modbus_client can give us current occupancy and heater state
    
    try:
        # Read current occupancy and heater status from Modbus
        # These are synchronous calls in the current modbus_client, might need async versions
        # or run in executor if modbus_client is not async-compatible directly
        current_occupancy_from_modbus = await asyncio.to_thread(
            modbus_client.read_occupancy_status, zone.modbus_host, zone.modbus_port
        )
        current_heater_state_from_modbus = await asyncio.to_thread(
            modbus_client.read_heater_status, zone.modbus_host, zone.modbus_port
        )
        if current_occupancy_from_modbus is None or current_heater_state_from_modbus is None:
            print(f"Control Logic: Failed to read current Modbus data for zone {zone_id}. Skipping.")
            return

    except Exception as e:
        print(f"Control Logic: Error reading Modbus data for zone {zone_id}: {e}. Skipping.")
        return

    # Fetch weather data
    current_weather_data = None
    if zone.weather_location:
        try:
            # Assuming weather.get_weather_forecast is async or can be awaited if it's a coroutine
            # If it's synchronous, it should be wrapped with asyncio.to_thread as well
            # For now, assuming it might be an async function or a regular function call
            # Let's assume get_weather_forecast is a synchronous function for now
            current_weather_data = await asyncio.to_thread(weather.get_weather_forecast, zone.weather_location)
            if current_weather_data and 'current' in current_weather_data:
                 current_weather_data = current_weather_data['current'] # Use the current weather part
            else:
                print(f"Control Logic: Weather data for {zone.weather_location} is not in expected format.")
                current_weather_data = None
        except Exception as e:
            print(f"Control Logic: Failed to fetch weather for zone {zone_id} at {zone.weather_location}: {e}")
            current_weather_data = None

    # Make control decision
    # We need to adjust make_control_decision to potentially use current_heater_state_from_modbus
    # for a more robust hysteresis. For now, it decides independently.
    now_time = datetime.datetime.now().time()
    
    heater_on_decision, target_setpoint_used = make_control_decision(
        db=db, 
        zone=zone, 
        current_temp=current_temp, 
        current_occupancy=current_occupancy_from_modbus, 
        current_heater_state_from_modbus=current_heater_state_from_modbus,
        current_time=now_time,
        current_weather=current_weather_data
    )

    if target_setpoint_used is None: # Should not happen if make_control_decision handles it
        print(f"Control Logic: No target setpoint determined by make_control_decision for zone {zone_id}. No action.")
        return

    # Update target temperature on Modbus if it has changed or needs to be set
    # We should read the current target from Modbus to avoid unnecessary writes.
    # For simplicity, we can just write it if a valid one was determined.
    # Or, only write if the *scheduled* target_setpoint is different from Modbus target_setpoint
    try:
        # Let's also update the target temperature in the simulator
        # This is useful if the simulator itself uses this target for its own logic or display
        # We should ideally get the *effective* target_setpoint that the control logic decided on.
        # which is target_setpoint_used (after occupancy, min/max adjustments)
        # Let's read current Modbus target temp first
        current_modbus_target_temp = await asyncio.to_thread(
            modbus_client.read_target_temperature, zone.modbus_host, zone.modbus_port
        )

        if current_modbus_target_temp is None:
            print(f"Control Logic: Failed to read current target temp from Modbus for zone {zone.id}. Skipping target update.")
        elif abs(current_modbus_target_temp - target_setpoint_used) > 0.1: # Check if significantly different
            print(f"Control Logic: Updating Modbus target temp for zone {zone.id} from {current_modbus_target_temp}°C to {target_setpoint_used}°C")
            success_target_write = await asyncio.to_thread(
                modbus_client.write_target_temperature, zone.modbus_host, zone.modbus_port, target_setpoint_used
            )
            if not success_target_write:
                print(f"Control Logic: Failed to write target temperature to Modbus for zone {zone.id}.")
            else:
                # Log command for setting target temperature
                cmd_target = models.Command(
                    zone_id=zone.id,
                    target_temp=target_setpoint_used,
                    command_type="SET_TARGET_TEMP",
                    details=json.dumps({"target_temp": target_setpoint_used, "previous_target_temp": current_modbus_target_temp}),
                    status="SUCCESS"
                )
                db.add(cmd_target)
                # db.commit() # Commit will be handled by the calling scheduler job

    except Exception as e:
        print(f"Control Logic: Error updating target temperature on Modbus for zone {zone_id}: {e}")


    # Send command to Modbus ONLY if the heater state needs to change
    if heater_on_decision != current_heater_state_from_modbus:
        print(f"Control Logic: Zone {zone.id} - Current Heater: {current_heater_state_from_modbus}, Decision: {heater_on_decision}. Action: Changing heater state.")
        try:
            success_heater_write = await asyncio.to_thread(
                modbus_client.write_heater_state, zone.modbus_host, zone.modbus_port, heater_on_decision
            )
            if success_heater_write:
                print(f"Control Logic: Successfully set heater for zone {zone.id} to {'ON' if heater_on_decision else 'OFF'}")
                cmd_heater = models.Command(
                    zone_id=zone.id,
                    target_temp=target_setpoint_used,
                    command_type="SET_HEATER",
                    details=json.dumps({"heater_on": heater_on_decision, "target_temp_at_decision": target_setpoint_used, "current_temp_at_decision": current_temp}),
                    status="SUCCESS"
                )
                db.add(cmd_heater)
            else:
                print(f"Control Logic: Failed to set heater state for zone {zone.id} via Modbus.")
                cmd_heater = models.Command(
                    zone_id=zone.id,
                    target_temp=target_setpoint_used,
                    command_type="SET_HEATER",
                    details=json.dumps({"heater_on": heater_on_decision, "error": "Modbus write failed"}),
                    status="FAILED"
                )
                db.add(cmd_heater)
            # db.commit() # Commit will be handled by the calling scheduler job
        except Exception as e:
            print(f"Control Logic: Error sending heater command to Modbus for zone {zone_id}: {e}")
            cmd_heater = models.Command(
                zone_id=zone.id,
                target_temp=target_setpoint_used,
                command_type="SET_HEATER",
                details=json.dumps({"heater_on": heater_on_decision, "error": str(e)}),
                status="ERROR"
            )
            db.add(cmd_heater)
            # db.commit()
    else:
        print(f"Control Logic: Zone {zone_id} - Current Heater: {current_heater_state_from_modbus}, Decision: {heater_on_decision}. Action: No change needed.")
    
    # The db.commit() should ideally be outside this function, managed by the scheduler job after all zones are processed.
    # For standalone testing, it would be here.

if __name__ == '__main__':
    # This part is for testing the control logic independently if needed
    # You would need to set up a test database session and a sample zone
    print("Testing control logic (requires manual setup)")
    # Example:
    # db_session = database.SessionLocal()
    # test_zone_id = 1 # Assuming a zone with ID 1 exists and is configured
    # asyncio.run(run_zone_control_logic(db_session, test_zone_id))
    # db_session.close()
    pass 