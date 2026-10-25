"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "./api";

export interface PollResult<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  refresh: () => void;
}

/** Poll an async function. Keeps the last good value on error (the caller shows the error beside it). */
export function usePoll<T>(fn: () => Promise<T>, intervalMs: number, enabled = true, deps: unknown[] = []): PollResult<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const fnRef = useRef(fn);
  useEffect(() => { fnRef.current = fn; });
  const alive = useRef(true);

  const run = useCallback(async () => {
    try {
      const v = await fnRef.current();
      if (!alive.current) return;
      setData(v);
      setError(null);
    } catch (e) {
      if (!alive.current) return;
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      if (alive.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    alive.current = true;
    if (!enabled) return;
    void run();
    const id = setInterval(() => void run(), intervalMs);
    return () => {
      alive.current = false;
      clearInterval(id);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intervalMs, enabled, run, ...deps]);

  return { data, error, loading, refresh: run };
}
