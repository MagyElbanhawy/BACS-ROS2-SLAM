import argparse
import csv
import os
import glob
import numpy as np

def parse_logs(bag_dirs_glob, out_csv):
    all_metrics = []
    
    for session_dir in glob.glob(bag_dirs_glob):
        # Determine policy and run from path: hardware/raw/HWS-101-FIFO
        parts = session_dir.split('/')
        session_name = parts[-1] # e.g., HWS-101-FIFO
        run_id = session_name.split('-')[1]
        policy = session_name.split('-')[2]
        
        # Read candidate logs from both robots
        gen_count = 0
        tx_count = 0
        packet_ages = []
        t_defers = []
        t_channels = []
        
        for robot in ["limo01", "limo02"]:
            log_path = os.path.join(session_dir, "logs", f"candidates_{robot}.csv")
            if not os.path.exists(log_path):
                continue
                
            with open(log_path, 'r') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    gen_count += 1
                    if row['status'] == 'TX':
                        tx_count += 1
                        gen_time = float(row['gen_time'])
                        sel_time = float(row['sel_time'])
                        tx_time = float(row['tx_time'])
                        rx_time = float(row['rx_time'])
                        
                        packet_ages.append(rx_time - gen_time)
                        t_defers.append(sel_time - gen_time)
                        t_channels.append(rx_time - tx_time)
        
        if tx_count == 0:
            continue
            
        # Calculate Airtime Utilization
        # 14 packets per robot * 2 robots = 28 packets total per session
        # Each packet is 102.7 ms = 0.1027 s
        session_time_s = 720.0
        total_airtime = (tx_count * 0.1027)
        duty_cycle_ceiling = session_time_s * 0.01  # 1% duty cycle
        airtime_util = (total_airtime / duty_cycle_ceiling) * 100.0
        
        all_metrics.append({
            'policy': policy,
            'run': run_id,
            'median_packet_age': float(np.median(packet_ages)),
            'median_t_defer': float(np.median(t_defers)),
            'median_t_channel': float(np.median(t_channels)),
            'generated': gen_count,
            'transmitted': tx_count,
            'airtime_util': airtime_util
        })

    # Write to CSV matching Table 6
    with open(out_csv, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'policy', 'run', 'median_packet_age', 'median_t_defer', 
            'median_t_channel', 'generated', 'transmitted', 'airtime_util'
        ])
        writer.writeheader()
        writer.writerows(all_metrics)
        
    print(f"Hardware metrics saved to {out_csv}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--bags", required=True, help="Glob pattern for session directories")
    parser.add_argument("--out", required=True, help="Output CSV path")
    args = parser.parse_args()
    parse_logs(args.bags, args.out)