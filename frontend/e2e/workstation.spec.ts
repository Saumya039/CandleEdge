import { expect, test, type Page } from "@playwright/test";

const API = "http://localhost:8765";

async function sim(page: Page, action: string, value?: number) {
  const r = await page.request.post(`${API}/api/simulator/control`, { data: { action, value } });
  expect(r.ok()).toBeTruthy();
}
const restart = (page: Page, seed = 1) => sim(page, "restart", seed);

test.describe.configure({ mode: "serial" });

test("no-data state: backend unreachable shows no fabricated prices", async ({ page }) => {
  await page.route("**/api/**", (r) => r.abort());
  await page.goto("/");
  await expect(page.getByTestId("no-data")).toBeVisible();
  await expect(page.getByTestId("status-bar")).toContainText("NO DATA");
  await expect(page.getByTestId("watchlist")).toHaveCount(0);
});

test("simulated mode is unmistakable and never says LIVE", async ({ page }) => {
  await restart(page);
  await page.goto("/");
  await expect(page.getByTestId("sim-banner")).toContainText("NOT market data");
  await expect(page.getByTestId("session-badge")).toHaveText("SIMULATION");
  await expect(page.getByTestId("session-badge")).not.toHaveText("LIVE");
  await expect(page.getByTestId("risk-unconfirmed")).toBeVisible();
  await expect(page.getByTestId("disclaimer")).toContainText("Live order placement is disabled");
  await expect(page.getByTestId("ist-clock")).toHaveText(/\d\d:\d\d:\d\d/);
});

test("risk settings must be confirmed; pause works", async ({ page }) => {
  await restart(page);
  await page.goto("/");
  await page.getByTestId("tab-settings").click();
  await expect(page.getByTestId("risk-confirmed-tag")).toHaveText("NOT CONFIRMED");
  await page.getByTestId("risk-save").click();
  await expect(page.getByTestId("risk-confirmed-tag")).toHaveText("CONFIRMED");
  await expect(page.getByTestId("risk-unconfirmed")).toHaveCount(0);
  await page.getByTestId("pause-btn").click();
  await expect(page.getByTestId("pause-banner")).toBeVisible();
  await page.getByTestId("pause-btn").click();
  await expect(page.getByTestId("pause-banner")).toHaveCount(0);
});

test("chart renders, timeframe switches, legend shows OHLC on hover", async ({ page }) => {
  await restart(page);
  await sim(page, "skip", 70 * 60); // 10:10
  await page.goto("/");
  await expect(page.getByTestId("price-chart").locator("canvas").first()).toBeVisible();
  await expect(page.getByTestId("chart-empty")).toHaveCount(0);
  await page.getByTestId("tf-15m").click();
  await expect(page.getByTestId("tf-15m")).toHaveAttribute("aria-pressed", "true");
  const box = await page.getByTestId("price-chart").boundingBox();
  await page.mouse.move(box!.x + box!.width / 2, box!.y + box!.height / 2);
  await expect(page.getByTestId("chart-legend")).toContainText(/O .* H .* L .* C .* Vol/);
  await expect(page.getByTestId("chart-legend")).toContainText("IST");
  await expect(page.getByTestId("wl-NIFTY")).not.toContainText("Unavailable");
});

test("candidate -> paper trade is explained, journaled, and labelled simulated", async ({ page }) => {
  await restart(page);
  await page.goto("/");
  await page.getByTestId("tab-settings").click();
  if ((await page.getByTestId("risk-confirmed-tag").textContent()) !== "CONFIRMED") await page.getByTestId("risk-save").click();
  await expect(page.getByTestId("risk-confirmed-tag")).toHaveText("CONFIRMED");
  await sim(page, "skip", 55 * 60); // seed 1 produces a BANKNIFTY put at 09:30
  const popup = page.getByTestId("signal-popup");
  await expect(popup).toBeVisible({ timeout: 15000 });
  await expect(popup).toContainText("no order has been or will be sent");
  await popup.getByRole("button", { name: "Dismiss alert" }).click();
  await expect(popup).toHaveCount(0);
  await page.getByTestId("wl-BANKNIFTY").getByRole("button").click();
  const card = page.getByTestId("signal-card");
  await expect(card).toBeVisible({ timeout: 15000 });
  await expect(card).toContainText("BUY PUT");
  await expect(card).toContainText("SIMULATED");
  await expect(page.getByTestId("rationale")).toContainText("Regime");
  await expect(page.getByTestId("entry-zone")).toContainText("–");
  await expect(page.getByTestId("lifecycle")).toContainText("CANDIDATE");
  await page.getByTestId("tab-journal").click();
  await expect(page.getByTestId("trade-journal")).toContainText("BANKNIFTY");
  await expect(page.getByTestId("signal-ledger")).toContainText("BUY PUT");
  await expect(page.getByText("PAPER · simulated fills")).toBeVisible();
  await page.getByTestId("tab-chain").click();
  await expect(page.getByTestId("chain-table")).toBeVisible();
  await page.getByTestId("tab-scan").click();
  await expect(page.getByTestId("scan-table")).toContainText("BUY PUT");
});

test("feed outage shows a prominent stale warning and suppresses signals; recovery clears it", async ({ page }) => {
  await restart(page, 9);
  await page.goto("/");
  await sim(page, "skip", 45 * 60);
  await sim(page, "outage", 300);
  await sim(page, "skip", 200);
  await expect(page.getByTestId("stale-banner")).toBeVisible({ timeout: 10000 });
  await expect(page.getByTestId("session-badge")).toHaveText("STALE DATA");
  await page.getByTestId("tab-scan").click();
  await sim(page, "skip", 600);
  await expect(page.getByTestId("stale-banner")).toHaveCount(0, { timeout: 10000 });
  await expect(page.getByTestId("session-badge")).toHaveText("SIMULATION");
});

test("mobile layout has no horizontal page scroll", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await restart(page);
  await sim(page, "skip", 60 * 60);
  await page.goto("/");
  await expect(page.getByTestId("watchlist")).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});
