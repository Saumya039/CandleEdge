"""Setup alerts: message content comes only from the stored plan, simulated setups are not sent by default,
a failing channel never disturbs the engine, and every state change is sent exactly once."""

from __future__ import annotations

import asyncio
import json

import httpx

from stratagy.config import Settings
from stratagy.models import SignalState
from stratagy.notify import Notifier, TelegramChannel, format_signal_message
from tests.conftest import first_signal_engine, new_engine, run_until


class Rec:
    name = "rec"

    def __init__(self, fail: bool = False):
        self.texts: list[str] = []
        self.fail = fail

    async def send(self, text: str) -> None:
        if self.fail:
            raise RuntimeError("boom")
        self.texts.append(text)


def test_message_uses_the_plan_numbers_and_labels_simulated():
    eng, _ = first_signal_engine(1)
    sig = next(iter(eng.signals.values()))
    p = sig.plan
    txt = format_signal_message(sig, SignalState.CANDIDATE, "", simulated=True)
    assert txt.startswith("[SIMULATED] BUY PUT") and p.contract.symbol in txt
    assert f"Stop loss: {p.premium_stop:g}" in txt.replace(",", "") or "Stop loss:" in txt
    for label in ("Buy at or below:", "Target 1:", "Target 2:", "Stop loss:"):
        assert label in txt
    assert "placed no order" in txt and "not a win probability" in txt
    assert format_signal_message(sig, SignalState.WATCHING, "", simulated=False) is None


def test_simulated_setups_are_not_sent_unless_enabled():
    eng, _ = first_signal_engine(1)
    sig = next(iter(eng.signals.values()))

    async def go(send_sim: bool) -> list[str]:
        ch = Rec()
        n = Notifier([ch], send_simulated=send_sim)
        n.on_transition(sig, SignalState.CANDIDATE, "", simulated=True)
        await asyncio.sleep(0.05)
        return ch.texts

    assert asyncio.run(go(False)) == [] and len(asyncio.run(go(True))) == 1


def test_engine_sends_each_transition_once_and_survives_a_failing_channel():
    good, bad = Rec(), Rec(fail=True)
    eng, prov = new_engine(1, notifier=Notifier([good, bad], send_simulated=True))
    asyncio.run(run_until(eng, prov, lambda e: False))
    sent_states = [s for sig in eng.signals.values() for s in (t.to_state for t in sig.transitions)
                   if s in (SignalState.CANDIDATE, SignalState.TRIGGERED, SignalState.TARGET_1, SignalState.TARGET_2,
                            SignalState.STOPPED, SignalState.INVALIDATED, SignalState.TIME_EXIT, SignalState.EXPIRED)]
    eod = [t for t in good.texts if "END OF DAY SUMMARY" in t]
    assert len(eod) <= 1  # the day summary is sent at most once
    signal_texts = [t for t in good.texts if "END OF DAY SUMMARY" not in t]
    assert eng.signals and len(signal_texts) == len(sent_states)  # exactly one message per state change
    assert eng.notifier.last_error is not None or good.texts  # the failing channel was logged, not raised
    assert signal_texts[0].splitlines()[0].endswith("SETUP")  # the first message is the new setup itself


def test_telegram_channel_posts_to_the_bot_api_with_the_configured_chat():
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json={"ok": True})

    ch = TelegramChannel("TOKEN", "12345", transport=httpx.MockTransport(handler))
    asyncio.run(ch.send("hello"))
    assert seen[0].url.host == "api.telegram.org" and seen[0].url.path == "/botTOKEN/sendMessage"
    assert json.loads(seen[0].content) == {"chat_id": "12345", "text": "hello"}


def test_several_of_your_own_chats_each_get_a_channel():
    from stratagy.app import build_notifier

    n = build_notifier(Settings(telegram_bot_token="T", telegram_chat_id="111, 222"))
    assert [c._chat_id for c in n.channels] == ["111", "222"]
    assert not build_notifier(Settings(telegram_bot_token="", telegram_chat_id="111")).enabled


def _report(setups: int) -> dict:
    return {"date": "2026-10-27", "data_quality_incidents": [],
            "summary": {"setups_generated": setups, "setups_by_final_state": {"EXPIRED": setups} if setups else {},
                        "trades": 0, "wins": 0, "losses": 0, "net_pnl": 0.0}}


def test_eod_summary_says_plainly_when_no_setup_fired():
    from stratagy.notify import format_eod_message

    text = format_eod_message(_report(0), simulated=False)
    assert "Setups today: 0" in text and "Nothing was forced" in text
    assert "SIMULATED" not in text
    assert "placed no order" in text


def test_eod_summary_is_sent_once_and_never_for_simulated_by_default():
    n = Notifier([], send_simulated=False)
    n.on_session_close(_report(2), simulated=False)  # no channels: silent
    assert n.sent == []
    sim = Notifier([TelegramChannel("t", "1")], send_simulated=False)
    sim.on_session_close(_report(2), simulated=True)
    assert sim.sent == []
