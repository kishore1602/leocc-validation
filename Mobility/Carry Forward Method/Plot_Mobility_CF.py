#!/usr/bin/env python3
"""
plot_mobility_carryforward.py
===================================
Plots 4-subplot performance graph for 3 mobility traces
using carry-forward delay method.

Subplots:
    Row 1: Throughput over time (all CCAs vs trace capacity) at 500ms granularity
    Row 2: Cubic packet delay scatter + base RTT scatter
    Row 3: BBR packet delay scatter + base RTT scatter
    Row 4: LeoCC packet delay scatter + base RTT scatter

Output: saved to ~/graphs/mobility/
"""

import os
import re
import subprocess
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from collections import defaultdict

# ── CONFIG ───────────────────────────────────────────────────────────────────
BASE      = os.path.expanduser("~/zach/LeoCC/LeoCC/leoreplayer/replayer/mobility/carryforward")
ICMP_BASE = "/mnt/nuwinslab_nas/nuwins_data_platform/datasets/bos_phi_trip_202601/trimmed_traces_mobility_20260208"
OUT       = os.path.expanduser("~/graphs/mobility")
os.makedirs(OUT, exist_ok=True)

DURATION = 120

# Offsets converted from ms to seconds
TRACES = {
    "1770565256238-0500": 3.936,   # T1
    "1770567213734-0500": 11.562,  # T8
    "1770569558888-0500": 6.639,   # T16
}

CCAS = [
    ("cubic",  "results_cubic",  "Cubic",               "red",    "--"),
    ("bbr",    "results_bbr",    "BBR",                 "green",  "--"),
    ("leocc",  "results_leocc",  "LeoCC (minRTT=10ms)", "purple", ":"),
]

# ── HELPER FUNCTIONS ─────────────────────────────────────────────────────────

