#!/usr/bin/env python3
import os
import glob
import json
import time
import sys

# Ensure pyserial is installed
try:
    import serial
except ImportError:
    print("Installing pyserial...")
    os.system('pip3 install pyserial')
    import serial

def configure_radio(port, address):
    print(f"Configuring RYLR998 on {port} with address {address}...")
    try:
        ser = serial.Serial(port, 115200, timeout=1)
        time.sleep(1)
        
        commands = [
            f"AT+ADDRESS={address}",
            "AT+NETWORKID=18",
            "AT+BAND=868000000",
            "AT+PARAMETER=7,7,1,8",
            "AT+CRFOP=14"
        ]
        
        config = {"port": port, "address": address, "commands": []}
        all_pass = True
        
        for cmd in commands:
            ser.write((cmd + "\r\n").encode())
            time.sleep(0.5)
            response = ser.read(ser.in_waiting).decode('utf-8', errors='ignore').strip()
            print(f"{cmd} -> {response}")
            
            if "+OK" not in response:
                print(f"FAIL: {cmd} did not return +OK")
                all_pass = False
            
            config["commands"].append({"cmd": cmd, "resp": response})
            
        config["status"] = "PASS" if all_pass else "FAIL"
        ser.close()
        return config
        
    except Exception as e:
        print(f"Error configuring {port}: {e}")
        return None

if __name__ == "__main__":
    # 1. Find available ports
    available_ports = glob.glob('/dev/ttyUSB*') + glob.glob('/dev/ttyACM*')
    
    # Define the required radios
    radios = [
        {"name": "limo01", "address": 1, "out_file": "radio_setup_limo01.json"},
        {"name": "limo02", "address": 2, "out_file": "radio_setup_limo02.json"},
        {"name": "server", "address": 100, "out_file": "radio_setup_server.json"}
    ]
    
    # If no ports found, generate mock files (useful for cloud testing)
    if not available_ports:
        print("===================================================================")
        print("WARNING: No physical serial ports (/dev/ttyUSB* or /dev/ttyACM*) found.")
        print("This usually means you are running this in a cloud environment without")
        print("physical hardware plugged in.")
        print("===================================================================")
        print("Generating MOCK radio configuration files so you can test the software pipeline.")
        print("DO NOT use these for final paper data. You need real hardware for that.\n")
        
        for r in radios:
            mock_config = {
                "port": "mock_port",
                "address": r["address"],
                "status": "PASS (MOCK)",
                "commands": [
                    {"cmd": f"AT+ADDRESS={r['address']}", "resp": "+OK"},
                    {"cmd": "AT+NETWORKID=18", "resp": "+OK"},
                    {"cmd": "AT+BAND=868000000", "resp": "+OK"},
                    {"cmd": "AT+PARAMETER=7,7,1,8", "resp": "+OK"},
                    {"cmd": "AT+CRFOP=14", "resp": "+OK"}
                ]
            }
            with open(r["out_file"], 'w') as f:
                json.dump(mock_config, f, indent=2)
            print(f"Created {r['out_file']} (Mock)")
            
        print("\nMock setup complete. You can now proceed with testing the scripts.")
        sys.exit(0)
        
    # If ports are found, try to configure them one by one
    print(f"Found ports: {available_ports}")
    print("Please ensure only ONE radio is plugged in at a time for reliable configuration.")
    
    port_idx = 0
    for r in radios:
        if port_idx >= len(available_ports):
            print(f"Not enough ports found for {r['name']}. Skipping.")
            continue
            
        port = available_ports[port_idx]
        print(f"\nSetting up {r['name']} on {port}...")
        config = configure_radio(port, r["address"])
        
        if config:
            with open(r["out_file"], 'w') as f:
                json.dump(config, f, indent=2)
            print(f"Saved config to {r['out_file']}")
            port_idx += 1
        else:
            print(f"Failed to configure {r['name']}.")