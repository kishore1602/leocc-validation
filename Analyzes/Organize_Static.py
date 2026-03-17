#!/usr/bin/env python3
"""
organize_static_for_replayer.py
================================
Reorganizes the combined static traces into the exact folder structure
that LeoReplayer expects before running experiments.

This script is STEP 3 of the data processing pipeline for static traces.

Why this step is needed:
    combine_static_traces.py already creates downlink/ and uplink/ subfolders,
    but this script ensures the final organized copy is clean and ready to be
    directly copied to the lab machine's LeoReplayer directory.

Input folder: final_static_traces/  (from combine_static_traces.py)
    └── <trace_id>/
        ├── downlink/
        │   ├── bw_downlink.txt
        │   └── delay_downlink.txt
        └── uplink/
            ├── bw_uplink.txt
            └── delay_uplink.txt

Output folder: organized_static_traces/
    └── <trace_id>/
        ├── downlink/
        │   ├── bw_downlink.txt      ← mahimahi bandwidth trace for downlink
        │   └── delay_downlink.txt   ← one-way delay for downlink 
        └── uplink/
            ├── bw_uplink.txt        ← mahimahi bandwidth trace for uplink
            └── delay_uplink.txt     ← one-way delay for uplink 

After this step:
    1. Copy organized_static_traces/ to the lab machine LeoReplayer directory:
       cp -r organized_static_traces/ ~/zach/LeoCC/LeoCC/leoreplayer/replayer/
    2. Add experiment scripts (inner.sh, outer.sh, run.sh) to each trace folder
    3. Run extract_reconfiguration.py to get per-trace reconfiguration offsets
    4. Run experiments with correct offsets for each trace

"""

from pathlib import Path
import shutil
import os

# ── CONFIG ────────────────────────────────────────────────────────────────────
# Input: combined traces from combine_static_traces.py
FINAL_TRACES = "/mnt/nuwinslab_nas/nuwins_data_platform/datasets/bos_phi_trip_202601/final_static_traces"

# Output: organized traces ready to copy to LeoReplayer on lab machine
OUTPUT = "/mnt/nuwinslab_nas/nuwins_data_platform/datasets/bos_phi_trip_202601/organized_static_traces"

os.makedirs(OUTPUT, exist_ok=True)

# Get all trace folders sorted alphabetically
traces = sorted([d for d in os.listdir(FINAL_TRACES)
                 if os.path.isdir(os.path.join(FINAL_TRACES, d))])

print(f"Organizing {len(traces)} static traces for replayer\n")

for i, trace_id in enumerate(traces, 1):
    print(f"[{i}/{len(traces)}] {trace_id}")

    trace_path  = Path(OUTPUT) / trace_id
    source_path = Path(FINAL_TRACES) / trace_id

    # Create downlink and uplink subfolders for this trace
    os.makedirs(trace_path / "downlink", exist_ok=True)
    os.makedirs(trace_path / "uplink",   exist_ok=True)

    # ── Copy DOWNLINK files ──
    # bw_downlink.txt   : mahimahi packet timestamps for downlink capacity
    # delay_downlink.txt: one-way delay values for downlink (RTT/2 from ICMP)
    shutil.copy(source_path / "bw_downlink.txt",    trace_path / "downlink/")
    shutil.copy(source_path / "delay_downlink.txt", trace_path / "downlink/")

    # ── Copy UPLINK files ──
    # bw_uplink.txt   : mahimahi packet timestamps for uplink capacity
    # delay_uplink.txt: one-way delay values for uplink (RTT/2 from ICMP)
    shutil.copy(source_path / "bw_uplink.txt",    trace_path / "uplink/")
    shutil.copy(source_path / "delay_uplink.txt", trace_path / "uplink/")

    print(f"  Organized\n")

print(f"{'='*60}")
print(f" {len(traces)} traces ready in: {OUTPUT}")
print(f"\nNext steps:")
print(f"1. Copy to replayer: cp -r {OUTPUT} ~/zach/LeoCC/LeoCC/leoreplayer/replayer/")
print(f"2. Add scripts (inner.sh, outer.sh, run.sh) to each folder")
print(f"3. Run tests with correct offsets for each trace")