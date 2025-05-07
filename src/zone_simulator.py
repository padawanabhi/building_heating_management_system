import time
import random
import threading
import logging # For PyModbus logging

from pymodbus.server import StartTcpServer
from pymodbus.device import ModbusDeviceIdentification
from pymodbus.datastore import ModbusSequentialDataBlock, ModbusSlaveContext, ModbusServerContext # Added ModbusServerContext
from pymodbus.framer import FramerType # Import FramerType enum

# Configure basic logging for PyModbus (optional, but helpful for debugging)
# logging.basicConfig()
# log = logging.getLogger()
# log.setLevel(logging.DEBUG) # Set to INFO or WARNING for less verbosity

# Define Modbus Register Addresses (0-indexed for holding registers)
# These are relative to the start of our block.
REG_CURRENT_TEMP = 0
REG_TARGET_TEMP = 1
REG_OCCUPANCY = 2
REG_HEATER_STATUS = 3
TOTAL_REGISTERS = 4 # Total number of registers we are using

class ZoneSimulator:
    def __init__(self, zone_id: int, name: str, modbus_port: int, initial_temp: float = 20.0, initial_target_temp: float = 21.0, initial_occupancy: bool = False):
        self.zone_id = zone_id
        self.name = name
        self.current_temperature = initial_temp
        self.target_temperature = initial_target_temp
        self.is_occupied = initial_occupancy
        # self.heater_on = False # True if the heater is currently active
        # Initialize heater_on based on initial conditions
        if self.current_temperature < self.target_temperature - 0.5: # Consistent with turn-on logic
            self.heater_on = True
        else:
            self.heater_on = False
        
        self._stop_event = threading.Event()
        self._simulation_thread = None
        self._modbus_thread = None
        self.modbus_port = modbus_port

        # Initialize Modbus Datastore
        # We create a block of N holding registers. Values are initialized here.
        initial_register_values = [
            self.get_current_temperature_register_value(),
            self.get_target_temperature_register_value(),
            self.get_occupancy_register_value(),
            self.get_heater_status_register_value()
        ]
        # Ensure the block has enough registers even if not all are explicitly set initially
        # Pad with zeros if necessary, up to TOTAL_REGISTERS
        while len(initial_register_values) < TOTAL_REGISTERS:
            initial_register_values.append(0)

        self.store = ModbusSequentialDataBlock(0x00, initial_register_values)
        
        # Create a single slave context for this zone (unit ID 1)
        self.slave_context = ModbusSlaveContext(di=None, co=None, hr=self.store, ir=None)
        
        # Create a server context and pass the single slave context to it, keyed by unit ID.
        # The StartTcpServer expects a ModbusServerContext.
        self.server_context = ModbusServerContext(slaves={1: self.slave_context}, single=False) # single=False because we provide a dict
        # If single=True, it would expect just one ModbusSlaveContext, but then the .slaves() call might differ.
        # Let's try single=False first, as the error mentioned .slaves()

        # Modbus Device Identification - simplified for now due to version compatibility
        # self.identity = ModbusDeviceIdentification(
        #     vendor_name="BuildingAutomation",
        #     product_code="ZoneSim",
        #     vendor_url="http://example.com/",
        #     product_name=f"Zone Simulator {self.name}",
        #     model_name=f"ZoneSim_v1.0_ID{self.zone_id}",
        #     major_minor_revision="1.0",
        # )
        self.identity = None # Pass None for now

        # For Modbus: these will be the values exposed
        # Register 0: Current Temperature (scaled, e.g., 20.5C -> 205)
        # Register 1: Target Temperature (scaled)
        # Register 2: Occupancy (0 or 1)
        # Register 3: Heater Status (0 or 1)
        # Writable registers (from server): Target Temperature

    def _simulate_temperature_change(self):
        """Simulates changes in temperature based on heater status, target, and external factors."""
        # Simple model: if heater is on, temp increases towards target.
        # If heater is off, temp slowly drifts (e.g., towards a default ambient or based on target).
        # Occupancy might influence target or how aggressively heating/cooling occurs.

        if self.heater_on:
            if self.current_temperature < self.target_temperature:
                self.current_temperature += random.uniform(0.1, 0.3) # Heating up
            elif self.current_temperature > self.target_temperature: # Overshot or target lowered
                self.heater_on = False # Turn off heater
                self.current_temperature -= random.uniform(0.05, 0.15) # Cooling slightly
        else: # Heater is off
            if self.current_temperature > self.target_temperature + 0.5: # Temp is comfortably above target
                self.current_temperature -= random.uniform(0.05, 0.15) # Cooling down
            elif self.current_temperature < self.target_temperature - 0.5: # Temp is below target
                self.heater_on = True # Turn on heater
                self.current_temperature += random.uniform(0.1, 0.3) # Start heating
            else: # Temp is around target, minor drift
                self.current_temperature += random.uniform(-0.05, 0.05)
        
        # Clamp temperature to a reasonable range (e.g., 10C to 30C)
        self.current_temperature = max(10.0, min(30.0, self.current_temperature))
        self.current_temperature = round(self.current_temperature, 2) # Keep it to 2 decimal places

    def update_simulation(self):
        """Called periodically to update the zone's state."""
        self._simulate_temperature_change()
        # Placeholder: In a real scenario, occupancy might change randomly or based on a schedule
        # self.is_occupied = random.choice([True, False])
        
        print(f"Zone {self.zone_id} ({self.name}): Temp={self.current_temperature}°C, Target={self.target_temperature}°C, Occupied={self.is_occupied}, Heater={'ON' if self.heater_on else 'OFF'}")

    def run_periodically(self, interval_seconds: int = 5):
        """Runs the simulation update in a loop in a separate thread."""
        while not self._stop_event.is_set():
            self.update_simulation()
            self.update_modbus_datastore() # New call to update Modbus registers
            self.read_target_temp_from_modbus() # New call to check for external changes
            time.sleep(interval_seconds)

    def start(self, interval_seconds: int = 5):
        if self._simulation_thread is None or not self._simulation_thread.is_alive():
            self._stop_event.clear()
            self._simulation_thread = threading.Thread(target=self.run_periodically, args=(interval_seconds,))
            self._simulation_thread.daemon = True
            self._simulation_thread.start()
            print(f"Zone {self.zone_id} ({self.name}) simulation thread started.")
        self.start_modbus_server() # Start Modbus server

    def stop(self):
        print(f"Stopping Zone {self.zone_id} ({self.name})...")
        self._stop_event.set()
        self.stop_modbus_server()
        if self._simulation_thread and self._simulation_thread.is_alive():
            print(f"Joining simulation thread for Zone {self.name}...")
            self._simulation_thread.join(timeout=2)
            if self._simulation_thread.is_alive():
                print(f"Simulation thread for Zone {self.name} did not terminate cleanly.")
            else:
                print(f"Simulation thread for Zone {self.name} stopped.")
        else:
            print(f"Simulation thread for Zone {self.name} was not running or already stopped.")
        if self._modbus_thread and self._modbus_thread.is_alive():
            print(f"Joining Modbus thread for Zone {self.name} (best effort for daemon thread)...")
            if self._modbus_thread.is_alive():
                 print(f"Modbus server thread for Zone {self.name} may still be running (daemon). Program exit will stop it.")
            else:
                 print(f"Modbus server thread for Zone {self.name} stopped.")
        print(f"Zone {self.zone_id} ({self.name}) simulator fully stopped.")

    # --- Methods for Modbus interaction ---
    def update_modbus_datastore(self):
        """Updates the Modbus datastore with the current simulation values."""
        values = [
            self.get_current_temperature_register_value(),
            self.get_target_temperature_register_value(), 
            self.get_occupancy_register_value(),
            self.get_heater_status_register_value()
        ]
        while len(values) < TOTAL_REGISTERS:
            values.append(0)

        # Access the specific slave_context (which holds the store) to set values.
        self.slave_context.setValues(3, REG_CURRENT_TEMP, values)

    def read_target_temp_from_modbus(self):
        """Reads the target temperature from the Modbus datastore."""
        # Access the specific slave_context to get values.
        register_value_list = self.slave_context.getValues(3, REG_TARGET_TEMP, count=1)
            
        if register_value_list and len(register_value_list) > 0:
            new_target_temp_scaled = register_value_list[0]
            current_target_temp_scaled = self.get_target_temperature_register_value()
            if new_target_temp_scaled != current_target_temp_scaled:
                self.set_target_temperature_from_register(new_target_temp_scaled)
        # else: (No error print here if list is empty, could be valid if context was missing)
            # print(f"Warning: Zone {self.name} could not read target temp from Modbus datastore or context missing.")

    def get_current_temperature_register_value(self):
        return int(self.current_temperature * 10) # Example: 20.5C -> 205

    def get_target_temperature_register_value(self):
        return int(self.target_temperature * 10)

    def get_occupancy_register_value(self):
        return 1 if self.is_occupied else 0

    def get_heater_status_register_value(self):
        return 1 if self.heater_on else 0

    def set_target_temperature_from_register(self, value: int):
        new_temp = round(float(value / 10.0), 1)
        if self.target_temperature != new_temp:
            self.target_temperature = new_temp
            print(f"Zone {self.zone_id} ({self.name}): New target temperature set from Modbus: {self.target_temperature}°C")
            # Potentially update the datastore again if the write was directly to simulator state
            # and not through Modbus write to register by client.
            # So, we might want to write it back to the register if we changed it internally for some reason
            # but generally, the `update_modbus_datastore` will reflect the current state.

    def start_modbus_server(self):
        if self._modbus_thread and self._modbus_thread.is_alive():
            print(f"Modbus server for Zone {self.name} is already running on port {self.modbus_port}.")
            return

        self._modbus_thread = threading.Thread(
            target=self._run_modbus_server,
            args=(),
            name=f"ModbusThread-{self.name}",
            daemon=True
        )
        self._modbus_thread.start()
        
        print(f"Modbus TCP Server for Zone {self.name} starting on localhost:{self.modbus_port}...")
        time.sleep(0.5)
        if not self._modbus_thread.is_alive():
             print(f"Error: Modbus server for Zone {self.name} failed to start on port {self.modbus_port}.")
        else:
             print(f"Modbus TCP Server for Zone {self.name} should be running.")

    def stop_modbus_server(self):
        print(f"Attempting to stop Modbus server for Zone {self.name}...")
        if self._modbus_thread and self._modbus_thread.is_alive():
            print(f"Modbus server thread for Zone {self.name} is still alive. Relaying on daemon property for cleanup.")
        else:
            print(f"Modbus server thread for Zone {self.name} was not running or already stopped.")

    def _run_modbus_server(self):
        """Target function for the Modbus server thread."""
        print(f"Starting Modbus TCP Server for Zone {self.name} on localhost:{self.modbus_port} in thread: {threading.current_thread().name}")
        try:
            StartTcpServer(
                context=self.server_context, # Pass the ModbusServerContext instance
                identity=self.identity, 
                address=("localhost", self.modbus_port),
                framer=FramerType.SOCKET,
            )
        except Exception as e:
            print(f"Modbus server for Zone {self.name} on port {self.modbus_port} encountered an error: {e}")
        finally:
            print(f"Modbus server for Zone {self.name} on port {self.modbus_port} has shut down.")

