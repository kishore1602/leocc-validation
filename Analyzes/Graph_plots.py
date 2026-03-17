#!/usr/bin/env python3
"""
plot_final.py - LeoCC Static Trace Performance Graphs
=======================================================
Plots 4-subplot performance graphs for all 9 static traces in both directions.

Subplots:
    Row 1: Throughput over time (all 3 CCAs vs trace capacity)
    Row 2: Cubic packet delay scatter + base RTT line
    Row 3: BBR packet delay scatter + base RTT line
    Row 4: LeoCC packet delay scatter + base RTT line

Methods:
    - Throughput: tshark frame.len per second from receiver-side pcap
    - Packet delay: TCP timestamp option matching between sender and receiver pcaps
    - Base RTT: median of ICMP ping one-way delay per second from delay_downlink.txt
    - Capacity: mahimahi packet timestamps converted to per-second Mbps

Direction conventions:
    Downlink: n2 sends → n1 receives
    Uplink:   n1 sends → n2 receives

Known limitation:
    Packet delay uses wall-clock difference between sender and receiver TCP timestamps.
    Since n1 and n2 have unsynchronized clocks, delay values include clock offset error.
    However values are consistent and comparable across CCAs since all three experience
    the same clock offset. Delay range matches LeoCC paper Figure 10 values.

Output: 18 PNG files (9 traces x 2 directions) saved to ~/graphs/static_final/
"""

import os
import subprocess
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from collections import defaultdict

# ── CONFIG ───────────────────────────────────────────────────────────────────
BASE = os.path.expanduser("~/zach/LeoCC/LeoCC/leoreplayer/replayer/static_traces_20260207")
OUT  = os.path.expanduser("~/graphs/static_final")
os.makedirs(OUT, exist_ok=True)

# Per-trace reconfiguration offsets computed using extract_reconfiguration.py
# Reconfiguration happens every 15s starting from offset: offset, offset+15, offset+30...
TRACES = {
    "1770506564594-0500": {"dl_offset": 12.3,  "ul_offset": 7.43},
    "1770506824350-0500": {"dl_offset": 9.83,  "ul_offset": 0.05},
    "1770507107930-0500": {"dl_offset": 11.13, "ul_offset": 0.5},
    "1770508413242-0500": {"dl_offset": 13.05, "ul_offset": 5.72},
    "1770508674186-0500": {"dl_offset": 14.99, "ul_offset": 0.5},
    "1770508935404-0500": {"dl_offset": 14.44, "ul_offset": 9.62},
    "1770509197343-0500": {"dl_offset": 5.82,  "ul_offset": 1.88},
    "1770509458429-0500": {"dl_offset": 12.48, "ul_offset": 12.91},
    "1770509718695-0500": {"dl_offset": 7.89,  "ul_offset": 3.73},
}

# CCA config: (key, label, color, linestyle,
#              dl_tput_pcap, dl_sender_pcap, dl_receiver_pcap,
#              ul_tput_pcap, ul_sender_pcap, ul_receiver_pcap)
# Downlink: n2 sends → n1 receives
# Uplink:   n1 sends → n2 receives
CCAS = [
    ("cubic", "Cubic", "red",    "--", "n1_cubic_dl.pcap", "n2_cubic_dl.pcap", "n1_cubic_dl.pcap", "n2_cubic_ul.pcap", "n1_cubic_ul.pcap", "n2_cubic_ul.pcap"),
    ("bbr",   "BBR",   "green",  "--", "n1_bbr_dl.pcap",   "n2_bbr_dl.pcap",   "n1_bbr_dl.pcap",   "n2_bbr_ul.pcap",   "n1_bbr_ul.pcap",   "n2_bbr_ul.pcap"),
    ("leocc", "LeoCC", "purple", ":",  "n1.pcap",          "n2.pcap",          "n1.pcap",          "n2.pcap",          "n1.pcap",          "n2.pcap"),
]

DURATION = 120  # total test duration in seconds

# ── HELPER FUNCTIONS ─────────────────────────────────────────────────────────

def rtt_from_delay_file(delay_path, duration=DURATION):
    """
    Read one-way delay file (100Hz ICMP ping, ms per line) and compute
    per-second median. Returns (times_array, rtt_array).
    """
    if not os.path.exists(delay_path):
        return np.array([]), np.array([])
    try:
        with open(delay_path) as f:
            vals = [float(l.strip()) for l in f if l.strip()]
        rtts, times = [], []
        for s in range(duration):
            chunk = vals[s*100:(s+1)*100]  # 100 samples per second at 100Hz
            if chunk:
                rtts.append(np.median(chunk))
                times.append(s)
        return np.array(times), np.array(rtts)
    except:
        return np.array([]), np.array([])


def capacity_from_bw(bw_path, duration=DURATION):
    """
    Convert mahimahi packet timestamp file to per-second Mbps.
    Each line is a timestamp in ms when one 1500-byte (12000-bit) packet is delivered.
    """
    if not os.path.exists(bw_path):
        return np.zeros(duration), np.arange(duration)
    try:
        with open(bw_path) as f:
            times = [int(l.strip()) for l in f if l.strip()]
        if not times:
            return np.zeros(duration), np.arange(duration)
        t0   = times[0]
        bins = defaultdict(int)
        for t in times:
            sec = int((t - t0) / 1000)  # ms to seconds
            if 0 <= sec < duration:
                bins[sec] += 12000       # 1500 bytes = 12000 bits per packet
        cap = np.array([bins.get(s, 0) / 1e6 for s in range(duration)])
        return cap, np.arange(duration)
    except:
        return np.zeros(duration), np.arange(duration)


