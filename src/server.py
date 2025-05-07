from fastapi import FastAPI, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List, Dict, Any
import logging # For logging from scheduler
import datetime # Added for time-based schedule logic
import asyncio # Added asyncio

from apscheduler.schedulers.asyncio import AsyncIOScheduler # Changed to AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from . import models, schemas, weather, zone_simulator, modbus_client
from .database import get_db, engine, SessionLocal # Added SessionLocal for scheduler
from .weather import get_weather_forecast
from .energy_pricer import get_current_energy_price # Import the energy price function
from .control_logic import run_zone_control_logic # Import the new control logic function
from .config import settings
from .schemas import Zone, ZonePreferences, HistoricalSimulationRunCreate, HistoricalSimulationRunSchema, HistoricalSimulationRunInfo # Added historical schemas
from . import historical_simulator # Import the historical simulation function

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
# These are now mostly superseded by per-zone preferences
# DEFAULT_OCCUPIED_SETPOINT = 21.0 # Superseded by zone.preferences.default_occupied_temp or schedule
# DEFAULT_UNOCCUPIED_SETPOINT = 17.0 # Superseded by zone.preferences.default_unoccupied_temp or schedule
# WEATHER_LOCATION_FOR_CONTROL = "London" # Superseded by zone.weather_location
HIGH_OUTSIDE_TEMP_THRESHOLD = 21.0 # Celsius - Can remain global or be moved to preferences later
OCCUPIED_TEMP_REDUCTION_HIGH_OUTSIDE = 1.0 # Reduce target by this much if outside is warm - Can remain global
# MIN_TARGET_TEMP = 15.0 # Superseded by zone.preferences.min_target_temp
# MAX_TARGET_TEMP = 25.0 # Superseded by zone.preferences.max_target_temp

# --- Scheduler for Polling Modbus Devices ---
scheduler = AsyncIOScheduler() # Use AsyncIOScheduler

async def poll_sensor_data_job(): # New/Reinstated polling job
    print("Sensor data polling job started.")
    db: Session = SessionLocal()
    try:
        zones_to_poll = db.query(models.Zone).filter(models.Zone.modbus_port != None).all()
        if not zones_to_poll:
            print("No zones with Modbus configuration found for polling sensor data.")
            db.close()
            return

        for zone in zones_to_poll:
            print(f"Polling sensor data for zone {zone.id} ({zone.name})")
            try:
                # Use a single call to read all zone data from Modbus
                zone_data = await asyncio.to_thread(
                    modbus_client.read_zone_data_from_modbus, zone.modbus_host, zone.modbus_port
                )

                if zone_data and "error" not in zone_data:
                    # Ensure all expected keys are present before creating SensorData
                    temp = zone_data.get("temperature")
                    occupancy = zone_data.get("occupancy")
                    heater_on = zone_data.get("heater_on")
                    target_temp = zone_data.get("target_temperature")

                    if temp is not None and occupancy is not None and heater_on is not None and target_temp is not None:
                        sensor_entry = models.SensorData(
                            zone_id=zone.id,
                            temperature=temp,
                            occupancy=occupancy,
                            heater_on=heater_on,
                            target_temperature=target_temp
                        )
                        db.add(sensor_entry)
                        print(f"Sensor data for zone {zone.id} logged: Temp={temp}, Occ={occupancy}, Heat={heater_on}, Target={target_temp}")
                    else:
                        print(f"Failed to log sensor data for zone {zone.id}: Incomplete data received from Modbus. Data: {zone_data}")
                elif zone_data and "error" in zone_data:
                    print(f"Error polling sensor data for zone {zone.id} from Modbus: {zone_data['error']}")
                else:
                    print(f"Failed to read sensor data from Modbus for zone {zone.id}. No data or unexpected response.")

            except Exception as e:
                print(f"Exception while polling sensor data for zone {zone.id}: {e}")
        
        db.commit() # Commit all collected sensor data
        print(f"Sensor data polling finished for {len(zones_to_poll)} zones.")
    except Exception as e:
        print(f"Error in sensor data polling job: {e}")
        db.rollback()
    finally:
        db.close()

