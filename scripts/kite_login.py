#!/usr/bin/env python3
"""Exchange a Kite Connect request_token for a daily access token (run on YOUR machine).

Usage:
  1. Open https://kite.zerodha.com/connect/login?v=3&api_key=<KITE_API_KEY> in a browser and log in yourself.
  2. Copy the `request_token` query parameter from the redirect URL.
  3. KITE_API_KEY=... KITE_API_SECRET=... python scripts/kite_login.py <request_token>
  4. Put the printed access token into your server-side environment as KITE_ACCESS_TOKEN.

The api_secret is read from the environment only; it is never written to disk or logged. Verify the flow
against the current Kite Connect documentation. The token only needs data permissions for this project; no
order code exists in this repository."""
import hashlib
import json
import os
import sys
import urllib.parse
import urllib.request


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    key, secret = os.environ.get("KITE_API_KEY"), os.environ.get("KITE_API_SECRET")
    if not key or not secret:
        print("Set KITE_API_KEY and KITE_API_SECRET in the environment (not on the command line).")
        return 2
    rt = sys.argv[1]
    checksum = hashlib.sha256((key + rt + secret).encode()).hexdigest()
    body = urllib.parse.urlencode({"api_key": key, "request_token": rt, "checksum": checksum}).encode()
    req = urllib.request.Request("https://api.kite.trade/session/token", data=body, headers={"X-Kite-Version": "3"})
    with urllib.request.urlopen(req, timeout=15) as r:  # noqa: S310
        data = json.load(r)["data"]
    print("KITE_ACCESS_TOKEN=" + data["access_token"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
