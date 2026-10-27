#!/usr/bin/env python3
"""One-step local launcher for CandleEdge (Windows, macOS, Linux).

  python run.py            practice mode: simulated data, nothing to set up
  python run.py --live     Zerodha Kite live data (asks once for your API key and secret)

It installs what is missing, starts the backend (127.0.0.1:8000) and the web app (localhost:3000), opens your
browser, and stops both when you press Ctrl+C. Everything stays on this computer. No orders are ever placed."""
from __future__ import annotations

import argparse
import getpass
import hashlib
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from typing import NoReturn
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND, FRONTEND, LOGS = ROOT / "backend", ROOT / "frontend", ROOT / "logs"
ENV_FILE = ROOT / ".env"
VENV = BACKEND / ".venv"
BIN = VENV / ("Scripts" if os.name == "nt" else "bin")
PY = BIN / ("python.exe" if os.name == "nt" else "python")
API_PORT, WEB_PORT = 8000, 3000


def say(msg: str) -> None:
    print(f"[CandleEdge] {msg}", flush=True)


def die(msg: str) -> NoReturn:
    print(f"\n[CandleEdge] Problem: {msg}\n", flush=True)
    sys.exit(1)


def digest(paths: list[Path]) -> str:
    h = hashlib.sha256()
    for p in sorted(paths):
        if p.is_file():
            h.update(str(p.relative_to(ROOT)).encode())
            h.update(p.read_bytes())
    return h.hexdigest()


def run(cmd: list[str], cwd: Path, env: dict | None = None) -> None:
    r = subprocess.run(cmd, cwd=cwd, env=env)
    if r.returncode != 0:
        die(f"'{' '.join(cmd[:3])}' failed. Scroll up for the error and send it to your helper (never share secrets).")


def read_env() -> dict[str, str]:
    out: dict[str, str] = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.split(" #")[0].strip().strip("'\"")
    return out


def write_env(updates: dict[str, str]) -> None:
    cur = read_env()
    cur.update(updates)
    keep = [ln for ln in (ENV_FILE.read_text().splitlines() if ENV_FILE.exists() else [])
            if ln.split("=", 1)[0].strip() not in updates]
    ENV_FILE.write_text("\n".join(keep + [f"{k}={v}" for k, v in updates.items()]) + "\n")
    try:
        ENV_FILE.chmod(0o600)
    except OSError:
        pass


def check_tools() -> str:
    if sys.version_info < (3, 11):
        die("Python 3.11 or newer is needed. Install it from python.org and run this again.")
    npm = shutil.which("npm")
    node = shutil.which("node")
    if not npm or not node:
        die("Node.js 20 or newer is needed. Install it from nodejs.org and run this again.")
    ver = subprocess.run([node, "--version"], capture_output=True, text=True).stdout.strip().lstrip("v")
    if int(ver.split(".")[0]) < 20:
        die(f"Node.js {ver} is too old. Install version 20 or newer from nodejs.org.")
    return npm


def setup_backend() -> None:
    if not PY.exists():
        say("Creating the Python environment (first run only)…")
        run([sys.executable, "-m", "venv", str(VENV)], ROOT)
    stamp = VENV / ".installed"
    want = digest([BACKEND / "pyproject.toml"])
    if not stamp.exists() or stamp.read_text() != want:
        say("Installing backend packages (first run takes a few minutes)…")
        run([str(PY), "-m", "pip", "install", "-q", "-e", "."], BACKEND)
        stamp.write_text(want)


def setup_frontend(npm: str, rebuild: bool) -> None:
    lock = digest([FRONTEND / "package-lock.json"])
    nm_stamp = FRONTEND / "node_modules" / ".installed"
    if not nm_stamp.exists() or nm_stamp.read_text() != lock:
        say("Installing web app packages (first run takes a few minutes)…")
        run([npm, "ci"], FRONTEND)
        nm_stamp.write_text(lock)
    src = [p for d in ("app", "components", "lib", "public") for p in (FRONTEND / d).rglob("*") if p.is_file()]
    src += [FRONTEND / f for f in ("package.json", "next.config.mjs", "tsconfig.json", "postcss.config.mjs")]
    want = digest(src) + os.environ.get("BACKEND_URL", "")
    stamp = FRONTEND / ".next" / ".built"
    if rebuild or not stamp.exists() or stamp.read_text() != want:
        say("Building the web app…")
        env = {**os.environ, "BACKEND_URL": f"http://127.0.0.1:{API_PORT}", "NEXT_PUBLIC_DEMO": ""}
        run([npm, "run", "build"], FRONTEND, env)
        stamp.write_text(want)