async def run_control_logic_for_all_zones_job(): # Renamed and made async
    print("Control logic job started.")
    db: Session = SessionLocal()
    try:
        zones_with_modbus = db.query(models.Zone).filter(models.Zone.modbus_port != None).all()
        if not zones_with_modbus:
            print("No zones with Modbus configuration found. Skipping control logic run.")
            return

        control_tasks = []
        for zone in zones_with_modbus:
            print(f"Queueing control logic for zone {zone.id} ({zone.name})")
            # Schedule the async function run_zone_control_logic for each zone
            control_tasks.append(run_zone_control_logic(db, zone.id))
        
        # Run all control logic tasks concurrently
        await asyncio.gather(*control_tasks)
        
        db.commit() # Commit all DB changes made by control logic runs
        print(f"Control logic executed for {len(zones_with_modbus)} zones.")

    except Exception as e:
        print(f"Error in control logic job: {e}")
        db.rollback() # Rollback in case of error during the batch processing
    finally:
        db.close()
    print("Control logic job finished.")

@app.on_event("startup")
async def startup_event(): # Made startup event async
    logger.info("FastAPI application startup...")
    db = SessionLocal()
    zones = db.query(models.Zone).all()
    for zone_model in zones:
        if zone_model.modbus_port: # Only start if port is defined
            print(f"Starting Modbus simulator for Zone {zone_model.id} ({zone_model.name}) on port {zone_model.modbus_port}")
            # Initial values can be fetched from DB or defaults
            initial_temp = 20.0
            initial_target = 22.0 # This will be passed as initial_target_temp
            initial_occupancy_val = False # This will be passed as initial_occupancy
            
            latest_sensor = db.query(models.SensorData).filter(models.SensorData.zone_id == zone_model.id).order_by(models.SensorData.timestamp.desc()).first()
            if latest_sensor:
                initial_temp = latest_sensor.temperature
                if latest_sensor.target_temperature is not None: initial_target = latest_sensor.target_temperature
                initial_occupancy_val = latest_sensor.occupancy

            sim = zone_simulator.ZoneSimulator(
                zone_id=zone_model.id, 
                name=zone_model.name, # Added name argument
                modbus_port=zone_model.modbus_port, # Added modbus_port argument
                initial_temp=initial_temp,
                initial_target_temp=initial_target, # Corrected to initial_target_temp
                initial_occupancy=initial_occupancy_val # Corrected to initial_occupancy
                # host argument removed as it's not in ZoneSimulator.__init__
            )
            # asyncio.create_task(sim.run_simulation_loop()) # Start the simulation loop - this was from an older version
            # The ZoneSimulator's start method should handle threading internally.
            sim.start() # Start the simulator (which starts its own threads for simulation and Modbus)
            print(f"Zone {zone_model.id} ({zone_model.name}) simulator started.")
    db.close()

    # Add the sensor data polling job
    scheduler.add_job(poll_sensor_data_job, IntervalTrigger(seconds=30), id="poll_sensor_data")
    # Add the control logic job
    scheduler.add_job(run_control_logic_for_all_zones_job, IntervalTrigger(seconds=60), id="control_logic_all_zones")
    scheduler.start()
    logger.info("APScheduler started with sensor polling and control logic jobs.")

@app.on_event("shutdown")
async def shutdown_event(): # Made shutdown event async
    logger.info("FastAPI application shutdown...")
    scheduler.shutdown()
    logger.info("APScheduler shut down.")

