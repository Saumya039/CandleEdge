"""FastAPI application: read model + controls for the workstation. No order endpoints exist."""

from __future__ import annotations

import asyncio
import json
import logging
import time as _time
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import numpy as np
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from . import auth
from . import indicators as ind
from .backtest import run_backtest
from .candles import forming_bar, resample
from .config import RiskSettings, Settings
from .engine import Engine
from .journal import Journal
from .models import IST, DataStatus, Direction
from .providers import kite_auth
from .providers.base import MarketDataProvider, ProviderUnavailable
from .providers.registry import build_provider, capability_matrix
from .providers.simulator import SimulatorProvider
from .reports import summarize_trades
from .sessions import ExchangeCalendar, SessionPhase

log = logging.getLogger("stratagy.api")
DISCLAIMER = ("Decision-support and paper-trading research tool. Not investment advice. Signals are conditional "
              "scenarios, not predictions or promises of profit. No live orders are ever placed by this software.")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        d = {"ts": datetime.now(IST).isoformat(), "level": record.levelname, "logger": record.name,
             "msg": record.getMessage(), "request_id": getattr(record, "request_id", None)}
        if record.exc_info:
            d["exc"] = self.formatException(record.exc_info)
        return json.dumps(d)


def setup_logging(level: str) -> None:
    h = logging.StreamHandler()
    h.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [h]
    root.setLevel(level)


class RiskIn(BaseModel):
    confirmed: bool = False
    capital: float = Field(gt=0, le=1e10)
    max_risk_per_trade: float = Field(gt=0, le=1e9)
    max_daily_loss: float = Field(gt=0, le=1e9)
    max_open_positions: int = Field(ge=1, le=10)
    max_trades_per_session: int = Field(ge=1, le=100)
    max_premium_deployed: float = Field(gt=0, le=1e10)
    cooldown_after_losses: int = Field(ge=1, le=20)
    cooldown_minutes: int = Field(ge=0, le=600)
    min_reward_risk: float = Field(ge=0.5, le=10)
    trading_cutoff: str = "15:15"
    paper_enabled: bool = True


class StrategyIn(BaseModel):
    trigger_tf: Literal["3m", "5m", "15m"] = "5m"
    sensitivity: Literal["conservative", "standard", "aggressive"] = "standard"


class LoginIn(BaseModel):
    password: str = Field(min_length=1, max_length=256)


class PauseIn(BaseModel):
    paused: bool
    reason: str = Field(default="manual", max_length=200)


class DataIn(BaseModel):
    accept_delayed: bool


class SimControlIn(BaseModel):
    action: Literal["pause", "resume", "speed", "restart", "outage", "skip"]
    value: float | None = None


class BacktestIn(BaseModel):
    sessions: int = Field(default=6, ge=2, le=30)
    first_seed: int = 100
    start_date: date | None = None


def _hhmm(s: str):
    try:
        h, m = s.split(":")
        from datetime import time as _t

        return _t(int(h), int(m))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(422, "time must be HH:MM") from e


class RateLimiter:
    def __init__(self, per_minute: int = 120):
        self.per_minute = per_minute
        self.hits: dict[str, list[float]] = defaultdict(list)

    def ok(self, key: str) -> bool:
        now = _time.time()
        arr = [t for t in self.hits[key] if now - t < 60]
        self.hits[key] = arr
        if len(arr) >= self.per_minute:
            return False
        arr.append(now)
        return True


class AppState:
    def __init__(self, settings: Settings, provider: MarketDataProvider | None = None, journal: Journal | None = None,
                 autorun: bool = True):
        self.settings = settings
        self.provider = provider or build_provider(settings)
        self.journal = journal
        self.autorun = autorun
        self.engine: Engine | None = None
        self.task: asyncio.Task | None = None
        self.jobs: dict[str, dict[str, Any]] = {}
        self.sim_paused = False
        self.limiter = RateLimiter()
        self.loop_error: str | None = None
        self.kite_states: set[str] = set()
        self.kite_message: str | None = None


