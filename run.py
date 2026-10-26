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
    ap.add_argument("--live", action="store_true", help="use Zerodha Kite live data instead of the simulator")
    ap.add_argument("--no-browser", action="store_true", help="do not open the browser")
    ap.add_argument("--rebuild", action="store_true", help="force a rebuild of the web app")
    args = ap.parse_args()

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
    else:
        env.update(PROVIDER="simulator", SIM_SPEED=env.get("SIM_SPEED", "60"))
    flags = {"creationflags": 0x00000200} if os.name == "nt" else {}  # own process group so Ctrl+C is ours to handle

    say(("LIVE (Kite)" if args.live else "PRACTICE (simulated data)") + " mode. Starting…")
    api = subprocess.Popen([str(PY), "-m", "uvicorn", "stratagy.app:create_app", "--factory", "--host", "127.0.0.1",
                            "--port", str(API_PORT)], cwd=BACKEND, env=env, stdout=(LOGS / "backend.log").open("w"),
                           stderr=subprocess.STDOUT, **flags)
    web = None
    try:
        if not wait_for(f"http://127.0.0.1:{API_PORT}/api/health", 60):
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
