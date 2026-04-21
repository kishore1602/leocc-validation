#!/usr/bin/env python3
"""
trim_common_window_mobility.py
===============================
Trims ICMP ping logs and UDP pcap files to common time window
for all mobility traces from 20260208.

Direction conventions:
    Downlink: client side pcap (udp_dl_client*.pcap)
    Uplink  : server side pcap (udp_ul_server*.pcap)

Output saved to trimmed_traces_mobility_20260208/<trace_id>/:
    icmp_dl_trimmed.log
    icmp_ul_trimmed.log
    udp_dl_trimmed.pcap
    udp_ul_trimmed.pcap
"""

import os
import re
import subprocess
from glob import glob

# ── CONFIG ────────────────────────────────────────────────────────────────────

CLIENT_BASE = "/mnt/nuwinslab_nas/nuwins_data_platform/datasets/bos_phi_trip_202601/client/20260208"
SERVER_BASE = "/mnt/nuwinslab_nas/nuwins_data_platform/datasets/bos_phi_trip_202601/server/20260208"
OUTPUT_BASE = "/mnt/nuwinslab_nas/nuwins_data_platform/datasets/bos_phi_trip_202601/trimmed_traces_mobility_20260208"

TRACES = [
    "1770565256238-0500",
    "1770565515966-0500",
    "1770565775416-0500",
    "1770566034975-0500",
    "1770566174757-0500",
    "1770566435822-0500",
    "1770566695147-0500",
    "1770566954461-0500",
    "1770567213734-0500",
    "1770567473399-0500",
    "1770567733345-0500",
    "1770567992320-0500",
    "1770568251875-0500",
    "1770568520376-0500",
    "1770568779853-0500",
    "1770569039333-0500",
    "1770569298579-0500",
    "1770569558888-0500",
    "1770569819104-0500",
]


# ── HELPER FUNCTIONS ──────────────────────────────────────────────────────────

def get_icmp_time_range(log_file):
    ts_pattern = re.compile(r'\[(\d+\.\d+)\]')
    first_ts   = None
    last_ts    = None

    with open(log_file, 'r') as f:
        for line in f:
            match = ts_pattern.search(line)
            if match:
                ts = float(match.group(1))
                if first_ts is None:
                    first_ts = ts
                last_ts = ts

    return first_ts, last_ts


def get_pcap_time_range(pcap_file):
    result = subprocess.run(
        f"tshark -r {pcap_file} -T fields -e frame.time_epoch 2>/dev/null",
        shell=True, capture_output=True, text=True, timeout=300
    )
    timestamps = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if line:
            try:
                timestamps.append(float(line))
            except ValueError:
                continue

    if not timestamps:
        return None, None

    return timestamps[0], timestamps[-1]


