from __future__ import annotations

from datetime import datetime
import time

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
