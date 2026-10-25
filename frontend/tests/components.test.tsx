import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { StatusBar } from "@/components/StatusBar";
import { Watchlist } from "@/components/Watchlist";
import { NoTradePanel, SignalCard } from "@/components/SignalCard";
import { ScanPanel } from "@/components/ScanPanel";
import { appState, signal, watchRow } from "./fixtures";

describe("StatusBar", () => {
  it("shows the no-data state without inventing values", () => {
    render(<StatusBar s={null} error="Backend unreachable" onPause={() => {}} />);
    expect(screen.getByText("NO DATA")).toBeInTheDocument();
  });
  it("labels simulation clearly and never says LIVE", () => {
    render(<StatusBar s={appState()} error={null} onPause={() => {}} />);
    expect(screen.getByTestId("session-badge")).toHaveTextContent("SIMULATION");
    expect(screen.getByTestId("sim-banner")).toHaveTextContent(/NOT market data/);
    expect(screen.queryByText("LIVE")).not.toBeInTheDocument();
  });
  it("shows a prominent warning when data is stale and when the backend is lost", () => {
    render(<StatusBar s={appState({ stale: true, badge: "STALE DATA" })} error="Backend unreachable" onPause={() => {}} />);
    expect(screen.getByTestId("stale-banner")).toHaveTextContent(/suppressed/);
    expect(screen.getByTestId("api-error")).toHaveTextContent(/Cannot reach the backend/);
    expect(screen.getByTestId("session-badge")).toHaveTextContent("STALE DATA");
  });
  it("explains missing credentials instead of faking a feed", () => {
    const s = appState();
    s.data = { ...s.data, is_simulated: false, status: "UNAVAILABLE", connected: false, start_error: "Missing credentials: KITE_API_KEY", missing_credentials: ["KITE_API_KEY", "KITE_ACCESS_TOKEN"] };
    s.badge = "MARKET CLOSED";
    render(<StatusBar s={s} error={null} onPause={() => {}} />);
    expect(screen.getByTestId("provider-error")).toHaveTextContent("KITE_ACCESS_TOKEN");
    expect(screen.queryByTestId("sim-banner")).not.toBeInTheDocument();
  });
  it("pause button toggles and warns when risk is unconfirmed", () => {
    const onPause = vi.fn();
    const s = appState();
    s.risk_settings.confirmed = false;
    render(<StatusBar s={s} error={null} onPause={onPause} />);
    expect(screen.getByTestId("risk-unconfirmed")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("pause-btn"));
    expect(onPause).toHaveBeenCalledWith(true);
  });
  it("shows the pause banner when paused", () => {
    const s = appState();
    s.risk_state.paused = true; s.risk_state.pause_reason = "lunch";
    render(<StatusBar s={s} error={null} onPause={() => {}} />);
    expect(screen.getByTestId("pause-banner")).toHaveTextContent("lunch");
  });
});

describe("Watchlist", () => {
  it("renders Unavailable for missing LTP and selects on click", () => {
    const onSelect = vi.fn();
    render(<Watchlist rows={appState().watchlist} selected="NIFTY" onSelect={onSelect} />);
    const bn = within(screen.getByTestId("wl-BANKNIFTY"));
    expect(bn.getAllByText("Unavailable").length).toBeGreaterThan(0);
    fireEvent.click(within(screen.getByTestId("wl-BANKNIFTY")).getByRole("button"));
    expect(onSelect).toHaveBeenCalledWith("BANKNIFTY");
  });
});

describe("SignalCard / NoTradePanel", () => {
  it("shows the complete explainable plan", () => {
    render(<SignalCard signal={signal()} />);
    const card = screen.getByTestId("signal-card");
    expect(card).toHaveTextContent("BUY CALL");
    expect(screen.getByTestId("entry-zone")).toHaveTextContent("24,500.00 – 24,511.00");
    expect(screen.getByTestId("rr")).toHaveTextContent("2.30 / 3.90");
    expect(screen.getByTestId("rationale")).toHaveTextContent("BREAKOUT");
    expect(card).toHaveTextContent(/not a probability/);
    expect(card).toHaveTextContent(/stop is not guaranteed to fill/);
    expect(card).toHaveTextContent("SIMULATED");
  });
  it("renders NO TRADE with reasons and failing gates", () => {
    render(<NoTradePanel symbol="NIFTY" ev={{
      underlying: "NIFTY", ts: "", strategy_version: "v", trigger_tf: "5m", decision: "NO_TRADE", direction: null, htf_regime: null,
      regime: { regime: "RANGE_CHOP", reasons: [], adx: 14, atr_pct: 0.1, rsi: 50 }, reasons: ["tick_fresh: Last underlying tick 60s ago"],
      checks: [{ name: "tick_fresh", passed: false, detail: "60s" }, { name: "calendar", passed: true, detail: "ok" }], score: null, score_components: [], indicators: {}, levels: {},
    }} />);
    expect(screen.getByTestId("decision-tag")).toHaveTextContent("NO TRADE");
    expect(screen.getByTestId("no-trade-reasons")).toHaveTextContent("tick_fresh");
  });
  it("handles missing evaluation", () => {
    render(<NoTradePanel symbol="NIFTY" ev={null} />);
    expect(screen.getByText(/No evaluation yet/)).toBeInTheDocument();
  });
});

describe("ScanPanel", () => {
  it("ranks by score and filters by direction and R:R", () => {
    const a = signal({ id: "a", score: 60 });
    const b = signal({ id: "b", score: 80, direction: "BUY_PUT" });
    const c = signal({ id: "c", score: 70 });
    c.plan = { ...c.plan, rr_t1: 1.6 };
    render(<ScanPanel state={appState({ watchlist: [watchRow({ symbol: "NIFTY", decision: "CANDIDATE" })] })} signals={[a, b, c]} onSelect={() => {}} />);
    const ids = screen.getAllByTestId(/^scan-(a|b|c)$/).map((r) => r.getAttribute("data-testid"));
    expect(ids).toEqual(["scan-b", "scan-c", "scan-a"]);
    fireEvent.change(screen.getByTestId("scan-type"), { target: { value: "BUY_PUT" } });
    expect(screen.getAllByTestId(/^scan-(a|b|c)$/)).toHaveLength(1);
  });
  it("lists NO TRADE rows with their reason", () => {
    render(<ScanPanel state={appState()} signals={[]} onSelect={() => {}} />);
    expect(screen.getByTestId("scan-nt-NIFTY")).toHaveTextContent("Trend present but no trigger");
  });
});
