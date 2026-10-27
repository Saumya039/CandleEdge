"""Kite Connect streaming (WebSocket) packet decoder. READ-ONLY market data; nothing here can place an order.

Binary frame layout (Kite Connect docs, "WebSocket streaming"): `>H` packet count, then per packet `>H` length
followed by that many bytes. A frame of one byte is a heartbeat. All numbers are big-endian int32; prices are in
paise (divide by 100) for equity/F&O segments (the low byte of the instrument token is the segment id).
  8 bytes   LTP        token, last_price
  28 / 32   index      token, ltp, high, low, open, close, change [, exchange_timestamp]
  44 / 184  quote/full token, ltp, last_qty, avg_price, volume, buy_qty, sell_qty, open, high, low, close
                       [, last_trade_time, oi, oi_high, oi_low, exchange_timestamp, depth...]
The layout was written from the public documentation and is covered by unit tests built from the same layout;
it has not been exercised against the live service from the build sandbox."""

from __future__ import annotations

import struct
from datetime import datetime
from typing import Any

from ..models import IST

_CDS, _BCD = 3, 6  # segment ids with different price divisors


def _divisor(token: int) -> float:
    seg = token & 0xFF
    return 10_000_000.0 if seg == _CDS else 10_000.0 if seg == _BCD else 100.0


def _ts(v: int) -> datetime | None:
    return datetime.fromtimestamp(v, IST) if v > 0 else None


def decode_frame(buf: bytes) -> list[dict[str, Any]]:
    """Decode one binary frame into plain dicts. Malformed or unknown packets are skipped, never guessed at."""
    if len(buf) < 4:
        return []  # 1-byte heartbeat or empty
    out: list[dict[str, Any]] = []
    try:
        n = struct.unpack_from(">H", buf, 0)[0]
        pos = 2
        for _ in range(n):
            ln = struct.unpack_from(">H", buf, pos)[0]
            pos += 2
            pkt = buf[pos:pos + ln]
            pos += ln
            if len(pkt) != ln:
                break
            d = _decode_packet(pkt)
            if d:
                out.append(d)
    except struct.error:
        return out
    return out


def _decode_packet(p: bytes) -> dict[str, Any] | None:
    ln = len(p)
    if ln not in (8, 28, 32, 44, 184):
        return None
    token = struct.unpack_from(">i", p, 0)[0]
    div = _divisor(token)
    ltp = struct.unpack_from(">i", p, 4)[0] / div
    d: dict[str, Any] = {"token": token, "ltp": ltp, "volume": None, "oi": None, "exchange_ts": None}
    if ln in (28, 32):  # index packet: no volume or OI
        if ln == 32:
            d["exchange_ts"] = _ts(struct.unpack_from(">i", p, 28)[0])
        return d
    if ln >= 44:
        d["volume"] = struct.unpack_from(">i", p, 16)[0]
    if ln == 184:
        d["oi"] = struct.unpack_from(">i", p, 48)[0]
        d["exchange_ts"] = _ts(struct.unpack_from(">i", p, 60)[0]) or _ts(struct.unpack_from(">i", p, 44)[0])
    return d
