from __future__ import annotations

import os
import tempfile
import time
from datetime import datetime

import pandas as pd
import pytest

from fastapi.testclient import TestClient

_fd, _db_path = tempfile.mkstemp(prefix="eurusd_test_", suffix=".db")
os.close(_fd)
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_db_path}")

from backend.app.main import app  # noqa: E402  pylint: disable=C0413

client = TestClient(app)


def test_healthcheck() -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


def test_root_page() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "EUR/USD Signal Simulator Dashboard" in response.text
    assert "Replay speed" in response.text
    assert "20×" in response.text


def test_simulation_lifecycle() -> None:
    start_payload = {
        "dataset_id": "eurusd_sample",
        "start_ts": datetime.utcnow().isoformat() + "Z",
        "speed": "20x",
        "initial_fund": 10000,
        "leverage_cap": 10,
        "risk_pct": 0.7,
        "entry_thresholds": {"buy": 3, "sell": -3},
        "sl_atr_mult": 1.2,
        "tp_mult": 2.0,
        "trailing_stop": False,
        "spread_model": {"type": "preset", "name": "spread_only"},
        "commission_model": {"type": "none"},
        "event_guard": {"enabled": True, "window_sec": 90},
        "rng_seed": 42,
    }
    response = client.post("/sim/start", json=start_payload)
    assert response.status_code == 200
    run_id = response.json()["run_id"]

    time.sleep(0.3)

    status_response = client.get("/sim/status")
    assert status_response.status_code == 200
    status_payload = status_response.json()
    assert status_payload["run_id"] == run_id
    assert status_payload["clock_ts"] is not None
    assert "trades" in status_payload["kpis"]

    trades = client.get("/sim/trades", params={"run_id": run_id})
    assert trades.status_code == 200
    assert isinstance(trades.json()["trades"], list)

    latest_status = client.get("/sim/status").json()
    stop = client.post("/sim/stop")
    if latest_status["run_id"]:
        assert stop.status_code == 200
        assert stop.json()["status"] == "stopped"
    else:
        assert stop.status_code == 400



def test_signal_endpoint() -> None:
    response = client.get("/signals")
    assert response.status_code == 200
    data = response.json()
    assert data["asset"] == "EUR_USD"
    assert -5 <= data["signal_int"] <= 5
    assert "prev_signal_int" in data["meta"]


def test_data_import_page() -> None:
    response = client.get("/data-import")
    assert response.status_code == 200
    assert "EUR/USD Data Import" in response.text
    assert "Run Dukascopy import" in response.text
    assert "pip install duka==0.2.3" in response.text


@pytest.fixture
def stubbed_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.app.api import data_import as data_api

    class _FakeProvider:
        def make_bars(self, start: datetime, end: datetime) -> pd.DataFrame:
            base = pd.date_range(start="2024-01-01T00:00:30Z", periods=4, freq="30S")
            return pd.DataFrame(
                {
                    "timestamp": base,
                    "bid_open": [1.08, 1.0805, 1.0810, 1.0815],
                    "bid_high": [1.081, 1.081, 1.0815, 1.082],
                    "bid_low": [1.0795, 1.0800, 1.0805, 1.0810],
                    "bid_close": [1.0805, 1.0810, 1.0815, 1.0818],
                    "ask_open": [1.0802, 1.0807, 1.0812, 1.0817],
                    "ask_high": [1.0812, 1.0814, 1.0819, 1.0824],
                    "ask_low": [1.0797, 1.0802, 1.0807, 1.0812],
                    "ask_close": [1.0807, 1.0812, 1.0817, 1.0820],
                    "volume": [25, 30, 28, 32],
                }
            )

    monkeypatch.setattr(data_api, "_get_provider", lambda policy: _FakeProvider())


def test_data_import_flow(stubbed_provider: None) -> None:
    start_ts = "2024-01-01T00:00:00Z"
    end_ts = "2024-01-01T00:02:00Z"

    response = client.post(
        "/data-import/dukascopy",
        json={
            "start": start_ts,
            "end": end_ts,
            "downsample_policy": "tickcount",
            "dry_run": False,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["rows"] == 4
    assert payload["stored_rows"] >= 4

    summary = client.get("/data-import/summary")
    assert summary.status_code == 200
    summary_payload = summary.json()
    assert summary_payload["rows"] >= 4

    validation = client.post("/data-import/validate", json={})
    assert validation.status_code == 200
    validation_payload = validation.json()
    assert validation_payload["valid"] is True


def test_data_import_missing_dependency(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(_policy: str) -> None:
        raise RuntimeError("install duka")

    monkeypatch.setattr(data_api, "_get_provider", _raise)

    response = client.post(
        "/data-import/dukascopy",
        json={
            "start": "2024-01-01T00:00:00Z",
            "end": "2024-01-01T00:01:00Z",
            "downsample_policy": "tickcount",
        },
    )

    assert response.status_code == 503
    assert "install duka" in response.json()["detail"].lower()
