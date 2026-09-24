import os
import sys
import glob
import argparse

def validate_session(session_dir):
    print(f"Validating session in {session_dir}...")
    errors = []
    
    # 1. Check clock offset files
    clock_files = [
        "clock_limo01_start.txt", "clock_limo01_end.txt",
        "clock_limo02_start.txt", "clock_limo02_end.txt"
    ]
    
    for cf in clock_files:
        fpath = os.path.join(session_dir, "logs", cf)
        if not os.path.exists(fpath):
            errors.append(f"Missing clock file: {fpath}")
            continue
            
        with open(fpath, 'r') as f:
            try:
                offset = float(f.read().strip())
                if abs(offset) > 1.0: # 1 ms requirement
                    errors.append(f"Clock offset > 1ms in {cf}: {offset}ms")
            except ValueError:
                errors.append(f"Invalid clock offset format in {cf}")
                
    # 2. Check required logs
    required_logs = [
        "candidates_limo01.csv", "candidates_limo02.csv",
        "serial_limo01.csv", "serial_limo02.csv", "serial_server.csv",
        "received_server.csv"
    ]
    
    for log in required_logs:
        if not os.path.exists(os.path.join(session_dir, "logs", log)):
            errors.append(f"Missing required log: {log}")
            
    # 3. Check fused poses CSV
    fused_files = glob.glob(os.path.join(session_dir, "fused_*.csv"))
    if len(fused_files) == 0:
        errors.append("Missing fused poses CSV file.")
        
    if errors:
        print("VALIDATION FAILED:")
        for e in errors:
            print(f" - {e}")
        return False
    else:
        print("VALIDATION PASSED.")
        return True

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", required=True, help="Session directory to validate")
    args = parser.parse_args()
    
    if not validate_session(args.dir):
        sys.exit(1)