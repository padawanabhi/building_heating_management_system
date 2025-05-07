from pymodbus.client import ModbusTcpClient
from pymodbus.exceptions import ModbusIOException, ConnectionException
import time

# These should match the definitions in zone_simulator.py
REG_CURRENT_TEMP = 0
REG_TARGET_TEMP = 1
REG_OCCUPANCY = 2
REG_HEATER_STATUS = 3

# Scaling factor used in the simulator
TEMP_SCALING_FACTOR = 10.0

def read_zone_data_from_modbus(host: str, port: int, slave_id: int = 1) -> dict:
    """
    Connects to a Modbus TCP slave (zone simulator) and reads relevant data.

    Args:
        host: The hostname or IP address of the Modbus slave.
        port: The port number of the Modbus slave.
        slave_id: The Modbus slave ID (unit ID).

    Returns:
        A dictionary containing {"temperature": float, "occupancy": bool, "target_temperature": float, "heater_on": bool}
        or {"error": str} if an error occurs.
    """
    client = ModbusTcpClient(host, port=port, timeout=3) # timeout in seconds
    try:
        if not client.connect():
            return {"error": f"Failed to connect to Modbus slave at {host}:{port}"}

        # Read multiple holding registers: current temp, target temp, occupancy, heater status
        # Address = starting register address (0-indexed)
        # Count = number of registers to read
        # Unit = slave ID
        response = client.read_holding_registers(address=REG_CURRENT_TEMP, count=4, slave=slave_id)

        if response.isError():
            return {"error": f"Modbus error reading registers: {response}"}

        if not response.registers or len(response.registers) < 4:
            return {"error": "Modbus response did not contain enough registers"}

        # Register 0: Current Temperature (scaled)
        # Register 1: Target Temperature (scaled)
        # Register 2: Occupancy (0 or 1)
        # Register 3: Heater Status (0 or 1)
        
        current_temp_scaled = response.registers[REG_CURRENT_TEMP]
        target_temp_scaled = response.registers[REG_TARGET_TEMP]
        occupancy_val = response.registers[REG_OCCUPANCY]
        heater_status_val = response.registers[REG_HEATER_STATUS]

        data = {
            "temperature": round(current_temp_scaled / TEMP_SCALING_FACTOR, 2),
            "target_temperature": round(target_temp_scaled / TEMP_SCALING_FACTOR, 2),
            "occupancy": True if occupancy_val == 1 else False,
            "heater_on": True if heater_status_val == 1 else False
        }
        return data

    except ConnectionException as e:
        return {"error": f"Connection exception with Modbus slave at {host}:{port}: {e}"}
    except ModbusIOException as e:
        return {"error": f"Modbus IO exception with slave at {host}:{port}: {e}"}
    except Exception as e:
        return {"error": f"Unexpected error communicating with Modbus slave at {host}:{port}: {e}"}
    finally:
        if client.is_socket_open():
            client.close()

def write_target_temp_to_modbus(host: str, port: int, target_temp: float, slave_id: int = 1) -> dict:
    """
    Connects to a Modbus TCP slave and writes the target temperature.

    Args:
        host: The hostname or IP address of the Modbus slave.
        port: The port number of the Modbus slave.
        target_temp: The target temperature to set.
        slave_id: The Modbus slave ID (unit ID).

    Returns:
        A dictionary {"success": True} or {"error": str}.
    """
    client = ModbusTcpClient(host, port=port, timeout=3)
    try:
        if not client.connect():
            return {"error": f"Failed to connect to Modbus slave at {host}:{port} for writing"}

        scaled_target_temp = int(round(target_temp * TEMP_SCALING_FACTOR))
        
        # Write single holding register: REG_TARGET_TEMP
        # Address = register address (0-indexed)
        # Value = value to write
        # Unit = slave ID
        response = client.write_register(address=REG_TARGET_TEMP, value=scaled_target_temp, slave=slave_id)

        if response.isError():
            return {"error": f"Modbus error writing target temperature: {response}"}
        
        return {"success": True, "message": f"Target temperature {target_temp}°C written to {host}:{port}"}

    except ConnectionException as e:
        return {"error": f"Connection exception writing to Modbus slave at {host}:{port}: {e}"}
    except ModbusIOException as e:
        return {"error": f"Modbus IO exception writing to slave at {host}:{port}: {e}"}
    except Exception as e:
        return {"error": f"Unexpected error writing to Modbus slave at {host}:{port}: {e}"}
    finally:
        if client.is_socket_open():
            client.close()

if __name__ == '__main__':
    # Example Usage (assumes a zone_simulator is running on localhost:5020)
    sim_host = "localhost"
    sim_port_zone1 = 5020
    sim_port_zone2 = 5021 # If you have a second simulator

    print(f"--- Reading data from Zone 1 (Port {sim_port_zone1}) ---")
    zone1_data = read_zone_data_from_modbus(sim_host, sim_port_zone1)
    if "error" in zone1_data:
        print(f"Error reading from Zone 1: {zone1_data['error']}")
    else:
        print(f"Zone 1 Data: {zone1_data}")

    time.sleep(1)

    print(f"\n--- Writing new target temperature to Zone 1 (Port {sim_port_zone1}) ---")
    new_target = 23.5
    write_result = write_target_temp_to_modbus(sim_host, sim_port_zone1, new_target)
    if "error" in write_result:
        print(f"Error writing to Zone 1: {write_result['error']}")
    else:
        print(f"Write to Zone 1 successful: {write_result.get('message')}")

    time.sleep(1)

    print(f"\n--- Reading data again from Zone 1 (Port {sim_port_zone1}) to verify change ---")
    zone1_data_after_write = read_zone_data_from_modbus(sim_host, sim_port_zone1)
    if "error" in zone1_data_after_write:
        print(f"Error reading from Zone 1: {zone1_data_after_write['error']}")
    else:
        print(f"Zone 1 Data after write: {zone1_data_after_write}")
        if zone1_data_after_write.get("target_temperature") == new_target:
            print(f"SUCCESS: Target temperature for Zone 1 correctly updated to {new_target}°C.")
        else:
            print(f"VERIFICATION FAILED: Target temperature for Zone 1 is {zone1_data_after_write.get("target_temperature")}, expected {new_target}°C.")

    # Example for Zone 2 if running
    # print(f"\n--- Reading data from Zone 2 (Port {sim_port_zone2}) ---")
    # zone2_data = read_zone_data_from_modbus(sim_host, sim_port_zone2)
    # if "error" in zone2_data:
    #     print(f"Error reading from Zone 2: {zone2_data['error']}")
    # else:
    #     print(f"Zone 2 Data: {zone2_data}") 