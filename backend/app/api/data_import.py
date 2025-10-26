"""API endpoints for managing historical data ingestion."""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

import pandas as pd
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator

from eurusd_ingest import DukascopyConfig, DukascopyProvider, validate_dataset

from .. import db

router = APIRouter(prefix="/data-import", tags=["data-import"])


class ImportRequest(BaseModel):
    start: datetime = Field(..., description="Start timestamp (UTC) of the import window.")
    end: datetime = Field(..., description="End timestamp (UTC) of the import window.")
    downsample_policy: Literal["tickcount", "sumsize"] = Field(
        "tickcount", description="Volume aggregation policy when resampling ticks."
    )
    dry_run: bool = Field(
        False, description="If true, fetch and validate the data but do not persist it."
    )

    @model_validator(mode="after")
    def _validate_range(cls, values: "ImportRequest") -> "ImportRequest":
        if values.end <= values.start:
            raise ValueError("End timestamp must be greater than start timestamp.")
        return values


class ImportResponse(BaseModel):
    rows: int
    stored_rows: int
    start_timestamp: Optional[datetime]
    end_timestamp: Optional[datetime]
    dry_run: bool


class SummaryResponse(BaseModel):
    rows: int
    start_timestamp: Optional[datetime]
    end_timestamp: Optional[datetime]


def _get_provider(policy: Literal["tickcount", "sumsize"]) -> DukascopyProvider:
    return DukascopyProvider(DukascopyConfig(downsample_policy=policy))


@router.post("/dukascopy", response_model=ImportResponse)
def import_from_dukascopy(payload: ImportRequest) -> ImportResponse:
    """Fetch, validate, and optionally persist Dukascopy EUR/USD data."""

    try:
        provider = _get_provider(payload.downsample_policy)
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error

    try:
        frame = provider.make_bars(payload.start, payload.end)
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    if frame.empty:
        raise HTTPException(status_code=404, detail="No candles returned for the requested range.")

    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    frame = frame.sort_values("timestamp").reset_index(drop=True)
    validate_dataset(frame)

    stored = 0
    if not payload.dry_run:
        try:
            stored = db.upsert_candles(frame)
        except RuntimeError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

    return ImportResponse(
        rows=len(frame),
        stored_rows=stored,
        start_timestamp=frame["timestamp"].iloc[0].to_pydatetime(),
        end_timestamp=frame["timestamp"].iloc[-1].to_pydatetime(),
        dry_run=payload.dry_run,
    )


@router.get("/summary", response_model=SummaryResponse)
def dataset_summary() -> SummaryResponse:
    """Return aggregate statistics for the stored EUR/USD candles."""

    try:
        summary = db.summarize_dataset()
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error

    return SummaryResponse(
        rows=summary.count,
        start_timestamp=None if summary.start is None else summary.start.to_pydatetime(),
        end_timestamp=None if summary.end is None else summary.end.to_pydatetime(),
    )


class ValidationRequest(BaseModel):
    start: Optional[datetime] = Field(None, description="Optional start of validation window.")
    end: Optional[datetime] = Field(None, description="Optional end of validation window.")

    @model_validator(mode="after")
    def _ensure_range(cls, values: "ValidationRequest") -> "ValidationRequest":
        if values.start and values.end and values.end <= values.start:
            raise ValueError("End timestamp must be greater than start timestamp.")
        return values


class ValidationResponse(BaseModel):
    rows: int
    valid: bool


@router.post("/validate", response_model=ValidationResponse)
def validate_stored_data(payload: ValidationRequest) -> ValidationResponse:
    """Load stored candles and run structural validation."""

    try:
        frame = db.load_candles(
            start=None if payload.start is None else pd.Timestamp(payload.start, tz="UTC"),
            end=None if payload.end is None else pd.Timestamp(payload.end, tz="UTC"),
        )
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error

    if frame.empty:
        raise HTTPException(status_code=404, detail="No stored candles found for the requested window.")

    validate_dataset(frame)
    return ValidationResponse(rows=len(frame), valid=True)
