#!/usr/bin/env python3
"""
parse_recorder_carryforward_mobility.py
========================================
Convert LeoRecorder outputs to LeoReplayer trace format.
Carry-forward version for mobility traces.

Delay parsing logic:
    - Time-based slot assignment using math.floor()
    - Multiple pings in same slot → averaged
    - Empty slots → carry forward last known RTT value
    - First slot empty → fill with 200ms (no previous value)

Input:
    - Trimmed ICMP ping log file
    - UDP pcap file (client side for downlink, server side for uplink)

Output:
    - bw_{trace_id}.txt  : Bandwidth trace (mahimahi packet timestamps)
    - delay_{trace_id}.txt: Delay trace (one-way delay per 10ms slot)
"""

import argparse
import math
import os
import re
import subprocess
from collections import defaultdict

# ── DEFAULT CONFIG ─────────────────────────────────────────────────────────────
DEFAULT_DELAY_INTERVAL_MS = 10
DEFAULT_DELAY_MS          = 200  # fallback if very first slot is empty
MBPS_PER_LINE             = 12
TOTAL_SLOTS               = 12000  # always 12000 lines = 120 seconds


def parse_ping_to_delay(ping_file: str, output_file: str,
                        delay_interval_ms: int = DEFAULT_DELAY_INTERVAL_MS,
                        default_delay_ms: int = DEFAULT_DELAY_MS) -> dict:
    """
    Convert ping RTT output to delay trace format.

    Slot assignment:
        - Use math.floor() on receive timestamp to assign to 10ms slot
        - Multiple pings in same slot → simple average
        - Empty slots → carry forward last known RTT value
        - First slot empty → fill with 200ms
        - Always generates exactly 12000 lines

    Args:
        ping_file         : Path to trimmed ICMP ping log file
        output_file       : Path to output delay trace file
        delay_interval_ms : Mahimahi slot size in ms (default: 10)
        default_delay_ms  : Fallback value if first slot is empty (default: 200)

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

    start_time = rtt_samples[0][0]

    # Group RTT samples by 10ms slot using math.floor()
    interval_rtts = defaultdict(list)
    for timestamp, rtt_ms in rtt_samples:
        interval_idx = math.floor((timestamp - start_time) * 1000 / delay_interval_ms)
        if 0 <= interval_idx < TOTAL_SLOTS:
            interval_rtts[interval_idx].append(rtt_ms)

    # Build exactly 12000 lines
    delays       = []
    empty_slots  = 0
    carry_slots  = 0

    for i in range(TOTAL_SLOTS):
        if i in interval_rtts:
            avg_rtt       = sum(interval_rtts[i]) / len(interval_rtts[i])
            one_way_delay = int(round(avg_rtt / 2))
        else:
            empty_slots += 1
            if delays:
                # Carry forward last known value
                one_way_delay = delays[-1]
                carry_slots  += 1
            else:
                # First slot empty — use default
                one_way_delay = default_delay_ms
        delays.append(one_way_delay)

    # Write output — one integer per line
    with open(output_file, 'w') as f:
        for delay in delays:
            f.write(f"{delay}\n")

    stats = {
        'ping_samples' : len(rtt_samples),
        'duration_sec' : round(rtt_samples[-1][0] - start_time, 2),
        'total_lines'  : len(delays),
        'empty_slots'  : empty_slots,
        'carry_slots'  : carry_slots,
        'avg_delay_ms' : round(sum(delays) / len(delays), 2),
        'min_delay_ms' : min(delays),
        'max_delay_ms' : max(delays),
    }
    return stats


def parse_pcap_to_bandwidth(pcap_file: str, output_file: str,
                             mbps_per_line: int = MBPS_PER_LINE) -> dict:
    """
    Convert pcap file to mahimahi bandwidth trace format.
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
        description='Convert LeoRecorder outputs to LeoReplayer trace format (carry-forward mobility)',
    )
    parser.add_argument('--ping_file',      required=True)
    parser.add_argument('--pcap_file',      required=True)
    parser.add_argument('--output_dir',     default='./output')
    parser.add_argument('--trace_id',       type=int, default=1)
    parser.add_argument('--delay_interval', type=int, default=DEFAULT_DELAY_INTERVAL_MS)
    parser.add_argument('--default_delay',  type=int, default=DEFAULT_DELAY_MS)
    parser.add_argument('--mbps_per_line',  type=int, default=MBPS_PER_LINE)

    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    delay_file = os.path.join(args.output_dir, f"delay_{args.trace_id}.txt")
    bw_file    = os.path.join(args.output_dir, f"bw_{args.trace_id}.txt")

    print(f"Converting recorder outputs to replayer format (carry-forward mobility)...")
    print(f"  Ping file  : {args.ping_file}")
    print(f"  PCAP file  : {args.pcap_file}")
    print(f"  Output dir : {args.output_dir}")
    print()

    print("Processing delay trace...")
    try:
        delay_stats = parse_ping_to_delay(
            args.ping_file, delay_file,
            args.delay_interval, args.default_delay
        )
        print(f"  Ping samples  : {delay_stats['ping_samples']}")
        print(f"  Duration      : {delay_stats['duration_sec']} sec")
        print(f"  Total lines   : {delay_stats['total_lines']}")
        print(f"  Empty slots   : {delay_stats['empty_slots']}")
        print(f"  Carry slots   : {delay_stats['carry_slots']}")
        print(f"  Delay range   : {delay_stats['min_delay_ms']}-{delay_stats['max_delay_ms']} ms")
        print(f"  Average delay : {delay_stats['avg_delay_ms']} ms")
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
