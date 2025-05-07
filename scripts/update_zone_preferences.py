import sys
import os
from sqlalchemy.orm import Session

# Adjust path to import from src
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.database import SessionLocal, engine
from src.models import Zone as ZoneModel
from src.schemas import ZonePreferences # To get default values

def update_existing_zone_preferences():
    """
    Fetches zones with IDs 1-5 and updates their preferences JSON
    to include new energy-related fields with default values if not present.
    """
    db: Session = SessionLocal()
    try:
        zones_to_update = db.query(ZoneModel).filter(ZoneModel.id.in_([1, 2, 3, 4, 5])).all()

        if not zones_to_update:
            print("No zones found with IDs 1-5 to update.")
            return

        # Get default values from the Pydantic schema
        default_prefs = ZonePreferences()
        new_preference_fields = {
            "peak_occupied_temp_reduction": default_prefs.peak_occupied_temp_reduction,
            "super_peak_occupied_temp_reduction": default_prefs.super_peak_occupied_temp_reduction,
            "allow_off_peak_preconditioning": default_prefs.allow_off_peak_preconditioning,
            "off_peak_occupied_temp_increase": default_prefs.off_peak_occupied_temp_increase,
        }

        updated_count = 0
        for zone in zones_to_update:
            print(f"Processing Zone ID: {zone.id}, Name: {zone.name}")
            current_prefs = zone.preferences
            if not isinstance(current_prefs, dict):
                print(f"  Skipping Zone ID: {zone.id} - preferences is not a valid dictionary or is null. Current value: {current_prefs}")
                current_prefs = {} # Initialize if null or invalid, so defaults can be added

            made_change_to_this_zone = False
            for key, default_value in new_preference_fields.items():
                if key not in current_prefs:
                    current_prefs[key] = default_value
                    print(f"  Added default for '{key}': {default_value} to Zone ID: {zone.id}")
                    made_change_to_this_zone = True
            
            if made_change_to_this_zone:
                zone.preferences = current_prefs # Assign back to trigger SQLAlchemy change detection for JSON field
                db.add(zone) # Add to session to mark as dirty if changes were made
                updated_count +=1
                print(f"  Zone ID: {zone.id} preferences updated.")
            else:
                print(f"  Zone ID: {zone.id} already had all new preference fields. No update needed.")

        if updated_count > 0:
            db.commit()
            print(f"Successfully updated preferences for {updated_count} zone(s).")
        else:
            print("No zones required updates for the new preference fields.")

    except Exception as e:
        db.rollback()
        print(f"An error occurred: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    print("Starting script to update zone preferences...")
    # Ensure the database exists, otherwise create_all (though this script doesn't create tables)
    # ZoneModel.metadata.create_all(bind=engine) # Not strictly needed if tables exist
    update_existing_zone_preferences()
    print("Script finished.") 