def throughput_from_pcap(pcap_path, duration=DURATION):
    """
    Compute per-second throughput (Mbps) from pcap using tshark frame.len.
    Uses frame.time_relative so time starts from 0 regardless of capture start.
    """
    if not os.path.exists(pcap_path):
        return np.zeros(duration)
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
                    sec = int(float(parts[0]))
                    if 0 <= sec < duration:
                        bins[sec] += int(parts[1])  # accumulate bytes per second
                except ValueError:
                    continue
        return np.array([bins.get(s, 0) * 8 / 1e6 for s in range(duration)])
    except:
        return np.zeros(duration)


def extract_ts_map(pcap_path):
    """
    Extract TCP timestamp option values and their epoch times from a pcap.
    Returns {ts_val: first_seen_epoch_time} mapping.
    Used for per-packet delay computation by matching sender and receiver timestamps.
    """
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
                            ts_map[ts_val] = epoch  # store first occurrence only
                        break
            except (ValueError, IndexError):
                continue
        return ts_map
    except:
        return {}


def compute_packet_delay(sender_pcap, receiver_pcap, duration=DURATION):
    """
    Compute per-packet one-way delay (ms) by matching TCP timestamp values
    between sender and receiver pcaps.
    delay = (receiver_epoch - sender_epoch) * 1000 ms
    Filters out negative delays and delays > 2000ms as invalid.
    """
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

def plot_trace(trace_id, direction):
    print(f"\n{'='*60}")
    print(f"Plotting {trace_id} [{direction}]")

    tdir    = os.path.join(BASE, trace_id, direction)
    bw_f    = os.path.join(tdir, "bw_downlink.txt"    if direction == "downlink" else "bw_uplink.txt")
    delay_f = os.path.join(tdir, "delay_downlink.txt" if direction == "downlink" else "delay_uplink.txt")

    # Compute trace-specific reconfiguration times using per-trace offset
    offset_s = TRACES[trace_id]["dl_offset"] if direction == "downlink" else TRACES[trace_id]["ul_offset"]
    reconf_times = [offset_s + i * 15 for i in range(8) if offset_s + i * 15 <= DURATION]

    cap, t_cap = capacity_from_bw(bw_f)
    print(f"  Capacity avg={cap.mean():.1f} Mbps")

    t_rtt, rtt = rtt_from_delay_file(delay_f)
    print(f"  Base RTT avg={rtt.mean():.1f} ms" if len(rtt) > 0 else "  Base RTT: no data")

    # Collect throughput and delay data for all 3 CCAs
    cca_data = {}
    for row in CCAS:
        cca_key, label, color, ls = row[0], row[1], row[2], row[3]

        # Select correct pcaps based on direction
        if direction == "downlink":
            tput_pcap   = row[4]   # receiver-side pcap for throughput
            sender_pcap = row[5]   # n2 sends downlink
            recv_pcap   = row[6]   # n1 receives downlink
        else:
            tput_pcap   = row[7]   # receiver-side pcap for throughput
            sender_pcap = row[8]   # n1 sends uplink
            recv_pcap   = row[9]   # n2 receives uplink

        tput_path = os.path.join(tdir, f"results_{cca_key}", tput_pcap)
        send_path = os.path.join(tdir, f"results_{cca_key}", sender_pcap)
        rcvr_path = os.path.join(tdir, f"results_{cca_key}", recv_pcap)

        print(f"\n  [{label}]")
        tput = throughput_from_pcap(tput_path)
        print(f"    Throughput avg={tput.mean():.1f} Mbps")
        dt, dd = compute_packet_delay(send_path, rcvr_path)
        print(f"    Delay avg={dd.mean():.1f} ms" if len(dd) > 0 else "    Delay: no data")

        cca_data[cca_key] = {
            "label": label, "color": color, "ls": ls,
            "tput": tput, "delay_t": dt, "delay_d": dd
        }

    # ── FIGURE: 4 subplots ──
    fig, axes = plt.subplots(4, 1, figsize=(14, 16), sharex=True)
    fig.suptitle(
        f"{'Downlink' if direction=='downlink' else 'Uplink'} Performance – Trace {trace_id}",
        fontsize=13, fontweight='bold'
    )

    # Row 1: Throughput — all CCAs vs trace capacity
    ax1 = axes[0]
    ax1.plot(t_cap, cap, color='blue', lw=2.0, label='Trace Capacity')
    for cca_key, d in cca_data.items():
        ax1.plot(np.arange(DURATION), d["tput"],
                 color=d["color"], lw=1.2, ls=d["ls"], label=d["label"])
    for rv in reconf_times:
        ax1.axvline(x=rv, color='black', lw=0.8, ls='-.', alpha=0.5)
    ax1.set_ylabel("Rate (Mbps)", fontsize=10)
    ax1.set_title("Throughput", fontsize=10)
    ax1.legend(loc='upper right', fontsize=8)
    ax1.set_ylim(bottom=0)
    ax1.grid(True, alpha=0.3)

    # Rows 2-4: Per-packet delay scatter for each CCA with base RTT overlay
    for ax, (cca_key, d) in zip(axes[1:], cca_data.items()):
        if len(d["delay_t"]) > 0:
            ax.scatter(d["delay_t"], d["delay_d"],
                      s=0.5, color=d["color"], alpha=0.3,
                      label=f'{d["label"]} Packet Delay')
        if len(t_rtt) > 0:
            ax.plot(t_rtt, rtt, color='blue', lw=1.5,
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
    out_path = os.path.join(OUT, f"{trace_id}_{direction}.png")
    plt.savefig(out_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"\n  Saved: {out_path}")


# ── MAIN ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    for trace_id in TRACES:
        for direction in ("downlink", "uplink"):
            plot_trace(trace_id, direction)
    print("\nAll plots done! Check ~/graphs/static_final/")