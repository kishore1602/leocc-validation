# Get the absolute directory path where this script (run.sh) is located
# So even if you run it from another folder, it still finds files correctly.
DIR=$(cd "$(dirname "$0")"; pwd)

# Which congestion control algorithm to test (here: cubic)
ALG=cubic

# How long the experiment should run (seconds)
RUNNING_TIME=10

# Queue size parameter used later (number of packets in droptail queues)
PACKET_LENGTH=500

# Loss rate to apply on the uplink direction (client -> server) in the emulator
UPLINK_LOSS_RATE=0.002

# Interval (ms) at which delay values are applied/updated from the delay trace
DELAY_INTERVAL=10

# Path to the bandwidth trace file (time-varying bandwidth)
TRACE_BW_PATH=$DIR/bw_example.txt

# Path to the delay trace file (time-varying delay/RTT)
TRACE_DELAY_PATH=$DIR/delay_example.txt


# Start an iperf3 server in daemon mode (runs in background)
# This makes the machine ready to receive iperf3 traffic from a client.
iperf3 -s -D

# Run the "outer" setup script for RUNNING_TIME seconds in background
# outer.sh usually prepares networking / namespaces / client side setup.
bash $DIR/outer.sh $RUNNING_TIME &


# This is the core replay pipeline using Mahimahi + LeoReplayer extensions:

# 1) mm-delay:
#    Applies time-varying delay using TRACE_DELAY_PATH,
#    updating every DELAY_INTERVAL ms.

# 2) mm-loss uplink:
#    Applies packet loss ONLY on uplink direction with rate UPLINK_LOSS_RATE.

# 3) mm-link:
#    Applies time-varying bandwidth using TRACE_BW_PATH.
#    NOTE: It passes the same BW trace twice (one for uplink, one for downlink),
#    meaning both directions use the same bandwidth trace in this example.

# 4) Queue configuration:
#    --uplink-queue droptail with queue length = PACKET_LENGTH packets
#    --downlink-queue droptail with queue length = PACKET_LENGTH packets
#    "droptail" means: when queue is full, new packets are dropped (tail drop).

# 5) Finally runs inner.sh INSIDE the emulated environment:
#    inner.sh is where they run iperf client and set the congestion control ALG.
mm-delay $DELAY_INTERVAL $TRACE_DELAY_PATH mm-loss uplink $UPLINK_LOSS_RATE mm-link $TRACE_BW_PATH $TRACE_BW_PATH \
--uplink-queue droptail --uplink-queue-args packets=$PACKET_LENGTH --downlink-queue droptail --downlink-queue-args packets=$PACKET_LENGTH \
bash $DIR/inner.sh $RUNNING_TIME $ALG


# After the experiment ends, kill iperf processes (cleanup)
pkill iperf
