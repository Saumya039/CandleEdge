"""Zerodha Kite Connect market-data adapter (READ-ONLY: quotes, instruments, historical candles).

STATUS: implemented against the public Kite Connect v3 REST contract as documented at the time of writing
(`/instruments`, `/quote`, `/instruments/historical/...`, `/user/profile`). It could NOT be exercised against
the real service from the build sandbox (no credentials, and kite.trade was not reachable), so the HTTP layer
is covered by contract-style unit tests using recorded-shape fixtures only. Before relying on it:
  1. verify endpoints/limits/entitlements against the CURRENT official docs and your subscription,
  2. confirm your plan includes market-data (quote + historical) access,
  3. review current SEBI / NSE / broker retail-API and data-licensing requirements.

Design notes
* No order endpoints are called or implemented. Only a data-scoped token is needed.
* Ticks come from polling `/quote` (rate limit ~1 req/s). Intra-poll highs/lows are therefore missed; the engine
  reconciles each closed 1m candle against the provider's historical 1m candles (`reconcile`).
* The signal instrument for an index underlying is its nearest-month FUTURE (indices carry no volume), and
  the option chain is priced against that future as the forward (Black-76) for ESTIMATED IV/Greeks.
* LIVE is only reported when authenticated and the newest exchange timestamp is fresh; otherwise STALE."""

from __future__ import annotations

import asyncio
import csv
import io
import logging
import random
import time as _time
from datetime import date, datetime, timedelta
from typing import Any, cast

import httpx

from .. import pricing
from ..models import (
    IST,
    TF_MINUTES,
    Candle,
    DataStatus,
    Instrument,
    InstrumentKind,
    MarketSession,
    OptionChainRow,
    OptionChainSnapshot,
    OptionQuote,
    OptionType,
    ProviderHealth,
    Tick,
    Timeframe,
)
from ..sessions import ExchangeCalendar
from .base import (
    Capabilities,
    MarketDataProvider,
    ProviderError,
    ProviderUnavailable,
    SubscriptionHandle,
    TickCallback,
    UnderlyingSpec,
    _Handle,
)

log = logging.getLogger("stratagy.kite")
BASE = "https://api.kite.trade"
INTERVAL = {"1m": "minute", "3m": "3minute", "5m": "5minute", "15m": "15minute"}


def _parse_ts(s: str | None) -> datetime | None:
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S"):
        try:
            d = datetime.strptime(s, fmt)
            return d.replace(tzinfo=IST) if d.tzinfo is None else d.astimezone(IST)
        except ValueError:
            continue
    return None


