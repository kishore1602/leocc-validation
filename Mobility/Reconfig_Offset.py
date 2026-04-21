#!/usr/bin/env python3
"""
extract_reconfig_timestamp_mobility.py
=======================================
Computes reconfiguration offset for all 16 mobility traces
using the global timestamp method.

Method:
    - Read the first ping timestamp from trimmed ICMP uplink log
    - Find position of t0 within the current minute (t0 % 60)
    - Find the nearest upcoming Starlink global reconfig boundary
      (12, 27, 42, 57 seconds of every minute)
    - Offset = distance from t0 to that nearest boundary

This method is reliable because Starlink global reconfigurations
happen synchronously worldwide at fixed 15-second intervals.

Output: reconfig_offsets_mobility_timestamp.json
"""

import os
import re
import json

# ── CONFIG ────────────────────────────────────────────────────────────────────
TRIMMED_BASE = "/mnt/nuwinslab_nas/nuwins_data_platform/datasets/bos_phi_trip_202601/trimmed_traces_mobility_20260208"
OUTPUT_FILE  = os.path.expanduser("~/graphs/mobility/reconfig_offsets_mobility_timestamp.json")

# Global Starlink reconfig boundaries (seconds within each minute)
GLOBAL_BOUNDARIES = [12, 27, 42, 57]

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

# ── HELPER FUNCTIONS ──────────────────────────────────────────────────────────

def get_first_timestamp(log_path):
    """Get the first ping timestamp from trimmed ICMP log."""
    pattern = re.compile(r'\[(\d+\.\d+)\].*time=(\d+\.?\d*)\s*ms')
    with open(log_path, 'r') as f:
        for line in f:
            match = pattern.search(line)
            if match:
                return float(match.group(1))
    return None


def compute_offset(t0):
    """
    Compute offset from t0 to nearest upcoming global reconfig boundary.
    
    Args:
        t0: First ping unix timestamp
        
    Returns:
        offset in seconds (rounded to 3 decimal places)
    """
    pos = t0 % 60  # position within current minute
    offsets = []
    for b in GLOBAL_BOUNDARIES:
        diff = b - pos
        if diff < 0:
            diff += 60
        offsets.append((diff, b))
    best_offset, best_boundary = min(offsets, key=lambda x: x[0])
    return round(best_offset, 3), best_boundary, round(pos, 3)


# ── MAIN ──────────────────────────────────────────────────────────────────────

results = {}

print(f"{'='*65}")
print(f"{'Trace':<25} {'t0_in_min':>10} {'Boundary':>10} {'Offset':>10}")
print(f"{'='*65}")

for trace_id in TRACES:
    ul_path = os.path.join(TRIMMED_BASE, trace_id, "icmp_ul_trimmed.log")

    if not os.path.exists(ul_path):
        print(f"{trace_id:<25} {'MISSING':>10}")
        continue

    t0 = get_first_timestamp(ul_path)
    if t0 is None:
        print(f"{trace_id:<25} {'NO DATA':>10}")
        continue

    offset, boundary, pos = compute_offset(t0)

    results[trace_id] = {
        "offset_sec"      : offset,
        "t0_unix"         : t0,
        "t0_in_minute"    : pos,
        "nearest_boundary": boundary,
    }

    print(f"{trace_id:<25} {pos:>10.3f} {boundary:>10} {offset:>10.3f}")

# Save results
with open(OUTPUT_FILE, 'w') as f:
    json.dump(results, f, indent=2)

print(f"\nSaved to: {OUTPUT_FILE}")
