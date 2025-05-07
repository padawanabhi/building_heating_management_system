from fastapi import FastAPI, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Dict, Any
import logging # For logging from scheduler

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from . import models, schemas, weather
from .database import get_db, engine, SessionLocal # Added SessionLocal for scheduler
from .weather import get_weather_forecast
from .modbus_client import read_zone_data_from_modbus, write_target_temp_to_modbus # Import the modbus client function

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create database tables (if they don't exist) - useful for development
# In production, you'd likely use Alembic migrations.
models.Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Building Heating Management System API",
    description="API for managing and monitoring building heating zones.",
    version="0.1.0"
)

# --- Constants for Control Logic ---
DEFAULT_OCCUPIED_SETPOINT = 21.0
DEFAULT_UNOCCUPIED_SETPOINT = 17.0
WEATHER_LOCATION_FOR_CONTROL = "London" # Use a default location for now
HIGH_OUTSIDE_TEMP_THRESHOLD = 21.0 # Celsius
OCCUPIED_TEMP_REDUCTION_HIGH_OUTSIDE = 1.0 # Reduce target by this much if outside is warm
MIN_TARGET_TEMP = 15.0 # Absolute minimum target temp
MAX_TARGET_TEMP = 25.0 # Absolute maximum target temp

# --- Scheduler for Polling Modbus Devices ---
scheduler = BackgroundScheduler()

def poll_modbus_zones_job():
    logger.info("APScheduler job: Starting to poll Modbus zones...")
    db: Session = SessionLocal() # Create a new session for this job
    try:
        zones_to_poll = db.query(models.Zone).filter(models.Zone.modbus_port != None).all()
        if not zones_to_poll:
            logger.info("APScheduler job: No zones configured for Modbus polling.")
            return

        for zone in zones_to_poll:
            logger.info(f"APScheduler job: Polling Zone ID {zone.id} ({zone.name}) at {zone.modbus_host}:{zone.modbus_port}")
            zone_data = read_zone_data_from_modbus(host=zone.modbus_host, port=zone.modbus_port)

            if "error" in zone_data:
                logger.error(f"APScheduler job: Error polling zone {zone.id} ({zone.name}): {zone_data['error']}")
            else:
                logger.info(f"APScheduler job: Successfully polled zone {zone.id} ({zone.name}). Data: {zone_data}")
                # Save sensor data to DB
                db_sensor_data = models.SensorData(
                    zone_id=zone.id,
                    temperature=zone_data["temperature"],
                    occupancy=zone_data["occupancy"]
                )
                db.add(db_sensor_data)
                # We can commit per zone or once at the end.
                # Committing per zone means if one poll fails, others are still saved.
        db.commit() # Commit all sensor data for this polling cycle
        logger.info("APScheduler job: Finished polling Modbus zones and saved data.")
    except Exception as e:
        logger.error(f"APScheduler job: An unexpected error occurred: {e}")
        db.rollback() # Rollback in case of error during commit or other issues
    finally:
        db.close() # Ensure session is closed

