"use client";
import {
  CandlestickSeries, ColorType, CrosshairMode, HistogramSeries, LineSeries, LineStyle, createChart, createSeriesMarkers,
  type IChartApi, type IPriceLine, type ISeriesApi, type ISeriesMarkersPluginApi, type SeriesMarker, type Time, type UTCTimestamp,
} from "lightweight-charts";
import { useEffect, useMemo, useRef, useState } from "react";
import type { ChartData, Signal } from "@/lib/types";
import { dirLabel, istDateTime, istHM, num } from "@/lib/format";
import { Panel, SimTag } from "./ui";

const TFS = ["1m", "3m", "5m", "15m"] as const;
export type VisibleRange = { from: number; to: number } | null;

const COLORS = { up: "#2bb5a0", down: "#f06461", text: "#93a0b0", grid: "#18202a", ema9: "#f2b84b", ema21: "#6cb2ff", ema50: "#c19bff", vwap: "#e8e8e8" };

function snapToBar(times: number[], t: number): number | null {
  // marker times must land on an existing bar: use the last bar starting at or before t
  let lo = 0, hi = times.length - 1, ans = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (times[mid] <= t) { ans = mid; lo = mid + 1; } else hi = mid - 1;
  }
  return ans >= 0 ? times[ans] : null;
}

const MARKER_STYLE: Record<string, { shape: "arrowUp" | "arrowDown" | "circle" | "square"; color: string; text: string }> = {
  CANDIDATE: { shape: "arrowUp", color: "#6cb2ff", text: "candidate" },
  TRIGGERED: { shape: "circle", color: "#f2b84b", text: "paper entry" },
  TARGET_1: { shape: "square", color: "#2bb5a0", text: "T1" },
  TARGET_2: { shape: "square", color: "#2bb5a0", text: "T2" },
  STOPPED: { shape: "square", color: "#f06461", text: "stopped" },
  INVALIDATED: { shape: "square", color: "#93a0b0", text: "invalidated" },
  EXPIRED: { shape: "square", color: "#93a0b0", text: "expired" },
  TIME_EXIT: { shape: "square", color: "#f2b84b", text: "time exit" },
};

