from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
import datetime

# Base model for Zone, used when creating a new zone
class ZoneBase(BaseModel):
    name: str
    preferences: Optional[Dict[str, Any]] = None
    modbus_port: Optional[int] = None
    modbus_host: Optional[str] = "localhost"

# Model for creating a zone, inherits from ZoneBase
class ZoneCreate(ZoneBase):
    pass

# Model for reading/returning a zone, includes the id
class Zone(ZoneBase):
    id: int

    model_config = {"from_attributes": True}

# --- SensorData Schemas ---
class SensorDataBase(BaseModel):
    temperature: float
    occupancy: bool
    # zone_id will be derived from the path or context usually, or passed explicitly

class SensorDataCreate(SensorDataBase):
    zone_id: int # Required when creating a reading directly via API

class SensorData(SensorDataBase):
    id: int
    zone_id: int
    timestamp: datetime.datetime
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