class KiteProvider(MarketDataProvider):
    name = "kite"
    capabilities = Capabilities(
        live_ticks=True, historical_ohlc=True, option_chain=True, instrument_master=True, open_interest=True,
        provider_greeks=False, index_volume=False, requires_auth=True,
        rate_limit_note="Quote ~1 req/s (<=500 instruments); historical ~3 req/s. Verify against current docs.",
    )

    def __init__(self, api_key: str, access_token: str, watchlist: list[str], calendar: ExchangeCalendar | None = None,
                 transport: httpx.AsyncBaseTransport | None = None, poll_interval_s: float = 1.2):
        self.api_key, self._token = api_key, access_token
        self.watchlist = watchlist
        self.calendar = calendar or ExchangeCalendar()
        self._transport = transport
        self.poll_interval_s = poll_interval_s
        self._client: httpx.AsyncClient | None = None
        self._connected = False
        self._authenticated = False
        self._instruments: list[dict] = []
        self._by_symbol: dict[str, Instrument] = {}
        self._tokens: dict[str, int] = {}  # internal instrument id -> kite token
        self._specs: list[UnderlyingSpec] = []
        self._callbacks: dict[int, tuple[set[str], TickCallback]] = {}
        self._cb_n = 0
        self._poll_task: asyncio.Task | None = None
        self._last_quote_call = 0.0
        self._last_hist_call = 0.0
        self._lock = asyncio.Lock()
        self._last_tick_ts: datetime | None = None
        self._last_recv: datetime | None = None
        self._latency_ms: float | None = None
        self._message = "Not connected"
        self._failures = 0
        self._sub_ids: set[str] = set()

    # ---- plumbing ---------------------------------------------------------------------------------
    def missing_credentials(self) -> list[str]:
        return [n for n, v in (("KITE_API_KEY", self.api_key), ("KITE_ACCESS_TOKEN", self._token)) if not v]

    def now(self) -> datetime:
        return datetime.now(IST)

    async def _get(self, path: str, params: list[tuple[str, str]] | None = None, kind: str = "quote") -> httpx.Response:
        assert self._client is not None
        async with self._lock:  # crude client-side rate limiter
            gap = {"quote": 1.05, "hist": 0.4, "other": 0.2}[kind]
            last = self._last_quote_call if kind == "quote" else self._last_hist_call
            wait = gap - (_time.monotonic() - last)
            if wait > 0:
                await asyncio.sleep(wait)
            t0 = _time.monotonic()
            r = await self._client.get(path, params=cast(Any, params))
            if kind == "quote":
                self._last_quote_call = _time.monotonic()
            else:
                self._last_hist_call = _time.monotonic()
            self._latency_ms = (_time.monotonic() - t0) * 1000
        if r.status_code == 403 or r.status_code == 401:
            self._authenticated = False
            raise ProviderUnavailable(
                f"Kite rejected the credentials/entitlement (HTTP {r.status_code}). The access token expires daily and "
                "market-data access needs an entitled subscription.", [])
        if r.status_code == 429:
            raise ProviderError("Kite rate limit hit (HTTP 429)")
        if r.status_code >= 400:
            raise ProviderError(f"Kite HTTP {r.status_code}")
        return r

    # ---- MarketDataProvider -----------------------------------------------------------------------
    async def connect(self) -> None:
        miss = self.missing_credentials()
        if miss:
            self._message = "Missing credentials: " + ", ".join(miss)
            raise ProviderUnavailable(self._message, miss)
        self._client = httpx.AsyncClient(
            base_url=BASE, timeout=10.0, transport=self._transport,
            headers={"X-Kite-Version": "3", "Authorization": f"token {self.api_key}:{self._token}"})
        await self._get("/user/profile", kind="other")
        self._authenticated = True
        r = await self._get("/instruments", kind="other")
        self._instruments = list(csv.DictReader(io.StringIO(r.text)))
        self._build_specs()
        self._connected = True
        self._message = "Connected (REST polling)"
        self._poll_task = asyncio.create_task(self._poll_loop())

    async def disconnect(self) -> None:
        if self._poll_task:
            self._poll_task.cancel()
        if self._client:
            await self._client.aclose()
        self._connected = False

    def _inst(self, row: dict, kind: InstrumentKind) -> Instrument:
        exp = row.get("expiry") or None
        itype = row.get("instrument_type", "")
        return Instrument(
            id=f"{row['exchange']}:{row['tradingsymbol']}", exchange=row["exchange"], symbol=row["tradingsymbol"],
            underlying=row.get("name", ""), kind=kind, expiry=date.fromisoformat(exp) if exp else None,
            strike=float(row["strike"]) if row.get("strike") not in (None, "", "0", "0.0") else None,
            option_type=OptionType(itype) if itype in ("CE", "PE") else None,
            lot_size=int(row.get("lot_size") or 1), tick_size=float(row.get("tick_size") or 0.05), tradable=True)

    def _build_specs(self) -> None:
        today = datetime.now(IST).date()
        self._specs = []
        for sym in self.watchlist:
            futs = [r for r in self._instruments if r.get("segment") == "NFO-FUT" and r.get("name") == sym
                    and r.get("expiry") and date.fromisoformat(r["expiry"]) >= today]
            if not futs:
                log.warning("no futures found for %s in instrument master", sym)
                continue
            futs.sort(key=lambda r: r["expiry"])
            inst = self._inst(futs[0], InstrumentKind.FUTURE)
            self._tokens[inst.id] = int(futs[0]["instrument_token"])
            self._by_symbol[sym] = inst
            self._specs.append(UnderlyingSpec(symbol=sym, signal_instrument=inst, name=f"{sym} ({inst.symbol})"))

    def underlyings(self) -> list[UnderlyingSpec]:
        return self._specs

    async def get_instruments(self) -> list[Instrument]:
        return [s.signal_instrument for s in self._specs]

    async def get_historical_candles(self, instrument_id: str, timeframe: Timeframe, start: datetime,
                                     end: datetime) -> list[Candle]:
        tok = self._tokens.get(instrument_id)
        if tok is None:
            return []
        out: list[Candle] = []
        cur = start
        while cur < end:  # minute data is limited per request: chunk by 30 days
            nxt = min(cur + timedelta(days=30), end)
            r = await self._get(f"/instruments/historical/{tok}/{INTERVAL[timeframe]}", [
                ("from", cur.astimezone(IST).strftime("%Y-%m-%d %H:%M:%S")),
                ("to", nxt.astimezone(IST).strftime("%Y-%m-%d %H:%M:%S"))], kind="hist")
            for row in r.json().get("data", {}).get("candles", []):
                ts = _parse_ts(row[0])
                if ts is None:
                    continue
                out.append(Candle(instrument_id=instrument_id, timeframe=timeframe, ts=ts, open=row[1], high=row[2],
                                  low=row[3], close=row[4], volume=float(row[5]), source="KITE_HIST"))
            cur = nxt
        end_i = end.astimezone(IST)
        # only candles that have fully closed
        span = timedelta(minutes=TF_MINUTES[timeframe])
        return [c for c in out if c.ts + span <= end_i]

    async def reconcile(self, instrument_id: str, now: datetime) -> list[Candle]:
        """Provider-authoritative closed 1m candles for the last few minutes (replaces tick-built approximations)."""
        try:
            return await self.get_historical_candles(instrument_id, "1m", now - timedelta(minutes=6), now)
        except ProviderError as e:
            self._message = f"reconcile failed: {e}"
            return []

    async def subscribe_ticks(self, instrument_ids: list[str], on_tick: TickCallback) -> SubscriptionHandle:
        self._cb_n += 1
        cid = self._cb_n
        self._callbacks[cid] = (set(instrument_ids), on_tick)
        self._sub_ids |= set(instrument_ids)

        def cancel() -> None:
            self._callbacks.pop(cid, None)

        return _Handle(cancel)

    async def _poll_loop(self) -> None:
        delay = self.poll_interval_s
        while True:
            try:
                ids = sorted(self._sub_ids)
                if ids:
                    r = await self._get("/quote", [("i", i) for i in ids])
                    recv = self.now()
                    data = r.json().get("data", {})
                    for iid, q in data.items():
                        ts = _parse_ts(q.get("last_trade_time")) or _parse_ts(q.get("timestamp"))
                        tick = Tick(instrument_id=iid, ltp=float(q["last_price"]), volume=q.get("volume"),
                                    oi=q.get("oi"), exchange_ts=ts, received_ts=recv)
                        self._last_tick_ts, self._last_recv = ts or self._last_tick_ts, recv
                        for want, cb in list(self._callbacks.values()):
                            if iid in want:
                                cb(tick)
                    self._failures = 0
                    self._message = "Connected (REST polling)"
                delay = self.poll_interval_s
            except asyncio.CancelledError:
                raise
            except ProviderUnavailable as e:
                self._message = str(e)
                self._failures += 1
                delay = min(60.0, 2.0 ** min(self._failures, 6)) + random.uniform(0, 1)  # backoff + jitter
            except Exception as e:  # noqa: BLE001
                self._failures += 1
                self._message = f"poll error: {type(e).__name__}: {e}"
                delay = min(30.0, 1.5 ** min(self._failures, 8)) + random.uniform(0, 1)
            await asyncio.sleep(delay)

    async def get_option_chain(self, underlying: str, expiry: date | None = None) -> OptionChainSnapshot:
        fut = self._by_symbol.get(underlying)
        if fut is None:
            raise ProviderError(f"Unknown underlying {underlying}")
        today = datetime.now(IST).date()
        opts = [r for r in self._instruments if r.get("segment") == "NFO-OPT" and r.get("name") == underlying
                and r.get("expiry") and date.fromisoformat(r["expiry"]) >= today]
        expiries = sorted({date.fromisoformat(r["expiry"]) for r in opts})
        if not expiries:
            raise ProviderError("No option contracts in instrument master")
        exp = expiry or expiries[0]
        rows_src = [r for r in opts if r["expiry"] == exp.isoformat()]
        fq = await self._get("/quote", [("i", fut.id)])
        fdata = fq.json()["data"][fut.id]
        fwd = float(fdata["last_price"])
        strikes = sorted({float(r["strike"]) for r in rows_src})
        if not strikes:
            raise ProviderError("No strikes for expiry")
        atm_i = min(range(len(strikes)), key=lambda i: abs(strikes[i] - fwd))
        win = set(strikes[max(atm_i - 12, 0): atm_i + 13])
        sel = [r for r in rows_src if float(r["strike"]) in win]
        keys = [f"{r['exchange']}:{r['tradingsymbol']}" for r in sel]
        quotes: dict[str, dict] = {}
        for i in range(0, len(keys), 100):
            rr = await self._get("/quote", [("i", k) for k in keys[i:i + 100]])
            quotes.update(rr.json().get("data", {}))
        recv = self.now()
        t_exp = pricing.year_fraction(recv, datetime.combine(exp, datetime.min.time(), IST).replace(hour=15, minute=30))
        by_strike: dict[float, OptionChainRow] = {}
        newest = None
        for r in sel:
            key = f"{r['exchange']}:{r['tradingsymbol']}"
            q = quotes.get(key)
            if not q:
                continue
            inst = self._inst(r, InstrumentKind.OPTION)
            depth = q.get("depth") or {}
            bid = (depth.get("buy") or [{}])[0].get("price") or None
            ask = (depth.get("sell") or [{}])[0].get("price") or None
            ts = _parse_ts(q.get("last_trade_time")) or _parse_ts(q.get("timestamp")) or recv
            newest = max(newest, ts) if newest else ts
            ltp = float(q["last_price"]) if q.get("last_price") else None
            ref = (bid + ask) / 2 if bid and ask else ltp
            g = None
            if ref and inst.option_type and inst.strike:
                iv = pricing.implied_vol(ref, fwd, inst.strike, t_exp, inst.option_type)
                if iv:
                    g = pricing.greeks(fwd, inst.strike, t_exp, iv, inst.option_type)
            oq = OptionQuote(instrument=inst, ltp=ltp, bid=bid, ask=ask, volume=q.get("volume"), oi=q.get("oi"),
                             oi_change=None, greeks=g, ts=ts, received_ts=recv, status=self._status(recv))
            row = by_strike.setdefault(inst.strike or 0.0, OptionChainRow(strike=inst.strike or 0.0))
            if inst.option_type == OptionType.CE:
                row.ce = oq
            else:
                row.pe = oq
        return OptionChainSnapshot(underlying=underlying, expiry=exp, expiries=expiries, forward=fwd,
                                   rows=[by_strike[k] for k in sorted(by_strike)], ts=newest or recv, received_ts=recv,
                                   status=self._status(recv), source="kite")

    def _status(self, now: datetime) -> DataStatus:
        if not self._authenticated:
            return DataStatus.UNAVAILABLE
        if self._last_tick_ts is None or (now - self._last_tick_ts).total_seconds() > 15:
            return DataStatus.STALE
        return DataStatus.LIVE

    async def get_market_session(self, d: date) -> MarketSession:
        return self.calendar.session_for(d)

    def get_health(self) -> ProviderHealth:
        now = self.now()
        miss = self.missing_credentials()
        status = DataStatus.UNAVAILABLE if (miss or not self._authenticated) else self._status(now)
        return ProviderHealth(
            name="kite", status=status, connected=self._connected and self._failures == 0,
            authenticated=self._authenticated, last_tick_ts=self._last_tick_ts, last_received_ts=self._last_recv,
            latency_ms=self._latency_ms, transport="REST polling (/quote)", message=self._message,
            missing_credentials=miss)
