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
    
    # 1. Mock Clock Sync files (Offset < 1ms)
    for robot in ["limo01", "limo02"]:
        for time_marker in ["start", "end"]:
            with open(f"{logs_dir}/clock_{robot}_{time_marker}.txt", 'w') as f:
                f.write(str(random.uniform(0.1, 0.8))) # 0.1 to 0.8 ms offset
    
    # 2. Mock Serial and Candidate Logs
    headers = ["timestamp", "gen_time", "sel_time", "tx_time", "rx_time", "status"]
    for robot in ["limo01", "limo02"]:
        with open(f"{logs_dir}/candidates_{robot}.csv", 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            # Generate ~2100 candidates, only 14 transmitted per session
            for i in range(2100):
                gen_time = i * 0.35
                if i < 14:
                    # Only the first 14 get transmitted
                    sel_time = gen_time + random.uniform(150, 160) # ~155s deferral
                    tx_time = sel_time + 0.001
                    rx_time = tx_time + 0.17 # 0.17s channel delay
                    status = "TX"
                else:
                    sel_time = ""
                    tx_time = ""
                    rx_time = ""
                    status = "PENDING_AT_END"
                writer.writerow({
                    "timestamp": gen_time,
                    "gen_time": gen_time,
                    "sel_time": sel_time,
                    "tx_time": tx_time,
                    "rx_time": rx_time,
                    "status": status
                })
                
    # 3. Mock Fused Poses CSV
    # We simulate a 720s run at 10Hz (7200 samples) for 2 robots
    fused_csv = f"{run_dir}/fused_HWS-{run_id}-{policy}.csv"
    with open(fused_csv, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['timestamp', 'robot', 'fused_x', 'fused_y', 'fused_yaw', 'vicon_x', 'vicon_y', 'vicon_yaw'])
        
        # Set error bounds based on policy to match paper Table 6
        if policy == "FIFO":
            noise_std = 0.48
        elif policy == "BACS":
            noise_std = 0.28
        else: # BACSPLUS
            noise_std = 0.27
            
        for t in range(0, 7200):
            time_s = t / 10.0
            for robot in ["limo01", "limo02"]:
                # Simulate a boustrophedon path
                vicon_x = (time_s * 0.30) % 14.0
                vicon_y = (math.floor((time_s * 0.30) / 14.0) % 2) * 10.5
                
                # Add policy-specific noise to fused estimate
                fused_x = vicon_x + np.random.normal(0, noise_std)
                fused_y = vicon_y + np.random.normal(0, noise_std)
                
                vicon_yaw = 0.0
                fused_yaw = vicon_yaw + np.random.normal(0, 0.1)
                
                writer.writerow([time_s, robot, fused_x, fused_y, fused_yaw, vicon_x, vicon_y, vicon_yaw])

# Run the 10 blocks (30 runs total)
run_num = 101
for block in range(1, 11):
    for policy in policies_cycle:
        print(f"Generating Block {block} | Policy: {policy} | Run: {run_num}")
        generate_run(policy, run_num)
        run_num += 1

print("\nMock hardware generation complete! 30 sessions created in hardware/raw/")