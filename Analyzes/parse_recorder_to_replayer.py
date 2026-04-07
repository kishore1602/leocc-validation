#!/usr/bin/env python3
"""
parse_recorder_to_replayer_interpolation.py
============================================
Convert LeoRecorder outputs to LeoReplayer trace format.

This is the INTERPOLATION version — for comparison with carry forward version.

Changes from carry forward version:
    1. Empty slots → fill with very high delay value (3,600,000 ms = 1 hour)
       instead of carry forward last known RTT value
    2. Loss rate = 0 in run.sh 
    3. min_rtt_fluctuation = 10000

Reason for high fill value:
    Carry forward slightly misinterprets RTT values during packet loss periods.
    By filling with a very high value, packets sent during loss periods will
    experience extremely high delay — effectively simulating packet loss without
    needing mm-loss shell. This is closer to what actually happens during
    reconfiguration-induced outages.

Original carry forward version: parse_recorder_to_replayer.py
"""

import argparse
import math
import os
import re
import subprocess
from collections import defaultdict

# ── DEFAULT CONFIG ─────────────────────────────────────────────────────────────
DEFAULT_DELAY_INTERVAL_MS = 10

# NEW: High fill value for empty slots = 1 hour in ms
# This simulates packet loss by making packets experience extremely high delay
HIGH_FILL_DELAY_MS = 3_600_000  # 1 hour = 3,600,000 ms

# OLD: Carry forward default (kept for reference)
# DEFAULT_DELAY_MS = 200

MBPS_PER_LINE = 12


def parse_ping_to_delay(ping_file: str, output_file: str,
                        delay_interval_ms: int = DEFAULT_DELAY_INTERVAL_MS,
                        fill_delay_ms: int = HIGH_FILL_DELAY_MS) -> dict:
    """
    Convert ping RTT output to delay trace format.

    Slot assignment:
        - Use math.floor() on receive timestamp to assign to 10ms slot
        - RTT at 16ms → floor(16/10) = slot 1 (0-10ms)
        - RTT at 22ms → floor(22/10) = slot 2 (10-20ms)
        - Multiple pings in same slot → simple average

    Empty slot handling:
        - Fill with very high delay value (3,600,000 ms = 1 hour)
        - This simulates packet loss without needing mm-loss shell
        - Loss rate = 0 in run.sh when using this approach

    OLD empty slot handling (carry forward — commented out):
        # one_way_delay = delays[-1] if delays else DEFAULT_DELAY_MS
        # This was Sizhe's suggestion — copy last known RTT value
        # Valid since mm-loss shell handles actual packet loss

    Args:
        ping_file         : Path to trimmed ICMP ping log file
        output_file       : Path to output delay trace file
        delay_interval_ms : Mahimahi slot size in ms (default: 10)
        fill_delay_ms     : Fill value for empty slots (default: 3,600,000 ms)

    Returns:
        dict with conversion statistics
    """
    pattern = re.compile(r'\[(\d+\.\d+)\].*time=(\d+\.?\d*)\s*ms')

    rtt_samples = []

    with open(ping_file, 'r') as f:
        for line in f:
            match = pattern.search(line)
            if match:
                timestamp = float(match.group(1))
                rtt_ms    = float(match.group(2))
                rtt_samples.append((timestamp, rtt_ms))

    if not rtt_samples:
        raise ValueError(f"No valid ping samples found in {ping_file}")

    start_time  = rtt_samples[0][0]
    end_time    = rtt_samples[-1][0]
    duration_ms = int((end_time - start_time) * 1000)

    interval_rtts = defaultdict(list)
    for timestamp, rtt_ms in rtt_samples:
        interval_idx = math.floor((timestamp - start_time) * 1000 / delay_interval_ms)
        interval_rtts[interval_idx].append(rtt_ms)

    num_intervals = duration_ms // delay_interval_ms + 1

    delays = []
    empty_slots = 0
    real_slots  = 0

    for i in range(num_intervals):
        if i in interval_rtts:
            # Real ping data — average and divide by 2 for one-way delay
            avg_rtt       = sum(interval_rtts[i]) / len(interval_rtts[i])
            one_way_delay = int(round(avg_rtt / 2))
            real_slots += 1
        else:
            # NEW: Empty slot — fill with very high delay value
            # This simulates packet loss — packets in these slots will
            # experience 1 hour delay effectively never arriving
            one_way_delay = fill_delay_ms
            empty_slots  += 1

            # OLD: Carry forward last known RTT value 
            # one_way_delay = delays[-1] if delays else 200
            # mm-loss shell handles actual packet loss simulation

        delays.append(one_way_delay)

    with open(output_file, 'w') as f:
        for delay in delays:
            f.write(f"{delay}\n")

    # Compute stats excluding high fill values for meaningful averages
    real_delays = [d for d in delays if d < fill_delay_ms]

    stats = {
        'ping_samples'  : len(rtt_samples),
        'duration_sec'  : round(end_time - start_time, 2),
        'intervals'     : len(delays),
        'real_slots'    : real_slots,
        'empty_slots'   : empty_slots,
        'avg_delay_ms'  : round(sum(real_delays) / len(real_delays), 2) if real_delays else 0,
        'min_delay_ms'  : min(real_delays) if real_delays else 0,
        'max_delay_ms'  : max(real_delays) if real_delays else 0,
        'fill_value_ms' : fill_delay_ms,
    }
    return stats


