# Deploying CandleEdge privately for live data

This puts the real app (not the replay demo) on one server that you control, behind HTTPS and a password. It only
reads market data and paper trades. It cannot place orders.

## What you need
1. **A small Linux server with a static public IP.** Any VPS works (1 vCPU, 2 GB RAM is enough). Kite requires the
   whitelisted IP to be static and used only by you or your immediate family. Note the server's IPv4 address.
2. **A domain or subdomain** whose DNS "A" record points at that IP. HTTPS needs a name. A free subdomain from a
   dynamic-DNS service also works if it points at your server's static IP.
3. **Your Kite Connect app**: API key, API secret (secret stays with you), redirect URL `http://127.0.0.1:5000/`.
4. **The static IP entered in your Kite profile's IP whitelist.**
5. **Docker and Docker Compose** installed on the server.

## One-time setup (on the server)
```bash
git clone https://github.com/Saumya039/CandleEdge && cd CandleEdge
git checkout claude/nse-fno-workstation      # until the PR is merged
python3 scripts/hash_password.py              # choose a long password; prints AUTH_PASSWORD_HASH and AUTH_SECRET
cp .env.prod.example .env.prod && nano .env.prod
mkdir -p data && nano data/exchange_calendar.json   # NSE holidays, format in README
```
In `.env.prod` set `SITE_ADDRESS`, `POSTGRES_PASSWORD` (long random), `KITE_API_KEY`, and paste the two AUTH values
(keep the quotes around the hash). Leave `KITE_ACCESS_TOKEN` empty for now. Open ports 80 and 443 in the server firewall.

## Every trading day (before 09:15 IST)
Kite tokens expire daily, and the login needs you (password and 2FA), so this step is manual by design.
1. Open `https://kite.zerodha.com/connect/login?v=3&api_key=YOUR_API_KEY`, log in, and copy `request_token=...` from the
   address bar of the page you land on (it shows an error page; that is expected).
2. On any machine: `KITE_API_KEY=... KITE_API_SECRET=... python scripts/kite_login.py REQUEST_TOKEN`
3. Put the printed value in `.env.prod` as `KITE_ACCESS_TOKEN=...`, then on the server:
   `docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build` (first time) or
   `docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --force-recreate backend` (daily).
4. Visit `https://your-domain`, sign in, and open **Provider**. It must show LIVE with a fresh last-tick time. If it shows
   anything else, signals stay suppressed by design.

## Checks and safety
- `curl https://your-domain/api/state` without signing in must return `401`.
- The app refuses to start with a live provider and no login, unless you set `ALLOW_INSECURE_NO_AUTH=true`.
- Login is limited to 8 attempts a minute across all clients. Someone hammering the login page can briefly lock you
  out, but cannot get in without the password.
- Keep paper trading on. Do not place real trades from signals until the compliance review in `docs/COMPLIANCE.md`
  and several weeks of forward paper results justify it.
- Back up the Postgres volume if you care about your journal. Update with `git pull` then `up -d --build`.

## Not covered
Docker images and this compose file were written but not built in the authoring environment (no Docker daemon). Expect
to fix small things on the first build, and send me the error text (never your secret or tokens).
