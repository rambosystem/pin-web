import { useCallback, useEffect, useRef, useState } from "react";
import { RefreshCw } from "lucide-react";
import { api } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { MarkdownLite } from "@/components/MarkdownLite";

// Client-side translation cache, keyed by (pin, field, source text). Survives
// navigating away and back within the tab, and de-duplicates the double
// effect run React StrictMode performs in dev.
const results = new Map<string, string>();
const inflight = new Map<string, Promise<string>>();

function cacheKey(pinKey: string, field: string, text: string): string {
  return `${pinKey}\u0000${field}\u0000${text}`;
}

function fetchTranslation(text: string, pinKey: string, field: string, bypass: boolean): Promise<string> {
  const key = cacheKey(pinKey, field, text);
  if (bypass) {
    results.delete(key);
    inflight.delete(key);
  } else {
    const hit = results.get(key);
    if (hit !== undefined) return Promise.resolve(hit);
    const pending = inflight.get(key);
    if (pending) return pending;
  }
  const p = api
    .translate(text, pinKey, field)
    .then((data) => {
      const t = data.translated ?? "";
      if (t) results.set(key, t);
      return t;
    })
    .finally(() => {
      if (inflight.get(key) === p) inflight.delete(key);
    });
  inflight.set(key, p);
  return p;
}

/** Returns true when the text is predominantly non-Chinese (worth translating). */
function needsTranslation(text: string): boolean {
  if (!text.trim()) return false;
  const letters = text.replace(/\s/g, "");
  if (!letters.length) return false;
  const chineseChars = (letters.match(/[一-鿿㐀-䶿]/g) ?? []).length;
  return chineseChars / letters.length < 0.3;
}

export function TranslatedText({
  text,
  pinKey = "",
  field = "",
  version = 0,
}: {
  text: string;
  pinKey?: string;
  field?: string;
  /** Bump to force a fresh translation (e.g. after Reload Form). */
  version?: number;
}) {
  const [translated, setTranslated] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  // Reload Form clears the server-side cache; a version bump (or a manual
  // retry) must not be answered from the client cache either. Only the effect
  // run triggered by that change bypasses the cache, not every later run.
  const bypassNext = useRef(false);
  const lastVersion = useRef(version);

  const retry = useCallback(() => {
    bypassNext.current = true;
    setAttempt((n) => n + 1);
  }, []);

  useEffect(() => {
    if (!needsTranslation(text)) return;
    let cancelled = false;
    setError(null);
    if (version !== lastVersion.current) {
      lastVersion.current = version;
      bypassNext.current = true;
    }
    const bypass = bypassNext.current;
    bypassNext.current = false;
    const key = cacheKey(pinKey, field, text);
    const hit = bypass ? undefined : results.get(key);
    if (hit !== undefined) {
      setTranslated(hit);
      setLoading(false);
      return;
    }
    setTranslated(null);
    setLoading(true);
    fetchTranslation(text, pinKey, field, bypass)
      .then((t) => {
        if (cancelled) return;
        if (!t) setError("翻译结果为空");
        setTranslated(t || null);
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [text, pinKey, field, version, attempt]);

  if (!needsTranslation(text)) return null;

  return (
    <div className="mt-3">
      <Separator className="mb-3" />
      {loading && (
        <div className="space-y-1.5">
          <Skeleton className="h-3 w-full" />
          <Skeleton className="h-3 w-[90%]" />
          <Skeleton className="h-3 w-[75%]" />
        </div>
      )}
      {!loading && translated && (
        <MarkdownLite
          text={translated}
          className="text-foreground/70 prose-p:text-foreground/70 prose-li:text-foreground/70 prose-strong:text-foreground/80"
        />
      )}
      {!loading && error && (
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <span>翻译失败：{error}</span>
          <Button variant="ghost" size="sm" className="h-6 px-2 text-xs" onClick={retry}>
            <RefreshCw className="h-3 w-3" />
            重试
          </Button>
        </div>
      )}
    </div>
  );
}
