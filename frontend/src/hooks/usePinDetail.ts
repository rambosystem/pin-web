import { useCallback, useEffect, useState } from "react";
import { api } from "@/api/client";
import type { PinDetail } from "@/api/types";

export function usePinDetail(key: string | undefined) {
  const [data, setData] = useState<PinDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    if (!key) return;
    setLoading(true);
    setError(null);
    try {
      setData(await api.getPin(key));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [key]);

  useEffect(() => {
    void reload();
  }, [reload]);

  return { data, setData, loading, error };
}
