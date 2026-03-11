#!/usr/bin/env python3
"""
combine_static_traces.py
========================
Combines client-side and server-side converted trace files into one
unified folder per trace for use in LeoReplayer experiments.

This script is STEP 2 of the data processing pipeline for static traces.

Why we need to combine client and server side:
    - Downlink bandwidth is measured at the CLIENT (Boston) because the
      client is the RECEIVER for downlink — it sees exactly what arrived
    - Uplink bandwidth is measured at the SERVER (Philadelphia) because the
      server is the RECEIVER for uplink — it sees exactly what arrived
    - Both delay files come from the client side since ICMP pings were
      only run from the Boston machine

Input folders:
    - converted_traces_client_20260207/  (from process_client_20260207.py)
        └── <trace_id>/
            ├── bw_dl_client_mahimahi.txt  ← downlink bandwidth
            ├── bw_ul_client_mahimahi.txt  ← not used here
            ├── delay_dl_oneway.txt        ← downlink one-way delay
            └── delay_ul_oneway.txt        ← uplink one-way delay

    - converted_traces_server_20260207/  (from process_server_20260207.py)
        └── <trace_id>/
            ├── bw_dl_server_mahimahi.txt  ← not used here
            └── bw_ul_server_mahimahi.txt  ← uplink bandwidth

Output folder: final_static_traces/
    └── <trace_id>/
        ├── downlink/
        │   ├── bw_downlink.txt      ← from client DL pcap (receiver side)
        │   └── delay_downlink.txt   ← from client ICMP ping log 
        └── uplink/
            ├── bw_uplink.txt        ← from server UL pcap (receiver side)
            └── delay_uplink.txt     ← from client ICMP ping log 

"""

from pathlib import Path
import shutil
import os

# ── CONFIG ────────────────────────────────────────────────────────────────────
# Input: converted client-side files (bandwidth + delay from Boston machine)
CLIENT_CONV = "/mnt/nuwinslab_nas/nuwins_data_platform/datasets/bos_phi_trip_202601/converted_traces_client_20260207"

# Input: converted server-side files (bandwidth from Philadelphia machine)
SERVER_CONV = "/mnt/nuwinslab_nas/nuwins_data_platform/datasets/bos_phi_trip_202601/converted_traces_server_20260207"

# Output: combined traces ready for organize step
OUTPUT = "/mnt/nuwinslab_nas/nuwins_data_platform/datasets/bos_phi_trip_202601/final_static_traces"

os.makedirs(OUTPUT, exist_ok=True)

# Get all trace folders from client side (source of truth for trace list)
client_traces = sorted([d for d in os.listdir(CLIENT_CONV)
                        if os.path.isdir(os.path.join(CLIENT_CONV, d))])

print(f"Combining {len(client_traces)} static traces\n")

success = 0
for trace_id in client_traces:
    print(f"{trace_id}...", end=" ")

    output_path = Path(OUTPUT) / trace_id

    # Create downlink and uplink subfolders for this trace
    os.makedirs(output_path / "downlink", exist_ok=True)
    os.makedirs(output_path / "uplink", exist_ok=True)

    try:
        client_path = Path(CLIENT_CONV) / trace_id
        server_path = Path(SERVER_CONV) / trace_id

        # ── DOWNLINK folder ──
        # Bandwidth from CLIENT side — client is receiver for downlink
        shutil.copy(client_path / "bw_dl_client_mahimahi.txt",
                    output_path / "downlink" / "bw_downlink.txt")
        # Delay from CLIENT ICMP ping log 
        shutil.copy(client_path / "delay_dl_oneway.txt",
                    output_path / "downlink" / "delay_downlink.txt")

        # ── UPLINK folder ──
        # Bandwidth from SERVER side — server is receiver for uplink
        shutil.copy(server_path / "bw_ul_server_mahimahi.txt",
                    output_path / "uplink" / "bw_uplink.txt")
        # Delay from CLIENT ICMP ping log 
        shutil.copy(client_path / "delay_ul_oneway.txt",
                    output_path / "uplink" / "delay_uplink.txt")

        print("")
        success += 1

    except Exception as e:
        print(f" {e}")

print(f"\n{'='*60}")
print(f" Combined: {success}/{len(client_traces)}")
print(f" Output: {OUTPUT}")
