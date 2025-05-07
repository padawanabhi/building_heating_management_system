# Building-Level Heating Management System Simulation

This project simulates a multi-zone heating management platform for a small building, demonstrating end-to-end functionality from virtual thermostats to a central service for data logging, control, and basic optimization.

## System Architecture

The system follows a multi-layer design:

1.  **Zone Simulators**: Multiple Python processes, each representing a virtual thermostat/heating zone. They simulate temperature changes and occupancy status.
2.  **Communication Layer**: Modbus TCP is used for real-time data exchange between the zone simulators (acting as Modbus slaves) and the central server (acting as a Modbus master).
3.  **Central Server**: A Python-based web service built with FastAPI. It:
    *   Periodically polls data (current temperature, occupancy, actual target temperature) from all configured zone simulators via Modbus.
    *   Logs this sensor data into an SQL database.
    *   Applies control logic (e.g., adjusting setpoints based on occupancy, weather forecasts).
    *   Sends commands (new target temperatures) back to zone simulators via Modbus.
    *   Exposes a REST API for status queries, data retrieval, and manual control actions.
4.  **Data Management**: A relational database (SQLite by default) stores time-series sensor data, zone configurations, and system commands. SQLAlchemy is used as the ORM.
5.  **Weather Integration**: Fetches weather forecasts from WeatherAPI.com to inform control decisions.
6.  **User Interface (Dashboard)**: A simple web-based dashboard built with Streamlit to monitor zone statuses, view historical data, and observe system behavior.

## Core Features Implemented

*   **Multi-Zone Simulation**: Simulates 5 independent heating zones, each with its own temperature dynamics and Modbus slave interface.
*   **Modbus TCP Communication**: Utilizes PyModbus for communication between the central server and zone simulators.
*   **Centralized Data Logging**: Sensor data (temperature, occupancy) from zones is logged into an SQL database.
*   **RESTful API**: FastAPI provides endpoints for:
    *   Managing zones (CRUD).
    *   Logging and retrieving sensor data.
    *   Logging and retrieving commands.
    *   Fetching weather forecasts.
*   **Automated Control Logic**:
    *   Periodically polls sensor data from all active zones.
    *   Adjusts zone target temperatures based on:
        *   Occupancy status (using different setpoints for occupied/unoccupied states).
        *   Current external weather conditions (e.g., reducing heating if a_is_day is warm).
    *   Sends new target temperatures to zones via Modbus.
    *   Logs control commands.
*   **WeatherAPI Integration**: Uses a free WeatherAPI key to get real-time and forecast weather data.
*   **Streamlit Dashboard**: A basic UI to visualize zone data, sensor readings, and commands.
*   **Database Management**: Uses SQLAlchemy for ORM and SQLite for data persistence. Includes a script to initialize the database schema.
*   **Scheduled Tasks**: APScheduler is used within the FastAPI application for periodic data polling and control logic execution.

## Tech Stack

