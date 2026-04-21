#!/usr/bin/env python3
"""
parse_recorder_to_replayer.py
==============================
Convert LeoRecorder outputs to LeoReplayer trace format.

This script converts raw pcap and ping data from the field trip recorder
into the bandwidth and delay trace files used by LeoReplayer.

Delay parsing logic:
    - Each ICMP sequence number maps directly to one line in delay file
    - seq 1 → line 1, seq 2 → line 2, ..., seq N → line N
    - No time-based slotting, no grouping
    - Anchor time = sender timestamp of first ICMP response
      (sender_timestamp = receive_timestamp - RTT)
    - Missing seq numbers → fill with 121000 ms (longer than test duration,
      effectively simulates complete packet loss)

Input:
    - Trimmed ICMP ping log file (from trim_common_window.py)
    - UDP pcap file (client side for downlink, server side for uplink)

Output:
    - bw_{trace_id}.txt  : Bandwidth trace (mahimahi packet timestamps)
    - delay_{trace_id}.txt: Delay trace (one-way delay per sequence number)

Usage:
    python parse_recorder_to_replayer.py \\
        --ping_file trimmed_traces/trace_id/icmp_dl_trimmed.log \\
        --pcap_file client/trace_id/udp_dl_client*.pcap \\
        --output_dir ./output/trace_id/downlink \\
        --trace_id 1
"""

import argparse
import os
import re
import subprocess
from collections import defaultdict

# ── DEFAULT CONFIG ─────────────────────────────────────────────────────────────
# Mahimahi delay interval confirmed from run.sh: DELAY_INTERVAL=10
DEFAULT_DELAY_INTERVAL_MS = 10

# Fill value for missing ICMP sequence numbers
# 121000ms > 120s test duration → effectively simulates complete packet loss
MISSING_SEQ_DELAY_MS = 121000

# Mbps represented by each line in bandwidth trace
MBPS_PER_LINE = 12


def parse_ping_to_delay(ping_file: str, output_file: str,
                        delay_interval_ms: int = DEFAULT_DELAY_INTERVAL_MS) -> dict:
    """
    Convert ping RTT output to delay trace format.

    Slot assignment:
        - Each ICMP sequence number maps directly to one line in the delay file
        - seq 1 → line 1, seq 2 → line 2, ..., seq N → line N
        - Anchor time is the sender timestamp of the first ICMP response:
          sender_timestamp = receive_timestamp - RTT
        - Missing sequence numbers are filled with 121000 ms

    Args:
        ping_file         : Path to trimmed ICMP ping log file
        output_file       : Path to output delay trace file
        delay_interval_ms : Mahimahi slot size in ms (default: 10)

    Returns:
        dict with conversion statistics
    """
    # Pattern matches: [1770506568.318547] ... icmp_seq=X ... time=Y ms
    pattern = re.compile(r'\[(\d+\.\d+)\].*icmp_seq=(\d+).*time=(\d+\.?\d*)\s*ms')

    seq_data = {}  # seq_num → (receive_timestamp, rtt_ms)

    with open(ping_file, 'r') as f:
        for line in f:
            match = pattern.search(line)
            if match:
                timestamp = float(match.group(1))
                seq_num   = int(match.group(2))
                rtt_ms    = float(match.group(3))
                seq_data[seq_num] = (timestamp, rtt_ms)

    if not seq_data:
        raise ValueError(f"No valid ping samples found in {ping_file}")

    min_seq = min(seq_data.keys())
    max_seq = max(seq_data.keys())

    # Anchor: sender timestamp of first received ICMP response
    first_recv_ts, first_rtt = seq_data[min_seq]
    anchor_time = first_recv_ts - (first_rtt / 1000.0)

    print(f"  First seq     : {min_seq}")
    print(f"  Last seq      : {max_seq}")
    print(f"  Anchor time   : {anchor_time:.6f} (sender timestamp)")

    # Build delay list: min_seq → line 1, min_seq+1 → line 2, ..., min_seq+11999 → line 12000
    # Missing seqs (gaps in middle, after last ping) → 121000ms
    TOTAL_SEQS = 12000
    delays = []
    missing_count = 0
    for seq in range(min_seq, min_seq + TOTAL_SEQS):
        if seq in seq_data:
            _, rtt_ms = seq_data[seq]
            one_way_delay = int(round(rtt_ms / 2))
        else:
            one_way_delay = MISSING_SEQ_DELAY_MS
            missing_count += 1
        delays.append(one_way_delay)

    # Write output — one integer per line
    with open(output_file, 'w') as f:
        for delay in delays:
            f.write(f"{delay}\n")

    stats = {
        'ping_samples' : len(seq_data),
        'min_seq'      : min_seq,
        'max_seq'      : max_seq,
        'total_lines'  : len(delays),
        'missing_seqs' : missing_count,
        'avg_delay_ms' : round(sum(d for d in delays if d < MISSING_SEQ_DELAY_MS) / max(1, len(seq_data)), 2),
        'min_delay_ms' : min(d for d in delays if d < MISSING_SEQ_DELAY_MS),
        'max_delay_ms' : max(d for d in delays if d < MISSING_SEQ_DELAY_MS),
        'anchor_time'  : anchor_time,
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
    parser.add_argument('--delay_interval', type=int, default=DEFAULT_DELAY_INTERVAL_MS,
                        help=f'Delay trace interval in ms (default: {DEFAULT_DELAY_INTERVAL_MS})')
    parser.add_argument('--mbps_per_line',  type=int, default=MBPS_PER_LINE,
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
            args.ping_file, delay_file, args.delay_interval
        )
        print(f"  Ping samples  : {delay_stats['ping_samples']}")
        print(f"  Seq range     : {delay_stats['min_seq']} - {delay_stats['max_seq']}")
        print(f"  Total lines   : {delay_stats['total_lines']}")
        print(f"  Missing seqs  : {delay_stats['missing_seqs']}")
        print(f"  Delay range   : {delay_stats['min_delay_ms']}-{delay_stats['max_delay_ms']} ms")
        print(f"  Average delay : {delay_stats['avg_delay_ms']} ms")
        print(f"  Anchor time   : {delay_stats['anchor_time']:.6f}")
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
