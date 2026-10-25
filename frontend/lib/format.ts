const TZ = "Asia/Kolkata";

const timeFmt = new Intl.DateTimeFormat("en-GB", { timeZone: TZ, hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
const hmFmt = new Intl.DateTimeFormat("en-GB", { timeZone: TZ, hour: "2-digit", minute: "2-digit", hour12: false });
const dateTimeFmt = new Intl.DateTimeFormat("en-GB", {
  timeZone: TZ, day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
});

/** All user-visible times are Asia/Kolkata, never the browser's local zone. */
export const istTime = (iso: string | number | null | undefined): string => {
  if (iso === null || iso === undefined) return "—";
  const d = typeof iso === "number" ? new Date(iso * 1000) : new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : timeFmt.format(d);
};
export const istHM = (epochSeconds: number): string => hmFmt.format(new Date(epochSeconds * 1000));
export const istDateTime = (epochSeconds: number): string => dateTimeFmt.format(new Date(epochSeconds * 1000)) + " IST";

export const num = (v: number | null | undefined, d = 2): string =>
  v === null || v === undefined || Number.isNaN(v) ? "Unavailable" : v.toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d });
export const rupees = (v: number | null | undefined, d = 0): string =>
  v === null || v === undefined || Number.isNaN(v) ? "Unavailable" : `${v < 0 ? "-" : ""}₹${Math.abs(v).toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d })}`;
export const pct = (v: number | null | undefined, d = 2): string =>
  v === null || v === undefined || Number.isNaN(v) ? "Unavailable" : `${v > 0 ? "+" : ""}${v.toFixed(d)}%`;
export const compact = (v: number | null | undefined): string =>
  v === null || v === undefined ? "Unavailable" : Intl.NumberFormat("en-IN", { notation: "compact", maximumFractionDigits: 1 }).format(v);

export const countdown = (seconds: number): string => {
  const s = Math.max(0, Math.round(seconds));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
  return `${h > 0 ? `${h}h ` : ""}${m}m ${String(r).padStart(2, "0")}s`;
};

export const STATE_LABEL: Record<string, string> = {
  CANDIDATE: "candidate", TRIGGERED: "triggered", INVALIDATED: "invalidated", TARGET_1: "target 1 reached",
  TARGET_2: "target 2 reached", STOPPED: "stopped", TIME_EXIT: "time exit", EXPIRED: "expired", WATCHING: "watching",
};
export const dirLabel = (d: string): string => (d === "BUY_CALL" ? "BUY CALL" : d === "BUY_PUT" ? "BUY PUT" : d);
