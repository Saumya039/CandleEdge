"""Workstation engine: ties provider, candles, strategy, signal lifecycle, risk and paper trading together.

The engine is clock-agnostic: it asks the provider for `now()` (virtual clock for the simulator, wall clock
IST for a live provider), so the same code path serves the simulator, replay/backtests and live data."""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from datetime import date, datetime, timedelta

from pydantic import BaseModel

from . import paper as paper_mod
from .candles import CandleBuilder, resample
from .config import ContractParams, CostModel, DataHealthParams, RiskSettings, StrategyParams
from .contracts import choose_expiry, quote_age_s
from .journal import Journal
from .models import (
    IST,
    TF_MINUTES,
    Candle,
    Direction,
    OptionChainSnapshot,
    OptionQuote,
    SignalState,
    Tick,
)
from .notify import Notifier
from .paper import PaperTrade, TradeStatus
from .providers.base import MarketDataProvider, ProviderError, UnderlyingSpec
from .risk import Check, RiskState, buy_fill, register_close, risk_gate, size_position
from .sessions import ExchangeCalendar, SessionPhase
from .statemachine import Signal, apply_event, new_signal
from .strategy import Evaluation, Snapshot, evaluate

log = logging.getLogger("stratagy.engine")

SENSITIVITY = {
    "conservative": {"adx_min_trend": 25.0, "min_rr": 2.0, "volume_mult_min": 1.2},
    "standard": {},
    "aggressive": {"adx_min_trend": 17.0, "min_rr": 1.3, "volume_mult_min": 0.8},
}
HTF_FOR = {"1m": "5m", "3m": "15m", "5m": "15m", "15m": "15m"}


def params_for(base: StrategyParams, trigger_tf: str, sensitivity: str) -> StrategyParams:
    upd: dict = {"trigger_tf": trigger_tf, "htf": HTF_FOR[trigger_tf], **SENSITIVITY[sensitivity]}
    suffix = ""
    if trigger_tf != base.trigger_tf:
        suffix += f"+tf{trigger_tf}"
    if sensitivity != "standard":
        suffix += f"+{sensitivity}"
    upd["version"] = base.version + suffix
    return base.model_copy(update=upd)


class Alert(BaseModel):
    ts: datetime
    kind: str
    signal_id: str | None = None
    underlying: str | None = None
    message: str


class UState:
    def __init__(self, spec: UnderlyingSpec, source: str):
        self.spec = spec
        self.builder = CandleBuilder(spec.signal_instrument.id, source)
        self.last_ltp: float | None = None
        self.last_tick_ts: datetime | None = None
        self.last_received_ts: datetime | None = None
        self.prev_close: float | None = None
        self.new_candle = True
        self.needs_reconcile = False
        self.last_eval_at: datetime | None = None
        self.latest_eval: Evaluation | None = None
        self.last_terminal_ts: datetime | None = None
        self.premium_series: dict[str, list[dict]] = {}
        self.bars_cache: tuple[tuple, list, float | None] | None = None  # (key, trigger-tf bars, last session VWAP) for the watchlist


