#!/usr/bin/env python3
"""
verify_conversion.py
====================
4 subplots for all 9 traces to verify conversion:
    Row 1: Raw ICMP one-way delay scatter
    Row 2: delay_uplink.txt line plot
    Row 3: Raw pcap per-second Mbps
    Row 4: bw_uplink.txt per-second Mbps
"""

import re
import os
import subprocess
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from collections import defaultdict

# ── CONFIG ────────────────────────────────────────────────────────────────────
TRIMMED_BASE  = "/mnt/nuwinslab_nas/nuwins_data_platform/datasets/bos_phi_trip_202601/trimmed_traces_20260207"
MAHIMAHI_BASE = "/home/nuwins/zach/LeoCC/LeoCC/leoreplayer/replayer/static_traces_20260207"
OUT           = os.path.expanduser("~/graphs/verify_conversion")
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

icmp_pattern = re.compile(r'\[(\d+\.\d+)\].*time=(\d+\.?\d*)\s*ms')
pcap_pattern = re.compile(r'^(\d+\.\d+)\s+\S+\s+In\s+IP.*length\s+(\d+)')

# ── MAIN LOOP ─────────────────────────────────────────────────────────────────
for TRACE_ID in TRACES:
    print(f"\n{'='*60}")
    print(f"Processing: {TRACE_ID}")

    ICMP_LOG  = os.path.join(TRIMMED_BASE,  TRACE_ID, "icmp_ul_trimmed.log")
    PCAP_FILE = os.path.join(TRIMMED_BASE,  TRACE_ID, "udp_ul_trimmed.pcap")
    DELAY_TXT = os.path.join(MAHIMAHI_BASE, TRACE_ID, "uplink", "delay_uplink.txt")
    BW_TXT    = os.path.join(MAHIMAHI_BASE, TRACE_ID, "uplink", "bw_uplink.txt")

    # ── PARSE ICMP LOG ────────────────────────────────────────────────────────
    print("  Parsing ICMP log...")
    icmp_times, icmp_rtts = [], []
    with open(ICMP_LOG) as f:
        for line in f:
            match = icmp_pattern.search(line)
            if match:
                icmp_times.append(float(match.group(1)))
                icmp_rtts.append(float(match.group(2)))

    t0_icmp  = icmp_times[0]
    icmp_rel = [t - t0_icmp for t in icmp_times]
    icmp_ow  = [r / 2 for r in icmp_rtts]
    print(f"    ICMP samples: {len(icmp_rel)}")

    # ── PARSE DELAY TXT ───────────────────────────────────────────────────────
    print("  Parsing delay_uplink.txt...")
    delay_vals = []
    with open(DELAY_TXT) as f:
        for line in f:
            line = line.strip()
            if line:
                delay_vals.append(int(line))
    delay_times = [i * 0.01 for i in range(len(delay_vals))]
    print(f"    Delay slots: {len(delay_vals)}")

    # ── PARSE PCAP ────────────────────────────────────────────────────────────
    print("  Parsing pcap...")
    result = subprocess.run(
        f"tcpdump -tt -n -r {PCAP_FILE} 2>/dev/null",
        shell=True, capture_output=True, text=True
    )
    pcap_bytes = defaultdict(int)
    t0_pcap = None
    for line in result.stdout.splitlines():
        match = pcap_pattern.match(line)
        if match:
            t = float(match.group(1))
            l = int(match.group(2))
            if t0_pcap is None:
                t0_pcap = t
            sec = int(t - t0_pcap)
            pcap_bytes[sec] += l

    pcap_dur   = max(pcap_bytes.keys()) + 1
    pcap_times = list(range(pcap_dur))
    pcap_mbps  = [pcap_bytes.get(s, 0) * 8 / 1e6 for s in pcap_times]
    print(f"    Pcap duration: {pcap_dur}s  avg: {sum(pcap_mbps)/len(pcap_mbps):.1f} Mbps")

    # ── PARSE BW TXT ─────────────────────────────────────────────────────────
    print("  Parsing bw_uplink.txt...")
    bw_ms = []
    with open(BW_TXT) as f:
        for line in f:
            line = line.strip()
            if line:
                bw_ms.append(int(line))

    bw_bins = defaultdict(int)
    t0_bw = bw_ms[0]
    for ms in bw_ms:
        sec = int((ms - t0_bw) / 1000)
        bw_bins[sec] += 1

    bw_dur   = int((bw_ms[-1] - t0_bw) / 1000) + 1
    bw_times = list(range(bw_dur))
    bw_mbps  = [bw_bins.get(s, 0) * 1500 * 8 / 1e6 for s in bw_times]
    print(f"    BW duration: {bw_dur}s  avg: {sum(bw_mbps)/len(bw_mbps):.1f} Mbps")

    # ── PLOT 4 SUBPLOTS ───────────────────────────────────────────────────────
    fig, axes = plt.subplots(4, 1, figsize=(14, 16))
    fig.suptitle(f"Conversion Verification — Trace {TRACE_ID} Uplink", fontsize=13, fontweight='bold')

    # Row 1: Raw ICMP one-way delay
    ax1 = axes[0]
    ax1.scatter(icmp_rel, icmp_ow, s=0.5, color='blue', alpha=0.4)
    ax1.set_ylabel("One-way Delay (ms)", fontsize=10)
    ax1.set_title("Row 1: Raw ICMP one-way delay (RTT/2)", fontsize=10)
    ax1.set_ylim(0, 200)
    ax1.set_xlim(0, 120)
    ax1.grid(True, alpha=0.3)

    # Row 2: delay_uplink.txt
    ax2 = axes[1]
    ax2.plot(delay_times, delay_vals, color='red', lw=0.8)
    ax2.set_ylabel("One-way Delay (ms)", fontsize=10)
    ax2.set_title("Row 2: delay_uplink.txt (10ms slots)", fontsize=10)
    ax2.set_ylim(0, 200)
    ax2.set_xlim(0, 120)
    ax2.grid(True, alpha=0.3)

    # Row 3: Raw pcap per-second Mbps
    ax3 = axes[2]
    ax3.plot(pcap_times, pcap_mbps, color='blue', lw=1.2)
    ax3.set_ylabel("Rate (Mbps)", fontsize=10)
    ax3.set_title("Row 3: Raw pcap bandwidth (per-second)", fontsize=10)
    ax3.set_ylim(bottom=0)
    ax3.set_xlim(0, 120)
    ax3.grid(True, alpha=0.3)

    # Row 4: bw_uplink.txt per-second Mbps
    ax4 = axes[3]
    ax4.plot(bw_times, bw_mbps, color='red', lw=1.2)
    ax4.set_ylabel("Rate (Mbps)", fontsize=10)
    ax4.set_title("Row 4: bw_uplink.txt bandwidth (per-second)", fontsize=10)
    ax4.set_ylim(bottom=0)
    ax4.set_xlim(0, 120)
    ax4.set_xlabel("Time (seconds)", fontsize=10)
    ax4.grid(True, alpha=0.3)

    plt.tight_layout()
    out_path = os.path.join(OUT, f"{TRACE_ID}_verify_conversion.png")
    plt.savefig(out_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {out_path}")

print("\nAll 9 traces done! Check ~/graphs/verify_conversion/")
