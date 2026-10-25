"use client";
import dynamic from "next/dynamic";
import { useCallback, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { usePoll } from "@/lib/usePoll";
import type { Signal } from "@/lib/types";
import type { VisibleRange } from "@/components/PriceChart";
import { StatusBar } from "@/components/StatusBar";
import { Watchlist } from "@/components/Watchlist";
import { NoTradePanel, SignalCard } from "@/components/SignalCard";
import { RiskPanel, StrategyPanel } from "@/components/RiskPanel";
import { ScanPanel } from "@/components/ScanPanel";
import { OptionChain } from "@/components/OptionChain";
import { Journal } from "@/components/Journal";
import { Reports } from "@/components/Reports";
import { ProviderPanel } from "@/components/ProviderPanel";
import { SimControls } from "@/components/SimControls";
import { Alerts } from "@/components/Alerts";
import { Panel } from "@/components/ui";
import { DemoBar } from "@/components/DemoBar";
import { DEMO } from "@/lib/demo";

const PriceChart = dynamic(() => import("@/components/PriceChart").then((m) => m.PriceChart), { ssr: false, loading: () => <Panel title="Chart"><div className="h-[420px]" /></Panel> });
const TradingViewPanel = dynamic(() => import("@/components/TradingViewPanel").then((m) => m.TradingViewPanel), { ssr: false });
const PremiumChart = dynamic(() => import("@/components/PremiumChart").then((m) => m.PremiumChart), { ssr: false });

const TABS = [
  ["scan", "Scan"], ["chain", "Option chain"], ["journal", "Journal"], ["reports", "Reports & backtest"], ["settings", "Risk & settings"], ["provider", "Provider"],
] as const;
type Tab = (typeof TABS)[number][0];

export default function Page() {
  const state = usePoll(api.state, 1000);
  const s = state.data;
  const [symChoice, setSym] = useState<string>("");
  const sym = symChoice || (s?.watchlist[0]?.symbol ?? "");
  const [tf, setTf] = useState("5m");
  const [tab, setTab] = useState<Tab>("scan");
  const [pinned, setPinned] = useState<string | null>(null);
  const [range, setRange] = useState<VisibleRange>(null);


  const chart = usePoll(() => api.candles(sym, tf), 2000, !!sym, [sym, tf]);
  const evalr = usePoll(() => api.evaluation(sym), 2000, !!sym, [sym]);
  const signals = usePoll(api.signals, 2500);
  const chain = usePoll(() => api.chain(sym), 3000, !!sym && (tab === "chain"), [sym, tab]);

  const sigs: Signal[] = useMemo(() => signals.data ?? [], [signals.data]);
  const selected: Signal | null = useMemo(() => {
    if (pinned) { const p = sigs.find((x) => x.id === pinned); if (p) return p; }
    const mine = sigs.filter((x) => x.underlying === sym);
    return mine.find((x) => !x.closed) ?? mine[0] ?? null;
  }, [sigs, pinned, sym]);

  const refresh = useCallback(() => { state.refresh(); signals.refresh(); evalr.refresh(); }, [state, signals, evalr]);
  const onSelect = useCallback((id: string, und: string) => { setPinned(id); setSym(und); }, []);
  const onPause = useCallback((p: boolean) => { void api.pause(p).then(refresh); }, [refresh]);

  return (
    <main className="mx-auto flex w-full max-w-[1800px] min-w-0 flex-col gap-3 p-3">
      {DEMO && <DemoBar />}
      <StatusBar s={s} error={state.error} onPause={onPause} />
      {!s && !state.loading && (
        <Panel title="No data"><p className="p-4 text-muted" data-testid="no-data">The backend is not reachable, so there is nothing to show. No placeholder prices are displayed. Start the API (see README) and this page will fill in.</p></Panel>
      )}
      {s && (
        <>
          <div className="grid grid-cols-[minmax(0,1fr)] gap-3 xl:grid-cols-[320px_minmax(0,1fr)_400px]">
            <div className="flex min-w-0 flex-col gap-3">
              <Watchlist rows={s.watchlist} selected={sym} onSelect={(x) => { setSym(x); setPinned(null); }} />
              <Alerts alerts={s.alerts} />
              <SimControls s={s} onChanged={refresh} />
            </div>
            <div className="flex min-w-0 flex-col gap-3">
              <PriceChart symbol={sym} tf={tf} onTf={setTf} data={chart.data?.symbol === sym ? chart.data : null} signal={selected} onRange={setRange} error={chart.error} />
              <PremiumChart signal={selected} range={range} />
              <TradingViewPanel symbol={sym} />
            </div>
            <div className="flex min-w-0 flex-col gap-3">
              {selected && selected.underlying === sym ? <SignalCard signal={selected} /> : <NoTradePanel ev={evalr.data ?? null} symbol={sym} />}
              {selected && selected.closed && <NoTradePanel ev={evalr.data ?? null} symbol={sym} />}
            </div>
          </div>
          <nav className="flex flex-wrap gap-1" role="tablist" aria-label="Workspace sections">
            {TABS.map(([k, label]) => (
              <button key={k} role="tab" aria-selected={tab === k} className={`btn ${tab === k ? "btn-primary" : ""}`} onClick={() => setTab(k)} data-testid={`tab-${k}`}>{label}</button>
            ))}
          </nav>
          <div role="tabpanel">
            {tab === "scan" && <ScanPanel state={s} signals={sigs} onSelect={onSelect} />}
            {tab === "chain" && <OptionChain data={chain.data} error={chain.error} symbol={sym} />}
            {tab === "journal" && <Journal onSelect={onSelect} />}
            {tab === "reports" && <Reports />}
            {tab === "settings" && <div className="grid gap-3 lg:grid-cols-2"><RiskPanel s={s} onChanged={refresh} /><StrategyPanel s={s} onChanged={refresh} /></div>}
            {tab === "provider" && <ProviderPanel />}
          </div>
          <footer className="px-1 pb-4 text-[11px] text-muted" data-testid="disclaimer">
            {s.disclaimer} Live order placement is <b>disabled</b> and not implemented. Times are Asia/Kolkata. <a className="underline" href="#privacy" onClick={(e) => e.preventDefault()}>Privacy policy (placeholder)</a>
          </footer>
        </>
      )}
    </main>
  );
}
