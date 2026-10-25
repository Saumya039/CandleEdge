from __future__ import annotations

import asyncio
import csv
import io
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from stratagy.app import create_app
from stratagy.backtest import run_backtest
from stratagy.config import Settings
from stratagy.journal import Journal
from stratagy.models import IST, DataStatus
from stratagy.providers.base import ProviderUnavailable
from stratagy.providers.kite import KiteProvider
from stratagy.providers.simulator import SimulatorProvider


# ------------------------------------------------------------------ API
@pytest.fixture
def client():
    prov = SimulatorProvider(seed=5, sim_date=date(2026, 10, 23))
    app = create_app(Settings(provider="simulator"), provider=prov, journal=Journal("sqlite://", create_tables=True), autorun=False)
    with TestClient(app) as c:
        yield c, app.state.st


def test_health_and_no_order_surface(client):
    c, st = client
    h = c.get("/api/health").json()
    assert h["status"] == "ok" and h["live_orders_enabled"] is False and h["order_api_present"] is False
    paths = [r.path for r in c.app.routes]
    assert not [p for p in paths if "order" in p.lower()]
    r = c.get("/api/health")
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-request-id"]


def test_state_labels_simulation_and_phase(client):
    c, st = client
    s = c.get("/api/state").json()
    assert s["badge"] == "SIMULATION" and s["data"]["is_simulated"] is True and s["data"]["status"] == "SIMULATED"
    assert s["phase"] == "PRE_MARKET" and s["tz"] == "Asia/Kolkata" and s["live_orders_enabled"] is False
    assert "Not investment advice" in s["disclaimer"]
    assert s["next_event"]["label"] == "Market opens"
    assert {w["symbol"] for w in s["watchlist"]} == {"NIFTY", "BANKNIFTY"}


def test_simulation_run_then_chart_chain_signals(client):
    c, st = client
    r = c.post("/api/simulator/control", json={"action": "skip", "value": 3 * 3600})
    assert r.status_code == 200
    s = c.get("/api/state").json()
    assert s["phase"] in ("TRADING", "OPENING_RANGE") and s["watchlist"][0]["ltp"]
    ch = c.get("/api/underlyings/NIFTY/candles", params={"tf": "5m"}).json()
    assert ch["label"] == "SIMULATED" and ch["candles"] and ch["opening_range"]["complete"] is True
    ts = [x["t"] for x in ch["candles"]]
    assert ts == sorted(ts) and len(set(ts)) == len(ts)  # ordered, no duplicates
    assert len(ch["ema9"]) == len(ch["candles"])
    chain = c.get("/api/underlyings/NIFTY/option-chain").json()
    assert chain["available"] and chain["status"] == "SIMULATED" and chain["rows"]
    assert "never a standalone signal" in chain["context_note"]
    ev = c.get("/api/underlyings/BANKNIFTY/evaluation").json()
    assert ev["decision"] in ("CANDIDATE", "NO_TRADE") and ev["strategy_version"]
    assert c.get("/api/underlyings/XYZ/candles").status_code == 404


def test_settings_controls_and_audit(client):
    c, st = client
    risk = dict(c.get("/api/state").json()["risk_settings"])
    assert risk["confirmed"] is False  # sizing refused until the user confirms
    risk.update(confirmed=True, trading_cutoff="15:10")
    r = c.post("/api/settings/risk", json={k: v for k, v in risk.items() if k not in ("paper_square_off",)})
    assert r.status_code == 200 and r.json()["confirmed"] is True and r.json()["trading_cutoff"] == "15:10:00"
    bad = dict(risk, max_risk_per_trade=-5)
    assert c.post("/api/settings/risk", json=bad).status_code == 422
    assert c.post("/api/settings/risk", json=dict(risk, trading_cutoff="25:99")).status_code in (422, 500)
    assert c.post("/api/settings/strategy", json={"trigger_tf": "15m", "sensitivity": "conservative"}).json()["version"].endswith("+tf15m+conservative")
    assert c.post("/api/settings/strategy", json={"trigger_tf": "7m", "sensitivity": "standard"}).status_code == 422
    assert c.post("/api/control/pause", json={"paused": True, "reason": "lunch"}).json() == {"paused": True}
    assert c.get("/api/state").json()["risk_state"]["paused"] is True
    kinds = [a["kind"] for a in c.get("/api/audit").json()]
    assert {"risk_settings_changed", "strategy_changed", "pause"} <= set(kinds)


