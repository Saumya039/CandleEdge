import { defineConfig } from "@playwright/test";

const BACKEND_PORT = 8765;
const FRONT_PORT = 3100;

export default defineConfig({
  testDir: "./e2e",
  timeout: 90_000,
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: { baseURL: `http://localhost:${FRONT_PORT}`, trace: "retain-on-failure", viewport: { width: 1440, height: 900 } },
  webServer: [
    {
      // deterministic SIMULATED session: pinned date + seed, virtual clock effectively frozen (tests drive it via /skip)
      command: `rm -f /tmp/stratagy-e2e.db && ../backend/.venv/bin/python -m uvicorn stratagy.app:create_app --factory --port ${BACKEND_PORT}`,
      cwd: "../backend",
      url: `http://localhost:${BACKEND_PORT}/api/health`,
      reuseExistingServer: false,
      env: { PROVIDER: "simulator", SIM_SEED: "1", SIM_DATE: "2026-10-23", SIM_SPEED: "1", DATABASE_URL: "sqlite:////tmp/stratagy-e2e.db" },
      timeout: 60_000,
    },
    {
      command: `BACKEND_URL=http://localhost:${BACKEND_PORT} npx next build && BACKEND_URL=http://localhost:${BACKEND_PORT} npx next start -p ${FRONT_PORT}`,
      url: `http://localhost:${FRONT_PORT}`,
      reuseExistingServer: false,
      timeout: 240_000,
    },
  ],
});
