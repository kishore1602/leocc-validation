#!/usr/bin/env python3
"""
convert_static_downlink_carryforward.py
=========================================
Converts trimmed ICMP ping logs and UDP pcap files to mahimahi format
for all 9 static traces (downlink only) using carry-forward method.

Input (from trimmed_traces_20260207):
    icmp_dl_trimmed.log   downlink ICMP ping log
    udp_dl_trimmed.pcap   downlink UDP pcap

Output saved to:
    /mnt/nuwinslab_nas/nuwins_data_platform/datasets/bos_phi_trip_202601/final_static_traces/<trace_id>/downlink/
        delay_downlink.txt
        bw_downlink.txt
"""

import os
import subprocess

# ── CONFIG ────────────────────────────────────────────────────────────────────
TRIMMED_BASE = "/mnt/nuwinslab_nas/nuwins_data_platform/datasets/bos_phi_trip_202601/trimmed_traces_20260207"
OUTPUT_BASE  = "/mnt/nuwinslab_nas/nuwins_data_platform/datasets/bos_phi_trip_202601/final_static_traces"
SCRIPT       = os.path.expanduser("~/graphs/static/parse_recorder_carryforward_static.py")

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

DIRECTIONS = [
    ("downlink", "icmp_dl_trimmed.log", "udp_dl_trimmed.pcap", "delay_downlink.txt", "bw_downlink.txt"),
]

# ── MAIN ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    for trace_id in TRACES:
        print(f"\n{'='*60}")
        print(f"Processing: {trace_id}")
        for direction, icmp_fname, pcap_fname, delay_out, bw_out in DIRECTIONS:
            print(f"\n  [{direction}]")
            ping_file  = os.path.join(TRIMMED_BASE, trace_id, icmp_fname)
            pcap_file  = os.path.join(TRIMMED_BASE, trace_id, pcap_fname)
            output_dir = os.path.join(OUTPUT_BASE,  trace_id, direction)
            os.makedirs(output_dir, exist_ok=True)

            if not os.path.exists(ping_file):
                print(f"  [WARN] ICMP log not found: {ping_file}")
                continue
            if not os.path.exists(pcap_file):
                print(f"  [WARN] Pcap not found: {pcap_file}")
                continue

            cmd = [
                "python3", SCRIPT,
                "--ping_file",  ping_file,
                "--pcap_file",  pcap_file,
                "--output_dir", output_dir,
                "--trace_id",   "1",
            ]

            result = subprocess.run(cmd, capture_output=False, text=True)

            if result.returncode == 0:
                os.rename(
                    os.path.join(output_dir, "delay_1.txt"),
                    os.path.join(output_dir, delay_out)
                )
                os.rename(
                    os.path.join(output_dir, "bw_1.txt"),
                    os.path.join(output_dir, bw_out)
                )
                print(f"  Saved: {output_dir}/{delay_out}")
                print(f"  Saved: {output_dir}/{bw_out}")
            else:
                print(f"  [ERROR] Conversion failed for {trace_id} {direction}")

    print("\nAll 9 static traces downlink converted (carry-forward).")
    print(f"Output: {OUTPUT_BASE}")
