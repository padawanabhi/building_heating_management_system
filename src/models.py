from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, ForeignKey, JSON, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func # For server_default=func.now()
import datetime

from .database import Base

class Zone(Base):
    __tablename__ = "zones"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)
    weather_location = Column(String, nullable=True) # For zone-specific weather forecasts
    latitude = Column(Float, nullable=True)         # For historical data API
    longitude = Column(Float, nullable=True)        # For historical data API
    # preferences will store more complex data including schedules:
    # Example:
    # {
    #   "schedule": [
    #     {"time": "00:00", "occupied_temp": 18.0, "unoccupied_temp": 16.0},
    #     {"time": "07:00", "occupied_temp": 21.0, "unoccupied_temp": 17.0}
    #   ],
    #   "default_occupied_temp": 21.0,
    #   "default_unoccupied_temp": 17.0,
    #   "min_target_temp": 15.0,
    #   "max_target_temp": 25.0
    #   New energy pricing related preferences (optional):
    #   "peak_occupied_temp_reduction": 0.5, (degrees C)
    #   "super_peak_occupied_temp_reduction": 1.0, (degrees C)
    #   "allow_off_peak_preconditioning": false, (boolean)
    #   "off_peak_occupied_temp_increase": 0.5 (degrees C)
    #   New predictive control preferences (optional):
    #   "allow_predictive_control": false,
    #   "predictive_window_hours": 4,
    #   "predictive_temp_drop_threshold": 2.0,
    #   "predictive_preheat_increase": 0.5,
    #   "predictive_temp_rise_threshold": 2.0,
    #   "predictive_avoid_overheat_reduction": 0.5
    #   New fields for refining predictive logic interactions (optional):
    #   "prioritize_comfort_over_peak_cost": false,
    #   "max_combined_preheat_boost": 1.5
    #   New fields for physics and overrides (optional):
    #   "high_outside_temp_threshold": 21.0,
    #   "occupied_temp_reduction_high_outside": 1.0,
    #   "heating_rate_degC_per_hour": 1.0,
    #   "cooling_rate_factor_per_hour": 0.2
    # }
    preferences = Column(JSON, nullable=True)
    modbus_port = Column(Integer, unique=True, nullable=True)
    modbus_host = Column(String, default="localhost", nullable=False)

    sensor_data = relationship("SensorData", back_populates="zone")
    commands = relationship("Command", back_populates="zone")

    def __repr__(self):
        return f"<Zone(id={self.id}, name='{self.name}', location='{self.weather_location}', lat={self.latitude}, lon={self.longitude}, port={self.modbus_port})>"

class SensorData(Base):
    __tablename__ = "sensor_data"

    id = Column(Integer, primary_key=True, index=True)
    zone_id = Column(Integer, ForeignKey("zones.id"), nullable=False)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    temperature = Column(Float, nullable=False)
    occupancy = Column(Boolean, default=False, nullable=False) # True if occupied, False otherwise
    # New fields from Modbus poll
    target_temperature = Column(Float, nullable=True)
    heater_on = Column(Boolean, nullable=True)

    zone = relationship("Zone", back_populates="sensor_data")

    def __repr__(self):
        return f"<SensorData(id={self.id}, zone_id={self.zone_id}, temp={self.temperature}, target={self.target_temperature}, occupied={self.occupancy}, heater={self.heater_on}, time={self.timestamp})>"

class Command(Base):
    __tablename__ = "commands"

    id = Column(Integer, primary_key=True, index=True)
    zone_id = Column(Integer, ForeignKey("zones.id"), nullable=False)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    
    # Changed target_temp to be nullable, as not all commands set a temp (e.g. raw heater on/off)
    # However, for SET_TARGET_TEMP and SET_HEATER (where target is known), we will populate it.
    target_temp = Column(Float, nullable=True) 

    command_type = Column(String, nullable=False) # E.g., "SET_TARGET_TEMP", "SET_HEATER"
    details = Column(JSON, nullable=True)       # For storing additional JSON context
    status = Column(String, nullable=False)     # E.g., "SUCCESS", "FAILED", "PENDING"

    zone = relationship("Zone", back_populates="commands")

    def __repr__(self):
        return f"<Command(id={self.id}, zone_id={self.zone_id}, target_temp={self.target_temp}, time={self.timestamp})>"

# New Models for Historical Simulation Results
class HistoricalSimulationRun(Base):
    __tablename__ = "historical_simulation_runs"

    id = Column(Integer, primary_key=True, index=True)
    zone_id = Column(Integer, ForeignKey("zones.id"), nullable=False)
    
    requested_at_utc = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    sim_period_start = Column(String, nullable=False) # Store as ISO date string "YYYY-MM-DD"
    sim_period_end = Column(String, nullable=False)   # Store as ISO date string "YYYY-MM-DD"
    
    status = Column(String, nullable=False, default="PENDING") # PENDING, RUNNING, COMPLETED, FAILED
    status_message = Column(Text, nullable=True) # For error messages or details
    
    # Example summary fields, can be expanded
    total_simulated_hours = Column(Float, nullable=True)
    calculated_energy_kwh = Column(Float, nullable=True) # Example summary metric

    zone = relationship("Zone") # Simple relationship to Zone
    data_points = relationship("HistoricalSimulationDataPoint", back_populates="run", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<HistoricalSimulationRun(id={self.id}, zone_id={self.zone_id}, period='{self.sim_period_start}' to '{self.sim_period_end}', status='{self.status}')>"

class HistoricalSimulationDataPoint(Base):
    __tablename__ = "historical_simulation_data_points"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(Integer, ForeignKey("historical_simulation_runs.id"), nullable=False)
    
    timestamp_utc = Column(DateTime(timezone=True), nullable=False) # The historical point in time
    
    temperature_simulated = Column(Float, nullable=False)
    target_temperature_control = Column(Float, nullable=False)
    heater_on_simulated = Column(Boolean, nullable=False)
    occupancy_simulated = Column(Boolean, nullable=False) # Assuming we might simulate occupancy too
    
    outdoor_temp_actual = Column(Float, nullable=True) # From historical weather
    energy_price_level_simulated = Column(String, nullable=True) # e.g., OFF_PEAK, PEAK
    # calculated_power_kw = Column(Float, nullable=True) # If we calculate instantaneous power

    run = relationship("HistoricalSimulationRun", back_populates="data_points")

    def __repr__(self):
        return f"<HistoricalSimulationDataPoint(id={self.id}, run_id={self.run_id}, time='{self.timestamp_utc}', temp={self.temperature_simulated})>"

# To handle the "date in table names" idea if strictly needed later, one might explore:
# 1. Dynamic table creation (complex with SQLAlchemy migrations and querying).
# 2. Database partitioning (requires PostgreSQL or similar, not straightforward with SQLite).
# 3. Keeping a single table and ensuring efficient indexing on the timestamp, then filtering by date.
# For this project, option 3 is the most practical starting point. 