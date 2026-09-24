#!/bin/bash

# Enforces V2 Protocol: 10 blocks, 3 policies rotating, 720s per run.
# Usage: ./run_v2_experiment.sh <BLOCK_NUMBER> <POLICY> <RUN_NUM>
# Example: ./run_v2_experiment.sh 1 FIFO 1

BLOCK=$1
POLICY=$2
RUN_NUM=$3
SESSION_ID="HWS-$(printf "%03d" $((100 + RUN_NUM)))-${POLICY}"
RUN_DIR="hardware/raw/${SESSION_ID}"
BAG_NAME="${SESSION_ID}_run${RUN_NUM}"

mkdir -p $RUN_DIR/logs

echo "=================================================="
echo "Starting Block $BLOCK | Policy: $POLICY | Run: $RUN_NUM"
echo "Session ID: $SESSION_ID"
echo "=================================================="

# 1. Start recording the bag on the Fusion Server
ros2 bag record -s mcap -o $RUN_DIR/$BAG_NAME \
    /tf /tf_static \
    /scan/limo01 /scan/limo02 \
    /odom/limo01 /odom/limo02 \
    /vicon/limo01/pose /vicon/limo02/pose \
    /bacs/candidates \
    /bacs/scheduler \
    /bacs/received \
    /bacs/keyframes \
    /bacs/kf_desc \
    /bacs/kf_request \
    /map &

BAG_PID=$!
echo "Bag recording started with PID $BAG_PID"

# 2. Start the Fused Poses Logger
python3 scripts/repro/log_fused_poses.py \
    --ros-args -p session:=${SESSION_ID} -p out:=${RUN_DIR}/fused_${SESSION_ID}.csv &

LOG_PID=$!

# 3. Start the 720-second timer
echo "Robots driving for 720 seconds (12 minutes)..."
sleep 720

# 4. Stop in reverse order (Senders first, as per V2 protocol)
echo "720s elapsed. Stopping run. Marking pending candidates as PENDING_AT_END."
kill -INT $BAG_PID
kill -INT $LOG_PID
wait $BAG_PID $LOG_PID

echo "Run $RUN_NUM complete. Data saved to $RUN_DIR."