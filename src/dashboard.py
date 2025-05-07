import streamlit as st
import requests
import pandas as pd
import time

# Configuration for the FastAPI backend URL
# Assumes the FastAPI server is running on the default localhost:8000
API_BASE_URL = "http://localhost:8000"

def fetch_zones():
    """Fetches the list of zones from the API."""
    try:
        response = requests.get(f"{API_BASE_URL}/zones/")
        response.raise_for_status() # Raise an exception for bad status codes
        return response.json()
    except requests.exceptions.RequestException as e:
        st.error(f"Error fetching zones: {e}")
        return []
    except Exception as e:
        st.error(f"An unexpected error occurred: {e}")
        return []

def fetch_zone_details(zone_id):
    """Fetches detailed status, including recent data, for a specific zone."""
    try:
        # Using the /details endpoint which includes sensor_data and commands
        response = requests.get(f"{API_BASE_URL}/zones/{zone_id}/details")
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        st.error(f"Error fetching details for zone {zone_id}: {e}")
        return None
    except Exception as e:
        st.error(f"An unexpected error occurred fetching details: {e}")
        return None

# --- Streamlit App Layout ---
st.set_page_config(page_title="Heating Management Dashboard", layout="wide")

st.title("Building Heating Management Dashboard")

# Fetch zones for the selection dropdown
zones = fetch_zones()

if not zones:
    st.warning("Could not fetch zones from the API. Is the FastAPI server running?")
else:
    zone_names = {zone['name']: zone['id'] for zone in zones}
    selected_zone_name = st.selectbox("Select Zone:", options=zone_names.keys())

    if selected_zone_name:
        selected_zone_id = zone_names[selected_zone_name]
        
        st.header(f"Status for {selected_zone_name} (ID: {selected_zone_id})")

        # Add a refresh button
        if st.button("Refresh Data"):
            st.rerun()

        # Fetch and display details
        zone_details = fetch_zone_details(selected_zone_id)

        if zone_details:
            col1, col2, col3, col4 = st.columns(4)

            # Display current Modbus target temp (if available from polling)
            # We need the latest actual target from the device, which our control logic uses
            # Let's fetch it via the modbus client functions or add it to the API response
            # For now, display preferences if available
            
            # Fetch current device state via modbus_client (may block slightly)
            # This is less ideal than having the central server cache/provide it via API
            # Alternative: Display the last *commanded* target temp from DB?
            # Let's display preferences for now as a placeholder for target state
            
            # Get latest sensor reading from the zone_details (API already provides it)
            latest_temp = "N/A"
            latest_occupancy = "N/A"
            if zone_details.get('sensor_data') and len(zone_details['sensor_data']) > 0:
                # Assuming sensor_data is sorted by timestamp descending from the API
                latest_reading = zone_details['sensor_data'][0]
                latest_temp = f"{latest_reading.get('temperature', 'N/A')}°C"
                latest_occupancy = "Occupied" if latest_reading.get('occupancy', False) else "Unoccupied"
            
            occupied_setpoint = zone_details.get('preferences', {}).get('occupied_temp', 'N/A')
            unoccupied_setpoint = zone_details.get('preferences', {}).get('unoccupied_temp', 'N/A')

            col1.metric("Current Temperature", latest_temp)
            col2.metric("Occupancy Status", latest_occupancy)
            col3.metric("Occupied Setpoint", f"{occupied_setpoint}°C" if isinstance(occupied_setpoint, (int, float)) else occupied_setpoint)
            col4.metric("Unoccupied Setpoint", f"{unoccupied_setpoint}°C" if isinstance(unoccupied_setpoint, (int, float)) else unoccupied_setpoint)

            st.subheader("Recent Sensor Readings")
            if zone_details.get('sensor_data'):
                sensor_df = pd.DataFrame(zone_details['sensor_data'])
                if not sensor_df.empty:
                    # Select and rename columns for clarity
                    sensor_df_display = sensor_df[['timestamp', 'temperature', 'occupancy']].copy()
                    sensor_df_display.rename(columns={'timestamp': 'Time', 'temperature': 'Temperature (°C)', 'occupancy': 'Occupied'}, inplace=True)
                    st.dataframe(sensor_df_display, use_container_width=True)

                    # Simple plot
                    st.line_chart(sensor_df_display.rename(columns={'Temperature (°C)': 'temp'}).set_index('Time')[['temp']])
                else:
                    st.info("No sensor readings available for this zone yet.")
            else:
                st.info("No sensor readings available for this zone yet.")

            st.subheader("Recent Commands")
            if zone_details.get('commands'):
                command_df = pd.DataFrame(zone_details['commands'])
                if not command_df.empty:
                    command_df_display = command_df[['timestamp', 'target_temp']].copy()
                    command_df_display.rename(columns={'timestamp': 'Time', 'target_temp': 'Target Temp (°C)'}, inplace=True)
                    st.dataframe(command_df_display, use_container_width=True)
                else:
                    st.info("No commands logged for this zone yet.")
            else:
                st.info("No commands logged for this zone yet.")

        else:
            st.error("Failed to load details for the selected zone.")

st.caption("Dashboard displaying data from the Building Heating Management API.") 