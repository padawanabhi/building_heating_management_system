from pymodbus.client import ModbusTcpClient
from pymodbus.exceptions import ModbusIOException, ConnectionException
import time
# from pymodbus.payload import BinaryPayloadDecoder, BinaryPayloadBuilder # Removed deprecated imports
# Remove ModbusDataTypes from import as it's accessed via client instance
from pymodbus.constants import Endian 

# Register Addresses from Simulator (all are single Holding Registers)
SIM_REG_CURRENT_TEMP = 0
SIM_REG_TARGET_TEMP = 1
SIM_REG_OCCUPANCY = 2
SIM_REG_HEATER_STATUS = 3
# Total registers in the simulator block relevant to us for reading in one go might be 4
SIM_TOTAL_REGISTERS_TO_READ = 4 

DEFAULT_MODBUS_PORT = 5020 # Default port if not specified
TEMP_SCALING_FACTOR = 10.0 # As used in simulator

# Custom Exceptions
class ModbusConnectionError(Exception):
    """Custom exception for Modbus connection failures."""
    pass

class ModbusReadError(Exception):
    """Custom exception for Modbus read failures."""
    pass

class ModbusWriteError(Exception):
    """Custom exception for Modbus write failures."""
    pass

# Helper function to handle client connection and closing
def _execute_modbus_operation(host, port, operation_callback):
    effective_port = port if port is not None else DEFAULT_MODBUS_PORT
    client = ModbusTcpClient(host, port=effective_port)
    try:
        if not client.connect():
            raise ModbusConnectionError(f"Failed to connect to Modbus server at {host}:{effective_port}")
        return operation_callback(client)
    except ConnectionException as e: # Catch pymodbus specific connection exception
        raise ModbusConnectionError(f"Modbus connection failed for {host}:{effective_port}: {e}")
    except Exception as e:
        if isinstance(e, (ModbusReadError, ModbusWriteError)):
            raise 
        print(f"An unexpected error occurred during Modbus operation with {host}:{effective_port}: {e}")
        raise 
    finally:
        if client.is_socket_open():
            client.close()

# --- Individual Read Functions (Updated to match simulator's holding registers) ---

def read_current_temperature(host: str, port: int) -> float | None:
    def operation(client):
        rr = client.read_holding_registers(SIM_REG_CURRENT_TEMP, count=1, slave=1)
        if rr.isError():
            raise ModbusReadError(f"Failed to read current temperature (reg {SIM_REG_CURRENT_TEMP}) from {host}:{port}. Error: {rr}")
        scaled_value = rr.registers[0]
        return round(float(scaled_value) / TEMP_SCALING_FACTOR, 2)
    try:
        return _execute_modbus_operation(host, port, operation)
    except (ModbusConnectionError, ModbusReadError) as e:
        print(f"Error in read_current_temperature: {e}")
        return None

def read_target_temperature(host: str, port: int) -> float | None:
    def operation(client):
        rr = client.read_holding_registers(SIM_REG_TARGET_TEMP, count=1, slave=1)
        if rr.isError():
            raise ModbusReadError(f"Failed to read target temperature (reg {SIM_REG_TARGET_TEMP}) from {host}:{port}. Error: {rr}")
        scaled_value = rr.registers[0]
        return round(float(scaled_value) / TEMP_SCALING_FACTOR, 2)
    try:
        return _execute_modbus_operation(host, port, operation)
    except (ModbusConnectionError, ModbusReadError) as e:
        print(f"Error in read_target_temperature: {e}")
        return None

def read_heater_status(host: str, port: int) -> bool | None:
    def operation(client):
        rr = client.read_holding_registers(SIM_REG_HEATER_STATUS, count=1, slave=1)
        if rr.isError():
            raise ModbusReadError(f"Failed to read heater status (reg {SIM_REG_HEATER_STATUS}) from {host}:{port}. Error: {rr}")
        return bool(rr.registers[0]) # 1 is True, 0 is False
    try:
        return _execute_modbus_operation(host, port, operation)
    except (ModbusConnectionError, ModbusReadError) as e:
        print(f"Error in read_heater_status: {e}")
        return None