# --- CRUD for Zones ---
@app.post("/zones/", response_model=schemas.Zone, tags=["Zones"])
def create_zone(zone: schemas.ZoneCreate, db: Session = Depends(get_db)):
    db_zone_by_name = db.query(models.Zone).filter(models.Zone.name == zone.name).first()
    if db_zone_by_name:
        raise HTTPException(status_code=400, detail="Zone name already registered")
    
    if zone.modbus_port is not None:
        existing_port = db.query(models.Zone).filter(models.Zone.modbus_port == zone.modbus_port).first()
        if existing_port:
            raise HTTPException(status_code=400, detail=f"Modbus port {zone.modbus_port} is already in use.")

    # Preferences will be passed as a Pydantic model (schemas.ZonePreferences) 
    # and needs to be converted to a dict for JSON storage if not handled automatically by SQLAlchemy JSON type.
    # SQLAlchemy's JSON type usually handles dicts directly.
    new_zone = models.Zone(
        name=zone.name, 
        weather_location=zone.weather_location, 
        latitude=zone.latitude,                 
        longitude=zone.longitude,               
        # preferences=zone.preferences.model_dump() if zone.preferences else None, # Convert Pydantic model to dict
        preferences=zone.preferences.model_dump(exclude_unset=False) if zone.preferences else ZonePreferences().model_dump(exclude_unset=False),
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

@app.put("/zones/{zone_id}", response_model=schemas.Zone, tags=["Zones"])
def update_zone(zone_id: int, zone_update_data: schemas.ZoneUpdate, db: Session = Depends(get_db)):
    db_zone = db.query(models.Zone).filter(models.Zone.id == zone_id).first()
    if db_zone is None:
        raise HTTPException(status_code=404, detail="Zone not found")

    update_data = zone_update_data.model_dump(exclude_unset=True) # Get only provided fields

    if "name" in update_data and update_data["name"] != db_zone.name:
        existing_name_zone = db.query(models.Zone).filter(models.Zone.name == update_data["name"]).first()
        if existing_name_zone:
            raise HTTPException(status_code=400, detail="Zone name already registered by another zone.")
        db_zone.name = update_data["name"]

    if "modbus_port" in update_data and update_data["modbus_port"] is not None and update_data["modbus_port"] != db_zone.modbus_port:
        existing_port_zone = db.query(models.Zone).filter(models.Zone.modbus_port == update_data["modbus_port"]).first()
        if existing_port_zone:
            raise HTTPException(status_code=400, detail=f"Modbus port {update_data['modbus_port']} is already in use by another zone.")
        db_zone.modbus_port = update_data["modbus_port"]
    elif "modbus_port" in update_data and update_data["modbus_port"] is None:
        db_zone.modbus_port = None # Allow unsetting the port

    if "weather_location" in update_data:
        db_zone.weather_location = update_data["weather_location"]

    if "modbus_host" in update_data:
        db_zone.modbus_host = update_data["modbus_host"]

    if "latitude" in update_data:
        db_zone.latitude = update_data["latitude"]
    
    if "longitude" in update_data:
        db_zone.longitude = update_data["longitude"]

    if "preferences" in update_data and update_data["preferences"] is not None:
        # update_data["preferences"] is already a dict from zone_update_data.model_dump()
        # Ensure it's a full representation if it came from a partial Pydantic model
        # One way is to load it into the Pydantic model and dump it again fully.
        try:
            loaded_prefs = schemas.ZonePreferences(**update_data["preferences"])
            db_zone.preferences = loaded_prefs.model_dump(exclude_unset=False)
        except Exception as e:
            # Handle error if dict can't be loaded into ZonePreferences, though FastAPI should validate upstream
            print(f"Error processing preferences in update_zone: {e}. Preferences not updated.")
            # Optionally raise HTTPException
            pass 
    elif "preferences" in update_data and update_data["preferences"] is None:
        # Allow explicitly setting preferences to None (or default)
        db_zone.preferences = schemas.ZonePreferences().model_dump(exclude_unset=False) # Set to default

    db.commit()
    db.refresh(db_zone)
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

# --- Energy Pricer Endpoint ---
@app.get("/energy/current_price", response_model=Dict[str, Any], tags=["Energy"])
async def read_current_energy_price():
    """
    Get the current simulated energy price information.
    """
    price_info = get_current_energy_price()
    if "error" in price_info:
        raise HTTPException(status_code=500, detail=price_info["error"])
    return price_info

@app.post("/zones/{zone_id}/trigger_control_logic", response_model=schemas.Zone, tags=["Control Logic"], summary="Trigger Control Logic for a Zone")
async def trigger_control_logic_for_zone(zone_id: int, db: Session = Depends(get_db)):
    """
    Manually triggers the control logic for a specific zone.
    This is useful for testing and forcing an immediate control decision.
    The control logic will run based on the latest sensor data and current preferences.
    """
    db_zone = db.query(models.Zone).filter(models.Zone.id == zone_id).first()
    if not db_zone:
        raise HTTPException(status_code=404, detail="Zone not found")

    if not db_zone.modbus_host or db_zone.modbus_port is None:
        # Although run_zone_control_logic also checks this, good to have an early exit
        raise HTTPException(status_code=400, detail=f"Zone {zone_id} does not have Modbus configuration. Cannot trigger control logic.")

    try:
        logger.info(f"Manual trigger for control logic received for zone {zone_id} ({db_zone.name}).")
        # Ensure the db session is passed correctly and handled within run_zone_control_logic
        # run_zone_control_logic is async and expects the db session.
        # It also handles its own commits/rollbacks internally if called standalone, 
        # but when called from scheduler, the scheduler job handles the commit.
        # For a manual trigger, we need to ensure the session is committed if changes are made.
        
        # Create a new session for this specific operation to avoid conflicts with scheduler
        # or pass the existing one and rely on its commit/close cycle if this endpoint is simple.
        # Given run_zone_control_logic itself doesn't commit (expects caller/scheduler to), we should commit here.
        
        await run_zone_control_logic(db, zone_id) # db is already a valid session from Depends(get_db)
        db.commit() # Commit any changes made by the control logic (like logging commands)
        logger.info(f"Control logic manually triggered and completed for zone {zone_id}.")
        
        # Refresh the zone data to return the latest state including any new commands/sensor data if applicable immediately
        db.refresh(db_zone) # Refresh might not show immediate Modbus changes unless polling has run
        return db_zone
    except Exception as e:
        logger.error(f"Error during manual trigger of control logic for zone {zone_id}: {e}", exc_info=True)
        db.rollback() # Rollback on error
        raise HTTPException(status_code=500, detail=f"Failed to trigger control logic: {str(e)}")

# --- Historical Simulation API Endpoints ---

@app.post("/zones/{zone_id}/historical_simulations/", 
          response_model=schemas.HistoricalSimulationRunInfo, # Return info about the created run
          status_code=202, # Accepted status code for background task
          tags=["Historical Simulation"],
          summary="Start a Historical Simulation for a Zone")
async def create_historical_simulation(
    zone_id: int,
    run_request: schemas.HistoricalSimulationRunCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Triggers a historical simulation for the specified zone and date range.
    
    - The simulation runs in the background.
    - Returns information about the simulation run task that was initiated.
    - Use other endpoints to check status and retrieve results.
    """
    db_zone = db.query(models.Zone).filter(models.Zone.id == zone_id).first()
    if not db_zone:
        raise HTTPException(status_code=404, detail="Zone not found")
        
    if not db_zone.latitude or not db_zone.longitude:
        raise HTTPException(status_code=400, detail="Zone is missing latitude/longitude required for historical weather data.")

    # Create the initial run entry in the database
    new_run = models.HistoricalSimulationRun(
        zone_id=zone_id,
        sim_period_start=run_request.sim_period_start,
        sim_period_end=run_request.sim_period_end,
        status="PENDING"
    )
    db.add(new_run)
    db.commit()
    db.refresh(new_run)

    # Add the actual simulation function to run in the background
    background_tasks.add_task(
        historical_simulator.run_historical_simulation_for_zone,
        zone_id=zone_id,
        run_id=new_run.id,
        sim_start_date_str=run_request.sim_period_start,
        sim_end_date_str=run_request.sim_period_end
    )
    
    logger.info(f"Queued historical simulation run ID {new_run.id} for zone {zone_id}.")
    
    # Return info about the accepted task
    return new_run # Pydantic will serialize using HistoricalSimulationRunInfo

@app.get("/zones/{zone_id}/historical_simulations/", 
         response_model=List[schemas.HistoricalSimulationRunInfo], 
         tags=["Historical Simulation"],
         summary="List Historical Simulation Runs for a Zone")
async def list_historical_simulations_for_zone(zone_id: int, db: Session = Depends(get_db)):
    """
    Retrieves a list of all historical simulation runs initiated for a specific zone.
    Does not include the detailed data points.
    """
    db_zone = db.query(models.Zone).filter(models.Zone.id == zone_id).first()
    if not db_zone:
        raise HTTPException(status_code=404, detail="Zone not found")
        
    # Construct query without explicit line continuation by chaining
    runs = (db.query(models.HistoricalSimulationRun)
            .filter(models.HistoricalSimulationRun.zone_id == zone_id)
            .order_by(models.HistoricalSimulationRun.requested_at_utc.desc())
            .all())
    return runs

@app.get("/historical_simulations/{run_id}", 
         response_model=schemas.HistoricalSimulationRunSchema, 
         tags=["Historical Simulation"],
         summary="Get Details of a Specific Historical Simulation Run")
async def get_historical_simulation_run_details(run_id: int, db: Session = Depends(get_db)):
    """
    Retrieves the full details of a specific historical simulation run, 
    including its status and all associated data points.
    Warning: This might return a large amount of data for long simulations.
    """
    # Import orm here as it's only used in this function
    from sqlalchemy import orm 
    
    # Construct query without explicit line continuation by chaining
    run = (db.query(models.HistoricalSimulationRun)
           .options(orm.selectinload(models.HistoricalSimulationRun.data_points)) # Eager load data points
           .filter(models.HistoricalSimulationRun.id == run_id)
           .first())
            
    if not run:
        raise HTTPException(status_code=404, detail="Historical simulation run not found")
        
    # Check if data points are loaded; if not, manually load them if needed
    # This depends on relationship loading strategy. selectinload is usually good.
    # If lazy loading is default, access run.data_points here to trigger load before return.
    _ = run.data_points # Access to potentially trigger lazy load if not eager loaded
        
    return run

# To run the server (from the project root directory):
# uvicorn src.server:app --reload 