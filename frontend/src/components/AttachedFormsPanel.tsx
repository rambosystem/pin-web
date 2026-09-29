import { useCallback, useEffect, useRef, useState } from "react";
import { CheckCircle2, Circle, FileText, Lock, RefreshCw } from "lucide-react";
import { api } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import type { AttachedForm } from "@/api/types";

function fmtRelative(iso: string): string {
  if (!iso) return "";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return iso;
  const diff = (Date.now() - t) / 1000;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  if (diff < 86400 * 30) return `${Math.floor(diff / 86400)}d ago`;
  return new Date(t).toLocaleDateString();
}

interface Props {
  pinKey: string;
  /** Highlight the form whose id matches (e.g. the locally cached intake form). */
  highlightFormId?: string;
  /** Increment to trigger a forms list reload from outside (e.g. after a status transition). */
  refreshTrigger?: number;
}

/**
 * Read-only list of the ProForma forms attached to a PIN (name, Draft /
 * Submitted, last update). Filling and submitting forms is done outside this
 * app (Claude Code); this panel only shows their state.
 */
export function AttachedFormsPanel({ pinKey, highlightFormId, refreshTrigger }: Props) {
  const [items, setItems] = useState<AttachedForm[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.listForms(pinKey);
      setItems(res.items);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [pinKey]);

  useEffect(() => {
    void load();
  }, [load]);

  const isFirstRender = useRef(true);
  useEffect(() => {
    if (isFirstRender.current) { isFirstRender.current = false; return; }
    if (refreshTrigger === undefined) return;
    void load();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshTrigger]);

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-3">
        <CardTitle className="text-sm flex items-center gap-2">
          <FileText className="h-4 w-4 text-muted-foreground" />
          Attached Forms
          {items && (
            <span className="text-xs text-muted-foreground font-normal">
              ({items.length})
            </span>
          )}
        </CardTitle>
        <Button
          variant="ghost"
          size="sm"
          className="h-7 px-2 text-xs text-muted-foreground"
          onClick={load}
          disabled={loading}
        >
          <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} />
          Refresh
        </Button>
      </CardHeader>
      <CardContent className="pt-0">
        {loading && !items && (
          <div className="space-y-2">
            <Skeleton className="h-10" />
            <Skeleton className="h-10" />
          </div>
        )}

        {error && (
          <div className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive">
            {error}
          </div>
        )}

        {items && items.length === 0 && !error && (
          <div className="py-2 text-xs text-muted-foreground">
            No ProForma forms attached to this issue.
          </div>
        )}

        {items && items.length > 0 && (
          <ul className="divide-y divide-border -mx-2">
            {items.map((f) => {
              const isHighlighted = highlightFormId && f.id === highlightFormId;
              return (
                <li
                  key={f.id}
                  className={cn(
                    "flex items-center justify-between gap-3 px-2 py-2 text-sm",
                    isHighlighted && "bg-muted/40 rounded-md"
                  )}
                >
                  <div className="flex items-center gap-2 min-w-0">
                    {f.submitted ? (
                      <CheckCircle2 className="h-4 w-4 text-emerald-600 dark:text-emerald-500 shrink-0" />
                    ) : (
                      <Circle className="h-4 w-4 text-muted-foreground shrink-0" />
                    )}
                    <span className="font-medium truncate">{f.name || "(unnamed form)"}</span>
                    {f.lock && (
                      <Lock
                        className="h-3 w-3 text-muted-foreground shrink-0"
                        aria-label="Locked"
                      />
                    )}
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <Badge
                      variant={f.submitted ? "default" : "outline"}
                      className="font-normal"
                    >
                      {f.submitted ? "Submitted" : "Draft"}
                    </Badge>
                    {f.updated && (
                      <span
                        className="text-xs text-muted-foreground tabular-nums"
                        title={f.updated}
                      >
                        {fmtRelative(f.updated)}
                      </span>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
