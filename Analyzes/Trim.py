#!/usr/bin/env python3
"""
trim_common_window.py
=====================
Step 1 of the new trace parsing pipeline.

For each trace and direction, finds the common time window between
the ICMP ping log and the UDP pcap file, then trims both to that
exact window so they are perfectly aligned.

Common window:
    start = max(icmp_start, pcap_start)  <- later of the two starts
    end   = min(icmp_end,   pcap_end)    <- earlier of the two ends

Direction conventions:
    Downlink: use client side pcap (udp_dl_client*.pcap)
    Uplink  : use server side pcap (udp_ul_server*.pcap)

Input:
    Raw ICMP ping logs and UDP pcap files from field trip data.

Output:
    Trimmed ICMP ping log files saved to trimmed_traces_20260207/:
    <trace_id>/icmp_dl_trimmed.log
    <trace_id>/icmp_ul_trimmed.log
    Also prints common window stats for verification.
"""

import os
import re
import subprocess
from glob import glob

# ── CONFIG ────────────────────────────────────────────────────────────────────

CLIENT_BASE = "/mnt/nuwinslab_nas/nuwins_data_platform/datasets/bos_phi_trip_202601/client/20260207"
SERVER_BASE = "/mnt/nuwinslab_nas/nuwins_data_platform/datasets/bos_phi_trip_202601/server/20260207"
OUTPUT_BASE = "/mnt/nuwinslab_nas/nuwins_data_platform/datasets/bos_phi_trip_202601/trimmed_traces_20260207"

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


# ── HELPER FUNCTIONS ──────────────────────────────────────────────────────────

def get_icmp_time_range(log_file):
    """
    Get start and end epoch timestamps from ICMP ping log.
    Uses the internal timestamp [1770506568.318547] format from each ping line.
    Returns (start_epoch, end_epoch) as floats.
    """
    ts_pattern = re.compile(r'\[(\d+\.\d+)\]')
    first_ts = None
    last_ts  = None

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
    """
    Get start and end epoch timestamps from pcap file using tshark.
    Returns (start_epoch, end_epoch) as floats.
    """
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
    """
    Trim pcap file to time window using editcap with Unix epoch timestamps.
    Returns True if successful, False otherwise.
    """
    cmd = [
        'editcap',
        '-B', str(start_epoch),
        '-A', str(end_epoch),
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
    """
    Trim ICMP ping log to exact time window.
    Only keeps lines where internal timestamp falls within [start_epoch, end_epoch].
    Uses the exact first and last packet timestamps from the trimmed pcap
    so both files start and end at exactly the same moment.

    Returns (total_lines, kept_lines).
    """
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
    """
    Find common time window between ICMP ping log and pcap for one trace.
    Trims ICMP log to common window and saves to output directory.
    """
    print(f"\n{'='*60}")
    print(f"Trace: {trace_id}")

    output_path = os.path.join(OUTPUT_BASE, trace_id)
    os.makedirs(output_path, exist_ok=True)

    for direction in ("downlink", "uplink"):

        print(f"\n  [{direction}]")

        # Find correct files based on direction
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

        # Find files
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

        # Get time ranges
        icmp_start, icmp_end = get_icmp_time_range(icmp_file)
        pcap_start, pcap_end = get_pcap_time_range(pcap_file)

        if None in (icmp_start, icmp_end, pcap_start, pcap_end):
            print(f"    [WARN] Could not get time range")
            continue

        print(f"    Raw ICMP : start={icmp_start:.3f}  end={icmp_end:.3f}  dur={icmp_end-icmp_start:.2f}s")
        print(f"    Raw Pcap : start={pcap_start:.3f}  end={pcap_end:.3f}  dur={pcap_end-pcap_start:.2f}s")

        # Step 2 — Find rough common window
        rough_start = max(icmp_start, pcap_start)
        rough_end   = min(icmp_end,   pcap_end)

        if rough_end <= rough_start:
            print(f"    [ERROR] No common window found!")
            continue

        # Step 3 — Trim pcap to rough common window
        success = trim_pcap(pcap_file, pcap_out, rough_start, rough_end)
        if not success:
            print(f"    [ERROR] Pcap trimming failed")
            continue

        # Step 4 — Read exact timestamps from trimmed pcap
        # These are the ground truth start and end for both files
        exact_start, exact_end = get_pcap_time_range(pcap_out)
        if None in (exact_start, exact_end):
            print(f"    [ERROR] Could not read trimmed pcap timestamps")
            continue

        print(f"    Exact window : start={exact_start:.6f}  end={exact_end:.6f}  dur={exact_end-exact_start:.2f}s")

        # Step 5 — Trim ICMP log using exact pcap timestamps
        total, kept = trim_icmp_log(icmp_file, icmp_out, exact_start, exact_end)

        print(f"    ICMP pings   : total={total}  kept={kept}")

        # Step 6 — Verify alignment by checking trimmed ICMP timestamps
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