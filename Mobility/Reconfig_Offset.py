#!/usr/bin/env python3
"""
extract_reconfig_mobility.py
=============================
Extracts reconfiguration offset for all 16 mobility traces
for both uplink and downlink separately.

Logic:
    1. Read trimmed ICMP log (uplink and downlink separately)
    2. Find RTT spikes (>80ms) and group into clusters
    3. Find clusters that repeat at ~15 second intervals (global reconfig)
    4. Ignore isolated clusters (local/aperiodic reconfig)
    5. Offset = first occurrence of the global reconfig cluster

Output: saves to reconfig_offsets_mobility.json with separate ul/dl offsets
"""

import os
import re
import json
import numpy as np

# ── CONFIG ────────────────────────────────────────────────────────────────────
TRIMMED_BASE = "/mnt/nuwinslab_nas/nuwins_data_platform/datasets/bos_phi_trip_202601/trimmed_traces_mobility_20260208"
OUTPUT_FILE  = os.path.expanduser("~/graphs/mobility/reconfig_offsets_mobility.json")

SPIKE_THRESHOLD  = 80
CLUSTER_GAP      = 1.0
PERIOD           = 15.0
PERIOD_TOLERANCE = 2.0
MIN_OCCURRENCES  = 3

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
    pattern = re.compile(r'\[(\d+\.\d+)\].*time=(\d+\.?\d*)\s*ms')
    samples = []
    with open(log_path, 'r') as f:
        for line in f:
            match = pattern.search(line)
            if match:
                ts  = float(match.group(1))
                rtt = float(match.group(2))
                samples.append((ts, rtt))
    if not samples:
        return [], 0
    t0 = samples[0][0]
    return [(ts - t0, rtt) for ts, rtt in samples], t0


def find_clusters(samples):
    spike_times = [t for t, rtt in samples if rtt > SPIKE_THRESHOLD]
    if not spike_times:
        return []
    clusters = []
    current  = [spike_times[0]]
    for t in spike_times[1:]:
        if t - current[-1] < CLUSTER_GAP:
            current.append(t)
        else:
            clusters.append(round(np.mean(current), 3))
            current = [t]
    clusters.append(round(np.mean(current), 3))
    return clusters


def find_global_reconfig_offset(clusters):
    if not clusters:
        return None, []
    best_cluster = None
    best_count   = 0
    best_chain   = []
    for i, c in enumerate(clusters):
        chain = [c]
        for j, other in enumerate(clusters):
            if i == j:
                continue
            diff = other - c
            remainder = diff % PERIOD
            if remainder > PERIOD / 2:
                remainder = PERIOD - remainder
            if remainder <= PERIOD_TOLERANCE and diff > 0:
                chain.append(other)
        if len(chain) > best_count:
            best_count   = len(chain)
            best_cluster = c
            best_chain   = sorted(chain)
    if best_count >= MIN_OCCURRENCES:
        return best_cluster, best_chain
    return clusters[0], clusters[:1]


def process_icmp(log_path):
    if not os.path.exists(log_path):
        return None, [], 0
    samples, t0  = parse_icmp_log(log_path)
    spike_times  = [t for t, rtt in samples if rtt > SPIKE_THRESHOLD]
    clusters     = find_clusters(samples)
    offset, chain = find_global_reconfig_offset(clusters)
    return offset, chain, len(spike_times)


# ── MAIN ──────────────────────────────────────────────────────────────────────

results = {}

print(f"{'='*70}")
print(f"{'Trace':<25} {'UL Offset':>12} {'DL Offset':>12}")
print(f"{'='*70}")

for trace_id in TRACES:
    ul_path = os.path.join(TRIMMED_BASE, trace_id, "icmp_ul_trimmed.log")
    dl_path = os.path.join(TRIMMED_BASE, trace_id, "icmp_dl_trimmed.log")

    ul_offset, ul_chain, ul_spikes = process_icmp(ul_path)
    dl_offset, dl_chain, dl_spikes = process_icmp(dl_path)

    results[trace_id] = {
        "uplink": {
            "offset_sec"   : ul_offset,
            "spike_count"  : ul_spikes,
            "global_chain" : ul_chain,
        },
        "downlink": {
            "offset_sec"   : dl_offset,
            "spike_count"  : dl_spikes,
            "global_chain" : dl_chain,
        },
    }

    print(f"{trace_id:<25} {str(ul_offset):>12} {str(dl_offset):>12}")
    print(f"  UL chain: {ul_chain[:6]}")
    print(f"  DL chain: {dl_chain[:6]}")

# Save results
with open(OUTPUT_FILE, 'w') as f:
    json.dump(results, f, indent=2)

print(f"\nSaved to: {OUTPUT_FILE}")
