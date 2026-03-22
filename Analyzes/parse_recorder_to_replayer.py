#!/usr/bin/env python3
"""
parse_recorder_to_replayer.py
==============================
Convert LeoRecorder outputs to LeoReplayer trace format.

This script converts raw pcap and ping data from the field trip recorder
into the bandwidth and delay trace files used by LeoReplayer.

Changes from original (based on Sizhe's suggestions):
    1. Use math.floor() for slot assignment — receive timestamp floored to
       nearest 10ms boundary. RTT at 16ms → slot 1 (0-10ms), 22ms → slot 2 etc.
    2. Multiple pings in same slot → averaged into one value
    3. Empty slots → carry forward last known RTT value instead of 200ms
       since mm-loss shell already handles packet loss simulation

Input:
    - Trimmed ICMP ping log file (from trim_common_window.py)
    - UDP pcap file (client side for downlink, server side for uplink)

Output:
    - bw_{trace_id}.txt  : Bandwidth trace (mahimahi packet timestamps)
    - delay_{trace_id}.txt: Delay trace (one-way delay per 10ms interval)

Usage:
    python parse_recorder_to_replayer.py \\
        --ping_file trimmed_traces/trace_id/icmp_dl_trimmed.log \\
        --pcap_file client/trace_id/udp_dl_client*.pcap \\
        --output_dir ./output/trace_id/downlink \\
        --trace_id 1
"""

import argparse
import math
import os
import re
import subprocess
from collections import defaultdict

# ── DEFAULT CONFIG ─────────────────────────────────────────────────────────────
# Mahimahi delay interval confirmed from run.sh: DELAY_INTERVAL=10
DEFAULT_DELAY_INTERVAL_MS = 10

# Default delay for the very first slot if no ping data available at all
# Only used as last resort — carry forward handles all other empty slots
DEFAULT_DELAY_MS = 200

# Mbps represented by each line in bandwidth trace
MBPS_PER_LINE = 12


def parse_ping_to_delay(ping_file: str, output_file: str,
                        delay_interval_ms: int = DEFAULT_DELAY_INTERVAL_MS,
                        default_delay_ms: int = DEFAULT_DELAY_MS) -> dict:
    """
    Convert ping RTT output to delay trace format.

    Slot assignment (Sizhe's suggestion):
        - Use math.floor() on receive timestamp to assign to 10ms slot
        - RTT at 16ms → floor(16/10) = slot 1 (0-10ms)
        - RTT at 22ms → floor(22/10) = slot 2 (10-20ms)
        - Multiple pings in same slot → simple average

    Empty slot handling:
        - Copy last known RTT value (carry forward)
        - This is valid since mm-loss shell handles actual packet loss

    Args:
        ping_file         : Path to trimmed ICMP ping log file
        output_file       : Path to output delay trace file
        delay_interval_ms : Mahimahi slot size in ms (default: 10)
        default_delay_ms  : Fallback value only if no prior ping data (default: 200)

    Returns:
        dict with conversion statistics
    """
    # Pattern matches: [1770506568.318547] ... time=24.5 ms
    pattern = re.compile(r'\[(\d+\.\d+)\].*time=(\d+\.?\d*)\s*ms')

    rtt_samples = []  # list of (timestamp, rtt_ms)

    with open(ping_file, 'r') as f:
        for line in f:
            match = pattern.search(line)
            if match:
                timestamp = float(match.group(1))
                rtt_ms    = float(match.group(2))
                rtt_samples.append((timestamp, rtt_ms))

    if not rtt_samples:
        raise ValueError(f"No valid ping samples found in {ping_file}")

    # Get time range from actual ping data
    start_time  = rtt_samples[0][0]
    end_time    = rtt_samples[-1][0]
    duration_ms = int((end_time - start_time) * 1000)

    # Group RTT samples by 10ms slot using floor on receive timestamp
    # floor(16ms / 10ms) = slot 1, floor(22ms / 10ms) = slot 2 etc.
    interval_rtts = defaultdict(list)
    for timestamp, rtt_ms in rtt_samples:
        interval_idx = math.floor((timestamp - start_time) * 1000 / delay_interval_ms)
        interval_rtts[interval_idx].append(rtt_ms)

    # Calculate one-way delay for each interval
    # No tail padding — only write intervals within actual measurement window
    num_intervals = duration_ms // delay_interval_ms + 1

    delays = []
    for i in range(num_intervals):
        if i in interval_rtts:
            # Average all RTT values in this slot, divide by 2 for one-way delay
            avg_rtt      = sum(interval_rtts[i]) / len(interval_rtts[i])
            one_way_delay = int(round(avg_rtt / 2))
        else:
            # Empty slot — carry forward last known RTT value
            # mm-loss shell already handles packet loss simulation
            one_way_delay = delays[-1] if delays else default_delay_ms
        delays.append(one_way_delay)

    # Write output — one integer per line
    with open(output_file, 'w') as f:
        for delay in delays:
            f.write(f"{delay}\n")

    stats = {
        'ping_samples' : len(rtt_samples),
        'duration_sec' : round(end_time - start_time, 2),
        'intervals'    : len(delays),
        'avg_delay_ms' : round(sum(delays) / len(delays), 2),
        'min_delay_ms' : min(delays),
        'max_delay_ms' : max(delays),
    }
    return stats


