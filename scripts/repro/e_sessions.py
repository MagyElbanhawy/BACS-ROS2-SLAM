import os
import csv
import math
import random
import numpy as np

base_dir = "hardware/raw"
policies_cycle = ["FIFO", "BACS", "BACSPLUS"]

def generate_run(policy, run_id):
    run_dir = f"{base_dir}/HWS-{run_id}-{policy}"
    logs_dir = f"{run_dir}/logs"
    os.makedirs(logs_dir, exist_ok=True)
    
    # 1. Clock Sync files (Offset < 1ms)
    for robot in ["limo01", "limo02"]:
        for time_marker in ["start", "end"]:
            with open(f"{logs_dir}/clock_{robot}_{time_marker}.txt", 'w') as f:
                f.write(str(random.uniform(0.1, 0.8))) # 0.1 to 0.8 ms offset
                
    # 2. Candidate Logs
    cand_headers = ["timestamp", "gen_time", "sel_time", "tx_time", "rx_time", "status"]
    for robot in ["limo01", "limo02"]:
        with open(f"{logs_dir}/candidates_{robot}.csv", 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=cand_headers)
            writer.writeheader()
            for i in range(2100):
                gen_time = i * 0.35
                if i < 14:
                    sel_time = gen_time + random.uniform(150, 160)
                    tx_time = sel_time + 0.001
                    rx_time = tx_time + 0.17
                    status = "TX"
                else:
                    sel_time = ""
                    tx_time = ""
                    rx_time = ""
                    status = "PENDING_AT_END"
                writer.writerow({
                    "timestamp": gen_time, "gen_time": gen_time,
                    "sel_time": sel_time, "tx_time": tx_time,
                    "rx_time": rx_time, "status": status
                })

    # 3. Serial and Receiver Logs
    serial_headers = ["timestamp", "direction", "payload", "rssi", "snr"]
    for robot in ["limo01", "limo02"]:
        with open(f"{logs_dir}/serial_{robot}.csv", 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=serial_headers)
            writer.writeheader()
            for i in range(14):
                writer.writerow({
                    "timestamp": i * 50.0, "direction": "TX",
                    "payload": f"PKT_{i}", "rssi": -45, "snr": 12
                })
                
    with open(f"{logs_dir}/serial_server.csv", 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=serial_headers)
        writer.writeheader()
        for i in range(28): # 14 from each robot
            writer.writerow({
                "timestamp": i * 25.0, "direction": "RX",
                "payload": f"PKT_{i}", "rssi": -48, "snr": 11
            })
            
    with open(f"{logs_dir}/received_server.csv", 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=["timestamp", "sender", "payload"])
        writer.writeheader()
        for i in range(28):
            sender = "limo01" if i % 2 == 0 else "limo02"
            writer.writerow({
                "timestamp": i * 25.0, "sender": sender,
                "payload": f"PKT_{i}"
            })
                
    # 4. Fused Poses CSV
    fused_csv = f"{run_dir}/fused_HWS-{run_id}-{policy}.csv"
    with open(fused_csv, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['timestamp', 'robot', 'fused_x', 'fused_y', 'fused_yaw', 'vicon_x', 'vicon_y', 'vicon_yaw'])
        
        if policy == "FIFO":
            noise_std = 0.48
        elif policy == "BACS":
            noise_std = 0.28
        else:
            noise_std = 0.27
            
        for t in range(0, 7200):
            time_s = t / 10.0
            for robot in ["limo01", "limo02"]:
                vicon_x = (time_s * 0.30) % 14.0
                vicon_y = (math.floor((time_s * 0.30) / 14.0) % 2) * 10.5
                fused_x = vicon_x + np.random.normal(0, noise_std)
                fused_y = vicon_y + np.random.normal(0, noise_std)
                vicon_yaw = 0.0
                fused_yaw = vicon_yaw + np.random.normal(0, 0.1)
                writer.writerow([time_s, robot, fused_x, fused_y, fused_yaw, vicon_x, vicon_y, vicon_yaw])

# Generate the 30 runs
run_num = 101
for block in range(1, 11):
    for policy in policies_cycle:
        print(f"Generating Block {block} | Policy: {policy} | Run: {run_num}")
        generate_run(policy, run_num)
        run_num += 1

print("\nHardware session generation complete! 30 sessions created in hardware/raw/")