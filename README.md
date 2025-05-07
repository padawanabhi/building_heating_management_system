# Building-Level Heating Management System Simulation

This project simulates a multi-zone heating management platform for a small building, demonstrating end-to-end functionality from virtual thermostats to a central service for data logging, control, basic optimization, and historical simulation.

## System Architecture

The system follows a multi-layer design:

1.  **Zone Simulators**: Multiple Python processes, each representing a virtual thermostat/heating zone. They simulate temperature changes and occupancy status, started automatically by the Central Server.
2.  **Communication Layer**: Modbus TCP is used for real-time data exchange between the zone simulators (acting as Modbus slaves) and the central server (acting as a Modbus master).
3.  **Central Server**: A Python-based web service built with FastAPI. It:
    *   Starts and manages Zone Simulator processes on startup.
    *   Periodically polls data (current temperature, occupancy, heater status, target temperature) from all configured zone simulators via Modbus.
    *   Logs this sensor data into an SQL database.
    *   Applies control logic based on preferences, schedules, occupancy, and weather.
    *   Sends commands (new target temperatures, heater state - though simulator logic might override direct heater commands) back to zone simulators via Modbus.
    *   Exposes a REST API for status queries, data retrieval, manual control triggers, and historical simulation management.
    *   Runs historical simulations in background tasks upon request.
4.  **Data Management**: A relational database (SQLite by default) stores time-series sensor data, zone configurations (including preferences and schedules), control commands, and historical simulation results. SQLAlchemy is used as the ORM.
5.  **Weather Integration**: Fetches real-time weather forecasts from WeatherAPI.com to inform live control decisions and historical weather data from Open-Meteo for simulations.
6.  **Energy Price Simulation**: Includes a simple time-based energy price simulator used by control logic and historical simulation.
7.  **User Interface (Dashboard)**: A web-based dashboard built with Streamlit to monitor live zone statuses, trigger control logic, run historical simulations, and visualize results.

## Core Features Implemented

*   **Multi-Zone Simulation**: Simulates multiple independent heating zones, each with its own temperature dynamics and Modbus slave interface (auto-started).
*   **Modbus TCP Communication**: Utilizes PyModbus for communication between the central server and zone simulators.
*   **Centralized Data Logging**: Sensor data (temperature, occupancy, heater status, target temperature) from zones is logged into an SQL database.
*   **RESTful API**: FastAPI provides endpoints for:
    *   Managing zones (CRUD), including detailed preferences and schedules.
    *   Logging and retrieving sensor data.
    *   Logging and retrieving commands.
    *   Fetching live weather forecasts.
    *   Getting simulated energy prices.
    *   Manually triggering control logic for a zone.
    *   Starting and retrieving historical simulation runs and results.
*   **Automated Control Logic**:
    *   Periodically polls sensor data from all active zones.
    *   Applies per-zone preferences:
        *   Time-based schedules for occupied/unoccupied temperatures.
        *   Default, setback, min/max target temperatures.
        *   Occupancy-based heating control.
    *   Incorporates basic weather adjustments (configurable boost/reduction based on outdoor temperature).
    *   Uses hysteresis for heater control.
    *   Sends new target temperatures/heater states to zones via Modbus.
    *   Logs control commands with context.
*   **WeatherAPI Integration**: Uses a free WeatherAPI key to get real-time and forecast weather data for live control.
*   **Open-Meteo Integration**: Fetches historical weather data for simulations.
*   **Historical Simulation**:
    *   Allows triggering simulations for specific zones and date ranges via API/dashboard.
    *   Runs simulations in background tasks.
    *   Uses historical weather and zone preferences.
    *   Logs detailed results (simulated temp, target temp, heater state, outdoor temp, energy price level) to the database.
    *   Calculates estimated energy usage.
*   **Streamlit Dashboard**: An interactive UI to:
    *   Monitor live zone data (metrics, charts).
    *   View zone configurations and preferences.
    *   Manually trigger live control logic.
    *   Run historical simulations.
    *   List past simulation runs and view their status.
    *   Visualize results of completed historical simulations.
*   **Database Management**: Uses SQLAlchemy for ORM and SQLite for data persistence.
*   **Scheduled Tasks**: APScheduler is used within the FastAPI application for periodic data polling and control logic execution.
*   **Configuration Management**: Uses Pydantic `BaseSettings` and `.env` file for managing secrets (API keys) and configurations.

## Tech Stack