def apply_control_logic_job():
    logger.info("APScheduler job: Applying control logic...")
    db: Session = SessionLocal() # Create a new session for this job
    try:
        zones = db.query(models.Zone).filter(models.Zone.modbus_port != None).all()
        if not zones:
            logger.info("APScheduler job: No zones configured for control logic.")
            return

        # Get weather forecast (only once per job run for efficiency)
        # Using current day forecast for simplicity
        weather_data = get_weather_forecast(location=WEATHER_LOCATION_FOR_CONTROL, days=1)
        current_outside_temp = None
        if "error" in weather_data:
            logger.error(f"APScheduler job: Could not get weather data for {WEATHER_LOCATION_FOR_CONTROL}: {weather_data['error']}")
        elif weather_data and 'current' in weather_data:
            current_outside_temp = weather_data['current']['temp_c']
            logger.info(f"APScheduler job: Current outside temp for {WEATHER_LOCATION_FOR_CONTROL}: {current_outside_temp}°C")
        else:
            logger.warning(f"APScheduler job: Weather data received but format unexpected.")

        commands_to_log = [] # Collect commands to log after potential Modbus writes

        for zone in zones:
            logger.info(f"APScheduler job: Evaluating control for Zone ID {zone.id} ({zone.name})")
            
            # Get latest sensor data for occupancy (could also get from Modbus, but DB is source of record)
            latest_reading = db.query(models.SensorData)\
                               .filter(models.SensorData.zone_id == zone.id)\
                               .order_by(models.SensorData.timestamp.desc())\
                               .first()

            if not latest_reading:
                logger.warning(f"APScheduler job: No recent sensor data found for zone {zone.id}, skipping control.")
                continue

            is_occupied = latest_reading.occupancy
            current_zone_temp = latest_reading.temperature
            logger.info(f"APScheduler job: Zone {zone.id} - Occupied: {is_occupied}, Current Temp: {current_zone_temp}°C")

            # --- Determine Ideal Target Temperature Based on Rules ---
            ideal_target_temp = DEFAULT_UNOCCUPIED_SETPOINT
            if is_occupied:
                ideal_target_temp = DEFAULT_OCCUPIED_SETPOINT
                # Adjust if outside temp is high
                if current_outside_temp is not None and current_outside_temp > HIGH_OUTSIDE_TEMP_THRESHOLD:
                    ideal_target_temp -= OCCUPIED_TEMP_REDUCTION_HIGH_OUTSIDE
                    logger.info(f"APScheduler job: Zone {zone.id} - Reducing target due to high outside temp. New ideal: {ideal_target_temp}°C")
            
            # Apply absolute limits
            ideal_target_temp = max(MIN_TARGET_TEMP, min(MAX_TARGET_TEMP, ideal_target_temp))
            ideal_target_temp = round(ideal_target_temp, 1) # Round to one decimal place

            # --- Compare with Actual Target on Device and Command if Needed ---
            # Read current state directly from Modbus device to get its actual current target
            modbus_data = read_zone_data_from_modbus(host=zone.modbus_host, port=zone.modbus_port)

            if "error" in modbus_data:
                logger.error(f"APScheduler job: Failed to read current state from Modbus for zone {zone.id}: {modbus_data['error']}")
                continue # Skip control for this zone if we can't read it
            
            current_device_target_temp = modbus_data.get("target_temperature")
            logger.info(f"APScheduler job: Zone {zone.id} - Ideal Target: {ideal_target_temp}°C, Device Target: {current_device_target_temp}°C")

            if current_device_target_temp is None:
                 logger.error(f"APScheduler job: Could not read target temperature from device for zone {zone.id}.")
                 continue

            # Check if the target needs changing (allow for small float differences)
            if abs(ideal_target_temp - current_device_target_temp) > 0.01:
                logger.info(f"APScheduler job: Zone {zone.id} - Target mismatch detected. Sending command to set target to {ideal_target_temp}°C.")
                write_result = write_target_temp_to_modbus(host=zone.modbus_host, port=zone.modbus_port, target_temp=ideal_target_temp)
                
                if "error" in write_result:
                    logger.error(f"APScheduler job: Failed to write target temperature to Modbus for zone {zone.id}: {write_result['error']}")
                else:
                    logger.info(f"APScheduler job: Successfully wrote target temperature {ideal_target_temp}°C to zone {zone.id}.")
                    # Prepare command to log in DB after successful write
                    commands_to_log.append(models.Command(zone_id=zone.id, target_temp=ideal_target_temp))
            else:
                 logger.info(f"APScheduler job: Zone {zone.id} - Target temperature already matches ideal ({ideal_target_temp}°C). No command sent.")

        # Add and commit all logged commands
        if commands_to_log:
            db.add_all(commands_to_log)
            db.commit()
            logger.info(f"APScheduler job: Logged {len(commands_to_log)} commands to database.")
        else:
             logger.info("APScheduler job: No commands needed logging this cycle.")

        logger.info("APScheduler job: Finished applying control logic.")
    except Exception as e:
        logger.exception(f"APScheduler job: An unexpected error occurred in control logic: {e}") # Use logger.exception for traceback
        db.rollback() # Rollback in case of error
    finally:
        db.close() # Ensure session is closed