def create_app(settings: Settings | None = None, provider: MarketDataProvider | None = None,
               journal: Journal | None = None, autorun: bool = True) -> FastAPI:
    settings = settings or Settings()
    setup_logging(settings.log_level)
    auth_on = bool(settings.auth_password_hash)
    if auth_on and len(settings.auth_secret) < 32:
        raise RuntimeError("AUTH_SECRET must be set to a random string of at least 32 characters when AUTH_PASSWORD_HASH is set")
    if not auth_on and settings.provider != "simulator" and not settings.allow_insecure_no_auth:
        raise RuntimeError("A live data provider requires a login: set AUTH_PASSWORD_HASH and AUTH_SECRET "
                           "(see docs/DEPLOY.md), or set ALLOW_INSECURE_NO_AUTH=true for a strictly local machine")
    login_limiter = RateLimiter(per_minute=8)
    open_paths = {"/api/health", "/api/auth/login", "/api/auth/session", "/api/auth/logout", "/api/kite/callback"}
    st = AppState(settings, provider, journal, autorun)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if st.journal is None:
            st.journal = Journal(settings.database_url)
            from .migrate import upgrade

            try:
                upgrade(settings.database_url)
            except Exception:  # noqa: BLE001
                log.exception("alembic upgrade failed; falling back to create_all")
                from .journal import Base

                Base.metadata.create_all(st.journal.engine)
        cal = (ExchangeCalendar() if st.provider.name == "simulator"
               else ExchangeCalendar.from_file(settings.calendar_file))
        st.engine = Engine(st.provider, calendar=cal, journal=st.journal,
                           risk=RiskSettings(confirmed=True, defaults_in_use=True) if settings.use_default_risk else None)
        await st.engine.start()
        if autorun:
            st.task = asyncio.create_task(_runner(st))
        yield
        if st.task:
            st.task.cancel()
        await st.engine.stop()

    app = FastAPI(title="Stratagy NSE F&O options workstation", version="0.1.0", lifespan=lifespan)
    app.state.st = st
    app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
                       allow_methods=["GET", "POST"], allow_headers=["content-type", "x-request-id"])

    @app.middleware("http")
    async def mw(request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        if (auth_on and request.url.path.startswith("/api/") and request.url.path not in open_paths
                and not auth.valid_token(settings.auth_secret, request.cookies.get(auth.COOKIE))):
            return JSONResponse({"detail": "login required"}, status_code=401, headers={"x-request-id": rid})
        if request.method == "POST" and not st.limiter.ok(request.client.host if request.client else "?"):
            return JSONResponse({"detail": "rate limit exceeded"}, status_code=429, headers={"x-request-id": rid})
        try:
            resp = await call_next(request)
        except Exception:  # noqa: BLE001
            log.exception("unhandled error", extra={"request_id": rid})
            return JSONResponse({"detail": "internal error", "request_id": rid}, status_code=500,
                                headers={"x-request-id": rid})
        resp.headers["x-request-id"] = rid
        resp.headers["x-content-type-options"] = "nosniff"
        resp.headers["x-frame-options"] = "DENY"
        resp.headers["referrer-policy"] = "no-referrer"
        resp.headers["cache-control"] = "no-store"
        return resp

    @app.get("/api/auth/session")
    async def auth_session(request: Request):
        ok = (not auth_on) or auth.valid_token(settings.auth_secret, request.cookies.get(auth.COOKIE))
        return {"required": auth_on, "authenticated": bool(ok)}

    @app.post("/api/auth/login")
    async def auth_login(body: LoginIn, request: Request):
        if not auth_on:
            return {"required": False, "authenticated": True}
        # Global limit (the app usually sits behind a proxy, so the client address is not a reliable key).
        if not login_limiter.ok("login"):
            raise HTTPException(429, "too many login attempts; wait a minute")
        if not auth.verify_password(body.password, settings.auth_password_hash):
            if st.journal is not None:
                st.journal.audit(datetime.now(IST), "login_failed", {})
            raise HTTPException(401, "wrong password")
        resp = JSONResponse({"required": True, "authenticated": True})
        ttl = settings.auth_session_hours * 3600
        resp.set_cookie(auth.COOKIE, auth.make_token(settings.auth_secret, ttl), max_age=ttl, httponly=True,
                        samesite="strict", secure=settings.auth_cookie_secure, path="/")
        return resp

    @app.post("/api/auth/logout")
    async def auth_logout():
        resp = JSONResponse({"authenticated": False})
        resp.delete_cookie(auth.COOKIE, path="/")
        return resp

    # ---------------------------------------------------------------- setup guide and Kite login
    def token_file() -> Path:
        return Path(settings.kite_token_file)

    @app.get("/api/setup")
    async def setup_status():
        sim = st.provider.name == "simulator"
        health = st.provider.get_health()
        token_today = bool(settings.kite_access_token or kite_auth.load_token(token_file()))
        cal_ok = settings.calendar_file.exists()
        steps = [
            {"id": "mode", "label": "Live data mode", "done": not sim,
             "detail": "Practice mode (simulated data). Start with the live launcher to use Kite." if sim else "Kite live mode"},
            {"id": "key", "label": "Kite API key", "done": bool(settings.kite_api_key), "detail": "Set KITE_API_KEY (the launcher asks for it)"},
            {"id": "secret", "label": "Kite API secret (server only)", "done": bool(settings.kite_api_secret),
             "detail": "Set KITE_API_SECRET. It stays on this computer and is never shown in the browser."},
            {"id": "token", "label": "Logged in to Kite today", "done": token_today,
             "detail": "Click Connect Kite. Kite asks you to log in, then returns here."},
            {"id": "calendar", "label": "NSE holiday calendar", "done": cal_ok,
             "detail": "Optional but recommended: data/exchange_calendar.json. Without it only weekends are skipped."},
            {"id": "risk", "label": "Risk limits set", "done": bool(st.engine and st.engine.risk.confirmed),
             "detail": "Open Risk & settings and confirm your limits."},
            {"id": "feed", "label": "Live feed healthy", "done": (not sim) and health.status == DataStatus.LIVE,
             "detail": health.message},
        ]
        needed = [x for x in steps if not x["done"] and x["id"] != "calendar"]
        state = None
        if st.provider.name == "kite" and settings.kite_api_key and settings.kite_api_secret:
            state = uuid.uuid4().hex
            st.kite_states = {state}  # one outstanding login attempt at a time
        return {"steps": steps, "next": needed[0]["id"] if needed else None, "provider": st.provider.name,
                "connect_url": kite_auth.login_url(settings.kite_api_key, state) if state else None,
                "kite_message": st.kite_message, "redirect_url_to_register": f"{settings.public_backend_url}/api/kite/callback"}

    @app.get("/api/kite/callback")
    async def kite_callback(request_token: str = "", status: str = "", state: str = ""):
        back = settings.app_url.rstrip("/") + "/"
        if state not in st.kite_states:
            st.kite_message = "Login link expired or not started here. Click Connect Kite again."
            return RedirectResponse(back, status_code=303)
        st.kite_states.discard(state)
        if status != "success" or not request_token:
            st.kite_message = "Kite login was not completed."
            return RedirectResponse(back, status_code=303)
        try:
            token = await kite_auth.exchange_request_token(settings.kite_api_key, settings.kite_api_secret, request_token)
        except ValueError as ex:
            st.kite_message = str(ex)
            return RedirectResponse(back, status_code=303)
        kite_auth.save_token(token_file(), token)
        settings.kite_access_token = token
        old = st.engine
        if old:
            await old.stop()
        st.provider = build_provider(settings)
        cal = ExchangeCalendar.from_file(settings.calendar_file)
        st.engine = Engine(st.provider, calendar=cal, journal=st.journal, risk=old.risk if old else RiskSettings())
        await st.engine.start()
        st.kite_message = "Connected to Kite for today." if st.engine.started else f"Kite login worked but the feed did not start: {st.engine.start_error}"
        if st.journal is not None:
            st.journal.audit(datetime.now(IST), "kite_login", {"started": st.engine.started})
        return RedirectResponse(back, status_code=303)

    def eng() -> Engine:
        if st.engine is None:
            raise HTTPException(503, "engine not started")
        return st.engine

    # ---------------------------------------------------------------- meta
    @app.get("/api/health")
    async def health():
        return {"status": "ok", "live_orders_enabled": False, "order_api_present": False,
                "provider": st.provider.name, "loop_error": st.loop_error}

    @app.get("/api/provider")
    async def provider_status():
        h = st.provider.get_health()
        return {"active": h.model_dump(mode="json"), "start_error": eng().start_error,
                "capability_matrix": capability_matrix(), "setup": SETUP_HELP}

    # ---------------------------------------------------------------- state
    @app.get("/api/state")
    async def state():
        return build_state(eng(), st)

    @app.get("/api/underlyings/{sym}/candles")
    async def candles(sym: str, tf: Literal["1m", "3m", "5m", "15m"] = "5m", limit: int = 300):
        e = eng()
        if sym not in e.u:
            raise HTTPException(404, "unknown underlying")
        return build_chart(e, sym, tf, min(limit, 1000))

    @app.get("/api/underlyings/{sym}/evaluation")
    async def evaluation(sym: str):
        e = eng()
        if sym not in e.u:
            raise HTTPException(404, "unknown underlying")
        ev = e.u[sym].latest_eval
        return ev.model_dump(mode="json") if ev else None

    @app.get("/api/underlyings/{sym}/option-chain")
    async def option_chain(sym: str):
        e = eng()
        if sym not in e.u:
            raise HTTPException(404, "unknown underlying")
        try:
            snap = await e._chain(sym, e.provider.now())
        except ProviderUnavailable as ex:
            raise HTTPException(503, str(ex)) from ex
        except Exception as ex:  # noqa: BLE001
            return {"available": False, "reason": f"{type(ex).__name__}: {ex}"}
        sig = e.active_signal(sym)
        sel = sig.plan.contract.id if sig else None
        ev = e.u[sym].latest_eval
        picked = ev.contract_choice.quote.instrument.id if ev and ev.contract_choice and ev.contract_choice.quote else None
        rows = []
        for r in snap.rows:
            def q(x):
                if x is None:
                    return None
                return {"id": x.instrument.id, "symbol": x.instrument.symbol, "ltp": x.ltp, "bid": x.bid, "ask": x.ask,
                        "spread_pct": x.spread_pct, "volume": x.volume, "oi": x.oi, "oi_change": x.oi_change,
                        "iv": x.greeks.iv if x.greeks else None, "delta": x.greeks.delta if x.greeks else None,
                        "greeks_source": x.greeks.source if x.greeks else None, "lot_size": x.instrument.lot_size,
                        "tick_size": x.instrument.tick_size, "tradable": x.instrument.tradable,
                        "age_s": (e.provider.now() - x.received_ts).total_seconds(), "status": x.status.value,
                        "selected": x.instrument.id == sel, "preferred": x.instrument.id == picked}
            rows.append({"strike": r.strike, "ce": q(r.ce), "pe": q(r.pe)})
        ce_oi = sum((r.ce.oi or 0) for r in snap.rows if r.ce)
        pe_oi = sum((r.pe.oi or 0) for r in snap.rows if r.pe)
        return {"available": True, "underlying": sym, "expiry": str(snap.expiry), "expiries": [str(x) for x in snap.expiries],
                "forward": snap.forward, "status": snap.status.value, "source": snap.source, "ts": snap.ts.isoformat(),
                "rows": rows, "pcr_in_window": round(pe_oi / ce_oi, 3) if ce_oi else None,
                "context_note": "PCR/OI are contextual only and never a standalone signal. Greeks/IV marked 'estimated' are "
                                "Black-76 estimates, not provider values.",
                "criteria": e.cp.model_dump()}

    @app.get("/api/signals")
    async def signals(underlying: str | None = None, state: str | None = None, direction: str | None = None,
                      min_rr: float | None = None):
        out = []
        for s in sorted(eng().signals.values(), key=lambda s: s.created_ts, reverse=True):
            if underlying and s.underlying != underlying:
                continue
            if state and s.state.value != state:
                continue
            if direction and s.direction.value != direction:
                continue
            if min_rr is not None and s.plan.rr_t1 < min_rr:
                continue
            out.append(s.model_dump(mode="json"))
        return out

    @app.get("/api/signals/{sid}/premium")
    async def premium(sid: str):
        e = eng()
        s = e.signals.get(sid)
        if not s:
            raise HTTPException(404, "unknown signal")
        ser = e.u[s.underlying].premium_series.get(s.plan.contract.id, [])
        return {"contract": s.plan.contract.symbol, "series": ser,
                "note": "Built from option-chain snapshots polled by the engine; not exchange candles."}

    @app.get("/api/trades")
    async def trades():
        return [t.model_dump(mode="json") for t in sorted(eng().trades.values(), key=lambda t: t.entry_ts, reverse=True)]

    # ---------------------------------------------------------------- journal / reports
    @app.get("/api/journal/signals")
    async def j_signals(date_: str | None = None):
        return st.journal.signals(date_) if st.journal else []

    @app.get("/api/journal/trades")
    async def j_trades(date_: str | None = None, origin: str | None = "PAPER"):
        return st.journal.trades(date_, origin) if st.journal else []

    @app.get("/api/reports/session")
    async def r_session():
        from .reports import session_report

        e = eng()
        return e.session_report or session_report(e, e.provider.now().date())

    @app.get("/api/reports/history")
    async def r_history():
        if not st.journal:
            return {}
        paper = st.journal.trades(None, "PAPER", limit=5000)
        by_day: dict[str, list[dict]] = defaultdict(list)
        for t in paper:
            by_day[t["entry_ts"][:10]].append(t)
        return {"origin": "PAPER", "overall": summarize_trades(paper),
                "days": {d: summarize_trades(v) for d, v in sorted(by_day.items())},
                "health_events": st.journal.health_events(None, 100)}

    @app.get("/api/audit")
    async def audit():
        return st.journal.audit_events(200) if st.journal else []

    # ---------------------------------------------------------------- settings / control
    @app.post("/api/settings/risk")
    async def set_risk(body: RiskIn):
        e = eng()
        data = body.model_dump()
        data["trading_cutoff"] = _hhmm(body.trading_cutoff)
        data["defaults_in_use"] = False  # the user has now set these values themselves
        new = e.risk.model_copy(update=data)
        e.set_risk(new, e.provider.now())
        return new.model_dump(mode="json")

    @app.post("/api/settings/strategy")
    async def set_strategy(body: StrategyIn):
        e = eng()
        e.set_strategy(body.trigger_tf, body.sensitivity, e.provider.now())
        return {"version": e.p.version, "trigger_tf": e.p.trigger_tf, "htf": e.p.htf, "sensitivity": e.sensitivity}

    @app.post("/api/settings/data")
    async def set_data(body: DataIn):
        e = eng()
        e.set_accept_delayed(body.accept_delayed, e.provider.now())
        return {"accept_delayed": e.dh.accept_delayed}

    @app.post("/api/control/pause")
    async def pause(body: PauseIn):
        e = eng()
        e.set_pause(body.paused, body.reason, e.provider.now())
        return {"paused": e.risk_state.paused}

    @app.post("/api/simulator/control")
    async def sim_control(body: SimControlIn):
        prov = st.provider
        if not isinstance(prov, SimulatorProvider):
            raise HTTPException(409, "simulator controls are only available in simulator mode")
        if body.action == "pause":
            st.sim_paused = True
        elif body.action == "resume":
            st.sim_paused = False
        elif body.action == "speed":
            st.settings.sim_speed = float(min(max(body.value or 60.0, 1.0), 1200.0))
        elif body.action == "outage":
            prov.inject_outage(float(min(max(body.value or 60.0, 5.0), 1800.0)))
        elif body.action == "skip":
            secs = float(min(max(body.value or 600.0, 10.0), 14400.0))
            e = eng()
            for _ in range(int(secs // 10)):
                prov.advance(10.0)
                await e.process()
        elif body.action == "restart":
            old = st.engine
            if old:
                await old.stop()
            prov.restart(int(body.value) if body.value is not None else None)
            cal = ExchangeCalendar()
            keep_risk = old.risk if old else RiskSettings()
            st.engine = Engine(prov, calendar=cal, journal=st.journal, risk=keep_risk)
            await st.engine.start()
        return sim_state(st)

    @app.post("/api/backtest/run")
    async def backtest(body: BacktestIn):
        jid = uuid.uuid4().hex[:8]
        st.jobs[jid] = {"status": "running", "started": datetime.now(IST).isoformat()}
        e = eng()
        start = body.start_date or date(2026, 1, 5)

        async def job():
            try:
                res = await run_backtest(list(range(body.first_seed, body.first_seed + body.sessions)), start,
                                         risk=e.risk, params=e.p, cost=e.cost, journal=None)
                st.jobs[jid] = {"status": "done", "result": res}
            except Exception as ex:  # noqa: BLE001
                log.exception("backtest failed")
                st.jobs[jid] = {"status": "error", "error": f"{type(ex).__name__}: {ex}"}

        asyncio.create_task(job())
        return {"job": jid}

    @app.get("/api/backtest/jobs/{jid}")
    async def job(jid: str):
        if jid not in st.jobs:
            raise HTTPException(404, "unknown job")
        return st.jobs[jid]

    return app


# ----------------------------------------------------------------------------------------------------
SETUP_HELP = {
    "kite": {
        "name": "Zerodha Kite Connect (REST quote polling)",
        "env": ["PROVIDER=kite", "KITE_API_KEY", "KITE_ACCESS_TOKEN"],
        "needs": [
            "A Kite Connect app with market-data (quotes + historical) entitlement on your subscription",
            "A fresh access token each trading day, generated with scripts/kite_login.py after you log in to Kite yourself",
            "Server-side environment variables only; never paste secrets in the browser or chat",
            "Compliance review (SEBI/NSE/broker retail-API rules, data licensing) before any use beyond viewing",
        ],
        "order_permissions": "Not requested. This project has no order code.",
    }
}


def sim_state(st: AppState) -> dict[str, Any]:
    prov = st.provider
    if prov.name != "simulator":
        return {}
    return {"paused": st.sim_paused, "speed": st.settings.sim_speed, "seed": prov.seed,  # type: ignore[attr-defined]
            "virtual_now": prov.now().isoformat(), "sim_date": str(prov.sim_date)}  # type: ignore[attr-defined]


def badge(e: Engine, now: datetime, phase: SessionPhase, stale: bool) -> str:
    sim = e.provider.name in ("simulator", "replay")
    if stale:
        return "STALE DATA"
    if sim:
        return "SIMULATION"
    if phase == SessionPhase.PRE_MARKET:
        return "PRE-MARKET"
    if phase in (SessionPhase.CLOSED, SessionPhase.POST_CLOSE):
        return "MARKET CLOSED"
    if phase == SessionPhase.OPENING_RANGE:
        return "OPEN"
    return "LIVE"


def build_state(e: Engine, st: AppState) -> dict[str, Any]:
    now = e.provider.now()
    phase = e.phase(now)
    stale = e.is_stale(now)
    h = e.provider.get_health()
    mkt_session = e.cal.session_for(now.date())
    next_ev = None
    if phase == SessionPhase.PRE_MARKET and mkt_session.open:
        next_ev = {"label": "Market opens", "ts": mkt_session.open.isoformat(), "seconds": (mkt_session.open - now).total_seconds()}
    elif phase in (SessionPhase.OPENING_RANGE, SessionPhase.TRADING) and mkt_session.close:
        next_ev = {"label": "Entry cutoff", "ts": e._cutoff_dt(now).isoformat(),
                   "seconds": (e._cutoff_dt(now) - now).total_seconds()}
    wl = []
    for sym, u in list(e.u.items()):
        closed = u.builder.closed_list()
        ev = u.latest_eval
        last = u.last_ltp
        # Resampling six days of 1m candles for 200+ names on every poll was ~1 s of CPU: recompute only when a candle closes.
        key = (len(closed), closed[-1].ts if closed else None, e.p.trigger_tf)
        if u.bars_cache is not None and u.bars_cache[0] == key:
            bars, vw = u.bars_cache[1], u.bars_cache[2]
        else:
            bars = resample(closed, e.p.trigger_tf)
            vw = None
            if bars:
                v = ind.session_vwap(bars)
                vw = None if np.isnan(v[-1]) else float(v[-1])
            u.bars_cache = (key, bars, vw)
        day_c = [c for c in closed if c.ts.date() == now.date()]
        day_open = day_c[0].open if day_c else None
        sig = e.active_signal(sym)
        vol_ratio = None
        if len(bars) > e.p.volume_lookback + 1:
            vv = np.array([b.volume for b in bars])
            avg = vv[-1 - e.p.volume_lookback:-1].mean()
            vol_ratio = float(vv[-1] / avg) if avg > 0 else None
        wl.append({
            "symbol": sym, "ltp": last, "prev_close": u.prev_close,
            "change_pct": (100 * (last - u.prev_close) / u.prev_close) if last and u.prev_close else None,
            "day_open": day_open, "vwap": vw,
            "vwap_relation": None if vw is None or last is None else ("ABOVE" if last > vw else "BELOW"),
            "regime": ev.regime.regime.value if ev else "INSUFFICIENT_DATA",
            "volatility": "HIGH" if ev and ev.regime.regime.value == "HIGH_VOLATILITY" else
            ("NORMAL" if ev and ev.regime.atr_pct is not None else "UNKNOWN"),
            "atr_pct": ev.regime.atr_pct if ev else None, "volume_ratio": vol_ratio,
            "last_tick_ts": u.last_tick_ts.isoformat() if u.last_tick_ts else None,
            "tick_age_s": (now - u.last_tick_ts).total_seconds() if u.last_tick_ts else None,
            "decision": ev.decision if ev else "NO_TRADE",
            "no_trade_reasons": ev.reasons if ev and ev.decision != "CANDIDATE" else [],
            "signal_state": sig.state.value if sig else ("NO_TRADE" if not ev or ev.decision != "CANDIDATE" else "CANDIDATE"),
            "signal_id": sig.id if sig else None,
            "dropped_out_of_order": u.builder.dropped_out_of_order, "dropped_duplicates": u.builder.dropped_duplicates,
        })
    risk = e.risk.model_dump(mode="json")
    return {
        "now": now.isoformat(), "tz": "Asia/Kolkata", "badge": badge(e, now, phase, stale), "phase": phase.value,
        "stale": stale, "next_event": next_ev,
        "data": {"provider": h.name, "status": h.status.value, "connected": h.connected, "authenticated": h.authenticated,
                 "transport": h.transport, "message": h.message, "last_tick_ts": h.last_tick_ts.isoformat() if h.last_tick_ts else None,
                 "latency_ms": h.latency_ms, "missing_credentials": h.missing_credentials,
                 "is_simulated": h.status == DataStatus.SIMULATED, "accept_delayed": e.dh.accept_delayed,
                 "start_error": e.start_error},
        "calendar": {"verified": mkt_session.calendar_verified, "note": mkt_session.note,
                     "open": mkt_session.open.isoformat() if mkt_session.open else None,
                     "close": mkt_session.close.isoformat() if mkt_session.close else None},
        "history_loading": e.history_loading, "risk_settings": risk, "risk_state": e.risk_state.model_dump(mode="json"),
        "strategy": {"version": e.p.version, "trigger_tf": e.p.trigger_tf, "htf": e.p.htf, "sensitivity": e.sensitivity},
        "watchlist": wl,
        "active_signals": [s.model_dump(mode="json") for s in e.signals.values() if not s.closed],
        "signal_count": len(e.signals),
        "open_trades": [t.model_dump(mode="json") for t in e.open_trades()],
        "alerts": [a.model_dump(mode="json") for a in list(e.alerts)[:40]],
        "health_log": list(e.health_log)[:30],
        "simulator": sim_state(st), "live_orders_enabled": False, "disclaimer": DISCLAIMER,
    }


def build_chart(e: Engine, sym: str, tf: str, limit: int) -> dict[str, Any]:
    u = e.u[sym]
    all1 = u.builder.closed_list()
    bars = resample(all1, tf) if tf != "1m" else all1  # type: ignore[arg-type]
    cl = np.array([b.close for b in bars]) if bars else np.array([])
    p = e.p
    e9, e21, e50 = ind.ema(cl, p.ema_fast), ind.ema(cl, p.ema_mid), ind.ema(cl, p.ema_slow)
    vw = ind.session_vwap(bars) if bars else np.array([])
    if bars:  # VWAP resets daily: draw only the latest session so the line never jumps across days
        last_day = bars[-1].ts.date()
        vw = np.array([v if b.ts.date() == last_day else np.nan for v, b in zip(vw, bars)])
    keep = bars[-limit:]
    off = len(bars) - len(keep)

    def series(arr):
        return [{"t": int(b.ts.timestamp()), "v": (None if np.isnan(arr[off + i]) else round(float(arr[off + i]), 2))}
                for i, b in enumerate(keep)]

    today = keep[-1].ts.date() if keep else None
    day1 = [c for c in all1 if today and c.ts.date() == today]
    sess_open = datetime.combine(today, p_open(), IST) if today else None
    orh, orl, orc = ind.opening_range(day1, sess_open, p.or_minutes) if sess_open and day1 else (float("nan"),) * 2 + (False,)
    prior_days = [c for c in all1 if today and c.ts.date() < today]
    levels: list[dict[str, Any]] = []
    if prior_days:
        pd_ = max(c.ts.date() for c in prior_days)
        pdc = [c for c in prior_days if c.ts.date() == pd_]
        levels += [{"name": "Prev day high", "price": max(c.high for c in pdc)},
                   {"name": "Prev day low", "price": min(c.low for c in pdc)},
                   {"name": "Prev close", "price": pdc[-1].close}]
    if day1:
        levels += [{"name": "Day high", "price": max(c.high for c in day1)}, {"name": "Day low", "price": min(c.low for c in day1)}]
    if len(bars) >= 10:
        from .strategy import _recent_swing_levels

        hi, lo = _recent_swing_levels(bars, p)
        last = bars[-1].close
        res = [x for x in hi if x > last]
        sup = [x for x in lo if x < last]
        if res:
            levels.append({"name": "Resistance (swing)", "price": min(res)})
        if sup:
            levels.append({"name": "Support (swing)", "price": max(sup)})
    sigs = [s for s in e.signals.values() if s.underlying == sym]
    markers = []
    plans = []
    for s in sigs:
        for tr in s.transitions:
            markers.append({"t": int(tr.ts.timestamp()), "state": tr.to_state.value, "direction": s.direction.value,
                            "signal_id": s.id, "price": tr.underlying_price})
        pl = s.plan
        plans.append({"signal_id": s.id, "state": s.state.value, "direction": s.direction.value, "active": not s.closed,
                      "entry_lo": pl.entry_zone_underlying[0], "entry_hi": pl.entry_zone_underlying[1],
                      "invalidation": pl.invalidation_underlying, "t1": pl.target1_underlying, "t2": pl.target2_underlying,
                      "created_t": int(s.created_ts.timestamp())})
    forming = e.forming_candle(sym)
    fbar = forming_bar(all1, forming, tf)  # type: ignore[arg-type]
    if fbar is not None and keep and fbar.ts <= keep[-1].ts:
        fbar = None
    return {
        "symbol": sym, "timeframe": tf, "label": "SIMULATED" if e.provider.name in ("simulator", "replay") else e.provider.get_health().status.value,
        "candles": [{"t": int(b.ts.timestamp()), "o": b.open, "h": b.high, "l": b.low, "c": b.close, "v": b.volume,
                     "q": b.quality} for b in keep],
        "ema9": series(e9), "ema21": series(e21), "ema50": series(e50), "vwap": series(vw),
        "opening_range": {"high": None if np.isnan(orh) else orh, "low": None if np.isnan(orl) else orl, "complete": orc},
        "levels": levels, "markers": markers, "plans": plans,
        "forming_1m": None if not forming else {"t": int(forming.ts.timestamp()), "o": forming.open, "h": forming.high,
                                              "l": forming.low, "c": forming.close},
        "forming": None if fbar is None else {"t": int(fbar.ts.timestamp()), "o": fbar.open, "h": fbar.high,
                                              "l": fbar.low, "c": fbar.close, "v": fbar.volume},
        "ema_periods": [p.ema_fast, p.ema_mid, p.ema_slow],
    }


def p_open():
    from datetime import time

    return time(9, 15)


async def _runner(st: AppState) -> None:
    """Drives the engine. Simulator: advances the virtual clock. Live provider: provider pushes its own ticks."""
    dt = 0.5
    while True:
        try:
            e = st.engine
            if e is not None and e.started:
                if st.provider.name == "simulator" and not st.sim_paused:
                    st.provider.advance(st.settings.sim_speed * dt)  # type: ignore[attr-defined]
                await e.process()
            st.loop_error = None
        except asyncio.CancelledError:
            raise
        except Exception as ex:  # noqa: BLE001
            st.loop_error = f"{type(ex).__name__}: {ex}"
            log.exception("engine loop error")
        await asyncio.sleep(dt)


_ = (timedelta, Direction)
