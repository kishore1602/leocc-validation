#!/usr/bin/env python3
"""
scatter_box_plot_uplink.py
==========================
Plots throughput vs one-way delay box plot across all 9 static uplink traces
for 4 CCAs: Cubic, BBR, LeoCC_20000, LeoCC_5000.

Follows Figure style:
    - Box: 25th-75th percentile
    - Whiskers: 5th-95th percentile (dotted lines)
    - Center point: median intersection
    - "Better" arrow in upper left

Output: scatter_box_uplink.png saved to ~/graphs/
"""

import os
import subprocess
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from collections import defaultdict

# ── CONFIG ────────────────────────────────────────────────────────────────────
BASE = os.path.expanduser("~/zach/LeoCC/LeoCC/leoreplayer/replayer/static_traces_20260207")
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
    ("cubic",       "results_cubic",       "Cubic",         "red"),
    ("bbr",         "results_bbr",         "BBR",           "green"),
    ("leocc_20000", "results_leocc_20000", "LeoCC (20000)", "blue"),
    ("leocc_5000",  "results_leocc_5000",  "LeoCC (5000)",  "purple"),
]

# ── HELPER FUNCTIONS ──────────────────────────────────────────────────────────

def avg_throughput_from_pcap(pcap_path, duration=DURATION):
    if not os.path.exists(pcap_path):
        return None
    try:
        result = subprocess.run(
            ["tshark", "-r", pcap_path, "-T", "fields",
             "-e", "frame.time_relative", "-e", "frame.len"],
            capture_output=True, text=True, timeout=360
        )
        total_bytes = 0
        for line in result.stdout.splitlines():
            parts = line.strip().split()
            if len(parts) == 2:
                try:
                    t = float(parts[0])
                    if 0 <= t <= duration:
                        total_bytes += int(parts[1])
                except ValueError:
                    continue
        return total_bytes * 8 / 1e6 / duration
    except:
        return None


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


def avg_delay_from_pcaps(sender_pcap, receiver_pcap, duration=DURATION):
    if not os.path.exists(sender_pcap) or not os.path.exists(receiver_pcap):
        return None
    sender_map   = extract_ts_map(sender_pcap)
    receiver_map = extract_ts_map(receiver_pcap)
    delays = []
    t0 = min(sender_map.values()) if sender_map else 0
    for ts_val, recv_time in receiver_map.items():
        if ts_val in sender_map:
            delay_ms = (recv_time - sender_map[ts_val]) * 1000
            if 0 <= delay_ms <= 2000:
                rel = recv_time - t0
                if 0 <= rel <= duration:
                    delays.append(delay_ms)
    return np.mean(delays) if delays else None


# ── COLLECT DATA ──────────────────────────────────────────────────────────────

data = {cca_key: [] for cca_key, _, _, _ in CCAS}

for trace_id in TRACES:
    print(f"\n{'='*50}")
    print(f"Trace: {trace_id}")
    tdir = os.path.join(BASE, trace_id, "uplink")

    for cca_key, results_folder, label, color in CCAS:
        results_dir   = os.path.join(tdir, results_folder)
        tput_pcap     = os.path.join(results_dir, "n2.pcap")
        sender_pcap   = os.path.join(results_dir, "n1.pcap")
        receiver_pcap = os.path.join(results_dir, "n2.pcap")

        avg_tput  = avg_throughput_from_pcap(tput_pcap)
        avg_delay = avg_delay_from_pcaps(sender_pcap, receiver_pcap)

        if avg_tput is not None and avg_delay is not None:
            data[cca_key].append((avg_tput, avg_delay))
            print(f"  [{label}] tput={avg_tput:.1f} Mbps  delay={avg_delay:.1f} ms")
        else:
            print(f"  [{label}] missing data")

# ── PLOT BOX PLOT ─────────────────────────────────────────────────────────────

fig, ax = plt.subplots(figsize=(10, 8))
ax.set_title("Average Throughput vs One-Way Delay — All 9 Uplink Traces",
             fontsize=12, fontweight='bold')

legend_handles = []

for cca_key, _, label, color in CCAS:
    points = data[cca_key]
    if not points:
        continue

    tputs  = [p[0] for p in points]
    delays = [p[1] for p in points]

    # Percentiles
    t5,  t25, t50, t75, t95  = np.percentile(tputs,  [5, 25, 50, 75, 95])
    d5,  d25, d50, d75, d95  = np.percentile(delays, [5, 25, 50, 75, 95])

    # Draw box (25th-75th percentile) with fill
    box = mpatches.FancyBboxPatch(
        (d25, t25), d75 - d25, t75 - t25,
        boxstyle="square,pad=0",
        linewidth=1.5, edgecolor=color, facecolor=color, alpha=0.25
    )
    ax.add_patch(box)

    # Horizontal whisker (delay 5th-95th) — dotted
    ax.plot([d5, d25], [t50, t50], color=color, lw=1.5, ls='--')
    ax.plot([d75, d95], [t50, t50], color=color, lw=1.5, ls='--')
    # End caps
    ax.plot([d5,  d5],  [t50 - 0.8, t50 + 0.8], color=color, lw=1.5)
    ax.plot([d95, d95], [t50 - 0.8, t50 + 0.8], color=color, lw=1.5)

    # Vertical whisker (throughput 5th-95th) — dotted
    ax.plot([d50, d50], [t5,  t25], color=color, lw=1.5, ls='--')
    ax.plot([d50, d50], [t75, t95], color=color, lw=1.5, ls='--')
    # End caps
    ax.plot([d50 - 0.4, d50 + 0.4], [t5,  t5],  color=color, lw=1.5)
    ax.plot([d50 - 0.4, d50 + 0.4], [t95, t95], color=color, lw=1.5)

    # Median intersection point
    ax.scatter([d50], [t50], color=color, s=80, zorder=6,
               marker='o', edgecolors='black', linewidth=1.0)

    legend_handles.append(mpatches.Patch(facecolor=color, edgecolor=color, alpha=0.5, label=label))

# "Better" arrow — upper left direction
ax.annotate('', xy=(0.12, 0.88), xytext=(0.22, 0.78),
            xycoords='axes fraction',
            arrowprops=dict(arrowstyle='->', color='red', lw=2.5))
ax.text(0.10, 0.90, 'Better', transform=ax.transAxes,
        fontsize=12, color='red', fontweight='bold')

ax.set_xlabel("Average One-Way Delay (ms)", fontsize=11)
ax.set_ylabel("Average Throughput (Mbps)", fontsize=11)
ax.legend(handles=legend_handles, fontsize=10, loc='lower right')
ax.grid(True, alpha=0.3)
ax.set_xlim(left=0)
ax.set_ylim(bottom=0)

plt.tight_layout()
out_path = os.path.join(OUT, "scatter_box_uplink.png")
plt.savefig(out_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"\nSaved: {out_path}")
