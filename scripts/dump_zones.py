import sys
import os
import json
from sqlalchemy.orm import Session

# Adjust path to import from src
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.database import SessionLocal
from src.models import Zone as ZoneModel # Assuming your model is named Zone

BACKUP_FILE = "zones_backup.json"

def dump_zone_configurations():
    """
    Fetches all zones from the database and dumps their configuration to a JSON file.
    """
    db: Session = SessionLocal()
    try:
        zones = db.query(ZoneModel).all()
        # zones = db.query(ZoneModel).filter(ZoneModel.id.in_([1, 2, 3, 4, 5])).all() # Uncomment to only dump zones 1-5

        if not zones:
            print("No zones found in the database to dump.")
            return

        zones_data = []
        for zone in zones:
            zones_data.append({
                "id": zone.id, # Keep original ID for reference, though it might change on load
                "name": zone.name,
                "weather_location": zone.weather_location,
                "latitude": zone.latitude,     # Temporarily commented out for dump from old DB
                "longitude": zone.longitude,   # Temporarily commented out for dump from old DB
                "preferences": zone.preferences, # This is already a dict/JSON
                "modbus_port": zone.modbus_port,
                "modbus_host": zone.modbus_host
            })
        
        with open(BACKUP_FILE, 'w') as f:
            json.dump(zones_data, f, indent=4)
        
        print(f"Successfully dumped {len(zones_data)} zone(s) to {BACKUP_FILE}")

    except Exception as e:
        print(f"An error occurred during dumping: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    print(f"Starting script to dump zone configurations to {BACKUP_FILE}...")
    dump_zone_configurations()
    print("Dumping script finished.") 