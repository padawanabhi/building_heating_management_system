import streamlit as st
import requests
import pandas as pd
import time
import datetime

# Configuration for the FastAPI backend URL
# Assumes the FastAPI server is running on the default localhost:8000
API_BASE_URL = "http://localhost:8000"
API_URL = API_BASE_URL # Use consistent naming

# --- Helper Functions --- 
def fetch_zones():
    """Fetches the list of zones from the API."""
    try:
        response = requests.get(f"{API_URL}/zones/")
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
        response = requests.get(f"{API_URL}/zones/{zone_id}/details")
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        st.error(f"Error fetching details for zone {zone_id}: {e}")
        return None
    except Exception as e:
        st.error(f"An unexpected error occurred fetching details: {e}")
        return None

def get_api_data(endpoint):
    """Generic function to fetch data from an API endpoint.""" # Added docstring
    try:
        response = requests.get(f"{API_URL}/{endpoint}")
        response.raise_for_status() # Raises an exception for HTTP errors
        return response.json()
    except requests.exceptions.RequestException as e:
        st.error(f"Error fetching data from {endpoint}: {e}")
        return None

def trigger_historical_simulation(zone_id, start_date, end_date):
    """Calls the API to start a historical simulation."""
    request_body = {
        "sim_period_start": start_date, 
        "sim_period_end": end_date
    }
    try:
        response = requests.post(f"{API_URL}/zones/{zone_id}/historical_simulations/", json=request_body)
        response.raise_for_status() 
        st.success(f"Historical simulation requested (Run ID: {response.json().get('id')}). Status: PENDING. Refresh list later.")
        return response.json()
    except requests.exceptions.RequestException as e:
        st.error(f"Error requesting historical simulation: {e} - {e.response.text if e.response else 'No response'}")
        return None
    except Exception as e:
        st.error(f"An unexpected error occurred requesting simulation: {e}")
        return None

def fetch_historical_runs_for_zone(zone_id):
    """Fetches the list of historical simulation runs for a zone."""
    try:
        response = requests.get(f"{API_URL}/zones/{zone_id}/historical_simulations/")
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        st.error(f"Error fetching historical runs: {e}")
        return []
    except Exception as e:
        st.error(f"An unexpected error occurred fetching runs: {e}")
        return []

def fetch_historical_run_details(run_id):
    """Fetches details and data points for a specific run."""
    try:
        response = requests.get(f"{API_URL}/historical_simulations/{run_id}")
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        st.error(f"Error fetching historical run details (ID: {run_id}): {e}")
        return None
    except Exception as e:
        st.error(f"An unexpected error occurred fetching run details: {e}")
        return None

# --- Streamlit App Layout ---
st.set_page_config(page_title="Heating Management Dashboard", layout="wide")

st.title("Building Heating Management Dashboard")

# Display Current Energy Price
st.subheader("Current Energy Price")
energy_price_data = get_api_data("energy/current_price")
if energy_price_data:
    price_level = energy_price_data.get("level", "N/A")
    price_kwh = energy_price_data.get("price_per_kwh", "N/A")
    currency = energy_price_data.get("currency", "")
    st.metric(label=f"Energy Price Level: {price_level.replace('_', ' ').title()}", value=f"{price_kwh} {currency}/kWh")
else:
    st.write("Could not load energy price data.")

st.divider()

# Fetch zones for the selection dropdown
zones = fetch_zones()

if not zones:
    st.warning("Could not fetch zones from the API. Is the FastAPI server running?")