def parse_pcap_to_bandwidth(pcap_file: str, output_file: str,
                             mbps_per_line: int = MBPS_PER_LINE) -> dict:
    """
    Convert pcap file to mahimahi bandwidth trace format.
    UNCHANGED from original version.
    """
    cmd = ['tcpdump', '-tt', '-n', '-r', pcap_file]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"tcpdump failed: {e.stderr}")
    except FileNotFoundError:
        raise RuntimeError("tcpdump not found. Please install tcpdump.")

    pattern = re.compile(r'^(\d+\.\d+)\s+\S+\s+In\s+IP.*length\s+(\d+)')
    packets = []
    for line in result.stdout.split('\n'):
        match = pattern.match(line)
        if match:
            timestamp = float(match.group(1))
            length    = int(match.group(2))
            packets.append((timestamp, length))

    if not packets:
        raise ValueError(f"No valid UDP packets found in {pcap_file}")

    start_time  = packets[0][0]
    end_time    = packets[-1][0]
    duration_ms = int((end_time - start_time) * 1000)

    bytes_per_ms = defaultdict(int)
    for timestamp, length in packets:
        ms_offset = int((timestamp - start_time) * 1000)
        bytes_per_ms[ms_offset] += length

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
        description='Convert LeoRecorder outputs to LeoReplayer trace format (interpolation version)',
    )
    parser.add_argument('--ping_file',   required=True)
    parser.add_argument('--pcap_file',   required=True)
    parser.add_argument('--output_dir',  default='./output')
    parser.add_argument('--trace_id',    type=int, default=1)
    parser.add_argument('--delay_interval', type=int, default=DEFAULT_DELAY_INTERVAL_MS)
    parser.add_argument('--fill_delay_ms',  type=int, default=HIGH_FILL_DELAY_MS,
                        help=f'Fill value for empty slots in ms (default: {HIGH_FILL_DELAY_MS})')
    parser.add_argument('--mbps_per_line',  type=int, default=MBPS_PER_LINE)

    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    delay_file = os.path.join(args.output_dir, f"delay_{args.trace_id}.txt")
    bw_file    = os.path.join(args.output_dir, f"bw_{args.trace_id}.txt")

    print(f"Converting recorder outputs to replayer format (INTERPOLATION version)...")
    print(f"  Ping file      : {args.ping_file}")
    print(f"  PCAP file      : {args.pcap_file}")
    print(f"  Output dir     : {args.output_dir}")
    print(f"  Fill delay     : {args.fill_delay_ms} ms (for empty slots)")
    print()

    print("Processing delay trace...")
    try:
        delay_stats = parse_ping_to_delay(
            args.ping_file, delay_file,
            args.delay_interval, args.fill_delay_ms
        )
        print(f"  Ping samples  : {delay_stats['ping_samples']}")
        print(f"  Duration      : {delay_stats['duration_sec']} sec")
        print(f"  Intervals     : {delay_stats['intervals']}")
        print(f"  Real slots    : {delay_stats['real_slots']}")
        print(f"  Empty slots   : {delay_stats['empty_slots']} (filled with {delay_stats['fill_value_ms']} ms)")
        print(f"  Delay range   : {delay_stats['min_delay_ms']}-{delay_stats['max_delay_ms']} ms (excluding fill)")
        print(f"  Average delay : {delay_stats['avg_delay_ms']} ms (excluding fill)")
        print(f"  Output        : {delay_file}")
    except Exception as e:
        print(f"  ERROR: {e}")
        return 1

    print()

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