def test_simulator_restart_and_outage_controls(client):
    c, st = client
    c.post("/api/simulator/control", json={"action": "skip", "value": 40 * 60})
    c.post("/api/simulator/control", json={"action": "outage", "value": 600})
    c.post("/api/simulator/control", json={"action": "skip", "value": 5 * 60})
    s = c.get("/api/state").json()
    assert s["stale"] is True and s["badge"] == "STALE DATA"
    c.post("/api/simulator/control", json={"action": "restart", "value": 9})
    s = c.get("/api/state").json()
    assert s["phase"] == "PRE_MARKET" and s["simulator"]["seed"] == 9


def test_provider_status_documents_requirements(client):
    c, _ = client
    j = c.get("/api/provider").json()
    names = {r["provider"]: r for r in j["capability_matrix"]}
    assert names["kite"]["order_api"] is False and names["simulator"]["requires_auth"] is False
    assert "KITE_ACCESS_TOKEN" in j["setup"]["kite"]["env"]


def test_backtest_job_endpoint(client):
    c, _ = client
    r = c.post("/api/backtest/run", json={"sessions": 2, "first_seed": 5})
    jid = r.json()["job"]
    assert c.get("/api/backtest/jobs/nope").status_code == 404
    assert jid


# ------------------------------------------------------------------ Kite adapter (contract tests, mocked transport)
INSTR_CSV_COLS = ["instrument_token", "exchange_token", "tradingsymbol", "name", "last_price", "expiry", "strike",
                  "tick_size", "lot_size", "instrument_type", "segment", "exchange"]


def instruments_csv(today: date) -> str:
    exp = (today + timedelta(days=3)).isoformat()
    rows = [[1000, 1, "NIFTYFUT", "NIFTY", 0, (today + timedelta(days=20)).isoformat(), 0, 0.05, 75, "FUT", "NFO-FUT", "NFO"]]
    tok = 2000
    for k in range(24300, 24701, 50):
        for t in ("CE", "PE"):
            tok += 1
            rows.append([tok, tok, f"NIFTYOPT{k}{t}", "NIFTY", 0, exp, k, 0.05, 75, t, "NFO-OPT", "NFO"])
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(INSTR_CSV_COLS)
    w.writerows(rows)
    return buf.getvalue()


def kite_handler(today: date, status_profile=200, quote_fail=False):
    now = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.headers["x-kite-version"] == "3" and req.headers["authorization"].startswith("token ")
        assert "order" not in req.url.path  # the adapter must never touch order endpoints
        p = req.url.path
        if p == "/user/profile":
            return httpx.Response(status_profile, json={"status": "success", "data": {"user_id": "AB1234"}})
        if p == "/instruments":
            return httpx.Response(200, text=instruments_csv(today))
        if p == "/quote":
            if quote_fail:
                return httpx.Response(500)
            data = {}
            for key in req.url.params.get_list("i"):
                if "FUT" in key:
                    data[key] = {"last_price": 24500.0, "volume": 12345, "oi": 1, "timestamp": now, "last_trade_time": now}
                else:
                    strike = int(key.replace("NFO:NIFTYOPT", "")[:-2])
                    px = max(24500 - strike, 0) + 120 - abs(24500 - strike) * 0.3 if key.endswith("CE") else max(strike - 24500, 0) + 120 - abs(24500 - strike) * 0.3
                    px = max(px, 5.0)
                    data[key] = {"last_price": px, "volume": 5000, "oi": 90000, "timestamp": now, "last_trade_time": now,
                                 "depth": {"buy": [{"price": px - 0.5, "quantity": 75, "orders": 3}], "sell": [{"price": px + 0.5, "quantity": 75, "orders": 3}]}}
            return httpx.Response(200, json={"status": "success", "data": data})
        if p.startswith("/instruments/historical/"):
            return httpx.Response(200, json={"status": "success", "data": {"candles": [
                ["2026-10-22T09:15:00+0530", 100, 101, 99, 100.5, 1000], ["2026-10-22T09:16:00+0530", 100.5, 102, 100, 101, 900]]}})
        return httpx.Response(404)

    return handler


