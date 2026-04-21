"""
RTT Post-Processor for calculating jitter and windowed loss rate.

This module provides reusable functions for computing per-packet jitter and
windowed packet loss rate from RTT data.
"""

import logging
from typing import Callable

import numpy as np
import pandas as pd


ICMP_SEQ_WRAP_THRESHOLD = 32768  # Half of 2^16; backward jump larger than this = wrap
ICMP_SEQ_RANGE = 65536  # 2^16


class RttPostProcessor:
    """Post-processor for RTT data to compute jitter and loss rate."""

    @staticmethod
    def compute_expected_packets(
        seq_series: pd.Series,
        ts_series: pd.Series,
    ) -> int:
        """Compute expected packet count, handling 16-bit icmp_seq wraps.

        Detects wrap points (seq decrease > ICMP_SEQ_WRAP_THRESHOLD between
        consecutive packets sorted by timestamp), splits into contiguous
        segments, and sums per-segment expected counts (max - min + 1).

        Does NOT mutate original seq values.

        Args:
            seq_series: Series of icmp_seq values.
            ts_series: Series of timestamps (for ordering).

        Returns:
            Expected number of packets across all segments.
        """
        if len(seq_series) <= 1:
            return len(seq_series)

        # Sort by timestamp
        order = ts_series.argsort()
        sorted_seq = seq_series.iloc[order].values

        # Find wrap points: where seq drops by > threshold
        diffs = np.diff(sorted_seq)
        wrap_indices = np.where(diffs < -ICMP_SEQ_WRAP_THRESHOLD)[0]

        # Split into segments at wrap points
        split_points = [0] + list(wrap_indices + 1) + [len(sorted_seq)]

        expected = 0
        for i in range(len(split_points) - 1):
            segment = sorted_seq[split_points[i] : split_points[i + 1]]
            expected += int(segment.max()) - int(segment.min()) + 1

        return expected

    @staticmethod
    def compute_session_loss(
        utc_ts: pd.Series,
        icmp_seq: pd.Series,
    ) -> dict[str, int | float]:
        """Compute loss stats for a single ping session.

        Args:
            utc_ts: Timestamps of received packets (used for ordering).
            icmp_seq: ICMP sequence numbers of received packets.

        Returns:
            Dict with keys ``expected`` (int), ``received`` (int),
            ``loss_rate_pct`` (float, or ``nan`` if expected == 0).

        Example:
            >>> result = RttPostProcessor.compute_session_loss(df["utc_ts"], df["icmp_seq"])
            >>> result
            {"expected": 120, "received": 118, "loss_rate_pct": 1.67}
        """
        received = len(icmp_seq)
        expected = RttPostProcessor.compute_expected_packets(icmp_seq, utc_ts)
        loss_rate_pct = (1 - received / expected) * 100 if expected > 0 else float("nan")
        return {"expected": expected, "received": received, "loss_rate_pct": loss_rate_pct}

    @staticmethod
    def compute_per_run_loss_rate(
        df: pd.DataFrame,
        run_id_col: str = "run_id",
        session_id_col: str = "ping_session_id",
        ts_col: str = "utc_ts",
        seq_col: str = "icmp_seq",
    ) -> pd.DataFrame:
        """Compute per-run loss rate from raw per-packet ICMP data.

        Groups by ``(run_id, session_id)``, computes wrap-aware expected packets
        per session, then aggregates to per-run by summing ``expected`` and
        ``received`` across sessions before deriving the final loss rate.
        Summing avoids the session-count bias introduced by averaging loss
        percentages directly.

        Args:
            df: Raw per-packet DataFrame containing at least the four columns
                named by the remaining arguments.
            run_id_col: Column identifying the measurement run.
            session_id_col: Column identifying the ping session within a run.
            ts_col: Column of packet timestamps (used for seq ordering).
            seq_col: Column of ``icmp_seq`` values.

        Returns:
            DataFrame with columns ``[run_id_col, expected, received,
            loss_rate_pct]``, one row per run.

        Example:
            >>> per_run = RttPostProcessor.compute_per_run_loss_rate(raw_df)
            >>> per_run.columns
            Index(['run_id', 'expected', 'received', 'loss_rate_pct'], dtype='object')
        """
        session_records = []
        for (run_id, _session_id), group in df.groupby([run_id_col, session_id_col]):
            stats = RttPostProcessor.compute_session_loss(group[ts_col], group[seq_col])
            session_records.append({run_id_col: run_id, **stats})

        session_df = pd.DataFrame(session_records)
        per_run = session_df.groupby(run_id_col, as_index=False).agg(
            expected=("expected", "sum"),
            received=("received", "sum"),
        )
        per_run["loss_rate_pct"] = (
            (1 - per_run["received"] / per_run["expected"]) * 100
        ).clip(lower=0.0)
        return per_run

    @staticmethod
    def resample_with_window(
        df: pd.DataFrame,
        group_cols: list[str],
        ts_col: str = "utc_ts",
        window_ms: int = 500,
        agg_dict: dict[str, list[str | Callable]] | None = None,
        logger: logging.Logger | None = None,
    ) -> pd.DataFrame:
        """
        Resample data at specified time windows with grouping.

        Uses pandas dt.floor() for consistent window boundaries.
        Groups by group_cols first (typically just ping_session_id for simple,
        continuous resampling), then applies time windowing within each group.

        Args:
            df: Input DataFrame
            group_cols: Columns to group by before windowing (e.g., ["ping_session_id"])
            ts_col: Timestamp column name (expects milliseconds since epoch)
            window_ms: Window size in milliseconds (default: 500)
            agg_dict: Aggregation specification {column: [funcs]}
                      Example: {"rtt_ms": ["mean", "std", "min"]}
            logger: Optional logger for statistics

        Returns:
            DataFrame with columns: group_cols + ts_col (as datetime) + aggregated columns
            Column names follow pattern: {original_col}_{agg_name}
        """
        if df.empty:
            if logger:
                logger.warning("Empty DataFrame, returning empty result")
            return pd.DataFrame()

        if agg_dict is None:
            raise ValueError("agg_dict must be provided")

        df = df.copy()

        # Convert timestamp to datetime for proper windowing
        window_str = f"{window_ms}ms"
        df["_window"] = pd.to_datetime(df[ts_col], unit="ms", utc=True).dt.floor(
            window_str
        )

        # Group by specified columns + window, then aggregate
        grouped = df.groupby(group_cols + ["_window"])
        result = grouped.agg(agg_dict)

        # Flatten column names: (col, agg) -> col_agg
        result.columns = [
            f"{col}_{agg}" if agg else col for col, agg in result.columns
        ]

        # Reset index to get group_cols and window as columns
        result = result.reset_index()

        # Rename _window back to the original timestamp column name
        result = result.rename(columns={"_window": ts_col})

        if logger:
            logger.info(f"Resampled {len(df):,} rows to {len(result):,} windows")

        return result

    @staticmethod
    def calculate_jitter(
        df: pd.DataFrame,
        group_col: str = "ping_session_id",
        ts_col: str = "utc_ts",
        rtt_col: str = "rtt_ms",
        logger: logging.Logger | None = None,
    ) -> pd.DataFrame:
        """
        Calculate per-packet jitter within each group.

        Jitter is |RTT[i] - RTT[i-1]|. First packet gets same jitter as second packet.
        Groups by group_col to ensure contiguous icmp_seq within each group.

        Args:
            df: DataFrame with RTT data
            group_col: Column name for grouping (e.g., 'ping_session_id')
            ts_col: Column name for timestamp (for sorting within group)
            rtt_col: Column name for RTT values
            logger: Optional logger for statistics

        Returns:
            DataFrame with jitter_ms column added
        """
        if df.empty:
            df["jitter_ms"] = pd.Series(dtype="float64")
            return df

        df = df.copy()
        df["jitter_ms"] = np.nan

        for group_id in df[group_col].unique():
            mask = df[group_col] == group_id
            group_idx = df[mask].sort_values(ts_col).index

            if len(group_idx) < 2:
                # Single packet: jitter is 0
                df.loc[group_idx, "jitter_ms"] = 0.0
                continue

            # Calculate consecutive RTT differences
            rtts = df.loc[group_idx, rtt_col].values
            jitters = np.abs(np.diff(rtts))

            # Pad first packet with second packet's jitter
            jitters_padded = np.concatenate([[jitters[0]], jitters])

            df.loc[group_idx, "jitter_ms"] = jitters_padded

        if logger:
            logger.info("Jitter statistics (ms):")
            logger.info(f"  Mean: {df['jitter_ms'].mean():.2f}")
            logger.info(f"  Median: {df['jitter_ms'].median():.2f}")
            logger.info(f"  P95: {df['jitter_ms'].quantile(0.95):.2f}")
            logger.info(f"  P99: {df['jitter_ms'].quantile(0.99):.2f}")

        return df

    @staticmethod
    def calculate_windowed_loss_rate(
        df: pd.DataFrame,
        group_col: str = "ping_session_id",
        ts_col: str = "utc_ts",
        seq_col: str = "icmp_seq",
        window_ms: int = 500,
        logger: logging.Logger | None = None,
    ) -> pd.DataFrame:
        """
        Calculate windowed loss rate within each group.

        Uses in-sequence loss calculation: (1 - packet_count / expected_packets) * 100
        Each packet gets the loss rate of the window it belongs to.
        Groups by group_col to ensure contiguous icmp_seq within each group.

        Internally uses resample_with_window() for consistent windowing logic.

        Args:
            df: DataFrame with RTT data
            group_col: Column name for grouping (e.g., 'ping_session_id')
            ts_col: Column name for timestamp in milliseconds
            seq_col: Column name for sequence numbers
            window_ms: Window size in milliseconds (default: 500)
            logger: Optional logger for statistics

        Returns:
            DataFrame with loss_rate_pct column added
        """
        if df.empty:
            df["loss_rate_pct"] = pd.Series(dtype="float64")
            return df

        df = df.copy()

        # Use resample_with_window for consistent windowing
        # Aggregate seq numbers to compute loss rate
        resampled = RttPostProcessor.resample_with_window(
            df=df,
            group_cols=[group_col],
            ts_col=ts_col,
            window_ms=window_ms,
            agg_dict={seq_col: ["min", "max", "count"]},
            logger=None,  # Suppress logging from resample_with_window
        )

        if resampled.empty:
            df["loss_rate_pct"] = 0.0
            return df

        # Calculate expected packets and loss rate per window
        seq_range = resampled[f"{seq_col}_max"] - resampled[f"{seq_col}_min"]
        resampled["expected_packets"] = seq_range + 1

        # Detect icmp_seq wrap within window: range exceeds half of 2^16
        wrap_mask = seq_range > ICMP_SEQ_WRAP_THRESHOLD

        resampled["loss_rate"] = np.where(
            resampled["expected_packets"] > 0,
            (1 - resampled[f"{seq_col}_count"] / resampled["expected_packets"]) * 100,
            0.0,
        )
        # Handle edge cases
        resampled.loc[resampled["expected_packets"] <= 0, "loss_rate"] = 0.0
        resampled.loc[resampled[f"{seq_col}_count"] == 1, "loss_rate"] = 0.0
        # Skip windows where icmp_seq wrapped — too small to split reliably
        resampled.loc[wrap_mask, "loss_rate"] = np.nan

        # Create window assignment for original data using same dt.floor() logic
        window_str = f"{window_ms}ms"
        df["_window"] = pd.to_datetime(df[ts_col], unit="ms", utc=True).dt.floor(
            window_str
        )

        # Create mapping from (group_col, window) to loss rate
        # resample_with_window returns ts_col as datetime (with UTC timezone)
        window_loss_map = {
            (row[group_col], row[ts_col]): row["loss_rate"]
            for _, row in resampled.iterrows()
        }

        # Map loss rate back to each packet
        df["loss_rate_pct"] = df.apply(
            lambda row: window_loss_map.get((row[group_col], row["_window"]), 0.0),
            axis=1,
        )

        # Clean up temporary column
        df = df.drop(columns=["_window"])

        if logger:
            logger.info("Loss rate statistics (%):")
            logger.info(f"  Mean: {df['loss_rate_pct'].mean():.2f}%")
            logger.info(f"  Median: {df['loss_rate_pct'].median():.2f}%")
            logger.info(f"  P95: {df['loss_rate_pct'].quantile(0.95):.2f}%")
            logger.info(f"  P99: {df['loss_rate_pct'].quantile(0.99):.2f}%")
            packets_with_loss = (df["loss_rate_pct"] > 0).sum()
            logger.info(
                f"  Packets in windows with loss: {packets_with_loss}/{len(df)} "
                f"({packets_with_loss / len(df) * 100:.2f}%)"
            )

        return df
