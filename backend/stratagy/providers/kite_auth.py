"""Kite Connect login helpers: login URL, request-token exchange, and the daily token file.

The API secret is read from the server environment and used only for the exchange request; it is never written to
disk, logged, or returned to the browser. Only the resulting access token is saved (valid for the current IST day)."""

from __future__ import annotations

import hashlib
import json
import os
import urllib.parse
from datetime import datetime
from pathlib import Path

import httpx

from ..models import IST

LOGIN_BASE = "https://kite.zerodha.com/connect/login"
SESSION_URL = "https://api.kite.trade/session/token"


def login_url(api_key: str, state: str) -> str:
    # redirect_params carries our anti-forgery state back to the callback.
    rp = urllib.parse.quote(urllib.parse.urlencode({"state": state}))
    return f"{LOGIN_BASE}?v=3&api_key={urllib.parse.quote(api_key)}&redirect_params={rp}"


async def exchange_request_token(api_key: str, api_secret: str, request_token: str,
                                 transport: httpx.AsyncBaseTransport | None = None) -> str:
    checksum = hashlib.sha256((api_key + request_token + api_secret).encode()).hexdigest()
    async with httpx.AsyncClient(timeout=15.0, transport=transport, headers={"X-Kite-Version": "3"}) as c:
        r = await c.post(SESSION_URL, data={"api_key": api_key, "request_token": request_token, "checksum": checksum})
    if r.status_code != 200:
        raise ValueError(f"Kite refused the login exchange (HTTP {r.status_code}). Check the API key and secret.")
    token = r.json().get("data", {}).get("access_token")
    if not token:
        raise ValueError("Kite returned no access token")
    return str(token)


def save_token(path: Path, token: str, now: datetime | None = None) -> None:
    now = now or datetime.now(IST)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"access_token": token, "date": now.astimezone(IST).date().isoformat()}, f)


def load_token(path: Path, now: datetime | None = None) -> str:
    """Today's saved token, or an empty string (tokens from earlier days are expired)."""
    now = now or datetime.now(IST)
    try:
        d = json.loads(path.read_text())
        if d.get("date") == now.astimezone(IST).date().isoformat():
            return str(d.get("access_token", ""))
    except (OSError, ValueError):
        pass
    return ""