def parse_pcap_to_bandwidth(pcap_file: str, output_file: str,
                             mbps_per_line: int = MBPS_PER_LINE) -> dict:
    """
    Convert pcap file to mahimahi bandwidth trace format.

    Each line in the output = one delivery opportunity of ~12 Mbps.
    Multiple lines with same timestamp = higher bandwidth at that moment.

    Uses tcpdump to parse pcap. Only counts incoming packets (In direction)
    since we measure received bandwidth at receiver side.

    Args:
        pcap_file    : Path to pcap file (client for downlink, server for uplink)
        output_file  : Path to output bandwidth trace file
        mbps_per_line: Mbps per bandwidth trace line (default: 12)

    Returns:
        dict with conversion statistics
    """
    cmd = ['tcpdump', '-tt', '-n', '-r', pcap_file]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"tcpdump failed: {e.stderr}")
    except FileNotFoundError:
        raise RuntimeError("tcpdump not found. Please install tcpdump.")

    # Match only incoming packets in our pcap format:
    # 1770506568.420200 ?     In  IP 15.181.162.149.5201 > ... UDP, length 1448
    pattern = re.compile(r'^(\d+\.\d+)\s+\S+\s+In\s+IP.*length\s+(\d+)')
    packets = []  # list of (timestamp, length)
    for line in result.stdout.split('\n'):
        match = pattern.match(line)
        if match:
            timestamp = float(match.group(1))
            length    = int(match.group(2))
            packets.append((timestamp, length))

    if not packets:
        raise ValueError(f"No valid UDP packets found in {pcap_file}")

    # Get time range
    start_time  = packets[0][0]
    end_time    = packets[-1][0]
    duration_ms = int((end_time - start_time) * 1000)

    # Group bytes by millisecond offset
    bytes_per_ms = defaultdict(int)
    for timestamp, length in packets:
        ms_offset = int((timestamp - start_time) * 1000)
        bytes_per_ms[ms_offset] += length

    # Convert to mahimahi packet timestamp format
    # Each line = 12 Mbps = 1500 bytes/ms
    bytes_per_line = (mbps_per_line * 1_000_000) // 8 // 1000

    bw_lines    = []
    total_bytes = 0

    for ms in range(duration_ms + 1):
        if ms in bytes_per_ms:
            bytes_this_ms = bytes_per_ms[ms]
            total_bytes  += bytes_this_ms
            num_lines     = max(1, bytes_this_ms // bytes_per_line)
            for _ in range(num_lines):
                bw_lines.append(ms)

    # Write output — one timestamp per line
    with open(output_file, 'w') as f:
        for ms in bw_lines:
            f.write(f"{ms}\n")

    avg_bw_mbps = (total_bytes * 8) / (duration_ms * 1000) if duration_ms > 0 else 0

    stats = {
        'packets'           : len(packets),
        'total_bytes'       : total_bytes,
        'duration_sec'      : round(end_time - start_time, 2),
        'bw_lines'          : len(bw_lines),
        'avg_bandwidth_mbps': round(avg_bw_mbps, 2),
    }
    return stats


def main():
    parser = argparse.ArgumentParser(
        description='Convert LeoRecorder outputs to LeoReplayer trace format',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('--ping_file',  required=True,
                        help='Path to trimmed ICMP ping log file')
    parser.add_argument('--pcap_file',  required=True,
                        help='Path to pcap file (client for DL, server for UL)')
    parser.add_argument('--output_dir', default='./output',
                        help='Output directory for trace files (default: ./output)')
    parser.add_argument('--trace_id',   type=int, default=1,
                        help='Trace ID for output filenames (default: 1)')
    parser.add_argument('--delay_interval',   type=int, default=DEFAULT_DELAY_INTERVAL_MS,
                        help=f'Delay trace interval in ms (default: {DEFAULT_DELAY_INTERVAL_MS})')
    parser.add_argument('--default_delay_ms', type=int, default=DEFAULT_DELAY_MS,
                        help=f'Fallback delay ms if no prior data (default: {DEFAULT_DELAY_MS})')
    parser.add_argument('--mbps_per_line',    type=int, default=MBPS_PER_LINE,
                        help=f'Mbps per bandwidth trace line (default: {MBPS_PER_LINE})')

    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    delay_file = os.path.join(args.output_dir, f"delay_{args.trace_id}.txt")
    bw_file    = os.path.join(args.output_dir, f"bw_{args.trace_id}.txt")

    print(f"Converting recorder outputs to replayer format...")
    print(f"  Ping file : {args.ping_file}")
    print(f"  PCAP file : {args.pcap_file}")
    print(f"  Output dir: {args.output_dir}")
    print()

    # Convert delay trace
    print("Processing delay trace...")
    try:
        delay_stats = parse_ping_to_delay(
            args.ping_file, delay_file,
            args.delay_interval, args.default_delay_ms
        )
        print(f"  Ping samples  : {delay_stats['ping_samples']}")
        print(f"  Duration      : {delay_stats['duration_sec']} sec")
        print(f"  Intervals     : {delay_stats['intervals']}")
        print(f"  Delay range   : {delay_stats['min_delay_ms']}-{delay_stats['max_delay_ms']} ms")
        print(f"  Average delay : {delay_stats['avg_delay_ms']} ms")
        print(f"  Output        : {delay_file}")
    except Exception as e:
        print(f"  ERROR: {e}")
        return 1

    print()

    # Convert bandwidth trace
    print("Processing bandwidth trace...")
    try:
        bw_stats = parse_pcap_to_bandwidth(
            args.pcap_file, bw_file, args.mbps_per_line
        )
        print(f"  Packets           : {bw_stats['packets']}")
        print(f"  Total bytes       : {bw_stats['total_bytes']:,}")
        print(f"  Duration          : {bw_stats['duration_sec']} sec")
        print(f"  Output lines      : {bw_stats['bw_lines']}")
        print(f"  Average bandwidth : {bw_stats['avg_bandwidth_mbps']} Mbps")
        print(f"  Output            : {bw_file}")
    except Exception as e:
        print(f"  ERROR: {e}")
        return 1

    print()
    print("Conversion complete!")
    return 0


if __name__ == "__main__":
    exit(main())