def make_kite(handler, key="k", token="t"):
    return KiteProvider(key, token, ["NIFTY"], transport=httpx.MockTransport(handler), poll_interval_s=0.05)


def test_kite_without_credentials_gives_explicit_setup_state_not_fake_data():
    p = KiteProvider("", "", ["NIFTY"])
    h = p.get_health()
    assert h.status == DataStatus.UNAVAILABLE and h.missing_credentials == ["KITE_API_KEY", "KITE_ACCESS_TOKEN"]
    with pytest.raises(ProviderUnavailable) as e:
        asyncio.run(p.connect())
    assert "KITE_ACCESS_TOKEN" in str(e.value)


def test_kite_rejected_token_is_reported_as_unavailable_not_live():
    p = make_kite(kite_handler(date.today(), status_profile=403))
    with pytest.raises(ProviderUnavailable):
        asyncio.run(p.connect())
    assert p.get_health().status == DataStatus.UNAVAILABLE and not p.get_health().authenticated


def test_kite_chain_history_and_ticks_via_mock_transport():
    today = datetime.now(IST).date()

    async def go():
        p = make_kite(kite_handler(today))
        p._lock = asyncio.Lock()
        await p.connect()
        specs = p.underlyings()
        assert [s.symbol for s in specs] == ["NIFTY"] and specs[0].signal_instrument.lot_size == 75  # lot size from master
        ticks = []
        await p.subscribe_ticks([specs[0].signal_instrument.id], ticks.append)
        await asyncio.sleep(1.6)
        assert ticks and ticks[0].ltp == 24500.0 and ticks[0].exchange_ts is not None
        assert p.get_health().status == DataStatus.LIVE and p.get_health().authenticated
        chain = await p.get_option_chain("NIFTY")
        assert chain.status == DataStatus.LIVE and chain.source == "kite" and chain.forward == 24500.0
        q = next(r.ce for r in chain.rows if r.strike == 24500)
        assert q.bid and q.ask and q.ask > q.bid and q.instrument.lot_size == 75
        assert q.greeks is None or q.greeks.source == "estimated"  # never presented as provider greeks
        hist = await p.get_historical_candles(specs[0].signal_instrument.id, "1m", datetime(2026, 10, 22, 9, 0, tzinfo=IST), datetime(2026, 10, 22, 10, 0, tzinfo=IST))
        assert len(hist) == 2 and hist[0].ts.tzinfo is not None and hist[0].source == "KITE_HIST"
        await p.disconnect()

    asyncio.run(go())


def test_kite_poll_failures_degrade_health_with_backoff():
    today = datetime.now(IST).date()

    async def go():
        p = make_kite(kite_handler(today, quote_fail=True))
        await p.connect()
        await p.subscribe_ticks(["NFO:NIFTYFUT"], lambda t: None)
        await asyncio.sleep(1.5)
        h = p.get_health()
        assert h.connected is False and "poll error" in h.message
        await p.disconnect()

    asyncio.run(go())


# ------------------------------------------------------------------ backtest + migrations
def test_backtest_runs_with_no_lookahead_and_honest_labelling():
    res = asyncio.run(run_backtest([5, 6], date(2026, 1, 5)))
    assert res["origin"] == "BACKTEST" and "SIMULATED" in res["data_label"] and res["sessions"] == 2
    assert "no_lookahead" in res and any("synthetic" in x.lower() for x in res["limitations"])
    assert res["overall"]["trades"] == res["in_sample"]["trades"] + res["out_of_sample"]["trades"]
    assert "forecast" in res["disclaimer"]
    assert res["overall"]["sample_warning"]  # tiny sample is flagged


def test_alembic_migration_creates_all_tables():
    from sqlalchemy import create_engine, inspect

    from stratagy.migrate import upgrade

    with tempfile.TemporaryDirectory() as d:
        url = f"sqlite:///{Path(d) / 'm.db'}"
        upgrade(url)
        tables = set(inspect(create_engine(url)).get_table_names())
    assert {"signals", "paper_trades", "candles", "health_events", "audit_events", "strategy_versions", "alembic_version"} <= tables