def ask_kite_credentials() -> None:
    env = read_env()
    if env.get("KITE_API_KEY") and env.get("KITE_API_SECRET"):
        return
    print("\nOne-time Kite setup. Create an app at https://developers.kite.trade (type: Connect) and set its\n"
          f"Redirect URL to: http://127.0.0.1:{API_PORT}/api/kite/callback\n"
          "Your key and secret are saved only in the file .env on this computer (never uploaded, never in the browser).\n")
    key = input("Kite API key: ").strip()
    secret = getpass.getpass("Kite API secret (hidden as you type): ").strip()
    if not key or not secret:
        die("The API key and secret are both needed for live mode. Run with --live again when you have them.")
    write_env({"KITE_API_KEY": key, "KITE_API_SECRET": secret})
    say("Saved to .env")


def telegram_setup() -> None:
    """Save your Telegram bot token and the chat id(s) in .env, then send a clearly-labelled test message.
    Run it again to add another of your own accounts: the saved token is reused."""
    import json
    import urllib.request

    def call(token: str, method: str, payload: dict | None = None) -> dict:
        req = urllib.request.Request(f"https://api.telegram.org/bot{token}/{method}",
                                     data=json.dumps(payload).encode() if payload else None,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as r:  # noqa: S310 - fixed https host
            return json.loads(r.read())

    env = read_env()
    token = env.get("TELEGRAM_BOT_TOKEN", "")
    print("\nTelegram alerts setup (alerts go only to YOUR own Telegram accounts).\n")
    if token:
        print("A bot token is already saved, so it will be reused. Chats now receiving alerts: "
              f"{env.get('TELEGRAM_CHAT_ID') or 'none'}\n")
    else:
        print("1. In Telegram, open @BotFather, send /newbot, and follow the steps. It gives you a token.\n"
              "The token is saved only in the file .env on this computer.\n")
        token = getpass.getpass("Bot token (hidden as you type): ").strip()
        if not token:
            die("No token entered.")
    print("Open your bot from EACH of your own Telegram accounts (including the new one) and press Start, or send it a message.")
    try:
        if not call(token, "getMe").get("ok"):
            die("Telegram did not accept that token. Check it and try again.")
        input("Press Enter here when you have done that... ")
        seen: dict[str, str] = {}
        for u in call(token, "getUpdates").get("result", []):
            m = u.get("message")
            if m and m["chat"].get("type") == "private":
                c = m["chat"]
                seen[str(c["id"])] = " ".join(x for x in (c.get("first_name"), c.get("last_name")) if x) or str(c["id"])
        if not seen:
            die("No message from you was found. Send a message to the bot first, then run this again.")
        print("\nChats that messaged your bot:")
        for cid, name in seen.items():
            print(f"  {name}  (id {cid})")
        if input("\nSend alerts to ALL of these chats? Only say yes if every one is you. (yes/no): ").strip().lower() not in ("y", "yes"):
            die("Nothing changed. Run this again once only your own accounts have messaged the bot.")
        ids = ",".join(seen)
        write_env({"TELEGRAM_BOT_TOKEN": token, "TELEGRAM_CHAT_ID": ids})
        for cid in seen:
            call(token, "sendMessage", {"chat_id": cid, "text": "TEST: CandleEdge alerts are connected. This is not a trade signal."})
    except OSError as e:
        die(f"Could not reach Telegram ({e}). Check your internet and try again.")
    say(f"Saved. A test message was sent to {len(seen)} chat(s). Real setup alerts will arrive there from now on (live data only).")


def port_busy(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sk:
        sk.settimeout(0.5)
        return sk.connect_ex(("127.0.0.1", port)) == 0


def wait_for(url: str, seconds: int) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        try:
            with urllib.request.urlopen(url, timeout=2):
                return True
        except Exception:  # noqa: BLE001
            time.sleep(1)
    return False


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--all-fno", action="store_true", help="with --live: watch every F&O index and stock (slow first start)")
    ap.add_argument("--live", action="store_true", help="use Zerodha Kite live data instead of the simulator")
    ap.add_argument("--telegram-setup", action="store_true", help="one-time setup of Telegram setup alerts, then exit")
    ap.add_argument("--no-browser", action="store_true", help="do not open the browser")
    ap.add_argument("--rebuild", action="store_true", help="force a rebuild of the web app")
    args = ap.parse_args()

    if args.telegram_setup:
        telegram_setup()
        return
    npm = check_tools()
    npx = shutil.which("npx") or die("npx was not found. Reinstall Node.js from nodejs.org.")
    if args.live:
        ask_kite_credentials()
    setup_backend()
    setup_frontend(npm, args.rebuild)

    for port in (API_PORT, WEB_PORT):
        if port_busy(port):
            die(f"Port {port} is already in use, so CandleEdge is probably still running in another black window. "
                "Close every CandleEdge / command window (or restart the computer) and start again.")
    LOGS.mkdir(exist_ok=True)
    (BACKEND / "data").mkdir(exist_ok=True)
    env = {**os.environ, **read_env(), "LIVE_ORDERS_ENABLED": "false",
           "PUBLIC_BACKEND_URL": f"http://127.0.0.1:{API_PORT}", "APP_URL": f"http://localhost:{WEB_PORT}",
           "CORS_ORIGINS": f"http://localhost:{WEB_PORT}", "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    if args.live:
        env.update(PROVIDER="kite", ALLOW_INSECURE_NO_AUTH="true")  # bound to 127.0.0.1 only
        if args.all_fno:
            env["WATCHLIST"] = "ALL_FNO"
            say("Watching every F&O index and stock. The first start loads history for each one and can take several minutes.")
    else:
        env.update(PROVIDER="simulator", SIM_SPEED=env.get("SIM_SPEED", "60"))
    flags = {"creationflags": 0x00000200} if os.name == "nt" else {}  # own process group so Ctrl+C is ours to handle

    say(("LIVE (Kite)" if args.live else "PRACTICE (simulated data)") + " mode. Starting…")
    api = subprocess.Popen([str(PY), "-m", "uvicorn", "stratagy.app:create_app", "--factory", "--host", "127.0.0.1",
                            "--port", str(API_PORT)], cwd=BACKEND, env=env, stdout=(LOGS / "backend.log").open("w"),
                           stderr=subprocess.STDOUT, **flags)
    web = None
    try:
        if not wait_for(f"http://127.0.0.1:{API_PORT}/api/health", 900 if args.all_fno else 60):
            die("The backend did not start. Open logs/backend.log to see why.")
        web = subprocess.Popen([npx, "next", "start", "-p", str(WEB_PORT)], cwd=FRONTEND,
                               env={**env, "BACKEND_URL": f"http://127.0.0.1:{API_PORT}"},
                               stdout=(LOGS / "frontend.log").open("w"), stderr=subprocess.STDOUT, **flags)
        if not wait_for(f"http://localhost:{WEB_PORT}", 60):
            die("The web app did not start. Open logs/frontend.log to see why.")
        url = f"http://localhost:{WEB_PORT}"
        say(f"Ready: {url}   (press Ctrl+C here to stop)")
        if args.live:
            say("In the app open the 'Provider' tab and click 'Connect Kite' once each trading day.")
        if not args.no_browser:
            webbrowser.open(url)
        while api.poll() is None and web.poll() is None:
            time.sleep(1)
        dead = "backend" if api.poll() is not None else "frontend"
        tail = (LOGS / f"{dead}.log").read_text(encoding="utf-8", errors="replace").strip().splitlines()[-15:]
        print(f"\n--- last lines of logs/{dead}.log ---\n" + "\n".join(tail) + "\n---")
        die(f"The {dead} stopped unexpectedly. Send the lines above (hide any keys) so it can be fixed.")
    except KeyboardInterrupt:
        say("Stopping…")
    finally:
        for p in (web, api):
            if p and p.poll() is None:
                p.terminate()
                try:
                    p.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    p.kill()


if __name__ == "__main__":
    main()
