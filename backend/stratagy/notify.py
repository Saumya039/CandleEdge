"""Outbound alerts for setups (personal notifications only; never orders).

Messages are built only from the stored signal and its TradePlan, so every number in them is one the app computed
from real input data. Sending is best-effort and never blocks or breaks the engine. SIMULATED signals are NOT sent
unless explicitly enabled, so a synthetic setup can never reach a phone looking like a real call."""

from __future__ import annotations

import asyncio
import logging
from typing import Protocol

import httpx

from .models import Direction, SignalState
from .statemachine import Signal

log = logging.getLogger("stratagy.notify")

HEADLINE = {
    SignalState.CANDIDATE: "SETUP",
    SignalState.TRIGGERED: "ENTRY ZONE HIT (paper)",
    SignalState.TARGET_1: "TARGET 1 REACHED",
    SignalState.TARGET_2: "TARGET 2 REACHED",
    SignalState.STOPPED: "STOP LOSS HIT",
    SignalState.INVALIDATED: "INVALIDATED",
    SignalState.TIME_EXIT: "TIME EXIT",
    SignalState.EXPIRED: "EXPIRED",
}


def _n(x: float) -> str:
    return f"{x:,.2f}".rstrip("0").rstrip(".")


def format_signal_message(sig: Signal, to: SignalState, reason: str, *, simulated: bool) -> str | None:
    """Plain-text message in the shape traders expect. Returns None for states that should not be sent."""
    head = HEADLINE.get(to)
    if head is None:
        return None
    p = sig.plan
    c = p.contract
    side = "BUY CALL" if sig.direction == Direction.CALL else "BUY PUT"
    opt = c.option_type.value if c.option_type else ""
    lines = [
        f"{'[SIMULATED] ' if simulated else ''}{side} - {head}",
        f"{c.symbol}" + (f"  (strike {_n(c.strike)} {opt}, exp {c.expiry:%d-%b-%Y})" if c.strike and c.expiry else ""),
        f"Buy at or below: {_n(p.premium_entry_limit)}",
        f"Target 1: {_n(p.premium_target1)}",
        f"Target 2: {_n(p.premium_target2)}",
        f"Stop loss: {_n(p.premium_stop)}",
        f"{sig.underlying} entry zone {_n(p.entry_zone_underlying[0])} to {_n(p.entry_zone_underlying[1])}, "
        f"invalid beyond {_n(p.invalidation_underlying)}",
        f"Lot {p.lot_size} | R:R to T1 {p.rr_t1:.2f} | score {sig.score if sig.score is not None else 'n/a'} (not a win probability)",
    ]
    if to not in (SignalState.CANDIDATE,):
        lines.append(f"Update: {reason}")
    lines.append("Signal from your own app. Not advice. The app placed no order: any trade is your own decision.")
    return "\n".join(lines)


def format_eod_message(report: dict, *, simulated: bool) -> str:
    """End-of-day summary built only from the session report the engine already computed."""
    s = report["summary"]
    states = s.get("setups_by_final_state", {})
    lines = [f"{'[SIMULATED] ' if simulated else ''}END OF DAY SUMMARY - {report['date']}"]
    if not s["setups_generated"]:
        lines.append("Setups today: 0. The rules found no valid setup, so no call was sent. Nothing was forced.")
    else:
        lines.append(f"Setups sent: {s['setups_generated']}")
        lines.append("Final status: " + ", ".join(f"{k} {v}" for k, v in sorted(states.items())))
        if s["trades"]:
            lines.append(f"Simulated results (assumed fills and costs): {s['wins']} won, {s['losses']} lost, "
                         f"net {s['net_pnl']:+,.0f} after estimated costs")
        else:
            lines.append("No setup reached its entry zone in the app's simulation.")
    inc = len(report.get("data_quality_incidents", []))
    lines.append(f"Data-health incidents today: {inc}")
    lines.append("Simulated results are not your real account. The app placed no order. "
                 "Past results do not predict future results; any trade is your own decision.")
    return "\n".join(lines)


class Channel(Protocol):
    name: str

    async def send(self, text: str) -> None: ...


class TelegramChannel:
    """Telegram Bot API. The bot token and chat id come from the server environment only."""

    name = "telegram"

    def __init__(self, token: str, chat_id: str, transport: httpx.AsyncBaseTransport | None = None):
        self._token, self._chat_id, self._transport = token, chat_id, transport

    async def send(self, text: str) -> None:
        async with httpx.AsyncClient(timeout=10.0, transport=self._transport) as c:
            r = await c.post(f"https://api.telegram.org/bot{self._token}/sendMessage",
                             json={"chat_id": self._chat_id, "text": text})
            if r.status_code >= 400:
                raise RuntimeError(f"telegram HTTP {r.status_code}")


class Notifier:
    def __init__(self, channels: list[Channel], send_simulated: bool = False):
        self.channels = channels
        self.send_simulated = send_simulated
        self.sent: list[str] = []  # last few messages, for the status screen and tests
        self.last_error: str | None = None
        self._tasks: set[asyncio.Task] = set()

    @property
    def enabled(self) -> bool:
        return bool(self.channels)

    def on_transition(self, sig: Signal, to: SignalState, reason: str, *, simulated: bool) -> None:
        if not self.channels or (simulated and not self.send_simulated):
            return
        text = format_signal_message(sig, to, reason, simulated=simulated)
        if text is None:
            return
        self.sent = (self.sent + [text])[-20:]
        for ch in self.channels:
            t = asyncio.get_running_loop().create_task(self._send(ch, text))
            self._tasks.add(t)
            t.add_done_callback(self._tasks.discard)

    def on_session_close(self, report: dict, *, simulated: bool) -> None:
        if not self.channels or (simulated and not self.send_simulated):
            return
        text = format_eod_message(report, simulated=simulated)
        self.sent = (self.sent + [text])[-20:]
        for ch in self.channels:
            t = asyncio.get_running_loop().create_task(self._send(ch, text))
            self._tasks.add(t)
            t.add_done_callback(self._tasks.discard)

    async def _send(self, ch: Channel, text: str) -> None:
        try:
            await ch.send(text)
            self.last_error = None
        except Exception as e:  # noqa: BLE001 - a failed notification must never affect trading logic
            self.last_error = f"{ch.name}: {type(e).__name__}"
            log.warning("notification via %s failed: %s", ch.name, type(e).__name__)
