from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, ForeignKey, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func # For server_default=func.now()
import datetime

from .database import Base

class Zone(Base):
    __tablename__ = "zones"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)
    # For preferences, we can use JSON for flexibility with SQLite/PostgreSQL
    # Example: {"occupied_temp": 22, "unoccupied_temp": 18, "min_temp": 16, "max_temp": 25}
    preferences = Column(JSON, nullable=True)
    modbus_port = Column(Integer, unique=True, nullable=True)
    modbus_host = Column(String, default="localhost", nullable=False)

    sensor_data = relationship("SensorData", back_populates="zone")
    commands = relationship("Command", back_populates="zone")

    def __repr__(self):
        return f"<Zone(id={self.id}, name='{self.name}', port={self.modbus_port})>"

class SensorData(Base):
    __tablename__ = "sensor_data"

    id = Column(Integer, primary_key=True, index=True)
    zone_id = Column(Integer, ForeignKey("zones.id"), nullable=False)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    temperature = Column(Float, nullable=False)
    occupancy = Column(Boolean, default=False, nullable=False) # True if occupied, False otherwise

    zone = relationship("Zone", back_populates="sensor_data")

    def __repr__(self):
        return f"<SensorData(id={self.id}, zone_id={self.zone_id}, temp={self.temperature}, occupied={self.occupancy}, time={self.timestamp})>"

class Command(Base):
    __tablename__ = "commands"

    id = Column(Integer, primary_key=True, index=True)
    zone_id = Column(Integer, ForeignKey("zones.id"), nullable=False)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    target_temp = Column(Float, nullable=False)
    # You might want to add a status for the command (e.g., pending, sent, acknowledged, failed)
    # status = Column(String, default="pending") 

    zone = relationship("Zone", back_populates="commands")

    def __repr__(self):
        return f"<Command(id={self.id}, zone_id={self.zone_id}, target_temp={self.target_temp}, time={self.timestamp})>"

# To handle the "date in table names" idea if strictly needed later, one might explore:
# 1. Dynamic table creation (complex with SQLAlchemy migrations and querying).
# 2. Database partitioning (requires PostgreSQL or similar, not straightforward with SQLite).
# 3. Keeping a single table and ensuring efficient indexing on the timestamp, then filtering by date.
# For this project, option 3 is the most practical starting point. 