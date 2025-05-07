from pydantic import BaseModel, Field, validator
from typing import Optional, Dict, Any, List
import datetime
import re # For time validation

# --- Schedule Schemas (for new preferences structure) ---
class ScheduleEntry(BaseModel):
    time: str # HH:MM format
    occupied_temp: float
    unoccupied_temp: float

    @validator('time')
    def validate_time_format(cls, value):
        if not re.match(r"^(?:[01]\d|2[0-3]):[0-5]\d$", value):
            raise ValueError("Time must be in HH:MM format")
        return value

class ZonePreferences(BaseModel):
    schedule: Optional[List[ScheduleEntry]] = None
    default_occupied_temp: Optional[float] = 21.0
    default_unoccupied_temp: Optional[float] = 17.0
    min_target_temp: Optional[float] = 15.0
    max_target_temp: Optional[float] = 25.0

    # Fields for occupancy-based control
    use_occupancy_for_heating: Optional[bool] = True # Default to using occupancy
    setback_setpoint: Optional[float] = 16.0      # Default setback temp when unoccupied

    # Fields for weather adjustment - ADDED
    allow_weather_adjustment: Optional[bool] = False # Default to False
    weather_adjustment_freezing_threshold: Optional[float] = 0.0
    weather_adjustment_cold_boost_degrees: Optional[float] = 0.5
    weather_adjustment_mild_threshold: Optional[float] = 15.0
    weather_adjustment_mild_reduction_degrees: Optional[float] = 0.0

    # New fields for energy price response sensitivity
    peak_occupied_temp_reduction: Optional[float] = 0.5 # Degrees to reduce setpoint during peak
    super_peak_occupied_temp_reduction: Optional[float] = 1.0 # Degrees to reduce setpoint during super peak
    allow_off_peak_preconditioning: Optional[bool] = False # Enable pre-heating/cooling
    off_peak_occupied_temp_increase: Optional[float] = 0.5 # Degrees to increase setpoint during off-peak if preconditioning

    # New fields for predictive control
    allow_predictive_control: Optional[bool] = False
    predictive_window_hours: Optional[int] = 4 # Hours ahead to look in forecast (e.g., 1-6)
    predictive_temp_drop_threshold: Optional[float] = 2.0 # Degrees C drop to trigger pre-heating
    predictive_preheat_increase: Optional[float] = 0.5      # Degrees C to boost setpoint for pre-heating
    predictive_temp_rise_threshold: Optional[float] = 2.0 # Degrees C rise to trigger heating reduction
    predictive_avoid_overheat_reduction: Optional[float] = 0.5 # Degrees C to reduce setpoint to avoid overshoot

    # New fields for refining predictive logic interactions
    prioritize_comfort_over_peak_cost: Optional[bool] = False # If true, predictive pre-heat ignores peak (not super-peak) price reduction
    max_combined_preheat_boost: Optional[float] = 1.5 # Max degrees C ideal_target_temp can be boosted by combined preconditioning effects

    # New fields for physics and overrides
    high_outside_temp_threshold: Optional[float] = 21.0 # Outside temp (°C) above which occupied reduction applies
    occupied_temp_reduction_high_outside: Optional[float] = 1.0 # Degrees C reduction when outside is high

# --- Zone Schemas ---
class ZoneBase(BaseModel):
    name: str
    weather_location: Optional[str] = None # Zone-specific weather location
    latitude: Optional[float] = None        # For historical API
    longitude: Optional[float] = None       # For historical API
    preferences: Optional[ZonePreferences] = Field(default_factory=ZonePreferences) # Use the new detailed preferences schema
    modbus_port: Optional[int] = None
    modbus_host: Optional[str] = "localhost"

# Model for creating a zone, inherits from ZoneBase
class ZoneCreate(ZoneBase):
    # weather_location should ideally be required if we want per-zone weather
    weather_location: str # Make it required for creation
    # latitude: float # Consider making required if simulation is core
    # longitude: float # Consider making required
    pass

# Model for reading/returning a zone, includes the id
class Zone(ZoneBase):
    id: int

    model_config = {"from_attributes": True}

# Model for updating a zone, all fields are optional for partial updates
class ZoneUpdate(BaseModel):
    name: Optional[str] = None
    weather_location: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    preferences: Optional[ZonePreferences] = None # Client can send partial or full preference updates
    modbus_port: Optional[int] = None
    modbus_host: Optional[str] = None # Usually localhost, but allow update

    model_config = {"from_attributes": True} # Useful if ever creating from a model instance

# --- SensorData Schemas ---
class SensorDataBase(BaseModel):
    temperature: float
    occupancy: bool
    target_temperature: Optional[float] = None # From Modbus poll
    heater_on: Optional[bool] = None      # From Modbus poll
    # zone_id will be derived from the path or context usually, or passed explicitly

class SensorDataCreate(SensorDataBase):
    zone_id: int # Required when creating a reading directly via API

class SensorData(SensorDataBase):
    id: int
    zone_id: int
    timestamp: datetime.datetime
    # target_temperature and heater_on are inherited from SensorDataBase
    model_config = {"from_attributes": True}

# --- Command Schemas ---
class CommandBase(BaseModel):
    target_temp: float
    # zone_id will be derived or passed explicitly

class CommandCreate(CommandBase):
    zone_id: int # Required when creating a command directly via API

class Command(CommandBase):
    id: int
    zone_id: int
    timestamp: datetime.datetime
    # status: Optional[str] = None # If we add status to the model
    model_config = {"from_attributes": True}

# For API responses that might list these
class ZoneWithDetails(Zone):
    sensor_data: List[SensorData] = []
    commands: List[Command] = []
    model_config = {"from_attributes": True}

# --- Historical Simulation Schemas ---

class HistoricalSimulationDataPointBase(BaseModel):
    timestamp_utc: datetime.datetime
    temperature_simulated: float
    target_temperature_control: float
    heater_on_simulated: bool
    occupancy_simulated: bool
    outdoor_temp_actual: Optional[float] = None
    energy_price_level_simulated: Optional[str] = None

class HistoricalSimulationDataPointCreate(HistoricalSimulationDataPointBase):
    pass # run_id will be implicit

class HistoricalSimulationDataPointSchema(HistoricalSimulationDataPointBase): # Renamed to avoid conflict
    id: int
    run_id: int
    model_config = {"from_attributes": True}

class HistoricalSimulationRunBase(BaseModel):
    zone_id: int
    sim_period_start: str # YYYY-MM-DD
    sim_period_end: str   # YYYY-MM-DD
    status: str = "PENDING"
    status_message: Optional[str] = None
    total_simulated_hours: Optional[float] = None
    calculated_energy_kwh: Optional[float] = None

class HistoricalSimulationRunCreate(BaseModel): # For the request body
    sim_period_start: str # YYYY-MM-DD
    sim_period_end: str   # YYYY-MM-DD
    
    @validator('sim_period_start', 'sim_period_end')
    def validate_date_format(cls, value):
        try:
            datetime.datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            raise ValueError("Date must be in YYYY-MM-DD format")
        return value

class HistoricalSimulationRunSchema(HistoricalSimulationRunBase): # Renamed to avoid conflict
    id: int
    requested_at_utc: datetime.datetime
    data_points: List[HistoricalSimulationDataPointSchema] = [] # Optionally include data points
    model_config = {"from_attributes": True}

class HistoricalSimulationRunInfo(HistoricalSimulationRunBase): # For listing runs without data points
    id: int
    requested_at_utc: datetime.datetime
    model_config = {"from_attributes": True} 