def read_occupancy_status(host: str, port: int) -> bool | None:
    def operation(client):
        rr = client.read_holding_registers(SIM_REG_OCCUPANCY, count=1, slave=1)
        if rr.isError():
            raise ModbusReadError(f"Failed to read occupancy status (reg {SIM_REG_OCCUPANCY}) from {host}:{port}. Error: {rr}")
        return bool(rr.registers[0]) # 1 is True, 0 is False
    try:
        return _execute_modbus_operation(host, port, operation)
    except (ModbusConnectionError, ModbusReadError) as e:
        print(f"Error in read_occupancy_status: {e}")
        return None

# --- Write Functions (Target Temp to holding register, Heater to holding register) ---

def write_target_temperature(host: str, port: int, temp: float) -> bool:
    def operation(client):
        scaled_value = int(round(temp * TEMP_SCALING_FACTOR))
        # Write a single holding register
        rq = client.write_register(SIM_REG_TARGET_TEMP, scaled_value, slave=1) 
        if rq.isError():
            raise ModbusWriteError(f"Failed to write target temperature to {host}:{port}. Error: {rq}")
        return True
    try:
        return _execute_modbus_operation(host, port, operation)
    except (ModbusConnectionError, ModbusWriteError) as e:
        print(f"Error in write_target_temperature: {e}")
        return False

def write_heater_state(host: str, port: int, state: bool) -> bool:
    # Note: The simulator primarily controls its own heater_on state based on its logic.
    # Writing heater state directly might conflict or be overridden by the simulator.
    # However, if the simulator were designed to accept external heater commands via a register, this would be how.
    # Let's assume for now that the simulator's REG_HEATER_STATUS is *readable* but not typically *writable* by client,
    # as the simulator manages it. If it needs to be writable, the simulator logic would need to accommodate that.
    # For now, let's make this write to the holding register as if it were supported.
    def operation(client):
        value = 1 if state else 0
        rq = client.write_register(SIM_REG_HEATER_STATUS, value, slave=1)
        if rq.isError():
            raise ModbusWriteError(f"Failed to write heater state to {host}:{port}. Error: {rq}")
        return True
    try:
        return _execute_modbus_operation(host, port, operation)
    except (ModbusConnectionError, ModbusWriteError) as e:
        print(f"Error in write_heater_state: {e}")
        return False

# Combined function to read all relevant data for SensorData table or control logic initial state
def read_zone_data_from_modbus(host: str, port: int) -> dict:
    """
    Reads current temperature, target temperature, heater status, and occupancy 
    from a zone's holding registers, matching the simulator's setup.
    Returns a dictionary with the data or an error key.
    """
    data = {}
    effective_port = port if port is not None else DEFAULT_MODBUS_PORT
    client = ModbusTcpClient(host, port=effective_port)
    try:
        if not client.connect():
            raise ModbusConnectionError(f"Failed to connect to Modbus server at {host}:{effective_port} for read_zone_data")

        # Read a block of 4 holding registers starting from SIM_REG_CURRENT_TEMP (address 0)
        # This covers CurrentTemp, TargetTemp, Occupancy, HeaterStatus
        rr = client.read_holding_registers(SIM_REG_CURRENT_TEMP, count=SIM_TOTAL_REGISTERS_TO_READ, slave=1)
        if rr.isError():
            raise ModbusReadError(f"Modbus error reading block of registers: {rr}")
        
        if len(rr.registers) < SIM_TOTAL_REGISTERS_TO_READ:
            raise ModbusReadError(f"Modbus read returned too few registers. Expected {SIM_TOTAL_REGISTERS_TO_READ}, got {len(rr.registers)}")

        # Extract and process values based on their known positions and scaling
        data["temperature"] = round(float(rr.registers[SIM_REG_CURRENT_TEMP]) / TEMP_SCALING_FACTOR, 2) # Index 0
        data["target_temperature"] = round(float(rr.registers[SIM_REG_TARGET_TEMP]) / TEMP_SCALING_FACTOR, 2) # Index 1
        data["occupancy"] = bool(rr.registers[SIM_REG_OCCUPANCY]) # Index 2
        data["heater_on"] = bool(rr.registers[SIM_REG_HEATER_STATUS]) # Index 3
        
        return data
    
    except ModbusConnectionError as e:
        print(f"Modbus Connection Error in read_zone_data_from_modbus for {host}:{effective_port}: {e}")
        return {"error": str(e), "details": "Connection failed"}
    except ModbusReadError as e:
        print(f"Modbus Read Error in read_zone_data_from_modbus for {host}:{effective_port}: {e}")
        return {"error": str(e), "details": "Read operation failed"}
    except IndexError as e: # Catch if we try to access a register index that wasn't returned
        print(f"Modbus Read Error (IndexError) in read_zone_data_from_modbus for {host}:{effective_port}: {e}. Likely too few registers returned.")
        return {"error": str(e), "details": "Not enough registers returned from read operation"}
    except Exception as e:
        print(f"Unexpected error in read_zone_data_from_modbus for {host}:{effective_port}: {e}")
        return {"error": str(e), "details": "Unexpected failure"}
    finally:
        if client.is_socket_open():
            client.close()