export function PriceChart({
  symbol, tf, onTf, data, signal, onRange, error,
}: {
  symbol: string; tf: string; onTf: (t: string) => void; data: ChartData | null; signal: Signal | null;
  onRange: (r: VisibleRange) => void; error: string | null;
}) {
  const host = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const lineRefs = useRef<Record<string, ISeriesApi<"Line">>>({});
  const markersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  const priceLines = useRef<IPriceLine[]>([]);
  const fitted = useRef<string>("");
  const [legend, setLegend] = useState<string>("");
  const lookup = useRef<{ ema9: Map<number, number>; ema21: Map<number, number>; ema50: Map<number, number>; vwap: Map<number, number>; vol: Map<number, number> }>({
    ema9: new Map(), ema21: new Map(), ema50: new Map(), vwap: new Map(), vol: new Map(),
  });
  const onRangeRef = useRef(onRange);
  useEffect(() => { onRangeRef.current = onRange; });

  useEffect(() => {
    if (!host.current) return;
    const chart = createChart(host.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "#10151c" }, textColor: COLORS.text, fontFamily: "ui-monospace, Menlo, monospace", fontSize: 11 },
      grid: { vertLines: { color: COLORS.grid }, horzLines: { color: COLORS.grid } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: "#212b37" },
      timeScale: { borderColor: "#212b37", timeVisible: true, secondsVisible: false, tickMarkFormatter: (t: Time) => istHM(t as number) },
      localization: { timeFormatter: (t: Time) => istDateTime(t as number) },
    });
    const candles = chart.addSeries(CandlestickSeries, {
      upColor: COLORS.up, downColor: COLORS.down, borderUpColor: COLORS.up, borderDownColor: COLORS.down, wickUpColor: COLORS.up, wickDownColor: COLORS.down,
    });
    const vol = chart.addSeries(HistogramSeries, { priceFormat: { type: "volume" }, priceScaleId: "vol", lastValueVisible: false, priceLineVisible: false });
    chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    const mk = (color: string, width: 1 | 2 = 1) => chart.addSeries(LineSeries, { color, lineWidth: width, lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false });
    lineRefs.current = { ema9: mk(COLORS.ema9), ema21: mk(COLORS.ema21), ema50: mk(COLORS.ema50), vwap: mk(COLORS.vwap, 2) };
    markersRef.current = createSeriesMarkers(candles, []);
    chartRef.current = chart;
    candleRef.current = candles;
    volRef.current = vol;

    chart.subscribeCrosshairMove((p) => {
      const c = p.seriesData.get(candles) as { open: number; high: number; low: number; close: number } | undefined;
      if (!p.time || !c) { setLegend(""); return; }
      const t = p.time as number;
      const g = (m: Map<number, number>) => (m.has(t) ? num(m.get(t)!) : "n/a");
      const L = lookup.current;
      setLegend(`${istDateTime(t)}  O ${num(c.open)}  H ${num(c.high)}  L ${num(c.low)}  C ${num(c.close)}  Vol ${L.vol.has(t) ? Math.round(L.vol.get(t)!).toLocaleString("en-IN") : "n/a"}  EMA9 ${g(L.ema9)}  EMA21 ${g(L.ema21)}  EMA50 ${g(L.ema50)}  VWAP ${g(L.vwap)}`);
    });
    chart.timeScale().subscribeVisibleTimeRangeChange((r) => onRangeRef.current(r ? { from: r.from as number, to: r.to as number } : null));
    return () => { chart.remove(); chartRef.current = null; };
  }, []);

  useEffect(() => {
    const chart = chartRef.current, candles = candleRef.current;
    if (!chart || !candles) return;
    if (!data) {
      // Another market's candles must never stay on screen under this market's title: clear until its own data arrives.
      candles.setData([]);
      volRef.current?.setData([]);
      Object.values(lineRefs.current).forEach((l) => l.setData([]));
      priceLines.current.forEach((l) => candles.removePriceLine(l));
      priceLines.current = [];
      markersRef.current?.setMarkers([]);
      fitted.current = "";
      return;
    }
    candles.setData(data.candles.map((c) => ({ time: c.t as UTCTimestamp, open: c.o, high: c.h, low: c.l, close: c.c })));
    volRef.current?.setData(data.candles.map((c) => ({ time: c.t as UTCTimestamp, value: c.v, color: c.c >= c.o ? "rgba(43,181,160,.35)" : "rgba(240,100,97,.35)" })));
    const setLine = (key: "ema9" | "ema21" | "ema50" | "vwap") => {
      const pts = data[key];
      lookup.current[key] = new Map(pts.filter((p) => p.v !== null).map((p) => [p.t, p.v as number]));
      lineRefs.current[key]?.setData(pts.map((p) => (p.v === null ? { time: p.t as UTCTimestamp } : { time: p.t as UTCTimestamp, value: p.v })));
    };
    (["ema9", "ema21", "ema50", "vwap"] as const).forEach(setLine);
    lookup.current.vol = new Map(data.candles.map((c) => [c.t, c.v]));

    // horizontal levels: opening range, support/resistance, active trade plan
    priceLines.current.forEach((l) => candles.removePriceLine(l));
    priceLines.current = [];
    const add = (price: number | null | undefined, color: string, title: string, style: LineStyle = LineStyle.Dashed, width: 1 | 2 = 1, label = true) => {
      if (price === null || price === undefined) return;
      priceLines.current.push(candles.createPriceLine({ price, color, lineWidth: width, lineStyle: style, axisLabelVisible: label, title: label ? title : "" }));
    };
    add(data.opening_range.high, "#f2b84b", data.opening_range.complete ? "OR high" : "OR high (forming)", LineStyle.Dotted);
    add(data.opening_range.low, "#f2b84b", data.opening_range.complete ? "OR low" : "OR low (forming)", LineStyle.Dotted);
    data.levels.forEach((l) => add(l.price, "#5b6878", l.name, LineStyle.SparseDotted, 1, l.name.includes("swing")));
    const plan = signal && signal.underlying === data.symbol ? signal.plan : null;
    if (plan) {
      add(plan.entry_zone_underlying[0], "#6cb2ff", "entry zone lo");
      add(plan.entry_zone_underlying[1], "#6cb2ff", "entry zone hi");
      add(plan.invalidation_underlying, "#f06461", "invalidation", LineStyle.Solid, 2);
      add(plan.target1_underlying, "#2bb5a0", "target 1", LineStyle.Solid);
      add(plan.target2_underlying, "#2bb5a0", "target 2", LineStyle.Dashed);
    }

    const times = data.candles.map((c) => c.t);
    const ms: SeriesMarker<Time>[] = [];
    for (const m of data.markers) {
      const bar = snapToBar(times, m.t);
      if (bar === null) continue;
      const st = MARKER_STYLE[m.state];
      if (!st) continue;
      const call = m.direction === "BUY_CALL";
      ms.push({
        time: bar as UTCTimestamp, shape: m.state === "CANDIDATE" ? (call ? "arrowUp" : "arrowDown") : st.shape,
        position: m.state === "CANDIDATE" ? (call ? "belowBar" : "aboveBar") : call ? "belowBar" : "aboveBar", color: st.color,
        text: m.state === "CANDIDATE" ? `${call ? "BUY CALL" : "BUY PUT"} candidate` : st.text,
      });
    }
    ms.sort((a, b) => (a.time as number) - (b.time as number));
    markersRef.current?.setMarkers(ms);

    const key = `${data.symbol}:${data.timeframe}`;
    if (fitted.current !== key && data.candles.length) {
      fitted.current = key;
      const n = data.candles.length;
      chart.timeScale().setVisibleLogicalRange({ from: Math.max(n - 90, 0), to: n + 6 });
    }
  }, [data, signal]);

  const lastPriceInfo = useMemo(() => (data?.candles.length ? data.candles[data.candles.length - 1] : null), [data]);

  return (
    <Panel
      title={<span>{symbol} · underlying · closed candles only</span>}
      right={
        <>
          {data && (data.label === "SIMULATED" ? <SimTag /> : <span className="tag text-up border-up/60">{data.label}</span>)}
          <div role="group" aria-label="Timeframe" className="flex gap-1">
            {TFS.map((t) => (
              <button key={t} className={`btn ${t === tf ? "btn-primary" : ""}`} onClick={() => onTf(t)} aria-pressed={t === tf} data-testid={`tf-${t}`}>{t}</button>
            ))}
          </div>
        </>
      }
    >
      <div className="relative">
        <div ref={host} className="h-[420px] w-full" data-testid="price-chart" />
        <div className="pointer-events-none absolute left-2 top-1 max-w-[95%] rounded bg-panel/80 px-1 text-[11px] text-muted num" aria-live="off" data-testid="chart-legend">
          {legend || (lastPriceInfo ? `Last closed ${tf} bar ${istDateTime(lastPriceInfo.t)}  C ${num(lastPriceInfo.c)}` : "")}
        </div>
        {!data && <div className="absolute inset-0 grid place-items-center text-muted" data-testid="chart-empty">{error ? `No chart data: ${error}` : "Loading candles…"}</div>}
        {data && data.candles.length === 0 && <div className="absolute inset-0 grid place-items-center text-muted" data-testid="chart-empty">No closed candles yet. Nothing is drawn until the feed delivers real or clearly simulated data.</div>}
      </div>
      <div className="flex flex-wrap items-center gap-3 border-t border-line px-3 py-1.5 text-[11px] text-muted">
        <span><i className="mr-1 inline-block h-[2px] w-4 align-middle" style={{ background: COLORS.ema9 }} />EMA9</span>
        <span><i className="mr-1 inline-block h-[2px] w-4 align-middle" style={{ background: COLORS.ema21 }} />EMA21</span>
        <span><i className="mr-1 inline-block h-[2px] w-4 align-middle" style={{ background: COLORS.ema50 }} />EMA50</span>
        <span><i className="mr-1 inline-block h-[2px] w-4 align-middle" style={{ background: COLORS.vwap }} />VWAP (daily reset; unavailable without volume)</span>
        <span className="text-amber">- - OR high/low</span>
        {signal && <span>Plan lines: {dirLabel(signal.direction)} {signal.id.split("-").slice(-2).join("-")}</span>}
        <span className="ml-auto">Times shown in IST</span>
      </div>
    </Panel>
  );
}