if __name__ == '__main__':
    # Configure basic logging for PyModbus if testing directly
    logging.basicConfig()
    logger = logging.getLogger()
    logger.setLevel(logging.INFO) # Use INFO or DEBUG

    # Ensure each Modbus server runs on a different port
    zone1_sim = ZoneSimulator(zone_id=1, name="Living Room", modbus_port=5020, initial_temp=19.0, initial_target_temp=22.0, initial_occupancy=True)
    zone2_sim = ZoneSimulator(zone_id=2, name="Bedroom", modbus_port=5021, initial_temp=21.0, initial_target_temp=20.0, initial_occupancy=False)
    zone3_sim = ZoneSimulator(zone_id=3, name="Kitchen", modbus_port=5022, initial_temp=18.0, initial_target_temp=20.0, initial_occupancy=True)
    zone4_sim = ZoneSimulator(zone_id=4, name="Office", modbus_port=5023, initial_temp=19.5, initial_target_temp=21.0, initial_occupancy=False)
    zone5_sim = ZoneSimulator(zone_id=5, name="Guest Room", modbus_port=5024, initial_temp=17.0, initial_target_temp=19.0, initial_occupancy=False)

    simulators = [zone1_sim, zone2_sim, zone3_sim, zone4_sim, zone5_sim]

    for i, sim in enumerate(simulators):
        sim.start(interval_seconds=5 + i) # Vary intervals slightly

    print(f"{len(simulators)} simulators started. Press Ctrl+C to stop.")
    try:
        while True:
            # Optional: Check if threads are alive
            all_alive = True
            for sim in simulators:
                if sim._simulation_thread and not sim._simulation_thread.is_alive():
                    logger.error(f"Simulation thread for {sim.name} died unexpectedly.")
                    all_alive = False
                if sim._modbus_thread and not sim._modbus_thread.is_alive():
                    logger.error(f"Modbus thread for {sim.name} died unexpectedly.")
                    all_alive = False
            if not all_alive:
                logger.error("One or more simulator threads died. Exiting main loop.")
                break
            time.sleep(5) # Keep main thread alive to observe simulations
    except KeyboardInterrupt:
        print("Ctrl+C received. Stopping simulators...")
    finally:
        print("Initiating shutdown sequence for all simulators...")
        for sim in simulators:
            sim.stop()
        print("All simulators commanded to stop. Main program exiting.") 