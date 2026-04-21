#!/usr/bin/env python3
"""
compute_mobility_loss.py
=========================
Computes per-run loss rates for all 16 mobility traces
for both uplink and downlink using Sizhe's RttPostProcessor.

Input: trimmed ICMP logs from trimmed_traces_mobility_20260208
Output: mobility_loss_rates.json saved to ~/graphs/mobility/
"""

import os
import re
import json
import sys
import pandas as pd

# Add mobility scripts folder to path to import RttPostProcessor
sys.path.insert(0, os.path.expanduser("~/graphs/mobility"))
from RttPostProcessor import RttPostProcessor

# ── CONFIG ────────────────────────────────────────────────────────────────────
TRIMMED_BASE = "/mnt/nuwinslab_nas/nuwins_data_platform/datasets/bos_phi_trip_202601/trimmed_traces_mobility_20260208"
OUTPUT_FILE  = os.path.expanduser("~/graphs/mobility/mobility_loss_rates.json")

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

def parse_icmp_log(log_path):
    """Parse trimmed ICMP log into DataFrame with utc_ts and icmp_seq columns."""
    pattern = re.compile(r'\[(\d+\.\d+)\].*icmp_seq=(\d+).*time=(\d+\.?\d*)\s*ms')
    rows = []
    with open(log_path, 'r') as f:
        for line in f:
            match = pattern.search(line)
            if match:
                ts     = float(match.group(1)) * 1000  # convert to ms
                seq    = int(match.group(2))
                rtt_ms = float(match.group(3))
                rows.append({
                    'utc_ts'  : ts,
                    'icmp_seq': seq,
                    'rtt_ms'  : rtt_ms,
                    'ping_session_id': 1  # single session per file
                })
    return pd.DataFrame(rows)

# ── MAIN ──────────────────────────────────────────────────────────────────────

results = {}

print(f"{'='*65}")
print(f"{'Trace':<25} {'Direction':<12} {'Expected':>10} {'Received':>10} {'Loss%':>8}")
print(f"{'='*65}")

for trace_id in TRACES:
    results[trace_id] = {}

    for direction, fname in [("uplink", "icmp_ul_trimmed.log"), ("downlink", "icmp_dl_trimmed.log")]:
        log_path = os.path.join(TRIMMED_BASE, trace_id, fname)

        if not os.path.exists(log_path):
            print(f"{trace_id:<25} {direction:<12} {'MISSING':>10}")
            results[trace_id][direction] = None
            continue

        df = parse_icmp_log(log_path)

        if df.empty:
            print(f"{trace_id:<25} {direction:<12} {'NO DATA':>10}")
            results[trace_id][direction] = None
            continue

        stats = RttPostProcessor.compute_session_loss(df['utc_ts'], df['icmp_seq'])

        loss_rate_decimal = round(stats['loss_rate_pct'] / 100, 10)

        results[trace_id][direction] = {
            'icmp_overall_loss_rate': loss_rate_decimal,
            'icmp_recv'             : stats['received'],
            'icmp_total'            : stats['expected'],
        }

        print(f"{trace_id:<25} {direction:<12} {stats['expected']:>10} {stats['received']:>10} {loss_rate_decimal:>12.10f}")

# Save results
with open(OUTPUT_FILE, 'w') as f:
    json.dump(results, f, indent=2)

print(f"\nSaved to: {OUTPUT_FILE}")