if __name__ == '__main__':
    # Example Usage (assumes a zone_simulator is running on localhost:5020)
    sim_host = "localhost"
    sim_port_zone1 = DEFAULT_MODBUS_PORT 

    print(f"--- Reading data from Zone 1 (Port {sim_port_zone1}) --- ({time.time()})")
    zone1_data = read_zone_data_from_modbus(sim_host, sim_port_zone1)
    if "error" in zone1_data:
        print(f"Error reading from Zone 1: {zone1_data['error']}")
    else:
        print(f"Zone 1 Data: {zone1_data}")

    time.sleep(1)

    print(f"\n--- Writing new target temperature to Zone 1 (Port {sim_port_zone1}) --- ({time.time()})")
    new_target = 23.5
    write_result_flag = write_target_temperature(sim_host, sim_port_zone1, new_target)
    if not write_result_flag:
        print(f"Error writing to Zone 1 (returned False)")
    else:
        print(f"Write Target Temp ({new_target}) to Zone 1 successful (returned True)")

    time.sleep(1)

    print(f"\n--- Reading data again from Zone 1 (Port {sim_port_zone1}) to verify change --- ({time.time()})")
    zone1_data_after_write = read_zone_data_from_modbus(sim_host, sim_port_zone1)
    if "error" in zone1_data_after_write:
        print(f"Error reading from Zone 1: {zone1_data_after_write['error']}")
    else:
        print(f"Zone 1 Data after write: {zone1_data_after_write}")
        if abs(zone1_data_after_write.get("target_temperature", 999) - new_target) < 0.01:
            print(f"SUCCESS: Target temperature for Zone 1 correctly updated to {new_target}°C.")
        else:
            print(f"VERIFICATION FAILED: Target temperature for Zone 1 is {zone1_data_after_write.get('target_temperature')}, expected {new_target}°C.")

    print(f"\n--- Toggling heater state (example, may be overridden by sim) --- ({time.time()})")
    # Read current heater state first
    current_heater_state = read_heater_status(sim_host, sim_port_zone1)
    if current_heater_state is not None:
        print(f"Current heater state: {current_heater_state}")
        write_heater_result = write_heater_state(sim_host, sim_port_zone1, not current_heater_state)
        print(f"Attempted to write heater state to '{not current_heater_state}': {'Success' if write_heater_result else 'Failed'}")
        time.sleep(0.5)
        new_heater_state = read_heater_status(sim_host, sim_port_zone1)
        print(f"New heater state after write attempt: {new_heater_state}")
    else:
        print("Could not read current heater state to toggle.")

    print(f"\n--- Reading occupancy status (example) --- ({time.time()})")
    occupancy = read_occupancy_status(sim_host, sim_port_zone1)
    if occupancy is not None:
        print(f"Zone 1 Occupancy: {occupancy}")
    else:
        print("Could not read Zone 1 occupancy.") 