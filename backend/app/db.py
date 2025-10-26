"""Database utilities for candle storage."""
from __future__ import annotations

import os
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator, Optional

import pandas as pd
from sqlalchemy import Column, DateTime, Float, MetaData, Table, create_engine, func, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

DATABASE_URL_ENV = "DATABASE_URL"


metadata = MetaData()

eurusd_candles = Table(
    "eurusd_candles",
    metadata,
    Column("timestamp", DateTime(timezone=True), primary_key=True),
    Column("bid_open", Float, nullable=False),
    Column("bid_high", Float, nullable=False),
    Column("bid_low", Float, nullable=False),
    Column("bid_close", Float, nullable=False),
    Column("ask_open", Float, nullable=False),
    Column("ask_high", Float, nullable=False),
    Column("ask_low", Float, nullable=False),
    Column("ask_close", Float, nullable=False),
    Column("volume", Float, nullable=False),
)


_engine: Optional[Engine] = None
_Session: Optional[sessionmaker] = None


def _to_utc_timestamp(value) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return ts


def get_engine() -> Engine:
    """Return the SQLAlchemy engine configured from ``DATABASE_URL``."""

    global _engine
    if _engine is None:
        database_url = os.environ.get(DATABASE_URL_ENV)
        if not database_url:
            raise RuntimeError(
                "DATABASE_URL is required to store imported candles. "
                "Set the environment variable before triggering an import."
            )
        _engine = create_engine(database_url, future=True, pool_pre_ping=True)
    return _engine


def ensure_database() -> None:
    """Create the required tables if they do not exist."""

    engine = get_engine()
    metadata.create_all(engine)


def get_session() -> Session:
    """Return a scoped session for imperative usage."""

    global _Session
    if _Session is None:
        _Session = sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)
    return _Session()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Provide a transactional scope for a series of operations."""

    session = get_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def upsert_candles(frame: pd.DataFrame) -> int:
    """Persist the provided candles, returning the affected row count."""

    if frame.empty:
        return 0

    ensure_database()
    records = []
    for row in frame.to_dict(orient="records"):
        normalised = {key: value for key, value in row.items()}
        normalised["timestamp"] = _to_utc_timestamp(normalised["timestamp"]).to_pydatetime()
        records.append(normalised)

    engine = get_engine()
    backend = engine.url.get_backend_name()
    if backend == "postgresql":
        stmt = postgresql.insert(eurusd_candles).values(records)
        update_cols = {
            column.name: stmt.excluded[column.name]
            for column in eurusd_candles.c
            if column.name != "timestamp"
        }
        stmt = stmt.on_conflict_do_update(
            index_elements=[eurusd_candles.c.timestamp], set_=update_cols
        )
    else:
        from sqlalchemy import insert
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        if backend == "sqlite":
            stmt = sqlite_insert(eurusd_candles).values(records)
            update_cols = {
                column.name: stmt.excluded[column.name]
                for column in eurusd_candles.c
                if column.name != "timestamp"
            }
            stmt = stmt.on_conflict_do_update(
                index_elements=[eurusd_candles.c.timestamp], set_=update_cols
            )
        else:
            stmt = insert(eurusd_candles).values(records)

    with engine.begin() as connection:
        result = connection.execute(stmt)
    return int(result.rowcount or 0)


@dataclass
class DatasetSummary:
    count: int
    start: Optional[pd.Timestamp]
    end: Optional[pd.Timestamp]


def summarize_dataset() -> DatasetSummary:
    """Return aggregate information about the stored candles."""

    ensure_database()
    engine = get_engine()
    with engine.connect() as connection:
        count = connection.execute(select(func.count()).select_from(eurusd_candles)).scalar_one()
        if count == 0:
            return DatasetSummary(count=0, start=None, end=None)
        min_ts = connection.execute(select(eurusd_candles.c.timestamp).order_by(eurusd_candles.c.timestamp).limit(1)).scalar_one()
        max_ts = connection.execute(select(eurusd_candles.c.timestamp).order_by(eurusd_candles.c.timestamp.desc()).limit(1)).scalar_one()
    return DatasetSummary(
        count=int(count),
        start=_to_utc_timestamp(min_ts),
        end=_to_utc_timestamp(max_ts),
    )


def load_candles(start: Optional[pd.Timestamp] = None, end: Optional[pd.Timestamp] = None) -> pd.DataFrame:
    """Fetch candles from storage for validation or inspection."""

    ensure_database()
    query = select(eurusd_candles)
    if start is not None:
        query = query.where(eurusd_candles.c.timestamp >= start.to_pydatetime())
    if end is not None:
        query = query.where(eurusd_candles.c.timestamp <= end.to_pydatetime())

    engine = get_engine()
    with engine.connect() as connection:
        result = connection.execute(query).mappings().all()
    frame = pd.DataFrame(result)
    if frame.empty:
        return pd.DataFrame(columns=[column.name for column in eurusd_candles.c])
    frame["timestamp"] = frame["timestamp"].apply(_to_utc_timestamp)
    ordered_columns = [column.name for column in eurusd_candles.c]
    return frame[ordered_columns]
