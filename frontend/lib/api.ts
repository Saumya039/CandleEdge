import type { AppState, ChainData, ChartData, Evaluation, PaperTrade, ProviderInfo, SessionReport, Signal } from "./types";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, { cache: "no-store", ...init, headers: { "content-type": "application/json", ...(init?.headers ?? {}) } });
  } catch {
    throw new ApiError(0, "Backend unreachable");
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}
const post = <T>(path: string, body: unknown) => request<T>(path, { method: "POST", body: JSON.stringify(body) });

export const api = {
  state: () => request<AppState>("/api/state"),
  candles: (sym: string, tf: string) => request<ChartData>(`/api/underlyings/${sym}/candles?tf=${tf}&limit=400`),
  evaluation: (sym: string) => request<Evaluation | null>(`/api/underlyings/${sym}/evaluation`),
  chain: (sym: string) => request<ChainData>(`/api/underlyings/${sym}/option-chain`),
  signals: () => request<Signal[]>("/api/signals"),
  premium: (id: string) =>
    request<{ contract: string; series: { ts: string; bid: number | null; ask: number | null; ltp: number | null }[]; note: string }>(`/api/signals/${id}/premium`),
  trades: () => request<PaperTrade[]>("/api/trades"),
  sessionReport: () => request<SessionReport>("/api/reports/session"),
  history: () => request<{ overall: SessionReport["summary"]; days: Record<string, SessionReport["summary"]>; health_events: { ts: string; kind: string; detail: string }[] }>("/api/reports/history"),
  provider: () => request<ProviderInfo>("/api/provider"),
  audit: () => request<{ ts: string; kind: string; detail: Record<string, unknown> }[]>("/api/audit"),
  setRisk: (b: unknown) => post("/api/settings/risk", b),
  setStrategy: (b: { trigger_tf: string; sensitivity: string }) => post("/api/settings/strategy", b),
  setData: (b: { accept_delayed: boolean }) => post("/api/settings/data", b),
  pause: (paused: boolean, reason = "manual") => post("/api/control/pause", { paused, reason }),
  sim: (action: string, value?: number) => post("/api/simulator/control", { action, value }),
  runBacktest: (sessions: number, firstSeed: number) => post<{ job: string }>("/api/backtest/run", { sessions, first_seed: firstSeed }),
  backtestJob: (id: string) => request<{ status: string; result?: Record<string, unknown>; error?: string }>(`/api/backtest/jobs/${id}`),
};
