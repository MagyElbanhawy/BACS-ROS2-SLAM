import serial
import time
import sys
import json
import argparse

def setup_rylr998(port, address, out_file):
    print(f"Configuring RYLR998 on {port} with address {address}...")
    try:
        ser = serial.Serial(port, 115200, timeout=1)
        time.sleep(1)
        
        commands = [
            f"AT+ADDRESS={address}",
            "AT+NETWORKID=18",
            "AT+BAND=868000000",
            "AT+PARAMETER=7,7,1,8",  # SF7, BW125kHz, CR 4/5, Preamble 8
            "AT+CRFOP=14"            # 14 dBm
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
        
        with open(out_file, 'w') as f:
            json.dump(config, f, indent=2)
            
        ser.close()
        
        if all_pass:
            print(f"PASS: Configuration saved to {out_file}")
            return True
        else:
            print("FAIL: Radio configuration failed.")
            return False
    except:
        print()
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", required=True)
    parser.add_argument("--address", type=int, required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    setup_rylr998(args.port, args.address, args.out)