import sys
import os
import json
from sqlalchemy.orm import Session

# Adjust path to import from src
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.database import SessionLocal, engine # engine for create_all if needed
from src.models import Zone as ZoneModel, Base as BaseModel # Base for create_all
from src.schemas import ZonePreferences # To validate and populate defaults in preferences

BACKUP_FILE = "zones_backup.json"

def load_and_update_zone_configurations():
    """
    Loads zone configurations from a JSON backup file, validates and updates 
    their preferences to include new fields with defaults, and saves them to the database.
    Assumes the database tables have been created (e.g., by running the FastAPI server once).
    """
    db: Session = SessionLocal()
    try:
        if not os.path.exists(BACKUP_FILE):
            print(f"Backup file {BACKUP_FILE} not found. Cannot load zones.")
            return

        with open(BACKUP_FILE, 'r') as f:
            zones_to_load = json.load(f)

        if not zones_to_load:
            print("No zones found in the backup file.")
            return

        loaded_count = 0
        print(f"Found {len(zones_to_load)} zone(s) in {BACKUP_FILE}. Attempting to load...")

        for zone_data in zones_to_load:
            print(f"Processing backed-up zone: {zone_data.get('name')}")
            
            # Validate and update preferences
            raw_preferences = zone_data.get("preferences")
            if not isinstance(raw_preferences, dict):
                print(f"  Warning: Preferences for zone '{zone_data.get('name')}' is not a dictionary or is null. Initializing to empty dict.")
                raw_preferences = {}
            
            try:
                # Use Pydantic model to validate and fill in defaults for any new preference fields
                validated_preferences = ZonePreferences.model_validate(raw_preferences)
                preferences_for_db = validated_preferences.model_dump()
            except Exception as e:
                print(f"  Error validating preferences for zone '{zone_data.get('name')}': {e}. Using raw preferences as is (might be incomplete).")
                preferences_for_db = raw_preferences # Fallback, though risky

            # Check if zone with this name or modbus_port already exists to avoid simple duplicates
            # This is a basic check. For true idempotency, one might update if exists.
            # For this script, we assume we are loading into a fresh or mostly empty DB.
            existing_by_name = db.query(ZoneModel).filter(ZoneModel.name == zone_data["name"]).first()
            if existing_by_name:
                print(f"  Skipping zone '{zone_data['name']}': A zone with this name already exists.")
                continue
            if zone_data.get("modbus_port") is not None:
                 existing_by_port = db.query(ZoneModel).filter(ZoneModel.modbus_port == zone_data["modbus_port"]).first()
                 if existing_by_port:
                    print(f"  Skipping zone '{zone_data['name']}': Modbus port {zone_data['modbus_port']} already in use.")
                    continue

            new_zone = ZoneModel(
                name=zone_data["name"],
                weather_location=zone_data.get("weather_location"),
                latitude=zone_data.get("latitude"),
                longitude=zone_data.get("longitude"),
                preferences=preferences_for_db, # Use the validated and potentially updated preferences
                modbus_port=zone_data.get("modbus_port"),
                modbus_host=zone_data.get("modbus_host", "localhost")
            )
            db.add(new_zone)
            loaded_count += 1
            print(f"  Zone '{new_zone.name}' prepared for adding.")

        if loaded_count > 0:
            db.commit()
            print(f"Successfully loaded and committed {loaded_count} zone(s) to the database.")
        else:
            print("No new zones were loaded into the database.")

    except Exception as e:
        db.rollback()
        print(f"An error occurred: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    print("Starting script to load and update zone configurations from backup...")
    # Optional: Ensure tables exist. 
    # BaseModel.metadata.create_all(bind=engine) # Usually done by server startup
    load_and_update_zone_configurations()
    print("Loading script finished.") 