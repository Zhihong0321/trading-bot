from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient

from backend.app.main import app

client = TestClient(app)


def test_healthcheck() -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


def test_root_page() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "EUR/USD Signal Simulator API" in response.text


def test_simulation_lifecycle() -> None:
    start_payload = {
        "dataset_id": "eurusd_sample",
        "start_ts": datetime.utcnow().isoformat() + "Z",
        "speed": "1x",
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

    status = client.get("/sim/status")
    assert status.status_code == 200
    assert status.json()["run_id"] == run_id

    trades = client.get("/sim/trades", params={"run_id": run_id})
    assert trades.status_code == 200
    assert trades.json()["trades"] == []

    stop = client.post("/sim/stop")
    assert stop.status_code == 200
    assert stop.json()["status"] == "stopped"



def test_signal_endpoint() -> None:
    response = client.get("/signals")
    assert response.status_code == 200
    data = response.json()
    assert data["asset"] == "EUR_USD"
    assert data["signal_int"] == 0
