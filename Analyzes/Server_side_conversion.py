#!/usr/bin/env python3
"""
process_server_20260207.py
==========================
Processes raw field trip data collected from the SERVER SIDE (Philadelphia machine)
on February 7, 2026 during the Boston-Philadelphia Starlink measurement trip.

This script is STEP 1b of the data processing pipeline for static traces.

Input files (per trace folder):
    - udp_dl_server*.pcap : UDP downlink pcap captured at server (Philadelphia)
                            Records packets arriving at server from client via Starlink
                            Used to measure uplink bandwidth from server's perspective
    - udp_ul_server*.pcap : UDP uplink pcap captured at server (Philadelphia)
                            Records packets sent from server to client via Starlink
                            Used to measure downlink bandwidth from server's perspective

Output files (per trace folder) saved to converted_traces_server_20260207/:
    - bw_dl_server_mahimahi.txt : Downlink bandwidth in Mahimahi packet timestamp format
    - bw_ul_server_mahimahi.txt : Uplink bandwidth in Mahimahi packet timestamp format

Note:
    No delay extraction on server side — ICMP pings were only run from the
    client side (Boston machine) so all delay files come from process_client_20260207.py

    For bandwidth, we use:
        - Client side for DOWNLINK bandwidth (client is receiver for downlink)
        - Server side for UPLINK bandwidth (server is receiver for uplink)
    Bandwidth is always most accurately measured at the RECEIVER side because
    the receiver sees exactly how much data actually arrived after any losses.

"""

import os
import subprocess
import re
from pathlib import Path
import sys

# ── CONFIG ────────────────────────────────────────────────────────────────────
# Raw server-side data from Philadelphia machine collected on Feb 7, 2026
SERVER_DIR = "/mnt/nuwinslab_nas/nuwins_data_platform/datasets/bos_phi_trip_202601/server/20260207"

# Output directory for converted mahimahi-compatible bandwidth files
OUTPUT_DIR = "/mnt/nuwinslab_nas/nuwins_data_platform/datasets/bos_phi_trip_202601/converted_traces_server_20260207"

os.makedirs(OUTPUT_DIR, exist_ok=True)


def extract_bw_from_pcap_to_mahimahi(pcap_file, output_file):
    """
    Extract bandwidth from a UDP pcap file and convert to Mahimahi packet timestamp format.

    Step 1 — Extract all packets from pcap using tshark:
        Gets epoch timestamp and frame size for every packet.

    Step 2 — Calculate bandwidth in 500ms bins:
        Groups packets into 0.5 second windows, counts total bytes,
        converts to Mbps. This gives time-varying link capacity.

    Step 3 — Convert Mbps to Mahimahi packet timestamps:
        Mahimahi does not understand Mbps directly. It needs a list of
        millisecond timestamps — each timestamp = one 1500-byte packet (12000 bits)
        that can be delivered at that moment.
        Formula: num_packets = (rate_mbps * 1e6 * 0.5) / 12000
        Packets are evenly spaced within each 500ms interval.

    Output format (one timestamp per line in milliseconds):
        0
        1
        2
        ...
    """
    print(f"    PCAP: {os.path.basename(pcap_file)}...", end=" ", flush=True)

    # Use tshark to extract epoch timestamp and frame length for every packet
    cmd = f"tshark -r {pcap_file} -T fields -e frame.time_epoch -e frame.len 2>/dev/null"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=300)

    if result.returncode != 0:
        print("ERROR")
        return False

    # Parse tshark output into list of (timestamp, size) tuples
    packets = []
    for line in result.stdout.strip().split('\n'):
        if line and '\t' in line:
            try:
                ts, size = line.split('\t')
                packets.append((float(ts), int(size)))
            except:
                continue

    if not packets:
        print("NO DATA")
        return False

    # Calculate bandwidth in 500ms bins
    start_time = packets[0][0]
    end_time   = packets[-1][0]

    bandwidth_mbps = []
    current_bin_start = start_time

    while current_bin_start < end_time:
        bin_end = current_bin_start + 0.5
        # Sum all bytes in this 500ms window
        bytes_in_bin = sum(size for ts, size in packets if current_bin_start <= ts < bin_end)
        bits = bytes_in_bin * 8
        # Convert to Mbps: bits / 0.5 seconds / 1,000,000
        mbps = (bits / 0.5) / 1e6
        bandwidth_mbps.append(int(mbps))
        current_bin_start = bin_end

    # Convert Mbps values to Mahimahi packet timestamps
    trace_data = []

    for j, rate_mbps in enumerate(bandwidth_mbps):
        # How many 1500-byte (12000-bit) packets fit in this 500ms interval?
        bits_in_interval = rate_mbps * 1e6 * 0.5
        num_packets = int(bits_in_interval / 12000)
        interval_start_ms = j * 500  # start time of this interval in ms

        if num_packets > 0:
            # Space packets evenly across the 500ms interval
            for p in range(num_packets):
                packet_time = interval_start_ms + int((p * 500) / num_packets)
                trace_data.append(packet_time)

    # Add a final timestamp 1 second after last packet to signal end of trace
    if trace_data:
        trace_data.append(trace_data[-1] + 1000)

    # Write one timestamp per line — this is the Mahimahi trace format
    with open(output_file, 'w') as f:
        for timestamp in trace_data:
            f.write(f"{timestamp}\n")

    print(f"OK ({len(bandwidth_mbps)} intervals → {len(trace_data)} packets)")
    return True


def process_server_trace(trace_id):
    """
    Process all server-side files for one trace folder.

    Finds the 2 input pcap files and runs bandwidth conversion
    to produce 2 output mahimahi format files.
    """
    server_path = Path(SERVER_DIR) / trace_id
    output_path = Path(OUTPUT_DIR) / trace_id
    os.makedirs(output_path, exist_ok=True)

    try:
        # Find input pcap files using glob pattern matching
        server_dl_pcap = list(server_path.glob("udp_dl_server*.pcap"))[0]
        server_ul_pcap = list(server_path.glob("udp_ul_server*.pcap"))[0]

        print(f"  SERVER-SIDE Processing:")
        success = True

        # Convert bandwidth pcaps to mahimahi format
        success &= extract_bw_from_pcap_to_mahimahi(str(server_dl_pcap), str(output_path / "bw_dl_server_mahimahi.txt"))
        success &= extract_bw_from_pcap_to_mahimahi(str(server_ul_pcap), str(output_path / "bw_ul_server_mahimahi.txt"))

        return success

    except Exception as e:
        print(f"  ERROR: {e}")
        return False


# ── MAIN ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # Get all trace folders sorted alphabetically
    server_traces = sorted([d for d in os.listdir(SERVER_DIR)
                            if os.path.isdir(os.path.join(SERVER_DIR, d))])

    print(f"Processing {len(server_traces)} SERVER-SIDE traces from 20260207 (STATIC)")
    print(f"Output: {OUTPUT_DIR}")
    print(f"Format: Mahimahi packet timestamps\n")

    success = 0
    for i, trace_id in enumerate(server_traces, 1):
        print(f"[{i}/{len(server_traces)}] {trace_id}")
        if process_server_trace(trace_id):
            success += 1
            print(f"  DONE\n")
        else:
            print(f"  FAILED\n")
        sys.stdout.flush()

    print(f"{'='*60}")
    print(f"SERVER-SIDE 20260207 Completed: {success}/{len(server_traces)}")
