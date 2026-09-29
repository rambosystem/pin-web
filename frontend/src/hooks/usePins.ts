import { useCallback, useEffect, useState } from "react";
import { api } from "@/api/client";
import type { PinSummary } from "@/api/types";

// Stale-while-revalidate cache for the PIN list.
//
// The list used to be re-fetched from Jira on every visit to /pins or the
// dashboard (several seconds each time). We now keep the last result in
// memory for the lifetime of the tab and mirror it to sessionStorage so a full
// page reload also paints instantly; a background revalidation then swaps in
// fresh data. The backend has its own cache, so the revalidation is cheap.

const STORAGE_KEY = "pin-web:pins:v1";
const CLIENT_TTL_MS = 60_000; // skip revalidation entirely if fetched this recently

interface CacheEntry {
  items: PinSummary[];
  ts: number;
}

let memoryCache: CacheEntry | null = null;
let inflight: Promise<PinSummary[]> | null = null;

function readStorage(): CacheEntry | null {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as CacheEntry;
    if (!parsed || !Array.isArray(parsed.items)) return null;
    return parsed;
  } catch {
    return null;
  }
}

function writeStorage(entry: CacheEntry): void {
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(entry));
  } catch {
    /* quota / private mode: ignore */
  }
}

function getCached(): CacheEntry | null {
  if (!memoryCache) memoryCache = readStorage();
  return memoryCache;
}

function setCached(items: PinSummary[]): void {
  memoryCache = { items, ts: Date.now() };
  writeStorage(memoryCache);
}

/** Fetch the list, coalescing concurrent callers into one request. */
function fetchPins(refresh: boolean): Promise<PinSummary[]> {
  if (inflight && !refresh) return inflight;
  const p = api
    .listPins(refresh)
    .then((data) => {
      setCached(data.items);
      return data.items;
    })
    .finally(() => {
      if (inflight === p) inflight = null;
    });
  inflight = p;
  return p;
}

/** Update one PIN in the cached list (e.g. after a status/assignee change). */
export function patchCachedPin(updated: PinSummary): void {
  const cached = getCached();
  if (!cached) return;
  const items = cached.items.some((p) => p.key === updated.key)
    ? cached.items.map((p) => (p.key === updated.key ? { ...p, ...updated } : p))
    : [updated, ...cached.items];
  setCached(items);
}

export function usePins() {
  const initial = getCached();
  const [items, setItems] = useState<PinSummary[]>(initial?.items ?? []);
  // `loading` is only true when there is nothing to show yet; `refreshing`
  // signals a background revalidation while cached rows stay on screen.
  const [loading, setLoading] = useState(initial === null);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async (force = false) => {
    const hasData = getCached() !== null;
    if (hasData) setRefreshing(true);
    else setLoading(true);
    setError(null);
    try {
      setItems(await fetchPins(force));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    const cached = getCached();
    if (cached && Date.now() - cached.ts < CLIENT_TTL_MS) {
      setItems(cached.items);
      return;
    }
    void reload(false);
  }, [reload]);

  return { items, loading, refreshing, error, reload };
}
