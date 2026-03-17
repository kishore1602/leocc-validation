#!/usr/bin/env python3
"""
Convert LeoRecorder outputs to LeoReplayer trace format.

This script converts raw pcap and ping data from the recorder into the
bandwidth and delay trace files used by LeoReplayer.

Input:
    - Ping output file (*.txt) with format: [timestamp] ... time=X.XX ms
    - Client pcap file with received UDP packets

Output:
    - bw_{trace_id}.txt: Bandwidth trace (timestamp per 12 Mbps unit)
    - delay_{trace_id}.txt: Delay trace (one-way delay per 10ms interval)

Usage:
    python parse_recorder_to_replayer.py \\
        --ping_file outputs/server/outputs/leocc_dl_record_1.txt \\
        --pcap_file outputs/client/leocc_dl_record_1.pcap \\
        --output_dir ./output \\
        --trace_id 1

Dependencies:
    - Python 3
    - tcpdump CLI (for pcap parsing)
"""

import argparse
import math
import os
import re
import subprocess
from collections import defaultdict


def parse_ping_to_delay(ping_file: str, output_file: str, delay_interval_ms: int = 10, default_delay_ms: int = 200) -> dict:
    """
    Convert ping RTT output to delay trace format.

    The delay trace has one value per line, where each line represents
    a delay_interval_ms interval. The value is the one-way delay in ms.

    Args:
        ping_file: Path to ping output file
        output_file: Path to output delay trace file
        delay_interval_ms: Interval size in milliseconds (default: 10)

    Returns:
        dict with statistics about the conversion
    """
    # Pattern to match: [timestamp] ... time=X.XX ms
    pattern = re.compile(r'\[(\d+\.\d+)\].*time=(\d+\.?\d*)\s*ms')

    rtt_samples = []  # List of (timestamp, rtt_ms)

    with open(ping_file, 'r') as f:
        for line in f:
            match = pattern.search(line)
            if match:
                timestamp = float(match.group(1))
                rtt_ms = float(match.group(2))
                rtt_samples.append((timestamp, rtt_ms))

    if not rtt_samples:
        raise ValueError(f"No valid ping samples found in {ping_file}")

    # Get time range
    start_time = rtt_samples[0][0]
    end_time = rtt_samples[-1][0]
    duration_ms = int((end_time - start_time) * 1000)

    # Group RTT samples by interval
    interval_rtts = defaultdict(list)
    for timestamp, rtt_ms in rtt_samples:
        interval_idx = math.floor((timestamp - start_time) * 1000 / delay_interval_ms)
        interval_rtts[interval_idx].append(rtt_ms)

    # Calculate one-way delay for each interval
    num_intervals = duration_ms // delay_interval_ms + 1
    delays = []

    for i in range(num_intervals):
        if i in interval_rtts:
            # Average RTT in this interval, divided by 2 for one-way delay
            avg_rtt = sum(interval_rtts[i]) / len(interval_rtts[i])
            one_way_delay = int(round(avg_rtt / 2))
        else:
            # No samples in this interval, use previous value or default
            # one_way_delay = delays[-1] if delays else default_delay_ms
            one_way_delay = default_delay_ms
        delays.append(one_way_delay)

    # Write output
    with open(output_file, 'w') as f:
        for delay in delays:
            f.write(f"{delay}\n")

    stats = {
        'ping_samples': len(rtt_samples),
        'duration_sec': round(end_time - start_time, 2),
        'intervals': len(delays),
        'avg_delay_ms': round(sum(delays) / len(delays), 2),
        'min_delay_ms': min(delays),
        'max_delay_ms': max(delays),
    }

    return stats


