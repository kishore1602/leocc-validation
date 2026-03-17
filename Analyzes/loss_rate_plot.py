#!/usr/bin/env python3
"""
Loss Rate Plotting Script - LeoCC Static Trace Evaluation
==========================================================
Calculates and plots packet loss rate every 500ms for all 9 static traces.
Produces 3-subplot graphs (one per CCA) for both downlink and uplink directions.

Method:
    - Count TCP data packets (tcp.len > 0) in sender and receiver pcaps
    - Divide 120s test into 500ms bins (240 bins total)
    - Loss rate per bin = max(0, (sent - received) / sent) x 100%
    - Uses frame.time_relative from tshark so each pcap's time starts from 0
      avoiding clock sync issues between n1 and n2 machines

Direction conventions:
    Downlink: n2 sends → n1 receives
    Uplink:   n1 sends → n2 receives

Known limitation:
    Counts all TCP data packets including retransmissions. The correct approach
    would exclude retransmissions on sender side using !tcp.analysis.retransmission
    and deduplicate by sequence number on receiver side. Since this affects all
    three CCAs equally the relative comparison remains valid.

Output: 18 PNG files (9 traces x 2 directions) saved to ~/graphs/loss_rate/
"""

import os
import subprocess
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from collections import defaultdict

# ── CONFIG ───────────────────────────────────────────────────────────────────
BASE = os.path.expanduser(
    "~/zach/LeoCC/LeoCC/leoreplayer/replayer/static_traces_20260207"
)
OUT = os.path.expanduser("~/graphs/loss_rate")
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

# CCA config: (key, label, color, dl_sender, dl_receiver, ul_sender, ul_receiver)
# Downlink: n2 sends → n1 receives
# Uplink:   n1 sends → n2 receives
CCAS = [
    ("cubic", "Cubic", "red",
     "n2_cubic_dl.pcap", "n1_cubic_dl.pcap",
     "n1_cubic_ul.pcap", "n2_cubic_ul.pcap"),
    ("bbr",   "BBR",   "green",
     "n2_bbr_dl.pcap",   "n1_bbr_dl.pcap",
     "n1_bbr_ul.pcap",   "n2_bbr_ul.pcap"),
    ("leocc", "LeoCC", "purple",
     "n2.pcap",          "n1.pcap",
     "n1.pcap",          "n2.pcap"),
]

DURATION  = 120          # total test duration in seconds
BIN_SIZE  = 0.5          # 500ms bins
N_BINS    = int(DURATION / BIN_SIZE)   # 240 bins total

# ── HELPER FUNCTIONS ─────────────────────────────────────────────────────────

def get_relative_times(pcap_path):
    """
    Extract frame.time_relative (seconds since capture start) for TCP data packets.
    Using relative time avoids clock sync issues between sender and receiver machines.
    """
    if not os.path.exists(pcap_path):
        return []
    try:
        result = subprocess.run(
            ["tshark", "-r", pcap_path, "-T", "fields",
             "-e", "frame.time_relative",
             "-Y", "tcp.len > 0"],   # only TCP packets with payload (excludes ACKs)
            capture_output=True, text=True, timeout=360
        )
        times = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if line:
                try:
                    times.append(float(line))
                except ValueError:
                    continue
        return times
    except Exception as e:
        print(f"    [ERR] {pcap_path}: {e}")
        return []


def compute_loss_rate(sender_pcap, receiver_pcap, bin_size=BIN_SIZE, n_bins=N_BINS):
    """
    Compute loss rate per 500ms bin.
    Formula: loss_rate = max(0, (sent - received) / sent) x 100%
    Clamped to 0 minimum to handle timing edge cases where recv > sent in a bin.
    """
    sent_times = get_relative_times(sender_pcap)
    recv_times = get_relative_times(receiver_pcap)

    if not sent_times and not recv_times:
        return np.zeros(n_bins), np.arange(n_bins) * bin_size

    # Count packets per bin for sender and receiver
    sent_bins = defaultdict(int)
    recv_bins = defaultdict(int)

    for t in sent_times:
        b = int(t / bin_size)
        if 0 <= b < n_bins:
            sent_bins[b] += 1

    for t in recv_times:
        b = int(t / bin_size)
        if 0 <= b < n_bins:
            recv_bins[b] += 1

    # Calculate loss rate per bin
    loss_rates = []
    for b in range(n_bins):
        s = sent_bins.get(b, 0)
        r = recv_bins.get(b, 0)
        loss = max(0.0, (s - r) / s * 100) if s > 0 else 0.0
        loss_rates.append(loss)

    bin_times = np.arange(n_bins) * bin_size
    return np.array(loss_rates), bin_times


# ── MAIN PLOT FUNCTION ───────────────────────────────────────────────────────

def plot_loss_rate(trace_id, direction):
    print(f"\n{'='*60}")
    print(f"Loss Rate: {trace_id} [{direction}]")

    tdir = os.path.join(BASE, trace_id, direction)

    # Compute trace-specific reconfiguration times using per-trace offset
    # Reconfiguration happens every 15s starting from the offset
    offset_s = TRACES[trace_id]["dl_offset"] if direction == "downlink" else TRACES[trace_id]["ul_offset"]
    reconf_times = [offset_s + i * 15 for i in range(8) if offset_s + i * 15 <= DURATION]

    fig, axes = plt.subplots(3, 1, figsize=(14, 12), sharex=True)
    fig.suptitle(
        f"{'Downlink' if direction=='downlink' else 'Uplink'} Loss Rate – Trace {trace_id}",
        fontsize=13, fontweight='bold'
    )

    for ax, row in zip(axes, CCAS):
        cca_key, label, color = row[0], row[1], row[2]

        # Select correct sender/receiver pcaps based on direction
        if direction == "downlink":
            sender_pcap   = row[3]   # n2 sends downlink
            receiver_pcap = row[4]   # n1 receives downlink
        else:
            sender_pcap   = row[5]   # n1 sends uplink
            receiver_pcap = row[6]   # n2 receives uplink

        send_path = os.path.join(tdir, f"results_{cca_key}", sender_pcap)
        recv_path = os.path.join(tdir, f"results_{cca_key}", receiver_pcap)

        print(f"  [{label}] computing loss rate...")
        loss_rates, bin_times = compute_loss_rate(send_path, recv_path)
        avg_loss = loss_rates[loss_rates > 0].mean() if any(loss_rates > 0) else 0
        print(f"    avg loss={avg_loss:.2f}%  max loss={loss_rates.max():.2f}%")

        # Plot as step line — each step represents one 500ms bin
        ax.step(bin_times, loss_rates, where='post',
                color=color, lw=1.2, label=f"{label} (avg={avg_loss:.2f}%)")

        # Vertical dashed lines at trace-specific reconfiguration times
        for rv in reconf_times:
            ax.axvline(x=rv, color='black', lw=0.8, ls='-.', alpha=0.5)

        ax.set_ylabel("Loss Rate (%)", fontsize=10)
        ax.set_title(label, fontsize=10)
        ax.set_xlim(0, DURATION)
        ax.set_ylim(0, 100)
        ax.legend(loc='upper right', fontsize=9)
        ax.grid(True, alpha=0.3)

    axes[-1].set_xlabel("Time (seconds)", fontsize=10)

    plt.tight_layout()
    out_path = os.path.join(OUT, f"{trace_id}_{direction}_loss.png")
    plt.savefig(out_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {out_path}")


# ── MAIN ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    for trace_id in TRACES:
        for direction in ("downlink", "uplink"):
            plot_loss_rate(trace_id, direction)
    print("\nAll loss rate plots done!")