else:
    zone_names = {zone['name']: zone['id'] for zone in zones}
    selected_zone_name = st.selectbox("Select Zone:", options=zone_names.keys())

    if selected_zone_name:
        selected_zone_id = zone_names[selected_zone_name]
        
        st.header(f"Live Status for {selected_zone_name} (ID: {selected_zone_id})")

        # --- Action Buttons (Live Data) --- 
        col_action1, col_action2 = st.columns([1,5]) # Give more space to the second column if needed
        with col_action1:
            if st.button("🔄 Refresh Live Data", key="refresh_main"):
                st.rerun()
        with col_action2: # Placeholder for other actions or leave empty
            if st.button("⚙️ Trigger Live Control Logic", key="trigger_control"):
                try:
                    response = requests.post(f"{API_BASE_URL}/zones/{selected_zone_id}/trigger_control_logic")
                    response.raise_for_status()
                    st.success(f"Control logic triggered for {selected_zone_name}. Check logs and refresh data.")
                    # Optionally, could try to parse response and show some info, or just rely on refresh
                    time.sleep(1) # Brief pause to allow server-side logging to catch up before potential rerun
                    st.rerun() # Rerun to fetch latest data after control logic
                except requests.exceptions.RequestException as e:
                    st.error(f"Failed to trigger control logic: {e}")
                except Exception as e:
                    st.error(f"An unexpected error occurred: {e}")

        # Fetch and display live details
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
            
            # Use correct keys for default setpoints from the preferences dict
            occupied_setpoint = zone_details.get('preferences', {}).get('default_occupied_temp', 'N/A')
            unoccupied_setpoint = zone_details.get('preferences', {}).get('default_unoccupied_temp', 'N/A')

            col1.metric("Current Temperature", latest_temp)
            col2.metric("Occupancy Status", latest_occupancy)
            col3.metric("Occupied Setpoint", f"{occupied_setpoint}°C" if isinstance(occupied_setpoint, (int, float)) else occupied_setpoint)
            col4.metric("Unoccupied Setpoint", f"{unoccupied_setpoint}°C" if isinstance(unoccupied_setpoint, (int, float)) else unoccupied_setpoint)

            st.subheader("Live Sensor Readings")
            if zone_details.get('sensor_data'):
                sensor_df = pd.DataFrame(zone_details['sensor_data'])
                if not sensor_df.empty:
                    # Convert timestamp to datetime for proper plotting
                    sensor_df['timestamp'] = pd.to_datetime(sensor_df['timestamp'])
                    sensor_df = sensor_df.sort_values(by='timestamp') # Ensure data is sorted by time for line chart

                    # Prepare data for combined chart
                    chart_data = sensor_df[['timestamp', 'temperature', 'target_temperature', 'heater_on']].copy()
                    chart_data.rename(columns={
                        'timestamp': 'Time',
                        'temperature': 'Current Temp (°C)',
                        'target_temperature': 'Target Temp (°C)',
                        'heater_on': 'Heater On'
                    }, inplace=True)
                    
                    # Convert Heater On to 0 or 1 for plotting as a line/step
                    chart_data['Heater On'] = chart_data['Heater On'].astype(int)

                    st.markdown("**Zone Performance Chart**")
                    # Use melt for better compatibility with st.line_chart for multiple lines from different columns
                    # Or set index to Time and select columns
                    # st.line_chart(chart_data.set_index('Time')) # This plots all numeric columns
                    
                    # For more control, especially if scales differ or for clearer legends:
                    # Plotting temperature and target temperature together
                    temp_chart_df = chart_data.set_index('Time')[['Current Temp (°C)', 'Target Temp (°C)']]
                    st.line_chart(temp_chart_df)

                    # Plotting heater status separately or finding a way to overlay with dual axis if supported
                    # Streamlit's st.line_chart doesn't directly support dual Y-axis from a single call easily.
                    # We can plot it separately or normalize if we want to overlay on the same numeric scale.
                    heater_chart_df = chart_data.set_index('Time')[['Heater On']]
                    st.line_chart(heater_chart_df, height=200) # Smaller chart for heater status
                    st.caption("Heater On: 1 = ON, 0 = OFF")

                    # Display the dataframe as well, as before
                    st.markdown("**Sensor Data Table**")
                    sensor_df_display = sensor_df[['timestamp', 'temperature', 'occupancy', 'heater_on', 'target_temperature']].copy()
                    sensor_df_display.rename(columns={
                        'timestamp': 'Time',
                        'temperature': 'Current Temp (°C)',
                        'occupancy': 'Occupied',
                        'heater_on': 'Heater Active',
                        'target_temperature': 'Device Target Temp (°C)'
                        }, inplace=True)
                    st.dataframe(sensor_df_display, use_container_width=True)

                else:
                    st.info("No sensor readings available for this zone yet.")
            else:
                st.info("No sensor readings available for this zone yet.")

            st.subheader("Live Commands")
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

            st.subheader("Zone Configuration & Preferences")
            if zone_details.get('preferences'):
                prefs = zone_details['preferences']
                # Basic Preferences
                st.markdown("**General Setpoints & Behavior:**")
                col_prefs1, col_prefs2 = st.columns(2)
                col_prefs1.metric("Default Occupied Temp", f"{prefs.get('default_occupied_temp', 'N/A')}°C")
                col_prefs2.metric("Default Unoccupied Temp", f"{prefs.get('default_unoccupied_temp', 'N/A')}°C")
                col_prefs1.metric("Setback Temp (Unoccupied)", f"{prefs.get('setback_setpoint', 'N/A')}°C")
                col_prefs2.metric("Use Occupancy for Heating", "Yes" if prefs.get('use_occupancy_for_heating') else "No")
                col_prefs1.metric("Min Allowed Setpoint", f"{prefs.get('min_target_temp', 'N/A')}°C")
                col_prefs2.metric("Max Allowed Setpoint", f"{prefs.get('max_target_temp', 'N/A')}°C")

                # Schedule Table
                st.markdown("**Heating Schedule:**")
                if prefs.get('schedule'):
                    if 'occupied_temp' in prefs['schedule'][0]:
                        schedule_df = pd.DataFrame(prefs['schedule'])
                        schedule_df_display = schedule_df[['time', 'occupied_temp', 'unoccupied_temp']].copy()
                        schedule_df_display.rename(columns={'time': 'Time (HH:MM)', 'occupied_temp': 'Occupied Temp (°C)', 'unoccupied_temp': 'Unoccupied Temp (°C)'}, inplace=True)
                    else:
                        schedule_df = pd.DataFrame(prefs['schedule'])
                        schedule_df_display = schedule_df[['time', 'setpoint']].copy()
                        schedule_df_display.rename(columns={'time': 'Time (HH:MM)', 'setpoint': 'Scheduled Setpoint (°C)'}, inplace=True)
                    st.dataframe(schedule_df_display, use_container_width=True)
                else:
                    st.caption("No heating schedule defined. Uses default temperatures.")

                # Weather Adjustments (Display if allow_weather_adjustment is present and True)
                if prefs.get('allow_weather_adjustment', False):
                    st.markdown("**Weather Adjustments:**")
                    col_wa1, col_wa2 = st.columns(2)
                    col_wa1.metric("Enabled", "Yes")
                    col_wa2.metric("Freezing Threshold", f"{prefs.get('weather_adjustment_freezing_threshold', 'N/A')}°C")
                    col_wa1.metric("Cold Boost", f"{prefs.get('weather_adjustment_cold_boost_degrees', 'N/A')}°C")
                    col_wa2.metric("Mild Threshold", f"{prefs.get('weather_adjustment_mild_threshold', 'N/A')}°C")
                    col_wa1.metric("Mild Reduction", f"{prefs.get('weather_adjustment_mild_reduction_degrees', 'N/A')}°C")
                else:
                    st.markdown("**Weather Adjustments:** Disabled")
                    
                # Predictive Control (Display if allow_predictive_control is present and True)
                if prefs.get('allow_predictive_control', False):
                    st.markdown("**Predictive Control:**")
                    # Add display for predictive control parameters here if they exist in preferences
                    # e.g., predictive_window_hours, predictive_temp_drop_threshold etc.
                    st.metric("Enabled", "Yes")
                    st.write("Further predictive parameters: (not yet displayed)") # Placeholder
                else:
                    st.markdown("**Predictive Control:** Disabled")

            else:
                st.info("No preferences configured for this zone.")

        else:
            st.error("Failed to load live details for the selected zone.")

        st.divider()

        # --- Historical Simulation Section --- 
        st.header(f"Historical Simulation for {selected_zone_name}")

        col_sim1, col_sim2, col_sim3 = st.columns([2, 2, 1])
        with col_sim1:
            start_date = st.date_input("Simulation Start Date", value=datetime.date.today() - datetime.timedelta(days=7))
        with col_sim2:
            end_date = st.date_input("Simulation End Date", value=datetime.date.today() - datetime.timedelta(days=1)) # Default to yesterday
        
        # Validate dates
        valid_dates = False
        if start_date and end_date:
            if start_date <= end_date:
                valid_dates = True
            else:
                st.warning("Start date must be before or the same as end date.")
        
        with col_sim3:
            st.write("&nbsp;") # Spacer for button alignment
            if st.button("🚀 Run New Simulation", disabled=not valid_dates):
                if valid_dates:
                    trigger_historical_simulation(selected_zone_id, start_date.isoformat(), end_date.isoformat())
                    # Don't rerun immediately, let user see status message and refresh runs list

        # --- Display List of Historical Runs --- 
        st.subheader("Past Simulation Runs")
        historical_runs = fetch_historical_runs_for_zone(selected_zone_id)
        if historical_runs:
            runs_df = pd.DataFrame(historical_runs)
            # Select and format columns for display
            runs_df_display = runs_df[['id', 'requested_at_utc', 'sim_period_start', 'sim_period_end', 'status', 'status_message', 'calculated_energy_kwh']].copy()
            runs_df_display['requested_at_utc'] = pd.to_datetime(runs_df_display['requested_at_utc']).dt.strftime('%Y-%m-%d %H:%M:%S')
            runs_df_display.rename(columns={
                'id': 'Run ID', 'requested_at_utc': 'Requested At', 
                'sim_period_start': 'Period Start', 'sim_period_end': 'Period End',
                'status': 'Status', 'status_message': 'Message', 
                'calculated_energy_kwh': 'Energy Used (kWh)'
            }, inplace=True)
            
            # Display table and allow selection
            # Use st.dataframe or st.data_editor for selection, or add buttons
            st.dataframe(runs_df_display, use_container_width=True)
            
            # Allow selecting a run to view its results
            # Option 1: Selectbox
            # run_ids = [run['id'] for run in historical_runs if run['status'] == 'COMPLETED']
            # selected_run_id = st.selectbox("Select Completed Run to View Results:", options=[None] + run_ids)
            
            # Option 2: Add view buttons in the table (more complex with st.dataframe)
            # Option 3: Input field for Run ID
            selected_run_id_input = st.number_input("Enter Run ID to View Results", min_value=1, step=1, value=None)
            
            if selected_run_id_input:
                # Find the selected run details
                selected_run_details = next((run for run in historical_runs if run['id'] == selected_run_id_input), None)
                if selected_run_details:
                    if selected_run_details['status'] == 'COMPLETED':
                        st.subheader(f"Results for Simulation Run ID: {selected_run_id_input}")
                        # Fetch detailed data points for the selected run
                        run_data = fetch_historical_run_details(selected_run_id_input)
                        if run_data and run_data.get('data_points'):
                            data_points_df = pd.DataFrame(run_data['data_points'])
                            data_points_df['timestamp_utc'] = pd.to_datetime(data_points_df['timestamp_utc'])
                            data_points_df = data_points_df.sort_values(by='timestamp_utc')
                            
                            # Prepare data for chart
                            hist_chart_data = data_points_df[['timestamp_utc', 'temperature_simulated', 'target_temperature_control', 'heater_on_simulated', 'outdoor_temp_actual']].copy()
                            hist_chart_data.rename(columns={
                                'timestamp_utc': 'Time',
                                'temperature_simulated': 'Simulated Temp (°C)',
                                'target_temperature_control': 'Control Target Temp (°C)',
                                'heater_on_simulated': 'Heater On',
                                'outdoor_temp_actual': 'Outdoor Temp (°C)'
                            }, inplace=True)
                            hist_chart_data['Heater On'] = hist_chart_data['Heater On'].astype(int)

                            # Plot Temps
                            st.markdown("**Temperature Simulation Chart**")
                            temp_hist_chart_df = hist_chart_data.set_index('Time')[['Simulated Temp (°C)', 'Control Target Temp (°C)', 'Outdoor Temp (°C)']]
                            st.line_chart(temp_hist_chart_df)

                            # Plot Heater Status
                            heater_hist_chart_df = hist_chart_data.set_index('Time')[['Heater On']]
                            st.line_chart(heater_hist_chart_df, height=200)
                            st.caption("Heater On: 1 = ON, 0 = OFF")
                            
                            st.markdown("**Simulation Data Table**")
                            st.dataframe(hist_chart_data, use_container_width=True)
                            
                        elif run_data and not run_data.get('data_points'):
                             st.warning("Simulation run completed but no data points were found.")
                        else:
                            st.error("Failed to load detailed data for the selected simulation run.")
                            
                    elif selected_run_details['status'] in ["PENDING", "RUNNING"]:
                         st.info(f"Simulation run {selected_run_id_input} is still {selected_run_details['status']}. Please refresh later.")
                    else: # FAILED
                         st.error(f"Simulation run {selected_run_id_input} failed: {selected_run_details.get('status_message', 'Unknown error')}")
                else:
                     st.warning(f"Run ID {selected_run_id_input} not found in the list of runs for this zone.")
        else:
            st.caption("No historical simulation runs found for this zone yet.")

st.caption("Dashboard displaying data from the Building Heating Management API.") 