def parse_pcap_to_bandwidth(pcap_file: str, output_file: str, mbps_per_line: int = 12) -> dict:
    """
    Convert pcap file to bandwidth trace format.

    The bandwidth trace has timestamps in milliseconds, where each line
    represents one "delivery opportunity" of ~12 Mbps. Multiple lines with
    the same timestamp indicate higher bandwidth at that moment.

    Args:
        pcap_file: Path to pcap file (client-side, received packets)
        output_file: Path to output bandwidth trace file
        mbps_per_line: Mbps represented by each line (default: 12)

    Returns:
        dict with statistics about the conversion
    """
    # Use tcpdump to extract timestamp and packet length
    # Format: timestamp IP ... length N
    cmd = ['tcpdump', '-tt', '-n', '-r', pcap_file]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"tcpdump failed: {e.stderr}")
    except FileNotFoundError:
        raise RuntimeError("tcpdump not found. Please install tcpdump.")

    # Parse tcpdump output
    # Example: 1768754347.710418 IP 192.168.100.200.5201 > 192.168.100.35.33384: UDP, length 1448
    pattern = re.compile(r'^(\d+\.\d+)\s+IP.*length\s+(\d+)')

    packets = []  # List of (timestamp, length)

    for line in result.stdout.split('\n'):
        match = pattern.match(line)
        if match:
            timestamp = float(match.group(1))
            length = int(match.group(2))
            packets.append((timestamp, length))

    if not packets:
        raise ValueError(f"No valid UDP packets found in {pcap_file}")

    # Get time range
    start_time = packets[0][0]
    end_time = packets[-1][0]
    duration_ms = int((end_time - start_time) * 1000)

    # Group bytes by millisecond
    bytes_per_ms = defaultdict(int)
    for timestamp, length in packets:
        ms_offset = int((timestamp - start_time) * 1000)
        bytes_per_ms[ms_offset] += length

    # Convert to bandwidth trace format
    # Each line = 12 Mbps = 12,000,000 bits/sec = 12,000 bits/ms = 1,500 bytes/ms
    bytes_per_line = (mbps_per_line * 1_000_000) // 8 // 1000  # bytes per ms per line

    bw_lines = []
    total_bytes = 0

    for ms in range(duration_ms + 1):
        if ms in bytes_per_ms:
            bytes_this_ms = bytes_per_ms[ms]
            total_bytes += bytes_this_ms
            # How many 12 Mbps units does this represent?
            num_lines = max(1, bytes_this_ms // bytes_per_line)
            for _ in range(num_lines):
                bw_lines.append(ms)

    # Write output
    with open(output_file, 'w') as f:
        for ms in bw_lines:
            f.write(f"{ms}\n")

    # Calculate statistics
    avg_bw_mbps = (total_bytes * 8) / (duration_ms * 1000) if duration_ms > 0 else 0

    stats = {
        'packets': len(packets),
        'total_bytes': total_bytes,
        'duration_sec': round(end_time - start_time, 2),
        'bw_lines': len(bw_lines),
        'avg_bandwidth_mbps': round(avg_bw_mbps, 2),
    }

    return stats


def main():
    parser = argparse.ArgumentParser(
        description='Convert LeoRecorder outputs to LeoReplayer trace format',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Example:
    python parse_recorder_to_replayer.py \\
        --ping_file ../leoreplayer/recorder/outputs/server/outputs/leocc_dl_record_1.txt \\
        --pcap_file ../leoreplayer/recorder/outputs/client/leocc_dl_record_1.pcap \\
        --output_dir ./output \\
        --trace_id 1
        """
    )

    parser.add_argument('--ping_file', required=True,
                        help='Path to ping output file (*.txt)')
    parser.add_argument('--pcap_file', required=True,
                        help='Path to client pcap file')
    parser.add_argument('--output_dir', default='./output',
                        help='Output directory for trace files (default: ./output)')
    parser.add_argument('--trace_id', type=int, default=1,
                        help='Trace ID for output filenames (default: 1)')
    parser.add_argument('--delay_interval', type=int, default=10,
                        help='Delay trace interval in ms (default: 10)')
    parser.add_argument('--default_delay_ms', type=int, default=10,
                        help='Default delay in ms (default: 10)')
    parser.add_argument('--mbps_per_line', type=int, default=12,
                        help='Mbps per bandwidth trace line (default: 12)')

    args = parser.parse_args()

    # Create output directory
    os.makedirs(args.output_dir, exist_ok=True)

    # Output file paths
    delay_file = os.path.join(args.output_dir, f"delay_{args.trace_id}.txt")
    bw_file = os.path.join(args.output_dir, f"bw_{args.trace_id}.txt")

    print(f"Converting recorder outputs to replayer format...")
    print(f"  Ping file: {args.ping_file}")
    print(f"  PCAP file: {args.pcap_file}")
    print(f"  Output dir: {args.output_dir}")
    print()

    # Convert delay trace
    print("Processing delay trace...")
    try:
        delay_stats = parse_ping_to_delay(
            args.ping_file,
            delay_file,
            args.delay_interval,
            default_delay_ms=args.default_delay_ms
        )
        print(f"  Ping samples: {delay_stats['ping_samples']}")
        print(f"  Duration: {delay_stats['duration_sec']} sec")
        print(f"  Output intervals: {delay_stats['intervals']}")
        print(f"  Delay range: {delay_stats['min_delay_ms']}-{delay_stats['max_delay_ms']} ms")
        print(f"  Average delay: {delay_stats['avg_delay_ms']} ms")
        print(f"  Output: {delay_file}")
    except Exception as e:
        print(f"  ERROR: {e}")
        return 1

    print()

    # Convert bandwidth trace
    print("Processing bandwidth trace...")
    try:
        bw_stats = parse_pcap_to_bandwidth(
            args.pcap_file,
            bw_file,
            args.mbps_per_line
        )
        print(f"  Packets: {bw_stats['packets']}")
        print(f"  Total bytes: {bw_stats['total_bytes']:,}")
        print(f"  Duration: {bw_stats['duration_sec']} sec")
        print(f"  Output lines: {bw_stats['bw_lines']}")
        print(f"  Average bandwidth: {bw_stats['avg_bandwidth_mbps']} Mbps")
        print(f"  Output: {bw_file}")
    except Exception as e:
        print(f"  ERROR: {e}")
        return 1

    print()
    print("Conversion complete!")

    return 0


if __name__ == "__main__":
    exit(main())