def rtt_from_icmp_log(log_path, duration=DURATION):
    if not os.path.exists(log_path):
        print(f"  WARNING: ICMP log not found: {log_path}")
        return np.array([]), np.array([])
    try:
        times_raw, rtts_raw = [], []
        with open(log_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                ts_match  = re.search(r'\[(\d+\.\d+)\]', line)
                rtt_match = re.search(r'time=(\d+\.?\d*)\s*ms', line)
                if ts_match and rtt_match:
                    times_raw.append(float(ts_match.group(1)))
                    rtts_raw.append(float(rtt_match.group(1)))

        if not times_raw:
            return np.array([]), np.array([])

        t0 = times_raw[0]
        times_out, rtts_out = [], []
        for t, r in zip(times_raw, rtts_raw):
            rel = t - t0
            if 0 <= rel <= duration:
                times_out.append(rel)
                rtts_out.append(r)

        print(f"  Base RTT: parsed {len(times_raw)} pings, avg={np.mean(rtts_out):.1f} ms")
        return np.array(times_out), np.array(rtts_out)
    except Exception as e:
        print(f"  ERROR parsing ICMP log: {e}")
        return np.array([]), np.array([])


def capacity_from_bw(bw_path, duration=DURATION):
    if not os.path.exists(bw_path):
        return np.zeros(duration * 2), np.arange(duration * 2) / 2
    try:
        with open(bw_path) as f:
            times = [int(l.strip()) for l in f if l.strip()]
        if not times:
            return np.zeros(duration * 2), np.arange(duration * 2) / 2
        t0   = times[0]
        bins = defaultdict(int)
        for t in times:
            slot = int((t - t0) / 500)
            if 0 <= slot < duration * 2:
                bins[slot] += 12000
        cap = np.array([bins.get(s, 0) / 1e6 / 0.5 for s in range(duration * 2)])
        print(f"  Capacity avg={cap.mean():.1f} Mbps")
        return cap, np.arange(duration * 2) / 2
    except Exception as e:
        print(f"  ERROR reading BW file: {e}")
        return np.zeros(duration * 2), np.arange(duration * 2) / 2


def throughput_from_pcap(pcap_path, duration=DURATION):
    if not os.path.exists(pcap_path):
        print(f"    WARNING: pcap not found: {pcap_path}")
        return np.zeros(duration * 2)
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
        return np.array([bins.get(s, 0) * 8 / 1e6 / 0.5 for s in range(duration * 2)])
    except Exception as e:
        print(f"    ERROR reading pcap: {e}")
        return np.zeros(duration * 2)


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


def compute_packet_delay(sender_pcap, receiver_pcap, duration=DURATION):
    print(f"    Extracting TS from sender:   {os.path.basename(sender_pcap)}")
    sender_map   = extract_ts_map(sender_pcap)
    print(f"    Extracting TS from receiver: {os.path.basename(receiver_pcap)}")
    receiver_map = extract_ts_map(receiver_pcap)
    times, delays = [], []
    t0 = min(sender_map.values()) if sender_map else 0
    for ts_val, recv_time in receiver_map.items():
        if ts_val in sender_map:
            delay_ms = (recv_time - sender_map[ts_val]) * 1000
            if 0 <= delay_ms <= 2000:
                rel = recv_time - t0
                if 0 <= rel <= duration:
                    times.append(rel)
                    delays.append(delay_ms)
    print(f"    Matched {len(times)} packets")
    return np.array(times), np.array(delays)


# ── MAIN PLOT FUNCTION ────────────────────────────────────────────────────────

def plot_trace(trace_id, ul_offset):
    print(f"\n{'='*60}")
    print(f"Plotting {trace_id} [mobility carry-forward]")

    tdir      = os.path.join(BASE, trace_id, "uplink")
    bw_path   = os.path.join(tdir, "bw_uplink.txt")
    icmp_path = os.path.join(ICMP_BASE, trace_id, "icmp_ul_trimmed.log")

    reconf_times = [ul_offset + i * 15 for i in range(8) if ul_offset + i * 15 <= DURATION]
    print(f"  Reconfiguration times: {[round(r,2) for r in reconf_times]}")

    cap, t_cap = capacity_from_bw(bw_path)
    t_rtt, rtt = rtt_from_icmp_log(icmp_path)

    cca_data = {}
    for cca_key, results_folder, label, color, ls in CCAS:
        results_dir = os.path.join(tdir, results_folder)
        tput_path   = os.path.join(results_dir, "n2.pcap")
        send_path   = os.path.join(results_dir, "n1.pcap")
        rcvr_path   = os.path.join(results_dir, "n2.pcap")

        print(f"\n  [{label}]")
        tput = throughput_from_pcap(tput_path)
        print(f"    Throughput avg={tput.mean():.1f} Mbps")
        dt, dd = compute_packet_delay(send_path, rcvr_path)
        print(f"    Delay avg={dd.mean():.1f} ms" if len(dd) > 0 else "    Delay: no data")

        cca_data[cca_key] = {
            "label": label, "color": color, "ls": ls,
            "tput": tput, "delay_t": dt, "delay_d": dd
        }

    fig, axes = plt.subplots(4, 1, figsize=(14, 16), sharex=True)
    fig.suptitle(
        f"Uplink Performance – Trace {trace_id} (Mobility, Carry-Forward)",
        fontsize=13, fontweight='bold'
    )

    ax1 = axes[0]
    ax1.plot(t_cap, cap, color='blue', lw=2.0, label='Trace Capacity')
    for cca_key, d in cca_data.items():
        ax1.plot(np.arange(DURATION * 2) / 2, d["tput"],
                 color=d["color"], lw=1.2, ls=d["ls"], label=d["label"])
    for rv in reconf_times:
        ax1.axvline(x=rv, color='black', lw=0.8, ls='-.', alpha=0.5)
    ax1.set_ylabel("Rate (Mbps)", fontsize=10)
    ax1.set_title("Throughput (500ms granularity)", fontsize=10)
    ax1.legend(loc='upper right', fontsize=8)
    ax1.set_ylim(bottom=0)
    ax1.grid(True, alpha=0.3)

    for ax, (cca_key, d) in zip(axes[1:], cca_data.items()):
        if len(d["delay_t"]) > 0:
            ax.scatter(d["delay_t"], d["delay_d"],
                       s=0.5, color=d["color"], alpha=0.3,
                       label=f'{d["label"]} Packet Delay')
        if len(t_rtt) > 0:
            ax.scatter(t_rtt, rtt, s=0.5, color='blue', alpha=0.4,
                       label='Base RTT (ICMP Ping)', zorder=5)
        for rv in reconf_times:
            ax.axvline(x=rv, color='black', lw=0.8, ls='-.', alpha=0.5)
        ax.set_ylabel("Delay (ms)", fontsize=10)
        ax.set_title(f"{d['label']} Delay", fontsize=10)
        ax.set_ylim(0, 200)
        ax.set_yticks(range(0, 225, 25))
        ax.legend(loc='upper right', fontsize=8, markerscale=15)
        ax.grid(True, alpha=0.3)

    axes[-1].set_xlabel("Time (seconds)", fontsize=10)
    axes[-1].set_xlim(0, DURATION)

    plt.tight_layout()
    out_path = os.path.join(OUT, f"{trace_id}_mobility_carryforward.png")
    plt.savefig(out_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"\n  Saved: {out_path}")


# ── MAIN ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    for trace_id, ul_offset in TRACES.items():
        plot_trace(trace_id, ul_offset)
    print("\nAll plots done! Check ~/graphs/mobility/")