*   **Python 3.13** (as per user's venv)
*   **FastAPI**: For the backend REST API.
*   **Uvicorn**: ASGI server to run FastAPI.
*   **SQLAlchemy**: ORM for database interaction.
*   **Pydantic**: For data validation and settings management.
*   **PyModbus**: For Modbus TCP client/server implementation.
*   **APScheduler**: For running background tasks (polling, control logic).
*   **Requests**: For making HTTP requests to the WeatherAPI.
*   **python-dotenv**: For managing environment variables (like API keys).
*   **Streamlit**: For the simple web dashboard.
*   **SQLite**: Default relational database.

## Project Structure

```
building_heating_management_system/
├── src/
│   ├── __init__.py
│   ├── config.py         # Handles .env loading and configuration
│   ├── database.py       # SQLAlchemy setup, engine, SessionLocal
│   ├── main.py           # Script to initialize DB tables
│   ├── models.py         # SQLAlchemy ORM models (Zone, SensorData, Command)
│   ├── schemas.py        # Pydantic schemas for API request/response
│   ├── server.py         # FastAPI application, API endpoints, scheduler
│   ├── zone_simulator.py # Simulates multiple zones as Modbus slaves
│   ├── modbus_client.py  # Utilities for Modbus master operations
│   ├── weather.py        # WeatherAPI integration
│   └── dashboard.py      # Streamlit dashboard application
├── .env.example          # Example for .env file
├── .gitignore
├── building_management.db # SQLite database file (created automatically)
├── requirements.txt      # Python dependencies
└── README.md             # This file
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
    source venv/bin/activate  # On Windows: venv\Scripts\activate
    ```

3.  **Install Dependencies**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Set up WeatherAPI Key**
    *   Sign up for a free API key at [WeatherAPI.com](https://www.weatherapi.com/).
    *   Create a file named `.env` in the project root directory (`building_heating_management_system/.env`).
    *   Add your API key to the `.env` file like this:
        ```
        WEATHERAPI_KEY="YOUR_ACTUAL_API_KEY"
        ```
    *   An `.env.example` file is provided as a template.

5.  **Initialize the Database**
    *   This step creates the necessary tables in the SQLite database based on the models defined in `src/models.py`.
    *   **Important**: If you make changes to the database models (`src/models.py`) later, you may need to delete the `building_management.db` file and re-run this command to reflect schema changes.
    ```bash
    python -m src.main
    ```

## Running the System

The system consists of three main components that need to be run, typically in separate terminal windows (with the virtual environment activated in each).

**1. Start the Zone Simulators**
*   This script starts multiple simulated heating zones, each running a Modbus TCP slave server on a unique port (5020-5024 by default).
    ```bash
    python -m src.zone_simulator
    ```
*   You should see output indicating that the simulators and their Modbus servers have started.

**2. Start the FastAPI Central Server**
*   This starts the main backend application, including the REST API, data polling scheduler, and control logic scheduler.
    ```bash
    uvicorn src.server:app --reload
    ```
*   The server will be available at `http://127.0.0.1:8000`.
*   API documentation (Swagger UI) will be at `http://127.0.0.1:8000/docs`.
*   You'll see logs from the server, including APScheduler jobs polling data and applying control logic.

**3. Add Zones to the System via API (One-time setup after DB initialization)**
*   Before the central server can poll or control zones, it needs to know about them. You must register the simulated zones in the database using the API.
*   Open your browser to `http://127.0.0.1:8000/docs`.
*   Use the `POST /zones/` endpoint to create entries for each zone defined in `src/zone_simulator.py`. Ensure the `modbus_port` in your API request matches the port used by the corresponding simulator.
    *   Example for "Living Room" (port 5020):
        ```json
        {
          "name": "Living Room",
          "preferences": {"occupied_temp": 22.0, "unoccupied_temp": 17.0},
          "modbus_port": 5020,
          "modbus_host": "localhost"
        }
        ```
    *   Add entries similarly for "Bedroom" (5021), "Kitchen" (5022), "Office" (5023), and "Guest Room" (5024), or as defined in your simulator.

**4. Start the Streamlit Dashboard (Optional)**
*   This provides a web interface to monitor the system.
    ```bash
    streamlit run src/dashboard.py
    ```
*   Streamlit will typically open the dashboard in your browser automatically, or provide a URL like `http://localhost:8501`.

## How It Works

*   **Zone Simulators (`src/zone_simulator.py`)**: Each instance simulates temperature changes based on its current state (heater on/off, current temperature, target temperature). It runs a Modbus TCP server (slave) exposing registers for:
    *   Current Temperature (read-only by master)
    *   Target Temperature (read/write by master)
    *   Occupancy Status (read-only by master)
    *   Heater Status (read-only by master)
*   **Central Server (`src/server.py`)**:
    *   **Polling Job (APScheduler)**: Periodically iterates through zones registered in the database (that have a `modbus_port`). For each zone, it uses `src/modbus_client.py` to connect to the zone's Modbus server, read its registers (current temp, occupancy), and saves this data to the `SensorData` table.
    *   **Control Logic Job (APScheduler)**: Periodically:
        1.  Fetches all zones.
        2.  For each zone, gets its latest recorded occupancy from the database.
        3.  Fetches a weather forecast using `src/weather.py`.
        4.  Applies rules to determine an ideal target temperature (e.g., lower for unoccupied zones, adjust based on high outside temperatures).
        5.  Reads the *actual current target temperature* from the zone's Modbus device.
        6.  If the ideal target differs significantly from the device's current target, it uses `src/modbus_client.py` to write the new ideal target temperature to the zone's Modbus `REG_TARGET_TEMP` register.
        7.  Logs this control action as a `Command` in the database.
*   **Modbus Client (`src/modbus_client.py`)**: Contains helper functions for the central server to act as a Modbus master to read from and write to the zone simulators.
*   **Database (`src/models.py`, `src/database.py`)**: Stores persistent information about zones, their sensor readings over time, and commands issued by the control system.

## Further Enhancements (Potential Future Work)

*   More sophisticated control algorithms (e.g., PID controllers, predictive control based on weather forecasts and thermal models).
*   Integration of energy pricing for cost optimization.
*   User authentication for API and dashboard.
*   More detailed zone preferences and scheduling (e.g., different setpoints for different times of day).
*   Error handling and resilience improvements.
*   Containerization using Docker for easier deployment.
*   A more advanced web UI with interactive controls.
*   Command-Line Interface (CLI) for system administration and quick checks.