@app.on_event("startup")
def startup_event():
    logger.info("FastAPI application startup...")
    # --- Add Polling Job --- 
    scheduler.add_job(
        poll_modbus_zones_job, 
        trigger=IntervalTrigger(seconds=30), # Poll every 30 seconds
        id="poll_modbus_zones", 
        name="Poll Modbus Zones Regularly",
        replace_existing=True
    )
    # --- Add Control Logic Job --- 
    scheduler.add_job(
        apply_control_logic_job, 
        trigger=IntervalTrigger(minutes=1), # Apply logic every 1 minute (adjust as needed)
        id="apply_control_logic", 
        name="Apply Control Logic Regularly",
        replace_existing=True
    )
    scheduler.start()
    logger.info("APScheduler started with polling and control jobs.")

@app.on_event("shutdown")
def shutdown_event():
    logger.info("FastAPI application shutdown...")
    scheduler.shutdown()
    logger.info("APScheduler shut down.")

# --- CRUD for Zones ---
@app.post("/zones/", response_model=schemas.Zone, tags=["Zones"])
def create_zone(zone: schemas.ZoneCreate, db: Session = Depends(get_db)):
    db_zone = db.query(models.Zone).filter(models.Zone.name == zone.name).first()
    if db_zone:
        raise HTTPException(status_code=400, detail="Zone name already registered")
    
    # Check for modbus_port uniqueness if a port is provided
    if zone.modbus_port is not None:
        existing_port = db.query(models.Zone).filter(models.Zone.modbus_port == zone.modbus_port).first()
        if existing_port:
            raise HTTPException(status_code=400, detail=f"Modbus port {zone.modbus_port} is already in use.")

    new_zone = models.Zone(
        name=zone.name, 
        preferences=zone.preferences,
        modbus_port=zone.modbus_port,
        modbus_host=zone.modbus_host
    )
    db.add(new_zone)
    db.commit()
    db.refresh(new_zone)
    return new_zone

