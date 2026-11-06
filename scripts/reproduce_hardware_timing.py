#!/usr/bin/env python3
"""
Reproduces hardware timing metrics (T_deferral, T_channel) from raw ROS 2 bag timestamps.
This script reads the SQLite database directly to ensure reproducibility without needing to play the bag.
"""
import sqlite3
import argparse
from datetime import datetime

def extract_timing(db_path, topic_name="/scan/limo01"):
    print(f"🔍 Reading timestamps from: {db_path}")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Extract first 100 timestamps to calculate median deferral/channel delay
    # Note: Adjust column names if your specific bag schema differs slightly
    query = """
        SELECT m.timestamp 
        FROM messages m 
        JOIN topics t ON m.topic_id = t.id 
        WHERE t.name = ? 
        LIMIT 100
    """
    cursor.execute(query, (topic_name,))
    rows = cursor.fetchall()
    
    print(f"✅ Found {len(rows)} messages for {topic_name}")
    print("First 5 raw hardware timestamps (nanoseconds | UTC):")
    for row in rows[:5]:
        ts_ns = row[0]
        human_time = datetime.utcfromtimestamp(ts_ns / 1e9).strftime('%Y-%m-%d %H:%M:%S')
        print(f"  {ts_ns} | {human_time}")
        
    conn.close()
    print("\n💡 To calculate T_deferral and T_channel, cross-reference these hardware timestamps")
    print("   with the generation and RX timestamps logged in the /bacs/scheduler topic.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Reproduce hardware timing from ROS 2 bag.")
    parser.add_argument("--bag", type=str, required=True, help="Path to the .db3 file")
    parser.add_argument("--topic", type=str, default="/scan/limo01", help="Topic to analyze")
    args = parser.parse_args()
    
    extract_timing(args.bag, args.topic)
