import { useCallback, useEffect, useState } from "react";
import { apiGet, ApiRequestError } from "../api/client";

interface UseApiResult<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  refetch: () => void;
}

/** Polls `path` every `intervalMs` (default 5s) — the failure-storm / scenario demos need
 * the dashboard and queue to visibly update shortly after events are posted, without a
 * websocket layer this build doesn't have. */
export function useApi<T>(path: string, intervalMs = 5000): UseApiResult<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);

  const refetch = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    apiGet<T>(path)
      .then((result) => {
        if (!cancelled) {
          setData(result);
          setError(null);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof ApiRequestError ? err.message : "Request failed");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, tick]);

  useEffect(() => {
    if (intervalMs <= 0) return;
    const id = setInterval(refetch, intervalMs);
    return () => clearInterval(id);
  }, [intervalMs, refetch]);

  return { data, error, loading, refetch };
}
