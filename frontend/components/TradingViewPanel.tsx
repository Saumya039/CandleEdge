"use client";
import { useEffect, useRef, useState } from "react";
import { Panel } from "./ui";

const TV_SYMBOL: Record<string, string> = { NIFTY: "NSE:NIFTY", BANKNIFTY: "NSE:BANKNIFTY", FINNIFTY: "NSE:CNXFINANCE", MIDCPNIFTY: "NSE:NIFTY_MID_SELECT" };
const SRC = "https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js";

export function tvSymbol(symbol: string): string {
  return TV_SYMBOL[symbol] ?? `NSE:${symbol}`;
}

/** Opt-in TradingView reference chart. Third-party widget: its data and clock are TradingView's, never fed into
 * signals, the paper engine or risk checks, and it is not loaded until the user asks for it. */
export function TradingViewPanel({ symbol }: { symbol: string }) {
  const [open, setOpen] = useState(false);
  const host = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = host.current;
    if (!open || !el) return;
    el.innerHTML = '<div class="tradingview-widget-container__widget" style="height:100%;width:100%"></div>';
    const s = document.createElement("script");
    s.src = SRC;
    s.async = true;
    s.innerHTML = JSON.stringify({
      autosize: true, symbol: tvSymbol(symbol), interval: "5", timezone: "Asia/Kolkata", theme: "dark", style: "1",
      locale: "en", allow_symbol_change: false, hide_side_toolbar: false, withdateranges: true,
    });
    el.appendChild(s);
    return () => { el.innerHTML = ""; };
  }, [open, symbol]);

  return (
    <Panel title="TradingView reference chart" right={<button className="btn" data-testid="tv-toggle" onClick={() => setOpen((o) => !o)}>{open ? "Hide" : "Load widget"}</button>}>
      {open ? (
        <div ref={host} data-testid="tv-host" className="tradingview-widget-container h-[420px]" />
      ) : (
        <p className="px-3 py-2 text-[11px] text-muted" data-testid="tv-note">
          Optional third-party chart from TradingView, loaded only when you click. It shows TradingView&apos;s own market data
          (typically delayed for NSE without a TradingView data subscription), not this app&apos;s feed. Signals, entries, stops
          and paper trades are always computed from, and drawn on, the app&apos;s own chart above.
        </p>
      )}
    </Panel>
  );
}
