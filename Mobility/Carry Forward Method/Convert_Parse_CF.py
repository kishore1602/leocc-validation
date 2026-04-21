#!/usr/bin/env python3
"""
convert_mobility_carryforward.py
=================================
Converts trimmed ICMP ping logs and UDP pcap files to mahimahi format
for all 16 good mobility traces using carry-forward method.

Input (from trimmed_traces_mobility_20260208):
    icmp_ul_trimmed.log   uplink ICMP ping log
    udp_ul_trimmed.pcap   uplink UDP pcap
    icmp_dl_trimmed.log   downlink ICMP ping log
    udp_dl_trimmed.pcap   downlink UDP pcap

Output saved to new_mahimahi_traces_mobility_carryforward/<trace_id>/uplink/:
    delay_uplink.txt
    bw_uplink.txt

Output saved to new_mahimahi_traces_mobility_carryforward/<trace_id>/downlink/:
    delay_downlink.txt
    bw_downlink.txt
"""
import os
import subprocess

# ── CONFIG ────────────────────────────────────────────────────────────────────
TRIMMED_BASE = "/mnt/nuwinslab_nas/nuwins_data_platform/datasets/bos_phi_trip_202601/trimmed_traces_mobility_20260208"
OUTPUT_BASE  = "/mnt/nuwinslab_nas/nuwins_data_platform/datasets/bos_phi_trip_202601/new_mahimahi_traces_mobility_carryforward"
SCRIPT       = os.path.expanduser("~/graphs/mobility/parse_recorder_carryforward_mobility.py")

TRACES = [
    "1770565256238-0500",
    "1770565515966-0500",
    "1770565775416-0500",
    "1770566174757-0500",
    "1770566435822-0500",
    "1770566695147-0500",
    "1770566954461-0500",
    "1770567213734-0500",
    "1770567473399-0500",
    "1770567733345-0500",
    "1770567992320-0500",
    "1770568251875-0500",
    "1770568779853-0500",
    "1770569039333-0500",
    "1770569298579-0500",
    "1770569558888-0500",
]

DIRECTIONS = [
    ("uplink",   "icmp_ul_trimmed.log", "udp_ul_trimmed.pcap", "delay_uplink.txt",   "bw_uplink.txt"),
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

    print("\nAll 16 mobility traces converted (carry-forward).")
    print(f"Output: {OUTPUT_BASE}")
