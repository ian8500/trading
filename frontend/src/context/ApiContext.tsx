import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { ApiNetworkError, apiRequest } from "../api/client";

export type ApiAvailability = "checking" | "online" | "offline";

interface ApiContextValue {
  availability: ApiAvailability;
  lastSuccessfulAt: string | null;
  lastError: string | null;
  request: <T>(path: string, init?: RequestInit) => Promise<T>;
  checkConnection: () => Promise<void>;
}

const ApiContext = createContext<ApiContextValue | null>(null);

export function ApiProvider({ children }: { children: ReactNode }) {
  const [availability, setAvailability] = useState<ApiAvailability>("checking");
  const [lastSuccessfulAt, setLastSuccessfulAt] = useState<string | null>(null);
  const [lastError, setLastError] = useState<string | null>(null);

  const request = useCallback(async <T,>(path: string, init?: RequestInit): Promise<T> => {
    try {
      const result = await apiRequest<T>(path, init);
      setAvailability("online");
      setLastSuccessfulAt(new Date().toISOString());
      setLastError(null);
      return result;
    } catch (error) {
      if (error instanceof ApiNetworkError) {
        setAvailability("offline");
        setLastError(error.message);
      } else {
        // An HTTP or response-level failure still proves that the API is reachable.
        setAvailability("online");
        setLastError(null);
      }
      throw error;
    }
  }, []);

  const checkConnection = useCallback(async () => {
    setAvailability("checking");
    try {
      await request<unknown>("/health");
    } catch {
      // The resource hooks will continue with their explicitly labelled demo data.
    }
  }, [request]);

  useEffect(() => {
    void checkConnection();
  }, [checkConnection]);

  const value = useMemo<ApiContextValue>(() => ({
    availability,
    lastSuccessfulAt,
    lastError,
    request,
    checkConnection,
  }), [availability, lastSuccessfulAt, lastError, request, checkConnection]);

  return <ApiContext.Provider value={value}>{children}</ApiContext.Provider>;
}

export function useApi(): ApiContextValue {
  const value = useContext(ApiContext);
  if (!value) throw new Error("useApi must be used within ApiProvider");
  return value;
}