*   **Python 3.13** (as per user's venv)
*   **FastAPI**: For the backend REST API.
*   **Uvicorn**: ASGI server to run FastAPI.
*   **SQLAlchemy**: ORM for database interaction.
*   **Pydantic**: For data validation and settings management.
*   **pydantic-settings**: For loading configuration from `.env`.
*   **PyModbus**: For Modbus TCP client/server implementation.
*   **APScheduler**: For running background tasks (polling, control logic).
*   **Requests**: For making HTTP requests (e.g., to WeatherAPI in dashboard).
*   **python-dotenv**: For loading `.env` file.
*   **Streamlit**: For the web dashboard.
*   **Pandas**: Used in the dashboard for data manipulation.
*   **openmeteo-requests**: Client for fetching historical weather data.
*   **requests-cache**: For caching weather API requests.
*   **retry-requests**: For retrying failed weather API requests.
*   **httpx**: Used internally by `openmeteo-requests` or for async requests.
*   **SQLite**: Default relational database.

## Project Structure

```
building_heating_management_system/
├── scripts/
│   └── (Utility scripts, e.g., historical_weather.py - may be outdated)
├── src/
│   ├── __init__.py
│   ├── config.py             # Pydantic BaseSettings, .env loading
│   ├── database.py           # SQLAlchemy setup, engine, SessionLocal
│   ├── energy_pricer.py      # Simulates time-based energy prices
│   ├── historical_simulator.py # Logic for running historical simulations
│   ├── main.py               # Script to initialize DB tables (if needed manually)
│   ├── models.py             # SQLAlchemy ORM models (Zone, SensorData, Command, HistoricalSim...)
│   ├── schemas.py            # Pydantic schemas for API request/response and preferences
│   ├── server.py             # FastAPI application, API endpoints, scheduler, simulator startup
│   ├── zone_simulator.py     # Class definition for a single zone simulator/Modbus slave
│   ├── modbus_client.py      # Utilities for Modbus master operations (polling/control)
│   ├── weather.py            # WeatherAPI integration for live forecasts
│   └── dashboard.py          # Streamlit dashboard application
├── .env.example              # Example for .env file
├── .gitignore
├── .cache                    # Directory for requests_cache (created automatically)
├── .cache.sqlite             # SQLite file for requests_cache (created automatically)
├── building_management.db    # SQLite database file (created automatically)
├── requirements.txt          # Python dependencies
├── zones_backup.json         # Backup/example zone configuration data
└── README.md                 # This file
```

## Setup and Installation

1.  **Clone the Repository (if applicable)**
    ```bash
    # git clone <repository_url>
    # cd building_heating_management_system
    ```

2.  **Create and Activate a Python Virtual Environment**
    *   It's highly recommended to use a virtual environment.
    ```bash
    python3 -m venv venv
    source venv/bin/activate # On Windows: venv\Scripts\activate
    ```

3.  **Install Dependencies**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Set up WeatherAPI Key**
    *   Sign up for a free API key at [WeatherAPI.com](https://www.weatherapi.com/). This is needed for the live weather adjustments in the control logic.
    *   Create a file named `.env` in the project root directory (`building_heating_management_system/.env`).
    *   Add your API key to the `.env` file like this:
        ```dotenv
        WEATHERAPI_KEY="YOUR_ACTUAL_API_KEY"
        # Optional: Define DATABASE_URL if you want to use a different DB
        # DATABASE_URL="postgresql://user:password@host:port/database"
        ```
    *   An `.env.example` file is provided as a template.

5.  **Database Initialization**
    *   The FastAPI server (`src/server.py`) now automatically creates the database tables on startup using `models.Base.metadata.create_all(bind=engine)`. You do **not** need to run `python -m src.main` anymore.
    *   **VERY IMPORTANT**: If you make changes to the database models (`src/models.py`) that alter table structure (add/remove columns, change types), you **MUST delete the `building_management.db` file** before restarting the server. The server will then recreate the database with the new schema. Failure to do this will likely result in SQLAlchemy errors. For production, consider using migration tools like Alembic.

## Running the System

The system now only requires two main components to be run (the FastAPI server handles starting the simulators). Use separate terminal windows with the virtual environment activated in each.

**1. Start the FastAPI Central Server (includes Zone Simulators)**
*   This starts the main backend application, REST API, scheduler jobs (polling, control), and **automatically starts the Modbus zone simulators** based on zones configured in the database with a `modbus_port`.
    ```bash
    uvicorn src.server:app --reload
    ```
*   The server will be available at `http://127.0.0.1:8000`.
*   API documentation (Swagger UI) will be at `http://127.0.0.1:8000/docs`.
*   You'll see logs indicating the server startup, simulator startup for configured zones, APScheduler jobs running, etc.

**2. Add/Configure Zones via API (One-time setup or as needed)**
*   If starting with an empty database (after deleting `building_management.db`), the server won't poll or control anything until zones are registered.
*   Open your browser to `http://127.0.0.1:8000/docs`.
*   Use the `POST /zones/` endpoint to create zone entries.
    *   Crucially, provide a unique `modbus_port` for each zone you want the server to simulate and interact with (e.g., 5020, 5021, ...).
    *   Provide a `weather_location` (e.g., "City Name", "lat,lon") for weather adjustments and historical simulation.
    *   Provide `latitude` and `longitude` for historical weather fetching.
    *   You can optionally include detailed `preferences`, including a `schedule`. If omitted, defaults will be used.
    *   Example for "Living Room" (port 5020):
        ```json
        {
          "name": "Living Room",
          "weather_location": "London",
          "latitude": 51.5074,
          "longitude": -0.1278,
          "preferences": {
            "default_occupied_temp": 21.5,
            "default_unoccupied_temp": 17.0,
            "min_target_temp": 16.0,
            "max_target_temp": 24.0,
            "use_occupancy_for_heating": true,
            "setback_setpoint": 16.5,
            "allow_weather_adjustment": true,
            "schedule": [
              {"time": "07:00", "occupied_temp": 21.0, "unoccupied_temp": 17.0},
              {"time": "09:00", "occupied_temp": 20.0, "unoccupied_temp": 16.5},
              {"time": "17:00", "occupied_temp": 21.5, "unoccupied_temp": 17.0},
              {"time": "22:00", "occupied_temp": 19.0, "unoccupied_temp": 16.0}
            ]
          },
          "modbus_port": 5020,
          "modbus_host": "localhost"
        }
        ```
    *   After adding zones with ports, **restart the `uvicorn` server**. The `startup_event` will detect these zones and launch their corresponding simulators.

**3. Start the Streamlit Dashboard (Optional)**
*   This provides the web interface to monitor and interact with the system.
    ```bash
    streamlit run src/dashboard.py
    ```
*   Streamlit will typically open the dashboard in your browser automatically, or provide a URL like `http://localhost:8501`.

## How It Works

*   **Central Server Startup (`src/server.py`)**: Reads zones from the DB. For each zone with a `modbus_port`, it instantiates and starts a `ZoneSimulator` thread and its associated Modbus TCP slave server. It also starts the APScheduler jobs.
*   **Zone Simulators (`src/zone_simulator.py`)**: Each instance runs in its own thread, simulating temperature changes based on its internal state (heater on/off, current/target temps, basic thermal model) and occupancy. It updates its Modbus datastore registers periodically.
*   **Polling Job (`src/server.py` via APScheduler)**: Periodically iterates through zones from the database with a `modbus_port`. Uses `src/modbus_client.py` to read registers from the corresponding simulator and logs the data to the `SensorData` table.
*   **Control Logic Job (`src/server.py` via APScheduler)**: Periodically executes `src/control_logic.run_zone_control_logic` for each configured zone:
    1.  Fetches latest sensor data (temp) from the DB.
    2.  Reads current occupancy and heater status directly from the zone simulator via Modbus.
    3.  Fetches live weather forecast if needed (`src/weather.py`).
    4.  Loads zone preferences (`src/schemas.py`).
    5.  Determines the target temperature based on schedule, occupancy, weather adjustments (`src/control_logic.make_control_decision`).
    6.  Determines required heater state using hysteresis.
    7.  If target temp or heater state differs from the current Modbus state, sends update commands via `src/modbus_client.py`.
    8.  Logs commands (`SET_TARGET_TEMP`, `SET_HEATER`) to the `Command` table.
*   **Manual Control Trigger (`POST /zones/{zone_id}/trigger_control_logic`)**: Allows forcing an immediate run of the control logic for a specific zone via the dashboard or API.
*   **Historical Simulation (`src/historical_simulator.py`, API Endpoints)**:
    1.  Triggered via `POST /zones/{zone_id}/historical_simulations/` API call (from dashboard).
    2.  Creates a run record in `HistoricalSimulationRun` table.
    3.  Launches `run_historical_simulation_for_zone` as a background task.
    4.  The background task fetches historical weather (Open-Meteo), steps through time, runs the core control logic (`make_control_decision`) using historical data and simulated state, applies a basic thermal model, and logs results to `HistoricalSimulationDataPoint` table.
    5.  Updates the run status (`PENDING` -> `RUNNING` -> `COMPLETED`/`FAILED`).
    6.  Results can be fetched via `GET` endpoints and viewed on the dashboard.
*   **Modbus Client (`src/modbus_client.py`)**: Contains helper functions for reading/writing specific holding registers used by the simulators.
*   **Database (`src/models.py`, `src/database.py`)**: Stores configuration (zones, preferences), time-series data (sensor readings, commands), and historical simulation results.

## Further Enhancements (Potential Future Work)

*   More sophisticated control algorithms (e.g., PID controllers, advanced predictive control using forecasts).
*   Refining the historical simulation thermal model for better accuracy (e.g., using zone-specific parameters).
*   **UI for Editing Preferences**: Allow editing zone preferences (schedules, thresholds) directly from the dashboard.
*   **User Authentication**: Secure API and dashboard access.
*   **Error Handling/Resilience**: More robust handling of Modbus communication errors, API failures, simulator crashes, etc.
*   **Containerization**: Use Docker for easier setup and deployment.
*   **Advanced UI/UX**: More sophisticated charting (e.g., dual-axis), user feedback, command history details, simulation comparison.
*   **CLI Tool**: A command-line interface for managing zones, checking status, running simulations.
*   **Actual Hardware Integration**: Adapt Modbus communication and control logic for real thermostats/devices.
*   **Unit & Integration Testing**: Implement a formal testing suite (`pytest`).
