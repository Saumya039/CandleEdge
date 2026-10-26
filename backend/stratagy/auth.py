"""Single-user password login for the web app (stdlib only).

The password is stored only as a salted PBKDF2 hash in the server environment. A successful login sets a signed,
expiring, HttpOnly, SameSite=Strict cookie. This protects the dashboard and its settings controls; it is not a
multi-user account system and it adds no order permission of any kind."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time

ITERATIONS = 310_000
COOKIE = "stratagy_session"


def hash_password(password: str, iterations: int = ITERATIONS) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, iters, salt, digest = stored.split("$")
        if scheme != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iters))
        return hmac.compare_digest(dk.hex(), digest)
    except (ValueError, TypeError):
        return False


def _sign(secret: str, payload: str) -> str:
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def make_token(secret: str, ttl_seconds: int, now: float | None = None) -> str:
    exp = int((now if now is not None else time.time()) + ttl_seconds)
    payload = f"{exp}.{secrets.token_hex(8)}"
    return base64.urlsafe_b64encode(f"{payload}.{_sign(secret, payload)}".encode()).decode()


def valid_token(secret: str, token: str | None, now: float | None = None) -> bool:
    if not token:
        return False
    try:
        exp_s, nonce, sig = base64.urlsafe_b64decode(token.encode()).decode().split(".")
        payload = f"{exp_s}.{nonce}"
        return hmac.compare_digest(sig, _sign(secret, payload)) and int(exp_s) > (now if now is not None else time.time())
    except (ValueError, TypeError, UnicodeError):
        return False