def trim_pcap(pcap_file, output_file, start_epoch, end_epoch):
    cmd = [
        'editcap',
        '-A', str(start_epoch),
        '-B', str(end_epoch),
        pcap_file,
        output_file
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            print(f"    [WARN] editcap error: {result.stderr.strip()}")
            return False
        return True
    except Exception as e:
        print(f"    [WARN] editcap failed: {e}")
        return False


def trim_icmp_log(log_file, output_file, start_epoch, end_epoch):
    ts_pattern  = re.compile(r'\[(\d+\.\d+)\]')
    rtt_pattern = re.compile(r'time=([0-9.]+)\s*ms')

    total = 0
    kept  = 0

    with open(log_file, 'r') as f_in, open(output_file, 'w') as f_out:
        for line in f_in:
            ts_match = ts_pattern.search(line)
            if ts_match and rtt_pattern.search(line):
                total += 1
                ts = float(ts_match.group(1))
                if start_epoch <= ts <= end_epoch:
                    f_out.write(line)
                    kept += 1

    return total, kept


# ── MAIN PROCESSING FUNCTION ──────────────────────────────────────────────────

def process_trace(trace_id):
    print(f"\n{'='*60}")
    print(f"Trace: {trace_id}")

    output_path = os.path.join(OUTPUT_BASE, trace_id)
    os.makedirs(output_path, exist_ok=True)

    for direction in ("downlink", "uplink"):
        print(f"\n  [{direction}]")

        if direction == "downlink":
            icmp_pattern = os.path.join(CLIENT_BASE, trace_id, "icmp_ping_dl_client*.log")
            pcap_pattern = os.path.join(CLIENT_BASE, trace_id, "udp_dl_client*.pcap")
            icmp_out     = os.path.join(output_path, "icmp_dl_trimmed.log")
            pcap_out     = os.path.join(output_path, "udp_dl_trimmed.pcap")
        else:
            icmp_pattern = os.path.join(CLIENT_BASE, trace_id, "icmp_ping_ul_client*.log")
            pcap_pattern = os.path.join(SERVER_BASE, trace_id, "udp_ul_server*.pcap")
            icmp_out     = os.path.join(output_path, "icmp_ul_trimmed.log")
            pcap_out     = os.path.join(output_path, "udp_ul_trimmed.pcap")

        icmp_matches = glob(icmp_pattern)
        pcap_matches = glob(pcap_pattern)

        if not icmp_matches:
            print(f"    [WARN] ICMP log not found: {icmp_pattern}")
            continue
        if not pcap_matches:
            print(f"    [WARN] Pcap not found: {pcap_pattern}")
            continue

        icmp_file = icmp_matches[0]
        pcap_file = pcap_matches[0]

        print(f"    ICMP : {os.path.basename(icmp_file)}")
        print(f"    Pcap : {os.path.basename(pcap_file)}")

        icmp_start, icmp_end = get_icmp_time_range(icmp_file)
        pcap_start, pcap_end = get_pcap_time_range(pcap_file)

        if None in (icmp_start, icmp_end, pcap_start, pcap_end):
            print(f"    [WARN] Could not get time range")
            continue

        print(f"    Raw ICMP : start={icmp_start:.3f}  end={icmp_end:.3f}  dur={icmp_end-icmp_start:.2f}s")
        print(f"    Raw Pcap : start={pcap_start:.3f}  end={pcap_end:.3f}  dur={pcap_end-pcap_start:.2f}s")

        rough_start = max(icmp_start, pcap_start)
        rough_end   = min(icmp_end,   pcap_end)

        if rough_end <= rough_start:
            print(f"    [ERROR] No common window found!")
            continue

        success = trim_pcap(pcap_file, pcap_out, rough_start, rough_end)
        if not success:
            print(f"    [ERROR] Pcap trimming failed")
            continue

        exact_start, exact_end = get_pcap_time_range(pcap_out)

        if None in (exact_start, exact_end):
            print(f"    [ERROR] Could not read trimmed pcap timestamps")
            continue

        print(f"    Exact window : start={exact_start:.6f}  end={exact_end:.6f}  dur={exact_end-exact_start:.2f}s")

        total, kept = trim_icmp_log(icmp_file, icmp_out, exact_start, exact_end)

        print(f"    ICMP pings   : total={total}  kept={kept}")

        icmp_trim_start, icmp_trim_end = get_icmp_time_range(icmp_out)

        if icmp_trim_start and icmp_trim_end:
            start_diff = abs(icmp_trim_start - exact_start) * 1000
            end_diff   = abs(icmp_trim_end   - exact_end)   * 1000
            print(f"    Alignment check:")
            print(f"      Pcap  start={exact_start:.6f}  end={exact_end:.6f}")
            print(f"      ICMP  start={icmp_trim_start:.6f}  end={icmp_trim_end:.6f}")
            print(f"      Start diff={start_diff:.2f}ms  End diff={end_diff:.2f}ms")

        print(f"    Saved ICMP : {icmp_out}")
        print(f"    Saved Pcap : {pcap_out}")


# ── MAIN ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    os.makedirs(OUTPUT_BASE, exist_ok=True)
    print(f"Output directory: {OUTPUT_BASE}")

    for trace_id in TRACES:
        process_trace(trace_id)

    print("\nAll mobility traces done.")
