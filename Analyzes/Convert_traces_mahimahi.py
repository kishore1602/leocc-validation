#!/usr/bin/env python3
"""
convert_all_traces_interpolation.py
=====================================
Converts trimmed ICMP ping logs and UDP pcap files to mahimahi format
for all 9 static traces using high fill value for empty slots.

Empty slots filled with 3,600,000 ms instead of carry forward.
Loss rate set to 0 in run.sh when using these traces.

Input (from trimmed_traces_20260207):
    icmp_ul_trimmed.log   uplink ICMP ping log
    udp_ul_trimmed.pcap   uplink UDP pcap

Output saved to new_mahimahi_traces_interpolation/<trace_id>/uplink/:
    delay_uplink.txt   one-way delay per 10ms slot
    bw_uplink.txt      mahimahi packet timestamps
"""

import os
import subprocess

# ── CONFIG ────────────────────────────────────────────────────────────────────
TRIMMED_BASE = "/mnt/nuwinslab_nas/nuwins_data_platform/datasets/bos_phi_trip_202601/trimmed_traces_20260207"
OUTPUT_BASE  = "/mnt/nuwinslab_nas/nuwins_data_platform/datasets/bos_phi_trip_202601/new_mahimahi_traces_interpolation"
SCRIPT       = os.path.expanduser("~/graphs/parse_recorder_to_replayer_interpolation.py")

TRACES = [
    "1770506564594-0500",
    "1770506824350-0500",
    "1770507107930-0500",
    "1770508413242-0500",
    "1770508674186-0500",
    "1770508935404-0500",
    "1770509197343-0500",
    "1770509458429-0500",
    "1770509718695-0500",
]

# ── MAIN ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    os.makedirs(OUTPUT_BASE, exist_ok=True)

    for trace_id in TRACES:
        print(f"\n{'='*60}")
        print(f"Processing uplink: {trace_id}")

        ping_file  = os.path.join(TRIMMED_BASE, trace_id, "icmp_ul_trimmed.log")
        pcap_file  = os.path.join(TRIMMED_BASE, trace_id, "udp_ul_trimmed.pcap")
        output_dir = os.path.join(OUTPUT_BASE,  trace_id, "uplink")
        os.makedirs(output_dir, exist_ok=True)

        if not os.path.exists(ping_file):
            print(f"  [WARN] ICMP log not found: {ping_file}")
            continue
        if not os.path.exists(pcap_file):
            print(f"  [WARN] Pcap not found: {pcap_file}")
            continue

        cmd = [
            "python3", SCRIPT,
            "--ping_file",    ping_file,
            "--pcap_file",    pcap_file,
            "--output_dir",   output_dir,
            "--trace_id",     "1",
            "--fill_delay_ms", "3600000",
        ]

        result = subprocess.run(cmd, capture_output=False, text=True)

        if result.returncode == 0:
            os.rename(
                os.path.join(output_dir, "delay_1.txt"),
                os.path.join(output_dir, "delay_uplink.txt")
            )
            os.rename(
                os.path.join(output_dir, "bw_1.txt"),
                os.path.join(output_dir, "bw_uplink.txt")
            )
            print(f"  Saved: {output_dir}/delay_uplink.txt")
            print(f"  Saved: {output_dir}/bw_uplink.txt")
        else:
            print(f"  [ERROR] Conversion failed for {trace_id}")

    print("\nAll 9 uplink traces converted.")
    print(f"Output: {OUTPUT_BASE}")
