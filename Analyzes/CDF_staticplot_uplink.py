#!/usr/bin/env python3
"""
cdf_plot_interpolation_3600000ms.py
=====================================
Plots CDF of throughput and one-way delay across all 9 static uplink traces
for 3 CCAs: Cubic, BBR, LeoCC (min_rtt_fluctuation=10000, 3600000ms fill value).

Each data point = per-500ms throughput sample or per-packet delay sample

Output: cdf_interpolation_3600000ms.png saved to ~/graphs/
"""

import os
import subprocess
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from collections import defaultdict

# ── CONFIG ────────────────────────────────────────────────────────────────────
BASE = os.path.expanduser("~/zach/LeoCC/LeoCC/leoreplayer/replayer/static_traces_interpolation")
OUT  = os.path.expanduser("~/graphs")
os.makedirs(OUT, exist_ok=True)

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

DURATION = 120

CCAS = [
    ("cubic",  "results_cubic",  "Cubic",         "red"),
    ("bbr",    "results_bbr",    "BBR",           "green"),
    ("leocc",  "results_leocc",  "LeoCC (10000)", "purple"),
]

# ── HELPER FUNCTIONS ──────────────────────────────────────────────────────────

def throughput_from_pcap(pcap_path, duration=DURATION):
    if not os.path.exists(pcap_path):
        print(f"    WARNING: pcap not found: {pcap_path}")
        return []
    try:
        result = subprocess.run(
            ["tshark", "-r", pcap_path, "-T", "fields",
             "-e", "frame.time_relative", "-e", "frame.len"],
            capture_output=True, text=True, timeout=360
        )
        bins = defaultdict(int)
        for line in result.stdout.splitlines():
            parts = line.strip().split()
            if len(parts) == 2:
                try:
                    slot = int(float(parts[0]) * 2)
                    if 0 <= slot < duration * 2:
                        bins[slot] += int(parts[1])
                except ValueError:
                    continue
        samples = [bins.get(s, 0) * 8 / 1e6 / 0.5 for s in range(duration * 2)]
        samples = [s for s in samples if s > 0]
        return samples
    except Exception as e:
        print(f"    ERROR: {e}")
        return []


def extract_ts_map(pcap_path):
    if not os.path.exists(pcap_path):
        return {}
    try:
        result = subprocess.run(
            f"tcpdump -r {pcap_path} -tt -n 2>/dev/null",
            shell=True, capture_output=True, text=True, timeout=120
        )
        ts_map = {}
        for line in result.stdout.splitlines():
            try:
                parts = line.split()
                epoch = float(parts[0])
                for i, p in enumerate(parts):
                    if p == "val":
                        ts_val = int(parts[i+1].rstrip(','))
                        if ts_val not in ts_map:
                            ts_map[ts_val] = epoch
                        break
            except (ValueError, IndexError):
                continue
        return ts_map
    except:
        return {}


def delay_from_pcaps(sender_pcap, receiver_pcap, duration=DURATION):
    if not os.path.exists(sender_pcap) or not os.path.exists(receiver_pcap):
        print(f"    WARNING: pcap not found")
        return []
    sender_map   = extract_ts_map(sender_pcap)
    receiver_map = extract_ts_map(receiver_pcap)
    delays = []
    t0 = min(sender_map.values()) if sender_map else 0
    for ts_val, recv_time in receiver_map.items():
        if ts_val in sender_map:
            delay_ms = (recv_time - sender_map[ts_val]) * 1000
            if 0 <= delay_ms <= 150:
                rel = recv_time - t0
                if 0 <= rel <= duration:
                    delays.append(delay_ms)
    return delays


# ── COLLECT DATA ──────────────────────────────────────────────────────────────

all_tput  = {cca_key: [] for cca_key, _, _, _ in CCAS}
all_delay = {cca_key: [] for cca_key, _, _, _ in CCAS}

for trace_id in TRACES:
    print(f"\n{'='*50}")
    print(f"Trace: {trace_id}")
    tdir = os.path.join(BASE, trace_id, "uplink")

    for cca_key, results_folder, label, color in CCAS:
        results_dir   = os.path.join(tdir, results_folder)
        tput_pcap     = os.path.join(results_dir, "n2.pcap")
        sender_pcap   = os.path.join(results_dir, "n1.pcap")
        receiver_pcap = os.path.join(results_dir, "n2.pcap")

        print(f"  [{label}]")

        tput_samples = throughput_from_pcap(tput_pcap)
        all_tput[cca_key].extend(tput_samples)
        print(f"    Throughput samples: {len(tput_samples)}  avg={np.mean(tput_samples):.1f} Mbps" if tput_samples else "    No throughput data")

        delay_samples = delay_from_pcaps(sender_pcap, receiver_pcap)
        all_delay[cca_key].extend(delay_samples)
        print(f"    Delay samples: {len(delay_samples)}  avg={np.mean(delay_samples):.1f} ms" if delay_samples else "    No delay data")

# ── PLOT CDF ──────────────────────────────────────────────────────────────────

fig, axes = plt.subplots(1, 2, figsize=(14, 6))
fig.suptitle("CDF of Throughput and One-Way Delay — All 9 Uplink Traces (3600000ms Interpolation)",
             fontsize=13, fontweight='bold')

ax1 = axes[0]
for cca_key, _, label, color in CCAS:
    data = sorted(all_tput[cca_key])
    if data:
        cdf = np.arange(1, len(data) + 1) / len(data)
        ax1.plot(data, cdf, color=color, lw=1.5, label=label)
ax1.set_xlabel("Throughput (Mbps)", fontsize=11)
ax1.set_ylabel("CDF", fontsize=11)
ax1.set_title("CDF of Throughput (500ms granularity)", fontsize=10)
ax1.legend(fontsize=9)
ax1.grid(True, alpha=0.3)
ax1.set_xlim(left=0)
ax1.set_ylim(0, 1)

ax2 = axes[1]
for cca_key, _, label, color in CCAS:
    data = sorted(all_delay[cca_key])
    if data:
        cdf = np.arange(1, len(data) + 1) / len(data)
        ax2.plot(data, cdf, color=color, lw=1.5, label=label)
ax2.set_xlabel("One-Way Delay (ms)", fontsize=11)
ax2.set_ylabel("CDF", fontsize=11)
ax2.set_title("CDF of One-Way Delay (per packet)", fontsize=10)
ax2.legend(fontsize=9)
ax2.grid(True, alpha=0.3)
ax2.set_xlim(0, 200)
ax2.set_ylim(0, 1)

plt.tight_layout()
out_path = os.path.join(OUT, "cdf_interpolation_3600000ms.png")
plt.savefig(out_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"\nSaved: {out_path}")