class Engine:
    def __init__(
        self,
        provider: MarketDataProvider,
        calendar: ExchangeCalendar | None = None,
        params: StrategyParams | None = None,
        contract_params: ContractParams | None = None,
        cost: CostModel | None = None,
        risk: RiskSettings | None = None,
        health_params: DataHealthParams | None = None,
        journal: Journal | None = None,
        origin: str = "PAPER",
        chain_ttl_s: float = 5.0,
        eval_interval_s: float = 10.0,
        fast_start_names: int = 12,
        notifier: Notifier | None = None,
    ):
        self.provider = provider
        self.cal = calendar or ExchangeCalendar()
        self.base_params = params or StrategyParams()
        self.sensitivity = "standard"
        self.p = self.base_params
        self.cp = contract_params or ContractParams()
        self.cost = cost or CostModel()
        self.risk = risk or RiskSettings()
        self.dh = health_params or DataHealthParams()
        floor = getattr(provider, "min_stale_s", None)  # REST-polling providers refresh slower than a push feed
        if floor and self.dh.stale_after_s < floor:
            self.dh = self.dh.model_copy(update={"stale_after_s": float(floor)})
        self.journal = journal
        self.origin = origin
        self.chain_ttl_s = chain_ttl_s
        self.eval_interval_s = eval_interval_s
        self.notifier = notifier
        self.fast_start_names = fast_start_names  # names loaded before 'started'; the rest load in the background
        self.history_total = 0
        self._bg_task: asyncio.Task | None = None
        self.u: dict[str, UState] = {}
        self.signals: dict[str, Signal] = {}
        self.trades: dict[str, PaperTrade] = {}
        self.risk_state = RiskState()
        self.alerts: deque[Alert] = deque(maxlen=300)
        self.health_log: deque[dict] = deque(maxlen=200)
        self._seen_keys: set[str] = set()
        self._seq = 0
        self._chain_cache: dict[str, tuple[datetime, OptionChainSnapshot]] = {}
        self._expiry_cache: dict[str, date | None] = {}
        self._last_stale: bool | None = None
        self._last_connected: bool | None = None
        self._session_open_cache: dict[date, datetime | None] = {}
        self._closed_reported: date | None = None
        self.session_report: dict | None = None
        self._handles: list = []
        self.started = False
        self.start_error: str | None = None

    # ---- lifecycle --------------------------------------------------------------------------------
    async def start(self) -> None:
        now = self.provider.now()
        try:
            await self.provider.connect()
            specs = self.provider.underlyings()
            source = self.provider.get_health().name.upper()
            self.history_total = len(specs)
            for spec in specs[: self.fast_start_names]:
                await self._load_one(spec, source, now)
            rest = specs[self.fast_start_names:]
            if rest:  # indices come first, so the busiest names are live right away; the others fill in
                self._bg_task = asyncio.create_task(self._load_rest(rest, source, now))
            self.start_error = None
            self.started = True
        except ProviderError as e:
            self.start_error = str(e)
            self.started = False
            self._health(now, "provider_error", str(e))
        if self.journal:
            self.journal.register_strategy(self.p, now)
            self.journal.audit(now, "engine_start", {"provider": self.provider.name, "strategy": self.p.version,
                                                      "live_orders_enabled": False})

    async def _load_one(self, spec, source: str, now: datetime) -> None:
        st = UState(spec, source)
        hist = await self.provider.get_historical_candles(spec.signal_instrument.id, "1m", now - timedelta(days=6), now)
        st.builder.seed_history(hist)
        if hist:
            st.prev_close = hist[-1].close
        self.u[spec.symbol] = st
        h = await self.provider.subscribe_ticks([spec.signal_instrument.id], self._make_cb(spec.symbol))
        self._handles.append(h)

    async def _load_rest(self, specs: list, source: str, now: datetime) -> None:
        for spec in specs:
            try:
                await self._load_one(spec, source, self.provider.now())  # fresh 'now': no hole before the first tick
            except asyncio.CancelledError:
                raise
            except ProviderError as e:  # one name failing must not stop the others; it simply stays unwatched
                self._health(now, "history_failed", f"{spec.symbol}: {e}")

    @property
    def history_loading(self) -> dict | None:
        done = len(self.u)
        return {"loaded": done, "total": self.history_total} if self._bg_task and not self._bg_task.done() else None

    async def stop(self) -> None:
        if self._bg_task:
            self._bg_task.cancel()
        for h in self._handles:
            h.cancel()
        self._handles.clear()
        await self.provider.disconnect()

    def _make_cb(self, symbol: str):
        def cb(tick: Tick) -> None:
            self._on_tick(symbol, tick)
        return cb

    def _on_tick(self, symbol: str, tick: Tick) -> None:
        st = self.u[symbol]
        closed = st.builder.on_tick(tick)
        # out-of-order / duplicate ticks are dropped by the builder and must not move 'last price' either
        if st.builder.last_ts is not None and (tick.exchange_ts or tick.received_ts).astimezone(IST) == st.builder.last_ts:
            st.last_ltp = tick.ltp
            st.last_tick_ts = (tick.exchange_ts or tick.received_ts).astimezone(IST)
            st.last_received_ts = tick.received_ts
        if closed is not None:
            st.new_candle = True
            st.needs_reconcile = True
            if self.journal:
                self.journal.save_candle(closed)

    # ---- helpers ----------------------------------------------------------------------------------
    def _next_id(self, prefix: str, now: datetime, und: str) -> str:
        self._seq += 1
        return f"{prefix}-{now:%Y%m%d}-{self._seq:04d}-{und}"

    def _alert(self, now: datetime, kind: str, msg: str, sig: Signal | None = None, und: str | None = None) -> None:
        self.alerts.appendleft(Alert(ts=now, kind=kind, signal_id=sig.id if sig else None,
                                     underlying=(sig.underlying if sig else und), message=msg))

    def _health(self, now: datetime, kind: str, detail: str) -> None:
        self.health_log.appendleft({"ts": now.isoformat(), "kind": kind, "detail": detail})
        if self.journal:
            self.journal.health_event(now, kind, detail)

    def _session_open(self, d: date) -> datetime | None:
        if d not in self._session_open_cache:
            s = self.cal.session_for(d)
            self._session_open_cache[d] = s.open
        return self._session_open_cache[d]

    async def _session_open_async(self, d: date) -> datetime | None:
        if d not in self._session_open_cache:
            s = await self.provider.get_market_session(d)
            self._session_open_cache[d] = s.open if s.is_trading_day else None
        return self._session_open_cache[d]

    def phase(self, now: datetime) -> SessionPhase:
        if self.provider.name == "simulator":
            sd = getattr(self.provider, "sim_date", now.date())
            if now.date() == sd:
                return ExchangeCalendar().phase(now, self.p.or_minutes, self.risk.trading_cutoff)
        return self.cal.phase(now, self.p.or_minutes, self.risk.trading_cutoff)

    def active_signal(self, und: str) -> Signal | None:
        for s in self.signals.values():
            if s.underlying == und and not s.closed:
                return s
        return None

    def open_trades(self) -> list[PaperTrade]:
        return [t for t in self.trades.values() if t.status == TradeStatus.OPEN]

    async def _chain(self, und: str, now: datetime, force: bool = False) -> OptionChainSnapshot:
        cached = self._chain_cache.get(und)
        if cached and not force and (now - cached[0]).total_seconds() < self.chain_ttl_s:
            return cached[1]
        snap = await self.provider.get_option_chain(und)
        want = choose_expiry(snap.expiries, now.date(), self.cp)
        if want is not None and want != snap.expiry:
            snap = await self.provider.get_option_chain(und, want)
        self._chain_cache[und] = (now, snap)
        return snap

    async def _quote_for(self, sig: Signal, now: datetime) -> OptionQuote | None:
        und = sig.underlying
        try:
            cached = self._chain_cache.get(f"{und}:{sig.plan.contract.expiry}")
            if cached and (now - cached[0]).total_seconds() < self.chain_ttl_s:
                snap = cached[1]
            else:
                snap = await self.provider.get_option_chain(und, sig.plan.contract.expiry)
                self._chain_cache[f"{und}:{sig.plan.contract.expiry}"] = (now, snap)
        except Exception as e:  # provider failure: keep position, flag stale
            self._health(now, "chain_error", f"{type(e).__name__}: {e}")
            return None
        for row in snap.rows:
            q = row.ce if sig.plan.contract.option_type and sig.plan.contract.option_type.value == "CE" else row.pe
            if q and q.instrument.id == sig.plan.contract.id:
                st = self.u[und]
                ser = st.premium_series.setdefault(q.instrument.id, [])
                if not ser or ser[-1]["ts"] != q.ts.isoformat():
                    ser.append({"ts": q.ts.isoformat(), "bid": q.bid, "ask": q.ask, "ltp": q.ltp})
                    del ser[:-600]
                return q
        return None

    # ---- main loop step ---------------------------------------------------------------------------
    async def process(self) -> None:
        if not self.started:
            return
        now = self.provider.now()
        phase = self.phase(now)
        self._track_health(now)
        for und, st in list(self.u.items()):
            if st.needs_reconcile and hasattr(self.provider, "reconcile"):
                st.needs_reconcile = False
                for c in await self.provider.reconcile(st.spec.signal_instrument.id, now):  # type: ignore[attr-defined]
                    if c.ts in st.builder.closed:
                        st.builder.closed[c.ts] = c  # provider candle is authoritative for closed minutes
            due = st.new_candle or st.last_eval_at is None or (now - st.last_eval_at).total_seconds() >= self.eval_interval_s
            if due:
                await self._evaluate(und, st, now, phase)
                await asyncio.sleep(0)  # let API requests run between underlyings so the UI stays responsive with 200+ names
        for sig in list(self.signals.values()):
            if not sig.closed:
                await self._manage(sig, now, phase)
        self._update_unrealized()
        if phase == SessionPhase.POST_CLOSE and self._closed_reported != now.date():
            await self._close_session(now)

    def _track_health(self, now: datetime) -> None:
        h = self.provider.get_health()
        stale = self.is_stale(now)
        if self._last_stale is not None and stale != self._last_stale:
            self._health(now, "stale" if stale else "recovered",
                         "Underlying data stale: new signals suppressed" if stale else "Data feed recovered")
            self._alert(now, "data_health", "DATA STALE: new signals suppressed" if stale else "Data feed recovered")
        if self._last_connected is not None and h.connected != self._last_connected:
            self._health(now, "connected" if h.connected else "disconnected", h.message)
        self._last_stale, self._last_connected = stale, h.connected

    def is_stale(self, now: datetime) -> bool:
        if self.phase(now) not in (SessionPhase.OPENING_RANGE, SessionPhase.TRADING, SessionPhase.NO_NEW_ENTRIES):
            return False
        # Feed-level: stale only when NO watched name has a fresh tick. A single illiquid name must not blank the
        # whole screen; it is blocked individually by the per-underlying `tick_fresh` gate (fail closed per name).
        if not self.u:
            return False
        return all(st.last_tick_ts is None or (now - st.last_tick_ts).total_seconds() > self.dh.stale_after_s
                   for st in list(self.u.values()))

    def _gates(self, now: datetime, und: str) -> list[Check]:
        g = risk_gate(now, self.risk_state, self.risk, self._cutoff_dt(now))
        st = self.u[und]
        cd = self.p.cooldown_bars * TF_MINUTES[self.p.trigger_tf]
        ok = not (st.last_terminal_ts and now < st.last_terminal_ts + timedelta(minutes=cd))
        g.append(Check(name="signal_cooldown", passed=ok,
                       detail="No recent signal for this underlying" if ok else f"Cooldown {cd}m after previous signal ended"))
        act = self.active_signal(und)
        g.append(Check(name="no_active_signal", passed=act is None,
                       detail="No active signal" if act is None else f"Signal {act.id} still {act.state.value}"))
        return g

    async def _evaluate(self, und: str, st: UState, now: datetime, phase: SessionPhase) -> None:
        st.new_candle = False
        st.last_eval_at = now
        sess_open = await self._session_open_async(now.date())
        snap = Snapshot(
            underlying=und, now=now, candles_1m=st.builder.closed_list(), spot=st.last_ltp,
            last_tick_ts=st.last_tick_ts, health=self.provider.get_health(), phase=phase, session_open=sess_open,
        )
        cal = self.cal
        gates = self._gates(now, und)
        ev = evaluate(snap, self.p, self.cp, self.cost, self.risk, self.dh, gates, cal)
        if ev.needs_chain:
            try:
                snap.chain = await self._chain(und, now)
            except Exception as e:
                snap.chain_error = f"{type(e).__name__}: {e}"
                self._health(now, "chain_error", snap.chain_error)
            ev = evaluate(snap, self.p, self.cp, self.cost, self.risk, self.dh, gates, cal)
        st.latest_eval = ev
        if ev.decision == "CANDIDATE" and ev.dedupe_key and ev.dedupe_key not in self._seen_keys:
            self._seen_keys.add(ev.dedupe_key)
            sig = new_signal(ev, self._next_id("sig", now, und), now)
            self.signals[sig.id] = sig
            p = sig.plan
            self._alert(now, "candidate",
                        f"{p.direction.value.replace('_', ' ')} candidate {und} {p.contract.symbol}: entry zone "
                        f"{p.entry_zone_underlying[0]:.2f}-{p.entry_zone_underlying[1]:.2f}, invalidation "
                        f"{p.invalidation_underlying:.2f}, R:R {p.rr_t1:.2f}", sig)
            self._persist_signal(sig, ev)
            self._notify(sig, SignalState.CANDIDATE, "")

    def _notify(self, sig: Signal, to: SignalState, reason: str) -> None:
        if self.notifier and self.origin == "PAPER":
            self.notifier.on_transition(sig, to, reason, simulated=self.provider.name in ("simulator", "replay"))

    def _persist_signal(self, sig: Signal, ev: Evaluation | None = None) -> None:
        if self.journal:
            reg = ev.regime.regime.value if ev else ""
            self.journal.save_signal(sig, regime=reg, data_status=sig.plan.quote.status.value)

    def _persist_trade(self, t: PaperTrade) -> None:
        if self.journal:
            self.journal.save_trade(t, origin=self.origin)

    def _transition(self, sig: Signal, kind: str, to: SignalState, now: datetime, reason: str, spot: float | None,
                    prem: float | None = None) -> bool:
        changed = apply_event(sig, kind, to, now, reason, spot, prem)
        if changed:
            self._alert(now, to.value.lower(), f"{sig.underlying} {sig.plan.contract.symbol}: {to.value.replace('_', ' ')} - {reason}", sig)
            if self.journal:
                self.journal.audit(now, "signal_transition", {"signal": sig.id, "to": to.value, "reason": reason})
            self._persist_signal(sig)
            self._notify(sig, to, reason)
            if sig.closed:
                self.u[sig.underlying].last_terminal_ts = now
        return changed

    # ---- signal / position management -------------------------------------------------------------
    async def _manage(self, sig: Signal, now: datetime, phase: SessionPhase) -> None:
        st = self.u[sig.underlying]
        spot = st.last_ltp
        p = sig.plan
        sign = 1 if sig.direction == Direction.CALL else -1
        tfm = TF_MINUTES[sig.trigger_tf]
        if sig.state == SignalState.CANDIDATE:
            bars = int((now - sig.created_ts).total_seconds() // (tfm * 60))
            if phase in (SessionPhase.NO_NEW_ENTRIES, SessionPhase.POST_CLOSE, SessionPhase.CLOSED) or now >= self._cutoff_dt(now):
                self._transition(sig, "expire_cutoff", SignalState.EXPIRED, now, "Trading cutoff reached before trigger", spot)
                return
            if bars > self.p.candidate_ttl_bars:
                self._transition(sig, "expire_ttl", SignalState.EXPIRED, now,
                                 f"Not triggered within {self.p.candidate_ttl_bars} {sig.trigger_tf} bars", spot)
                return
            if spot is None or self.is_stale(now):
                return  # fail closed: cannot trigger on stale data
            if sign * (spot - p.invalidation_underlying) <= 0:
                self._transition(sig, "invalidate", SignalState.INVALIDATED, now,
                                 f"Underlying breached invalidation {p.invalidation_underlying:.2f} before entry", spot)
                return
            lo, hi = p.entry_zone_underlying
            beyond = spot > hi if sign > 0 else spot < lo
            if beyond:
                self._transition(sig, "expire_zone", SignalState.EXPIRED, now,
                                 "Price moved beyond the planned entry zone (no chasing)", spot)
                return
            in_zone = lo <= spot <= hi
            if in_zone:
                await self._try_trigger(sig, now, spot)
            return
        # TRIGGERED / TARGET_1: manage the paper position
        trade = self.trades.get(f"trade-{sig.id}")
        if trade is None or trade.status == TradeStatus.CLOSED:
            return
        quote = await self._quote_for(sig, now)
        stale_mark = quote is None
        if quote is None:
            quote = p.quote  # last known snapshot: flagged as stale mark
        else:
            paper_mod.mark_trade(trade, quote)
        trade.data_status = "STALE_MARK" if stale_mark else quote.status.value
        if spot is None:
            return
        if self._square_off_due(now):
            self._exit_all(sig, trade, quote, now, spot, "sqoff", SignalState.TIME_EXIT, "Intraday square-off time reached (paper)")
            return
        if sign * (spot - p.invalidation_underlying) <= 0:
            self._exit_all(sig, trade, quote, now, spot, "stop_u", SignalState.STOPPED,
                           f"Underlying invalidation {p.invalidation_underlying:.2f} breached")
            return
        if trade.stop_moved_to_breakeven and sign * (spot - p.entry_ref_underlying) <= 0:
            self._exit_all(sig, trade, quote, now, spot, "stop_be", SignalState.STOPPED, "Breakeven stop after Target 1 hit")
            return
        if not stale_mark and quote.bid is not None and quote.bid <= trade.premium_stop:
            self._exit_all(sig, trade, quote, now, spot, "stop_p", SignalState.STOPPED,
                           f"Premium risk-control level {trade.premium_stop:.2f} reached")
            return
        if sign * (spot - p.target2_underlying) >= 0:
            self._exit_all(sig, trade, quote, now, spot, "t2", SignalState.TARGET_2, f"Target 2 {p.target2_underlying:.2f} reached")
            return
        if sig.state == SignalState.TRIGGERED and sign * (spot - p.target1_underlying) >= 0:
            if trade.lots >= 2:
                half = trade.lots // 2
                net = paper_mod.close_lots(trade, half, quote, now, "Target 1 (partial)", self.cost)
                trade.stop_moved_to_breakeven = True
                trade.premium_stop = max(trade.premium_stop, trade.entry_fill)
                self._transition(sig, "t1", SignalState.TARGET_1, now,
                                 f"Target 1 {p.target1_underlying:.2f}: {half} lot(s) sold, stop moved to breakeven", spot)
                self._persist_trade(trade)
                _ = net
            else:
                self._exit_all(sig, trade, quote, now, spot, "t1", SignalState.TARGET_1,
                               f"Target 1 {p.target1_underlying:.2f} reached (single lot: fully exited)", close_signal=True)
            return
        if now >= p.time_stop:
            self._exit_all(sig, trade, quote, now, spot, "time", SignalState.TIME_EXIT, "Time stop reached")

    def _cal_for(self, now: datetime) -> ExchangeCalendar:
        if self.provider.name == "simulator" and now.date() == getattr(self.provider, "sim_date", None):
            return ExchangeCalendar()
        return self.cal

    def _cutoff_dt(self, now: datetime) -> datetime:
        return self._cal_for(now).offset_time(now.date(), self.risk.trading_cutoff)

    def _square_off_due(self, now: datetime) -> bool:
        return now >= self._cal_for(now).offset_time(now.date(), self.risk.paper_square_off)

    def _exit_all(self, sig: Signal, trade: PaperTrade, quote: OptionQuote, now: datetime, spot: float, kind: str,
                  to: SignalState, reason: str, close_signal: bool = False) -> None:
        # premium stops/targets are not guaranteed: fill is bid - slippage even if worse than the level
        before_net = trade.gross_pnl - trade.est_costs
        paper_mod.close_lots(trade, trade.lots_open, quote, now, reason, self.cost)
        leg_net = trade.net_pnl
        _ = before_net
        self._transition(sig, kind, to, now, reason, spot, trade.fills[-1].price)
        if close_signal:
            sig.closed = True
            self.u[sig.underlying].last_terminal_ts = now
            self._persist_signal(sig)
        register_close(self.risk_state, leg_net, now, self.risk)
        self._persist_trade(trade)
        self._alert(now, "paper_exit", f"PAPER exit {trade.symbol}: net P&L Rs {trade.net_pnl:,.0f} ({reason})", sig)

    async def _try_trigger(self, sig: Signal, now: datetime, spot: float) -> None:
        p = sig.plan
        und = sig.underlying
        gate = [c for c in risk_gate(now, self.risk_state, self.risk, self._cutoff_dt(now)) if not c.passed]
        if gate:
            self._transition(sig, "blocked", SignalState.EXPIRED, now,
                             "Entry blocked by risk safeguards: " + "; ".join(c.name for c in gate), spot)
            return
        quote = await self._quote_for(sig, now)
        if quote is None or quote_age_s(quote, now) > self.cp.max_quote_age_s or quote.ask is None or quote.bid is None:
            return  # no fresh two-sided quote: wait (fail closed)
        if quote.spread_pct is None or quote.spread_pct > self.cp.max_spread_pct:
            return
        fill = buy_fill(quote.ask, quote.instrument.tick_size, self.cost)
        if fill > p.premium_entry_limit:
            return  # premium has run away from the plan: do not chase
        sz = size_position(fill, p.premium_stop, p.lot_size, quote.instrument.tick_size, self.cost, self.risk)
        if sz.lots < 1:
            self._transition(sig, "size_fail", SignalState.EXPIRED, now, f"NO TRADE: {sz.reason}", spot)
            return
        trade = paper_mod.open_trade(sig.id, f"trade-{sig.id}", p, quote, sz.lots, now, self.cost)
        self.trades[trade.id] = trade
        self.risk_state.trades_today += 1
        self.risk_state.open_positions += 1
        self.risk_state.day = now.date().isoformat()
        self._transition(sig, "trigger", SignalState.TRIGGERED, now,
                         f"Underlying {spot:.2f} inside entry zone; PAPER BUY {sz.lots} lot(s) @ {fill:.2f} (simulated fill)", spot, fill)
        self._persist_trade(trade)
        if self.journal:
            self.journal.audit(now, "paper_entry", {"trade": trade.id, "lots": sz.lots, "fill": fill, "live_order": False})
        _ = und

    def _update_unrealized(self) -> None:
        self.risk_state.unrealized = sum(t.unrealized() for t in self.open_trades())

    async def _close_session(self, now: datetime) -> None:
        from .reports import session_report

        for sig in list(self.signals.values()):
            if not sig.closed:
                if sig.state == SignalState.CANDIDATE:
                    self._transition(sig, "expire_close", SignalState.EXPIRED, now, "Session closed", None)
                else:
                    t = self.trades.get(f"trade-{sig.id}")
                    if t and t.status == TradeStatus.OPEN:
                        q = await self._quote_for(sig, now) or sig.plan.quote
                        self._exit_all(sig, t, q, now, self.u[sig.underlying].last_ltp or 0.0, "sqoff_close",
                                       SignalState.TIME_EXIT, "Session closed: paper position closed")
        self._closed_reported = now.date()
        self.session_report = session_report(self, now.date())
        if self.journal:
            self.journal.audit(now, "session_closed", {"date": now.date().isoformat(), "summary": self.session_report["summary"]})
        self._health(now, "session_closed", "Session closed; journal saved")

    # ---- user actions -----------------------------------------------------------------------------
    def set_risk(self, new: RiskSettings, now: datetime) -> None:
        before = self.risk.model_dump(mode="json")
        self.risk = new
        if self.journal:
            self.journal.audit(now, "risk_settings_changed", {"before": before, "after": new.model_dump(mode="json")})

    def set_strategy(self, trigger_tf: str, sensitivity: str, now: datetime) -> None:
        old = self.p.version
        self.sensitivity = sensitivity
        self.p = params_for(self.base_params, trigger_tf, sensitivity)
        if self.journal:
            self.journal.register_strategy(self.p, now)
            self.journal.audit(now, "strategy_changed", {"from": old, "to": self.p.version})
        for st in list(self.u.values()):
            st.last_eval_at = None

    def set_pause(self, paused: bool, reason: str, now: datetime) -> None:
        self.risk_state.paused = paused
        self.risk_state.pause_reason = reason if paused else ""
        self._alert(now, "pause", "Trading PAUSED: no new paper entries" if paused else "Trading resumed")
        if self.journal:
            self.journal.audit(now, "pause" if paused else "resume", {"reason": reason})

    def set_accept_delayed(self, accept: bool, now: datetime) -> None:
        self.dh = self.dh.model_copy(update={"accept_delayed": accept})
        if self.journal:
            self.journal.audit(now, "accept_delayed_changed", {"accept_delayed": accept})

    # ---- read model for the API -------------------------------------------------------------------
    def candles(self, und: str, tf: str, limit: int = 400, today_only: bool = False) -> list[dict]:
        st = self.u[und]
        c1 = st.builder.closed_list()
        if st.builder.current is not None:
            pass  # forming candle intentionally excluded: only CLOSED candles feed strategy and charts
        series = resample(c1, tf) if tf != "1m" else c1  # type: ignore[arg-type]
        if today_only and series:
            d = series[-1].ts.date()
            series = [c for c in series if c.ts.date() == d]
        return [c.model_dump(mode="json") for c in series[-limit:]]

    def forming_candle(self, und: str) -> Candle | None:
        return self.u[und].builder.current
