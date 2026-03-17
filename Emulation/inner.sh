# Get the absolute directory path where this script (inner.sh) is located
# This helps save output files (pcap) in the same directory reliably
DIR=$(cd "$(dirname "$0")"; pwd)

# Name of the network interface to capture packets from
# "ingress" is a virtual interface created by Mahimahi / LeoReplayer
# It represents packets entering the emulated network
DEV=ingress

# Start tcpdump to capture packets on the ingress interface
# -i $DEV     → capture on ingress interface
# -s 66       → capture only first 66 bytes of each packet (headers only, saves space)
# -w $DIR/n1.pcap → write captured packets to n1.pcap in the same directory
# &            → run tcpdump in background so the script can continue
tcpdump -i $DEV -s 66 -w $DIR/n1.pcap &

# Store the process ID (PID) of the background tcpdump command
# $! gives the PID of the last background process
CAP=$!

# Run iperf3 client inside the emulated network
# -c 100.64.0.1 → connect to iperf server at this IP (server side inside Mahimahi)
# -C $2         → use congestion control algorithm passed as second argument
#                 (e.g., cubic, bbr, leocc)
# -t $1         → run iperf for $1 seconds (first argument)
#
# In run.sh, this script is called as:
#   bash inner.sh RUNNING_TIME ALG
# So:
#   $1 = RUNNING_TIME
#   $2 = ALG
iperf3 -c 100.64.0.1 -C $2 -t $1

# After iperf finishes, stop tcpdump
# Uses the saved PID to kill only this tcpdump process
kill $CAP
