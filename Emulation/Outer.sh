# Get the absolute directory path where this script (outer.sh) is located
# Used to store output files (pcap) in the same folder
DIR=$(cd "$(dirname "$0")"; pwd)

# Continuously wait until the emulated network interface is created
# LeoReplayer / Mahimahi dynamically creates interfaces like: delay-0, delay-1, etc.
while true; do
    # Look for an interface whose name matches "delay-<number>"
    DEV=$(ip -br link | grep -o 'delay-[[:digit:]]*')
    
    # If such an interface exists AND is valid, break out of the loop
    if [ -n "$DEV" ] && ip link show ${DEV} >/dev/null 2>&1; then
        break
    fi
    
    # If not found yet, keep waiting
    echo "Waiting for Network Interface Creation ..."
done

# At this point, the emulated interface has been created
echo "Network Interface Created ..."

# Add a routing rule:
# Route all traffic destined to 100.64.0.0/24 through the emulated interface
# This ensures packets go into the LeoReplayer/Mahimahi network pipeline
ip route add 100.64.0.0/24 dev $DEV

# Start tcpdump on the emulated interface
# -w $DIR/n2.pcap → save packets to n2.pcap
# -s 66           → capture only first 66 bytes (headers only)
# -i $DEV         → capture on the emulated delay interface
# &               → run tcpdump in background
tcpdump -w $DIR/n2.pcap -s 66 -i $DEV &

# Save the process ID (PID) of tcpdump
CAP=$!

# Sleep for the duration of the experiment
# $1 is passed from run.sh as RUNNING_TIME
sleep $1

# Stop tcpdump after the experiment finishes
kill $CAP
