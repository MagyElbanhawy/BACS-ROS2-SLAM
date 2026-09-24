import serial
import time
import os
import argparse

def calibrate_ok(tx_port, rx_port, count, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    
    print(f"Starting +OK calibration: {count} packets from {tx_port} to {rx_port}")
    tx_ser = serial.Serial(tx_port, 115200, timeout=1)
    rx_ser = serial.Serial(rx_port, 115200, timeout=1)
    time.sleep(1)
    
    results = []
    ok_after_tx_count = 0
    ok_on_accept_count = 0
    
    for i in range(count):
        # Send a test packet via AT command on TX
        msg = f"AT+SEND=0,5,TEST{i:03d}"
        tx_start_time = time.time()
        tx_ser.write((msg + "\r\n").encode())
        
        # Measure when +OK appears on TX
        ok_time = None
        rx_time = None
        
        # Wait for TX +OK and RX data (simplified blocking read for 1 second)
        start_wait = time.time()
        while time.time() - start_wait < 2.0:
            if tx_ser.in_waiting > 0:
                tx_resp = tx_ser.read(tx_ser.in_waiting).decode('utf-8', errors='ignore').strip()
                if "+OK" in tx_resp:
                    ok_time = time.time()
            
            if rx_ser.in_waiting > 0:
                rx_resp = rx_ser.read(rx_ser.in_waiting).decode('utf-8', errors='ignore').strip()
                if "TEST" in rx_resp:
                    rx_time = time.time()
            
            if ok_time and rx_time:
                break
                
        if ok_time and rx_time:
            if ok_time > rx_time:
                ok_after_tx_count += 1
                classification = "OK_AFTER_TRANSMISSION"
            else:
                ok_on_accept_count += 1
                classification = "OK_ON_ACCEPT"
        else:
            classification = "MISSING"
            
        results.append({"packet": i, "ok_time": ok_time, "rx_time": rx_time, "class": classification})
        print(f"Pkt {i}: {classification}")
        
        # V2 protocol says ~18 minutes for 100 packets. 
        # 18 min / 100 pkts = ~10.8 seconds per packet to respect duty cycle.
        time.sleep(10.8) 
        
    tx_ser.close()
    rx_ser.close()
    
    # Determine final classification
    if ok_after_tx_count > count * 0.8:
        final_class = "OK_AFTER_TRANSMISSION"
    elif ok_on_accept_count > count * 0.8:
        final_class = "OK_ON_ACCEPT"
    else:
        final_class = "AMBIGUOUS"
        
    print(f"Calibration Complete. Classification: {final_class}")
    
    with open(os.path.join(out_dir, "calibration_summary.txt"), 'w') as f:
        f.write(f"Total Packets: {count}\n")
        f.write(f"OK_AFTER_TRANSMISSION: {ok_after_tx_count}\n")
        f.write(f"OK_ON_ACCEPT: {ok_on_accept_count}\n")
        f.write(f"Final Classification: {final_class}\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--tx-port", required=True)
    parser.add_argument("--rx-port", required=True)
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    calibrate_ok(args.tx_port, args.rx_port, args.count, args.out)