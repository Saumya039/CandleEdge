"use client";
import { useEffect, useState, type ReactNode } from "react";
import { api, ApiError } from "@/lib/api";

type Phase = "checking" | "open" | "login" | "unreachable";

/** Shows a password form when the server requires a login. When the server has no login configured (local simulator
 * use) it renders the app straight away. No password or token is ever kept in browser storage: the server sets an
 * HttpOnly cookie. */
export function AuthGate({ children }: { children: ReactNode }) {
  const [phase, setPhase] = useState<Phase>("checking");
  const [pw, setPw] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let alive = true;
    api.authSession()
      .then((s) => { if (alive) setPhase(!s.required || s.authenticated ? "open" : "login"); })
      // Backend down: render the app so its own "no data" state explains it.
      .catch(() => { if (alive) setPhase("unreachable"); });
    return () => { alive = false; };
  }, []);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true); setErr(null);
    try {
      await api.login(pw);
      setPw(""); setPhase("open");
    } catch (x) {
      setErr(x instanceof ApiError ? x.message : "Could not reach the server");
    } finally { setBusy(false); }
  };

  if (phase === "checking") return <main className="p-6 text-muted">Connecting…</main>;
  if (phase === "open" || phase === "unreachable") return <>{children}</>;
  return (
    <main className="mx-auto flex min-h-screen w-full max-w-sm flex-col justify-center gap-3 p-4">
      <h1 className="text-[18px] font-semibold">Stratagy</h1>
      <p className="text-muted">Private workstation. Enter the password you set on the server.</p>
      <form onSubmit={(e) => void submit(e)} className="space-y-2" data-testid="login-form">
        <label className="block text-muted" htmlFor="login-password">Password
          <input id="login-password" className="input mt-0.5" type="password" autoComplete="current-password" autoFocus value={pw}
            onChange={(e) => setPw(e.target.value)} data-testid="login-password" />
        </label>
        <button className="btn btn-primary" type="submit" disabled={busy || !pw} data-testid="login-submit">Sign in</button>
        {err && <p role="alert" className="text-down" data-testid="login-error">{err}</p>}
      </form>
    </main>
  );
}
