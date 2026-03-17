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


def trim_icmp_log(log_file, output_file, start_epoch, end_epoch):
    """
    Trim ICMP ping log to the common time window.
    Only keeps lines where the internal timestamp falls within [start, end].
    Header and footer lines (Start time, End time, PING) are excluded.
    """
    ts_pattern  = re.compile(r'\[(\d+\.\d+)\]')
    rtt_pattern = re.compile(r'time=([0-9.]+)\s*ms')

    kept  = 0
    total = 0

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


def trim_pcap(pcap_file, output_file, start_epoch, end_epoch):
    """
    Trim pcap file to the common time window using editcap.
    Uses -A (start time) and -B (end time) flags with epoch timestamps.

    Args:
        pcap_file   : Path to input pcap file
        output_file : Path to output trimmed pcap file
        start_epoch : Common window start time as epoch float
        end_epoch   : Common window end time as epoch float

    Returns:
        True if successful, False otherwise
    """
    # Convert epoch float to editcap datetime format: YYYY-MM-DD HH:MM:SS.ffffff
    from datetime import datetime, timezone
    start_dt = datetime.fromtimestamp(start_epoch, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")
    end_dt   = datetime.fromtimestamp(end_epoch,   tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")

    cmd = ['editcap', '-A', start_dt, '-B', end_dt, pcap_file, output_file]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            print(f"    [WARN] editcap error: {result.stderr.strip()}")
            return False
        return True
    except Exception as e:
        print(f"    [WARN] editcap failed: {e}")
        return False


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

        print(f"    ICMP start : {icmp_start:.3f}  end : {icmp_end:.3f}  duration : {icmp_end - icmp_start:.2f}s")
        print(f"    Pcap start : {pcap_start:.3f}  end : {pcap_end:.3f}  duration : {pcap_end - pcap_start:.2f}s")

        # Find common window
        common_start = max(icmp_start, pcap_start)
        common_end   = min(icmp_end,   pcap_end)
        common_dur   = common_end - common_start

        print(f"    Common start : {common_start:.3f}")
        print(f"    Common end   : {common_end:.3f}")
        print(f"    Common dur   : {common_dur:.2f}s")

        if common_dur <= 0:
            print(f"    [ERROR] No common window found!")
            continue

        # Trim ICMP log to common window
        total, kept = trim_icmp_log(icmp_file, icmp_out, common_start, common_end)
        print(f"    Total pings  : {total}")
        print(f"    Kept pings   : {kept}")
        print(f"    ICMP saved   : {icmp_out}")

        # Trim pcap to common window using editcap
        success = trim_pcap(pcap_file, pcap_out, common_start, common_end)
        if success:
            print(f"    Pcap saved   : {pcap_out}")
        else:
            print(f"    [WARN] Pcap trimming failed for {pcap_file}")


# ── MAIN ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    os.makedirs(OUTPUT_BASE, exist_ok=True)
    print(f"Output directory: {OUTPUT_BASE}")

for trace_id in TRACES:
    process_trace(trace_id)