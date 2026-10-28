#!/usr/bin/env python3
"""Record a deterministic SIMULATOR session into a JSON tape for the static replay demo (frontend demo mode).

Everything in the tape comes from this app's own API running on the seeded simulator; nothing is hand-written.
Usage (from backend/, venv active): python ../scripts/record_demo_tape.py <seed> <out.json> [step_seconds]"""
import json
import sys
from datetime import date

from fastapi.testclient import TestClient

from stratagy.app import create_app
from stratagy.config import Settings
from stratagy.journal import Journal
from stratagy.providers.simulator import SimulatorProvider

SYMS = ("NIFTY", "BANKNIFTY")
TFS = ("1m", "3m", "5m", "15m")


def main() -> None:
    seed, out = int(sys.argv[1]), sys.argv[2]
    step = int(sys.argv[3]) if len(sys.argv) > 3 else 300
    prov = SimulatorProvider(seed=seed, sim_date=date(2026, 10, 23))
    app = create_app(Settings(provider="simulator"), provider=prov, journal=Journal("sqlite://", create_tables=True), autorun=False)
    with TestClient(app) as c:
        c.post("/api/simulator/control", json={"action": "pause"})
        risk = c.get("/api/state").json()["risk_settings"]
        risk["confirmed"] = True
        risk["trading_cutoff"] = risk["trading_cutoff"][:5]
        risk.pop("paper_square_off", None)
        r = c.post("/api/settings/risk", json=risk)
        assert r.status_code == 200, r.text
        frames = []
        for i in range(0, 12 * 3600 // step):
            c.post("/api/simulator/control", json={"action": "skip", "value": step})
            state = c.get("/api/state").json()
            f = {"state": state, "signals": c.get("/api/signals").json(), "trades": c.get("/api/trades").json(),
                 "report": c.get("/api/reports/session").json(), "eval": {}, "chain": {}, "chart": {}}
            for s in SYMS:
                f["eval"][s] = c.get(f"/api/underlyings/{s}/evaluation").json()
                f["chain"][s] = c.get(f"/api/underlyings/{s}/option-chain").json()
                for tf in TFS:
                    d = c.get(f"/api/underlyings/{s}/candles", params={"tf": tf, "limit": 400}).json()
                    f["chart"][f"{s}|{tf}"] = {k: d[k] for k in ("markers", "plans", "levels", "opening_range", "label", "ema_periods", "symbol", "timeframe")}
            f["virtual_now"] = state.get("sim", {}).get("virtual_now") or prov.now().isoformat()
            frames.append(f)
            if state["phase"] == "POST_CLOSE":
                break
        full = {f"{s}|{tf}": c.get(f"/api/underlyings/{s}/candles", params={"tf": tf, "limit": 400}).json() for s in SYMS for tf in TFS}
        premium = {s["id"]: c.get(f"/api/signals/{s['id']}/premium").json() for s in frames[-1]["signals"]}
        tape = {"seed": seed, "step_seconds": step, "frames": frames, "candles": full, "premium": premium,
                "provider": c.get("/api/provider").json(), "history": c.get("/api/reports/history").json()}
    json.dump(tape, open(out, "w"), separators=(",", ":"))
    last = frames[-1]
    print("frames", len(frames), "signals", len(last["signals"]), "trades", len(last["trades"]), "phase", last["state"]["phase"])


main()
