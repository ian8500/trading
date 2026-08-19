import { useCallback, useEffect, useRef, useState } from "react";
import { useApi } from "../context/ApiContext";

export interface ResourceState<T> {
  data: T;
  loading: boolean;
  source: "api" | "demo";
  error: string | null;
  refresh: () => Promise<void>;
  acceptApiData: (data: T) => void;
}

export function useApiResource<T>(path: string, demoData: T): ResourceState<T> {
  const { request } = useApi();
  const [data, setData] = useState<T>(demoData);
  const [loading, setLoading] = useState(true);
  const [source, setSource] = useState<"api" | "demo">("demo");
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(true);
  const revision = useRef(0);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const refresh = useCallback(async () => {
    const requestRevision = ++revision.current;
    setLoading(true);
    try {
      const result = await request<T>(path);
      if (!mounted.current || requestRevision !== revision.current) return;
      setData(result);
      setSource("api");
      setError(null);
    } catch (cause) {
      if (!mounted.current || requestRevision !== revision.current) return;
      setData(demoData);
      setSource("demo");
      setError(cause instanceof Error ? cause.message : "Backend unavailable");
    } finally {
      if (mounted.current && requestRevision === revision.current) setLoading(false);
    }
  }, [demoData, path, request]);

  const acceptApiData = useCallback((nextData: T) => {
    revision.current += 1;
    setData(nextData);
    setSource("api");
    setError(null);
    setLoading(false);
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { data, loading, source, error, refresh, acceptApiData };
}
