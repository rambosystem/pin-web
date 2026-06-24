import { useCallback, useEffect, useMemo, useState } from "react";
import {
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  FileCheck2,
  Lock,
  RefreshCw,
} from "lucide-react";
import { api } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { MarkdownLite } from "@/components/MarkdownLite";
import { cn } from "@/lib/utils";
import type { SubmittedFormSummary } from "@/api/types";

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
}

export function SubmittedFormsCard({ pinKey }: Props) {
  const [items, setItems] = useState<SubmittedFormSummary[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.listSubmittedForms(pinKey);
      setItems(res.items);
      const init: Record<string, boolean> = {};
      res.items.forEach((f, i) => {
        init[f.form_id] = i === 0;
      });
      setExpanded(init);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [pinKey]);

  useEffect(() => {
    void load();
  }, [load]);

  const totalFields = useMemo(
    () => (items || []).reduce((n, f) => n + Object.keys(f.fields).length, 0),
    [items]
  );

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-3">
        <CardTitle className="text-sm flex items-center gap-2">
          <FileCheck2 className="h-4 w-4 text-muted-foreground" />
          Submitted Forms
          {items && (
            <span className="text-xs text-muted-foreground font-normal">
              ({items.length} {items.length === 1 ? "form" : "forms"}
              {totalFields > 0 ? `, ${totalFields} fields` : ""})
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
            <Skeleton className="h-12" />
            <Skeleton className="h-12" />
          </div>
        )}

        {error && (
          <div className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive">
            {error}
          </div>
        )}

        {items && items.length === 0 && !error && (
          <div className="py-2 text-xs text-muted-foreground">
            No submitted forms on this issue.
          </div>
        )}

        {items && items.length > 0 && (
          <div className="space-y-2">
            {items.map((form, idx) => {
              const open = !!expanded[form.form_id];
              const fieldKeys = Object.keys(form.fields);
              return (
                <div
                  key={form.form_id}
                  className="rounded-md border border-border bg-muted/20"
                >
                  <button
                    type="button"
                    onClick={() =>
                      setExpanded((s) => ({
                        ...s,
                        [form.form_id]: !s[form.form_id],
                      }))
                    }
                    className="w-full flex items-center justify-between gap-3 px-3 py-2 text-sm hover:bg-muted/40 transition rounded-md"
                  >
                    <div className="flex items-center gap-2 min-w-0 text-left">
                      {open ? (
                        <ChevronDown className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                      ) : (
                        <ChevronRight className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                      )}
                      <CheckCircle2 className="h-4 w-4 text-emerald-600 dark:text-emerald-500 shrink-0" />
                      <span className="font-medium truncate">
                        {form.form_name || "(unnamed form)"}
                      </span>
                      {form.lock && (
                        <Lock
                          className="h-3 w-3 text-muted-foreground shrink-0"
                          aria-label="Locked"
                        />
                      )}
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      <Badge variant="secondary" className="font-normal">
                        {fieldKeys.length} fields
                      </Badge>
                      {form.updated && (
                        <span
                          className="text-xs text-muted-foreground tabular-nums"
                          title={form.updated}
                        >
                          {fmtRelative(form.updated)}
                        </span>
                      )}
                    </div>
                  </button>
                  {open && (
                    <div className="px-3 pb-3">
                      <Separator className="mb-3" />
                      {fieldKeys.length === 0 ? (
                        <div className="text-xs text-muted-foreground">
                          (no readable fields)
                        </div>
                      ) : (
                        <dl className="space-y-3">
                          {fieldKeys.map((label) => (
                            <div key={label}>
                              <dt className="text-xs uppercase tracking-wide text-muted-foreground mb-1">
                                {label}
                              </dt>
                              <dd className="text-sm">
                                <MarkdownLite text={form.fields[label]} />
                              </dd>
                            </div>
                          ))}
                        </dl>
                      )}
                    </div>
                  )}
                  {idx === items.length - 1 ? null : null}
                </div>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
