/** Recorded-replay demo. The tape is produced by scripts/record_demo_tape.py from this app's own backend running on the
 * seeded SIMULATOR, so every number is simulator output, never a market price. Only enabled by NEXT_PUBLIC_DEMO=1. */
import type { RealApi } from "./api";
import { ApiError } from "./errors";
import type { AppState, ChartData } from "./types";

export const DEMO = process.env.NEXT_PUBLIC_DEMO === "1";
export const TAPES = [
  { id: 1, label: "Seed 1 · bearish day (BUY PUT setup)" },
  { id: 7, label: "Seed 7 · bullish day (BUY CALL setup)" },
] as const;

type Tape = {
  step_seconds: number; frames: any[]; candles: Record<string, ChartData>; premium: Record<string, any>; provider: any; history: any;
};
const TF_SECONDS: Record<string, number> = { "1m": 60, "3m": 180, "5m": 300, "15m": 900 };

export interface DemoStatus { tape: number; idx: number; count: number; playing: boolean; fps: number; loading: boolean; clock: string }

const store = { tape: 1, idx: 0, playing: true, fps: 1, loaded: new Map<number, Tape>(), loading: new Map<number, Promise<Tape>>(), acc: 0 };
const listeners = new Set<() => void>();
let timer: ReturnType<typeof setInterval> | null = null;

function load(id: number): Promise<Tape> {
  const have = store.loaded.get(id);
  if (have) return Promise.resolve(have);
  let p = store.loading.get(id);
  if (!p) {
    const url = new URL(`tape-${id}.json`, document.baseURI).toString();
    p = fetch(url).then((r) => {
      if (!r.ok) throw new ApiError(r.status, "Demo tape could not be loaded");
      return r.json() as Promise<Tape>;
    }).then((t) => { store.loaded.set(id, t); notify(); return t; });
    store.loading.set(id, p);
  }
  return p;
}
function notify() { listeners.forEach((l) => l()); }
function ensureTimer() {
  if (timer || typeof window === "undefined") return;
  timer = setInterval(() => {
    const t = store.loaded.get(store.tape);
    if (!t || !store.playing) return;
    store.acc += store.fps * 0.25;
    const whole = Math.floor(store.acc);
    if (whole > 0) {
      store.acc -= whole;
      store.idx = Math.min(t.frames.length - 1, store.idx + whole);
      if (store.idx >= t.frames.length - 1) store.playing = false;
      notify();
    }
  }, 250);
}
async function tape(): Promise<Tape> { ensureTimer(); return load(store.tape); }
const frameOf = (t: Tape) => t.frames[Math.min(store.idx, t.frames.length - 1)];
const nowEpoch = (f: any) => Math.floor(new Date(f.virtual_now).getTime() / 1000);

export const demoControl = {
  subscribe(fn: () => void) { listeners.add(fn); ensureTimer(); void load(store.tape); return () => { listeners.delete(fn); }; },
  status(): DemoStatus {
    const t = store.loaded.get(store.tape);
    return { tape: store.tape, idx: store.idx, count: t?.frames.length ?? 0, playing: store.playing, fps: store.fps, loading: !t,
      clock: t ? frameOf(t).virtual_now.slice(11, 16) : "" };
  },
  play(p: boolean) { if (p && store.idx >= (store.loaded.get(store.tape)?.frames.length ?? 1) - 1) store.idx = 0; store.playing = p; notify(); },
  seek(i: number) { store.idx = Math.max(0, i); store.acc = 0; notify(); },
  speed(fps: number) { store.fps = fps; notify(); },
  async choose(id: number) { store.tape = id; store.idx = 0; store.acc = 0; store.playing = true; notify(); await load(id); notify(); },
};

const readonly = (what: string) => async () => { throw new ApiError(0, `${what} is not available in the recorded demo`); };
const ok = async () => ({ ok: true });

export const demoApi: RealApi = {
  state: async () => {
    const t = await tape(); const f = frameOf(t);
    const st = f.state as AppState;
    return { ...st, simulator: { paused: !store.playing, speed: store.fps * t.step_seconds, seed: store.tape, virtual_now: f.virtual_now, sim_date: f.virtual_now.slice(0, 10) } };
  },
  candles: async (sym, tf) => {
    const t = await tape(); const f = frameOf(t); const key = `${sym}|${tf}`;
    const full = t.candles[key]; const live = f.chart[key];
    if (!full || !live) throw new ApiError(404, "unknown underlying");
    const cutoff = nowEpoch(f); const dur = TF_SECONDS[tf] ?? 300;
    const keep = <T extends { t: number }>(a: T[], width = 0) => a.filter((x) => x.t + width <= cutoff);
    return { ...full, ...live, candles: keep(full.candles, dur), ema9: keep(full.ema9, dur), ema21: keep(full.ema21, dur), ema50: keep(full.ema50, dur), vwap: keep(full.vwap, dur) };
  },
  evaluation: async (sym) => { const t = await tape(); return frameOf(t).eval[sym] ?? null; },
  chain: async (sym) => { const t = await tape(); return frameOf(t).chain[sym]; },
  signals: async () => { const t = await tape(); return frameOf(t).signals; },
  premium: async (id) => {
    const t = await tape(); const f = frameOf(t); const p = t.premium[id];
    if (!p) throw new ApiError(404, "unknown signal");
    return { ...p, series: p.series.filter((x: { ts: string }) => new Date(x.ts).getTime() <= new Date(f.virtual_now).getTime()) };
  },
  trades: async () => { const t = await tape(); return frameOf(t).trades; },
  sessionReport: async () => { const t = await tape(); return frameOf(t).report; },
  history: async () => (await tape()).history,
  provider: async () => (await tape()).provider,
  audit: async () => [],
  setRisk: ok,
  setStrategy: ok,
  setData: ok,
  pause: async (paused) => ({ paused }),
  sim: async (action, value) => {
    const t = await tape();
    if (action === "pause") demoControl.play(false);
    else if (action === "resume") demoControl.play(true);
    else if (action === "speed") demoControl.speed(Math.max(0.2, (value ?? 300) / t.step_seconds));
    else if (action === "skip") demoControl.seek(store.idx + Math.max(1, Math.round((value ?? 600) / t.step_seconds)));
    else if (action === "restart") await demoControl.choose(store.tape === 1 ? 7 : 1);
    return {};
  },
  runBacktest: readonly("Backtesting"),
  backtestJob: readonly("Backtesting"),
};
