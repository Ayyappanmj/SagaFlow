import { useCallback, useEffect, useState } from "react";

export class ApiError extends Error {}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`/api/v1${path}`, init);
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new ApiError(body?.error?.message ?? `HTTP ${r.status}`);
  return body as T;
}

/** Fetch + loading/error state; refetch() for manual refresh. Polls every `pollMs` if given. */
export function useApi<T>(path: string, pollMs = 0) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const load = useCallback(() => {
    api<T>(path).then((d) => { setData(d); setError(null); })
      .catch((e) => setError(e.message)).finally(() => setLoading(false));
  }, [path]);
  useEffect(() => { setLoading(true); load(); if (pollMs) { const t = setInterval(load, pollMs); return () => clearInterval(t); } }, [load, pollMs]);
  return { data, error, loading, refetch: load };
}

export const newKey = () => crypto.randomUUID();
export const money = (c: number) => `$${(c / 100).toFixed(2)}`;