@app.get("/zones/", response_model=List[schemas.Zone], tags=["Zones"])
def read_zones(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    zones = db.query(models.Zone).offset(skip).limit(limit).all()
    return zones

@app.get("/zones/{zone_id}", response_model=schemas.Zone, tags=["Zones"])
def read_zone(zone_id: int, db: Session = Depends(get_db)):
    db_zone = db.query(models.Zone).filter(models.Zone.id == zone_id).first()
    if db_zone is None:
        raise HTTPException(status_code=404, detail="Zone not found")
    return db_zone

# --- Weather Endpoint ---
@app.get("/weather/forecast/{location}", response_model=Dict[str, Any], tags=["Weather"])
async def get_forecast(location: str, days: int = Query(1, ge=1, le=14)):
    """
    Get weather forecast for a specific location.
    - **location**: City name (e.g., London), zip code, or lat,long.
    - **days**: Number of days for forecast (1-14).
    """
    forecast_data = get_weather_forecast(location=location, days=days)
    if "error" in forecast_data:
        # You might want to map specific errors to HTTP status codes
        # For now, let's assume a generic error if the API key is missing or other config issue
        if forecast_data["error"] == "WeatherAPI key not configured.":
             raise HTTPException(status_code=500, detail="Weather service not configured")
        # For other errors from the weather service (e.g., location not found, API limits)
        # returning them directly might be okay, or map to 400/404/429 etc.
        # For simplicity, we can return 400 for general client-side type errors from weather service
        if "Error fetching weather data" in forecast_data["error"] or "Number of forecast days" in forecast_data["error"]:
            raise HTTPException(status_code=400, detail=forecast_data["error"])
        # Fallback for other unexpected errors within the weather module
        raise HTTPException(status_code=500, detail=forecast_data.get("error", "Unknown error fetching weather"))
    return forecast_data

@app.get("/", tags=["Root"])
async def read_root():
    return {"message": "Welcome to the Building Heating Management System API"}

# --- CRUD for SensorData ---
@app.post("/sensordata/", response_model=schemas.SensorData, tags=["SensorData"])
def create_sensor_reading(sensor_data: schemas.SensorDataCreate, db: Session = Depends(get_db)):
    # Check if zone exists
    db_zone = db.query(models.Zone).filter(models.Zone.id == sensor_data.zone_id).first()
    if not db_zone:
        raise HTTPException(status_code=404, detail=f"Zone with id {sensor_data.zone_id} not found")
    
    db_sensor_data = models.SensorData(
        zone_id=sensor_data.zone_id,
        temperature=sensor_data.temperature,
        occupancy=sensor_data.occupancy
        # timestamp is auto-generated by server_default in the model
    )
    db.add(db_sensor_data)
    db.commit()
    db.refresh(db_sensor_data)
    return db_sensor_data

@app.get("/sensordata/zone/{zone_id}", response_model=List[schemas.SensorData], tags=["SensorData"])
def read_sensor_readings_for_zone(zone_id: int, skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    # Check if zone exists
    db_zone = db.query(models.Zone).filter(models.Zone.id == zone_id).first()
    if not db_zone:
        raise HTTPException(status_code=404, detail=f"Zone with id {zone_id} not found")

    sensor_readings = db.query(models.SensorData).filter(models.SensorData.zone_id == zone_id).order_by(models.SensorData.timestamp.desc()).offset(skip).limit(limit).all()
    return sensor_readings

@app.get("/sensordata/", response_model=List[schemas.SensorData], tags=["SensorData"])
def read_all_sensor_readings(skip: int = 0, limit: int = 1000, db: Session = Depends(get_db)):
    sensor_readings = db.query(models.SensorData).order_by(models.SensorData.timestamp.desc()).offset(skip).limit(limit).all()
    return sensor_readings

# --- CRUD for Commands ---
@app.post("/commands/", response_model=schemas.Command, tags=["Commands"])
def create_command_for_zone(command: schemas.CommandCreate, db: Session = Depends(get_db)):
    # Check if zone exists
    db_zone = db.query(models.Zone).filter(models.Zone.id == command.zone_id).first()
    if not db_zone:
        raise HTTPException(status_code=404, detail=f"Zone with id {command.zone_id} not found")

    db_command = models.Command(
        zone_id=command.zone_id,
        target_temp=command.target_temp
        # timestamp is auto-generated
    )
    db.add(db_command)
    db.commit()
    db.refresh(db_command)
    # Here, we would also publish this command to the Modbus device (zone simulator)
    # This will be handled by the Modbus client logic later.
    print(f"TODO: Send command to Modbus device for Zone {db_command.zone_id} to set target_temp={db_command.target_temp}")
    return db_command

@app.get("/commands/zone/{zone_id}", response_model=List[schemas.Command], tags=["Commands"])
def read_commands_for_zone(zone_id: int, skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    # Check if zone exists
    db_zone = db.query(models.Zone).filter(models.Zone.id == zone_id).first()
    if not db_zone:
        raise HTTPException(status_code=404, detail=f"Zone with id {zone_id} not found")

    commands = db.query(models.Command).filter(models.Command.zone_id == zone_id).order_by(models.Command.timestamp.desc()).offset(skip).limit(limit).all()
    return commands

@app.get("/zones/{zone_id}/details", response_model=schemas.ZoneWithDetails, tags=["Zones"])
def read_zone_with_details(zone_id: int, db: Session = Depends(get_db)):
    db_zone = db.query(models.Zone).filter(models.Zone.id == zone_id).first()
    if db_zone is None:
        raise HTTPException(status_code=404, detail="Zone not found")
    # The relationships in models.Zone (sensor_data, commands) should be automatically 
    # populated by SQLAlchemy if accessed, and Pydantic will handle serialization.
    return db_zone

# To run the server (from the project root directory):
# uvicorn src.server:app --reload 