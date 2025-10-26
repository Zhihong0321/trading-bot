#!/usr/bin/env python3
"""EUR/USD historical ingestion utilities.

This module downloads bid/ask candles from Dukascopy ticks or OANDA S30 candles
and writes normalized 30-second bars to CSV or Parquet. A validation subcommand
ensures the on-disk dataset conforms to the canonical schema.
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import logging
import os
import subprocess
import sys
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, List, Literal, Optional

import numpy as np
import pandas as pd
from dateutil import parser as dtparser
from tenacity import RetryError, retry, retry_if_exception_type, stop_after_attempt, wait_exponential

try:
    import pyarrow as pa
    import pyarrow.dataset as ds
    import pyarrow.fs as pafs
    import pyarrow.parquet as pq
except Exception:  # pragma: no cover - pyarrow optional for CSV-only usage
    pa = None
    ds = None
    pafs = None
    pq = None

PAIR = "EURUSD"
SCHEMA_COLUMNS = [
    "timestamp",
    "bid_open",
    "bid_high",
    "bid_low",
    "bid_close",
    "ask_open",
    "ask_high",
    "ask_low",
    "ask_close",
    "volume",
]

LOGGER = logging.getLogger("eurusd_ingest")


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def to_utc_datetime(value: str | datetime) -> datetime:
    """Return an aware UTC datetime for the provided value."""

    if isinstance(value, datetime):
        dt_value = value
    else:
        dt_value = dtparser.parse(value)
    if dt_value.tzinfo is None:
        dt_value = dt_value.replace(tzinfo=timezone.utc)
    else:
        dt_value = dt_value.astimezone(timezone.utc)
    return dt_value


def _ensure_pyarrow() -> None:
    if pa is None or pq is None or pafs is None:
        raise RuntimeError("pyarrow is required for parquet operations")


def _resolve_filesystem(path: str):
    if "://" not in path:
        return None, Path(path)
    _ensure_pyarrow()
    filesystem, inner = pafs.FileSystem.from_uri(path)
    # Normalise to remove leading separators that confuse directory joins.
    inner = inner.lstrip("/")
    return filesystem, inner


# ---------------------------------------------------------------------------
# Dataset validation and writing
# ---------------------------------------------------------------------------

def validate_dataset(df: pd.DataFrame) -> None:
    """Validate canonical schema and data quality constraints."""

    if df.empty:
        raise ValueError("Dataset is empty")
    missing_cols = [c for c in SCHEMA_COLUMNS if c not in df.columns]
    if missing_cols:
        raise ValueError(f"Dataset missing columns: {missing_cols}")

    df = df[SCHEMA_COLUMNS].copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)

    timestamps = df["timestamp"].view("int64") // 10**9
    deltas = np.diff(timestamps)
    if deltas.size and not (deltas > 0).all():
        raise ValueError("Timestamps must be strictly increasing")
    if not np.all(timestamps % 30 == 0):
        raise ValueError("All timestamps must align to 30-second closes")

    for side in ("bid", "ask"):
        high = df[f"{side}_high"].to_numpy()
        low = df[f"{side}_low"].to_numpy()
        open_ = df[f"{side}_open"].to_numpy()
        close = df[f"{side}_close"].to_numpy()
        if not (
            np.all(low <= open_)
            and np.all(low <= close)
            and np.all(open_ <= high)
            and np.all(close <= high)
        ):
            raise ValueError(f"{side} OHLC bounds violated")

    if df.isna().any().any():
        raise ValueError("NaN values detected in dataset")


def write_dataset(
    df: pd.DataFrame,
    out_path: str,
    fmt: Literal["parquet", "csv"] = "parquet",
    partition_by: Optional[str] = None,
) -> None:
    """Write dataset to disk in the requested format."""

    validate_dataset(df)
    df = df[SCHEMA_COLUMNS].copy()

    if fmt == "csv":
        if "://" in out_path:
            raise ValueError("CSV output does not support remote URIs; use a local path")
        path_obj = Path(out_path)
        if partition_by == "month":
            if not path_obj.exists():
                path_obj.mkdir(parents=True, exist_ok=True)
            grouped = df.groupby([df["timestamp"].dt.year, df["timestamp"].dt.month], sort=True)
            for (year, month), chunk in grouped:
                file_name = f"{PAIR}_{year:04d}-{month:02d}.csv"
                file_path = path_obj / file_name if path_obj.is_dir() else path_obj
                if path_obj.is_dir():
                    LOGGER.info("Writing CSV partition %s", file_path)
                chunk.to_csv(file_path, index=False, quoting=csv.QUOTE_NONNUMERIC)
        else:
            if path_obj.parent and not path_obj.parent.exists():
                path_obj.parent.mkdir(parents=True, exist_ok=True)
            LOGGER.info("Writing CSV %s", path_obj)
            df.to_csv(path_obj, index=False, quoting=csv.QUOTE_NONNUMERIC)
        return

    if fmt != "parquet":
        raise ValueError("Unsupported format; use 'csv' or 'parquet'")

    _ensure_pyarrow()

    filesystem, fs_path = _resolve_filesystem(out_path)

    if partition_by == "month":
        df["year"] = df["timestamp"].dt.year
        df["month"] = df["timestamp"].dt.month
        for (year, month), chunk in df.groupby(["year", "month"], sort=True):
            relative_dir = f"pair={PAIR}/year={year:04d}/month={month:02d}"
            file_name = f"{PAIR}_{year:04d}-{month:02d}.parquet"
            table = pa.Table.from_pandas(chunk.drop(columns=["year", "month"]))
            if filesystem is None:
                partition_dir = fs_path / relative_dir
                partition_dir.mkdir(parents=True, exist_ok=True)
                file_path = partition_dir / file_name
                LOGGER.info("Writing Parquet partition %s", file_path)
                pq.write_table(table, file_path, compression="snappy")
            else:
                directory = f"{fs_path.rstrip('/')}" if fs_path else ""
                if directory:
                    directory = f"{directory.rstrip('/')}/{relative_dir}"
                else:
                    directory = relative_dir
                filesystem.create_dir(directory, recursive=True)
                target = f"{directory}/{file_name}"
                fs_name = getattr(filesystem, "type_name", lambda: "fs")
                fs_label = fs_name() if callable(fs_name) else fs_name
                LOGGER.info("Writing Parquet partition %s://%s", fs_label, target)
                with filesystem.open_output_stream(target) as sink:
                    pq.write_table(table, sink, compression="snappy")
        return

    table = pa.Table.from_pandas(df)
    if filesystem is None:
        file_path = fs_path
        if file_path.parent and not file_path.parent.exists():
            file_path.parent.mkdir(parents=True, exist_ok=True)
        LOGGER.info("Writing Parquet %s", file_path)
        pq.write_table(table, file_path, compression="snappy")
    else:
        directory, _, file_name = fs_path.rpartition("/")
        if directory:
            filesystem.create_dir(directory, recursive=True)
        target = fs_path
        fs_name = getattr(filesystem, "type_name", lambda: "fs")
        fs_label = fs_name() if callable(fs_name) else fs_name
        LOGGER.info("Writing Parquet %s://%s", fs_label, target)
        with filesystem.open_output_stream(target) as sink:
            pq.write_table(table, sink, compression="snappy")


def read_dataset(path: str, fmt: Literal["parquet", "csv"] | None = None) -> pd.DataFrame:
    """Load dataset from disk for validation."""

    is_remote = "://" in path
    if fmt is None and not is_remote:
        path_obj = Path(path)
        if path_obj.is_dir():
            fmt = "parquet"
        else:
            fmt = "csv" if path_obj.suffix.lower() == ".csv" else "parquet"
    elif fmt is None:
        fmt = "parquet"

    if fmt == "csv":
        if is_remote:
            raise ValueError("CSV validation does not support remote URIs")
        path_obj = Path(path)
        if path_obj.is_dir():
            frames: List[pd.DataFrame] = []
            for csv_file in sorted(path_obj.glob("*.csv")):
                LOGGER.info("Loading %s", csv_file)
                frames.append(
                    pd.read_csv(
                        csv_file,
                        parse_dates=["timestamp"],
                        date_parser=lambda x: pd.to_datetime(x, utc=True),
                    )
                )
            if not frames:
                raise ValueError(f"No CSV files found under {path}")
            return pd.concat(frames, ignore_index=True)
        LOGGER.info("Loading %s", path_obj)
        return pd.read_csv(
            path_obj,
            parse_dates=["timestamp"],
            date_parser=lambda x: pd.to_datetime(x, utc=True),
        )

    if fmt != "parquet":
        raise ValueError("Format must be 'csv' or 'parquet'")

    _ensure_pyarrow()
    if is_remote:
        LOGGER.info("Loading Parquet dataset %s", path)
        dataset = ds.dataset(path, format="parquet")
        table = dataset.to_table()
        df = table.to_pandas()
    else:
        path_obj = Path(path)
        if path_obj.is_dir():
            LOGGER.info("Loading Parquet dataset %s", path_obj)
            dataset = ds.dataset(path_obj, format="parquet")
            table = dataset.to_table()
            df = table.to_pandas()
        else:
            LOGGER.info("Loading %s", path_obj)
            table = pq.read_table(path_obj)
            df = table.to_pandas()
    extra_cols = set(df.columns) - set(SCHEMA_COLUMNS)
    if extra_cols:
        df = df.drop(columns=list(extra_cols))
    return df


# ---------------------------------------------------------------------------
# Resampling utilities
# ---------------------------------------------------------------------------

def resample_ticks_to_30s(
    df_ticks: pd.DataFrame,
    volume_mode: Literal["tickcount", "sumsize"] = "tickcount",
) -> pd.DataFrame:
    """Resample tick data to 30-second OHLCV bars."""

    if df_ticks.empty:
        return pd.DataFrame(columns=SCHEMA_COLUMNS)

    df = df_ticks.copy()
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df.sort_values("time")
    df = df.set_index("time")

    def ohlc(series: pd.Series) -> pd.Series:
        return pd.Series(
            {
                "open": series.iloc[0],
                "high": series.max(),
                "low": series.min(),
                "close": series.iloc[-1],
            }
        )

    bid = df["bid"].resample("30S", label="right", closed="right").apply(ohlc).dropna()
    ask = df["ask"].resample("30S", label="right", closed="right").apply(ohlc).dropna()

    if volume_mode == "sumsize" and {"bidVolume", "askVolume"}.issubset(df.columns):
        volume = (df["bidVolume"] + df["askVolume"]).resample("30S", label="right", closed="right").sum()
    else:
        volume = df["bid"].resample("30S", label="right", closed="right").count()

    out = pd.DataFrame(
        {
            "timestamp": bid.index,
            "bid_open": bid["open"].values,
            "bid_high": bid["high"].values,
            "bid_low": bid["low"].values,
            "bid_close": bid["close"].values,
            "ask_open": ask["open"].values,
            "ask_high": ask["high"].values,
            "ask_low": ask["low"].values,
            "ask_close": ask["close"].values,
            "volume": volume.values,
        }
    )

    return out


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------


class BaseProvider(ABC):
    def __init__(self) -> None:
        self.logger = logging.getLogger(self.__class__.__name__)

    @abstractmethod
    def fetch(self, start: datetime, end: datetime) -> pd.DataFrame:
        """Fetch data between start (inclusive) and end (exclusive)."""


@dataclass
class DukascopyConfig:
    downsample_policy: Literal["tickcount", "sumsize"] = "tickcount"


class DukascopyProvider(BaseProvider):
    def __init__(self, config: DukascopyConfig) -> None:
        super().__init__()
        self.config = config
        if importlib.util.find_spec("duka") is None:
            raise RuntimeError(
                "The Dukascopy importer requires the 'duka' package. Install it with `pip install duka==0.2.3` "
                "before running a Dukascopy ingestion job."
            )

    @retry(
        reraise=True,
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=1, max=30),
        retry=retry_if_exception_type(subprocess.CalledProcessError),
    )
    def _run_duka(self, start: datetime, end: datetime, output_dir: Path) -> None:
        """Invoke the duka CLI to download ticks."""

        command = [
            sys.executable,
            "-m",
            "duka",
            "download",
            "-i",
            PAIR,
            "-from",
            start.strftime("%Y-%m-%d %H:%M"),
            "-to",
            (end - timedelta(seconds=1)).strftime("%Y-%m-%d %H:%M"),
            "-t",
            "tick",
            "-o",
            str(output_dir),
        ]
        self.logger.info("Downloading ticks %s -> %s", start.isoformat(), end.isoformat())
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        if result.returncode != 0:
            raise subprocess.CalledProcessError(
                result.returncode,
                command,
                output=result.stdout,
                stderr=result.stderr,
            )

    def fetch(self, start: datetime, end: datetime) -> pd.DataFrame:
        volume_mode = "sumsize" if self.config.downsample_policy == "sumsize" else "tickcount"
        frames: List[pd.DataFrame] = []
        with tempfile.TemporaryDirectory(prefix="duka_") as tmpdir:
            day_start = start
            while day_start < end:
                day_end = min(day_start + timedelta(days=1), end)
                day_dir = Path(tmpdir) / day_start.strftime("%Y%m%d")
                day_dir.mkdir(parents=True, exist_ok=True)
                try:
                    self._run_duka(day_start, day_end, day_dir)
                except RetryError as exc:
                    raise RuntimeError(f"Failed to download Dukascopy ticks for {day_start.date()}: {exc}") from exc

                tick_frames = self._load_tick_csvs(day_dir)
                if tick_frames:
                    frames.extend(tick_frames)
                day_start = day_end

        if not frames:
            self.logger.warning("No tick data retrieved from Dukascopy")
            return pd.DataFrame(columns=SCHEMA_COLUMNS)

        ticks = pd.concat(frames, ignore_index=True)
        ticks["time"] = pd.to_datetime(ticks["time"], utc=True)
        ticks = ticks[(ticks["time"] >= start) & (ticks["time"] <= end)]
        bars = resample_ticks_to_30s(ticks, volume_mode=volume_mode)
        bars = bars[(bars["timestamp"] > start) & (bars["timestamp"] <= end)]
        return bars

    def _load_tick_csvs(self, directory: Path) -> List[pd.DataFrame]:
        frames: List[pd.DataFrame] = []
        for csv_path in directory.rglob("*.csv"):
            self.logger.debug("Reading %s", csv_path)
            df = pd.read_csv(csv_path)
            df = df.rename(
                columns={
                    "Ask": "ask",
                    "Bid": "bid",
                    "AskVolume": "askVolume",
                    "BidVolume": "bidVolume",
                }
            )
            expected_cols = {"time", "bid", "ask"}
            if not expected_cols.issubset(df.columns):
                raise RuntimeError(f"Unexpected Dukascopy schema in {csv_path}")
            for col in ("bidVolume", "askVolume"):
                if col not in df.columns:
                    df[col] = 0.0
            frames.append(df[["time", "bid", "ask", "bidVolume", "askVolume"]])
        return frames


@dataclass
class OandaConfig:
    api_key: str
    account_type: Literal["practice", "live"] = "practice"


class OandaProvider(BaseProvider):
    def __init__(self, config: OandaConfig) -> None:
        super().__init__()
        self.config = config
        domain = "api-fxpractice" if config.account_type == "practice" else "api-fxtrade"
        self.base_url = f"https://{domain}.oanda.com/v3/instruments/{PAIR.replace('/', '_')}"

    @retry(
        reraise=True,
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=1, max=30),
        retry=retry_if_exception_type(Exception),
    )
    def _request(self, params: dict) -> dict:
        import requests

        url = f"{self.base_url}/candles"
        headers = {"Authorization": f"Bearer {self.config.api_key}"}
        response = requests.get(url, headers=headers, params=params, timeout=60)
        if response.status_code in {429, 500, 502, 503, 504}:
            raise RuntimeError(f"OANDA request failed: {response.status_code} {response.text[:200]}")
        response.raise_for_status()
        return response.json()

    def fetch(self, start: datetime, end: datetime) -> pd.DataFrame:
        current = start
        records: List[dict] = []
        while current < end:
            params = {
                "granularity": "S30",
                "price": "BA",
                "from": current.isoformat().replace("+00:00", "Z"),
                "to": end.isoformat().replace("+00:00", "Z"),
                "count": 5000,
            }
            try:
                payload = self._request(params)
            except RetryError as exc:
                raise RuntimeError(f"Failed to fetch OANDA candles: {exc}") from exc

            candles = payload.get("candles", [])
            if not candles:
                break

            for candle in candles:
                if not candle.get("complete", True):
                    continue
                timestamp = pd.Timestamp(candle["time"]).tz_convert("UTC")
                if timestamp <= current:
                    continue
                if timestamp > end:
                    break
                bid = candle["bid"]
                ask = candle["ask"]
                records.append(
                    {
                        "timestamp": timestamp,
                        "bid_open": float(bid["o"]),
                        "bid_high": float(bid["h"]),
                        "bid_low": float(bid["l"]),
                        "bid_close": float(bid["c"]),
                        "ask_open": float(ask["o"]),
                        "ask_high": float(ask["h"]),
                        "ask_low": float(ask["l"]),
                        "ask_close": float(ask["c"]),
                        "volume": int(candle.get("volume", 0)),
                    }
                )
            last_ts = records[-1]["timestamp"] if records else current
            current = max(current + timedelta(seconds=30), last_ts + timedelta(seconds=30))

        df = pd.DataFrame(records, columns=SCHEMA_COLUMNS)
        return df


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

def configure_logging(level: str) -> None:
    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO), format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def run_fetch(args: argparse.Namespace) -> int:
    configure_logging(args.log_level)
    start = to_utc_datetime(args.start)
    end = to_utc_datetime(args.end)
    if end <= start:
        raise SystemExit("--end must be after --start")

    LOGGER.info("Requested range %s -> %s", start.isoformat(), end.isoformat())
    if args.dry_run:
        LOGGER.info("Dry run complete; nothing fetched")
        return 0

    if args.provider == "dukascopy":
        volume_policy = args.downsample_policy
        if args.volume:
            volume_policy = "sumsize" if args.volume.lower() == "sum_size" else "tickcount"
        provider = DukascopyProvider(DukascopyConfig(downsample_policy=volume_policy))
    else:
        api_key = os.environ.get("OANDA_API_KEY")
        if not api_key:
            raise SystemExit("OANDA_API_KEY environment variable is required for provider=oanda")
        account_type = os.environ.get("OANDA_ACCOUNT_TYPE", "practice")
        provider = OandaProvider(OandaConfig(api_key=api_key, account_type=account_type))

    df = provider.fetch(start, end)
    if df.empty:
        raise SystemExit("No data retrieved for the requested range")

    df = df.sort_values("timestamp").reset_index(drop=True)
    df = df[(df["timestamp"] > start) & (df["timestamp"] <= end)]
    if df.empty:
        raise SystemExit("Dataset empty after filtering to requested range")

    write_dataset(df, args.out, fmt=args.format, partition_by=args.partition_by)
    LOGGER.info(
        "Wrote %s rows covering %s to %s",
        len(df),
        df["timestamp"].iloc[0].isoformat(),
        df["timestamp"].iloc[-1].isoformat(),
    )
    return 0


def run_validate(args: argparse.Namespace) -> int:
    configure_logging(args.log_level)
    df = read_dataset(args.path, fmt=args.format)
    validate_dataset(df)
    LOGGER.info(
        "Validated %s rows spanning %s to %s",
        len(df),
        df["timestamp"].iloc[0].isoformat() if not df.empty else "n/a",
        df["timestamp"].iloc[-1].isoformat() if not df.empty else "n/a",
    )
    return 0


def build_fetch_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch EUR/USD bid/ask data and write 30-second candles",
        add_help=False,
    )
    general = parser.add_argument_group("General")
    general.add_argument("--provider", choices=["dukascopy", "oanda"], required=True)
    general.add_argument("--start", required=True, help="UTC start timestamp (inclusive)")
    general.add_argument("--end", required=True, help="UTC end timestamp (exclusive)")
    general.add_argument("--out", required=True, help="Output file or directory")
    general.add_argument("--format", choices=["parquet", "csv"], default="parquet")
    general.add_argument("--partition-by", choices=["month"], default=None)
    general.add_argument("--dry-run", action="store_true", help="Print planned actions and exit")
    general.add_argument("--log-level", default="INFO", help="Logging level (default INFO)")

    dukas = parser.add_argument_group("Dukascopy options")
    dukas.add_argument(
        "--downsample-policy",
        choices=["tickcount", "sumsize"],
        default="tickcount",
        help="How to aggregate tick volume when resampling",
    )
    dukas.add_argument(
        "--volume",
        choices=["tickcount", "sum_size"],
        help="Compatibility alias for downsample policy",
    )

    return parser


def build_validate_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate an existing EUR/USD dataset")
    parser.add_argument("path", help="File or directory to validate")
    parser.add_argument("--format", choices=["parquet", "csv"], default=None)
    parser.add_argument("--log-level", default="INFO")
    return parser


def main(argv: Optional[Iterable[str]] = None) -> int:
    argv = list(argv or sys.argv[1:])
    if not argv:
        fetch_parser = build_fetch_parser()
        fetch_parser.print_help(sys.stderr)
        return 1

    if argv[0] in {"validate", "validate_only"}:
        validate_parser = build_validate_parser()
        args = validate_parser.parse_args(argv[1:])
        return run_validate(args)

    fetch_parser = build_fetch_parser()
    args = fetch_parser.parse_args(argv)
    return run_fetch(args)


if __name__ == "__main__":
    raise SystemExit(main())
