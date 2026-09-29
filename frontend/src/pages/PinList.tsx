import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  ExternalLink,
  RefreshCw,
  Search,
  TerminalSquare,
} from "lucide-react";
import type { PinSummary } from "@/api/types";
import { buildClaudeCodeLink, buildProcessPinPrompt } from "@/lib/claudeLink";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { MultiFilter } from "@/components/MultiFilter";
import { DateRangeFilter } from "@/components/DateRangeFilter";
import type { DateFilterValue } from "@/components/DateRangeFilter";
import { StatusBadge } from "@/components/StatusBadge";
import { usePins } from "@/hooks/usePins";

function uniqueValues(items: PinSummary[], pick: (p: PinSummary) => string) {
  const set = new Set<string>();
  for (const p of items) {
    const k = (pick(p) || "").trim();
    if (k) set.add(k);
  }
  return Array.from(set).sort();
}

type SortKey = "key" | "status" | "urgency" | "reporter" | "created";
type SortDir = "asc" | "desc";

const URGENCY_RANK: Record<string, number> = {
  Critical: 4,
  High: 3,
  Medium: 2,
  Low: 1,
};

const STATUS_RANK: Record<string, number> = {
  "Ready for Technical Review": 3,
  Backlog: 2,
  "Accepted for Development": 1,
};

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

function keyNum(k: string): number {
  const m = /(\d+)/.exec(k);
  return m ? parseInt(m[1], 10) : 0;
}

function compareBy(a: PinSummary, b: PinSummary, key: SortKey): number {
  if (key === "urgency") {
    return (URGENCY_RANK[a.urgency] ?? 0) - (URGENCY_RANK[b.urgency] ?? 0);
  }
  if (key === "status") {
    return (STATUS_RANK[a.status] ?? 0) - (STATUS_RANK[b.status] ?? 0);
  }
  if (key === "reporter") {
    return (a.reporter || "").localeCompare(b.reporter || "");
  }
  if (key === "created") {
    return new Date(a.created || 0).getTime() - new Date(b.created || 0).getTime();
  }
  return keyNum(a.key) - keyNum(b.key);
}

function SortButton({
  label,
  active,
  dir,
  order,
  onClick,
}: {
  label: string;
  active: boolean;
  dir?: SortDir;
  order?: number;
  onClick: (multi: boolean) => void;
}) {
  return (
    <button
      type="button"
      onClick={(e) => onClick(e.shiftKey)}
      title="Shift+click to add as secondary sort"
      className={`-ml-2 inline-flex h-8 items-center gap-1 rounded-md px-2 text-xs font-medium transition-colors hover:bg-accent hover:text-foreground ${
        active ? "text-foreground" : "text-muted-foreground"
      }`}
    >
      <span>{label}</span>
      {active && order !== undefined && (
        <span className="text-[10px] leading-none text-muted-foreground">{order}</span>
      )}
      {active ? (
        dir === "asc" ? (
          <ArrowUp className="h-3.5 w-3.5" />
        ) : (
          <ArrowDown className="h-3.5 w-3.5" />
        )
      ) : (
        <ArrowUpDown className="h-3.5 w-3.5 opacity-40" />
      )}
    </button>
  );
}

export function PinList() {
  const { items, loading, refreshing, error, reload } = usePins();
  const [q, setQ] = useState("");
  const [statuses, setStatuses] = useState<string[]>(["Backlog", "Ready for Technical Review"]);
  const [urgencies, setUrgencies] = useState<string[]>([]);
  const [reporters, setReporters] = useState<string[]>([]);
  const [dateFilter, setDateFilter] = useState<DateFilterValue | null>(null);
  const [sorts, setSorts] = useState<{ key: SortKey; dir: SortDir }[]>([
    { key: "urgency", dir: "desc" },
  ]);

  const statusOptions = useMemo(() => uniqueValues(items, (p) => p.status), [items]);
  const urgencyOptions = useMemo(() => uniqueValues(items, (p) => p.urgency), [items]);
  const reporterOptions = useMemo(() => uniqueValues(items, (p) => p.reporter), [items]);
  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const DAY = 86_400_000;
    return items.filter((p) => {
      if (statuses.length > 0 && !statuses.includes(p.status)) return false;
      if (urgencies.length > 0 && !urgencies.includes(p.urgency)) return false;
      if (reporters.length > 0 && !reporters.includes(p.reporter)) return false;
      if (dateFilter) {
        const ts = p.created ? new Date(p.created).getTime() : 0;
        const now = Date.now();
        if (dateFilter.mode === "within") {
          if (ts < now - (dateFilter.days ?? 0) * DAY) return false;
        } else if (dateFilter.mode === "more_than") {
          if (ts > now - (dateFilter.days ?? 0) * DAY) return false;
        } else if (dateFilter.mode === "in_range") {
          if (dateFilter.dateFrom && ts < new Date(dateFilter.dateFrom).getTime()) return false;
          if (dateFilter.dateTo && ts > new Date(dateFilter.dateTo + "T23:59:59").getTime()) return false;
        }
      }
      if (!needle) return true;
      return (
        p.key.toLowerCase().includes(needle) ||
        (p.summary || "").toLowerCase().includes(needle)
      );
    });
  }, [items, q, statuses, urgencies, reporters, dateFilter]);

  const sorted = useMemo(() => {
    const arr = [...filtered];
    arr.sort((a, b) => {
      for (const { key, dir } of sorts) {
        const c = compareBy(a, b, key);
        if (c !== 0) return dir === "desc" ? -c : c;
      }
      if (!sorts.some((s) => s.key === "urgency")) {
        const u = compareBy(a, b, "urgency");
        if (u !== 0) return -u;
      }
      return keyNum(b.key) - keyNum(a.key);
    });
    return arr;
  }, [filtered, sorts]);

  function toggleSort(key: SortKey, multi: boolean) {
    const defaultDir: SortDir = key === "key" || key === "reporter" ? "asc" : "desc";
    const flip = (d: SortDir): SortDir => (d === "asc" ? "desc" : "asc");
    setSorts((prev) => {
      const idx = prev.findIndex((s) => s.key === key);
      if (multi) {
        if (idx < 0) return [...prev, { key, dir: defaultDir }];
        return prev.map((s, i) => (i === idx ? { ...s, dir: flip(s.dir) } : s));
      }
      if (prev.length === 1 && idx === 0) return [{ key, dir: flip(prev[0].dir) }];
      return [{ key, dir: defaultDir }];
    });
  }

  const sortInfo = (key: SortKey) => {
    const idx = sorts.findIndex((s) => s.key === key);
    return {
      active: idx >= 0,
      dir: idx >= 0 ? sorts[idx].dir : undefined,
      order: idx >= 0 && sorts.length > 1 ? idx + 1 : undefined,
    };
  };

  const hasFilters = statuses.length + urgencies.length + reporters.length > 0 || dateFilter !== null || q.length > 0;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">PIN List</h1>
        <Button
          variant="outline"
          size="sm"
          onClick={() => void reload(true)}
          disabled={loading || refreshing}
        >
          <RefreshCw className={loading || refreshing ? "animate-spin" : ""} />
          Refresh
        </Button>
      </div>

      <Card>
        <CardContent className="pt-4 pb-3">
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative w-72">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <Input
                placeholder="Search key or summary"
                value={q}
                onChange={(e) => setQ(e.target.value)}
                className="pl-8 h-9"
              />
            </div>
            <MultiFilter
              label="Status"
              options={statusOptions}
              value={statuses}
              onChange={setStatuses}
            />
            <MultiFilter
              label="Urgency"
              options={urgencyOptions}
              value={urgencies}
              onChange={setUrgencies}
            />
            <MultiFilter
              label="Reporter"
              options={reporterOptions}
              value={reporters}
              onChange={setReporters}
            />
            <DateRangeFilter value={dateFilter} onChange={setDateFilter} />
            {hasFilters && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  setQ("");
                  setStatuses([]);
                  setUrgencies([]);
                  setReporters([]);
                  setDateFilter(null);
                }}
              >
                Reset
              </Button>
            )}
            <div className="ml-auto text-xs text-muted-foreground">
              {filtered.length} / {items.length}
            </div>
          </div>
        </CardContent>
      </Card>

      {error && (
        <div className="rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
          {error}
        </div>
      )}

      <Card>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-[110px]">
                <SortButton
                  label="Key"
                  {...sortInfo("key")}
                  onClick={(multi) => toggleSort("key", multi)}
                />
              </TableHead>
              <TableHead>Summary</TableHead>
              <TableHead className="w-[160px]">
                <SortButton
                  label="Reporter"
                  {...sortInfo("reporter")}
                  onClick={(multi) => toggleSort("reporter", multi)}
                />
              </TableHead>
              <TableHead className="w-[240px]">
                <SortButton
                  label="Status"
                  {...sortInfo("status")}
                  onClick={(multi) => toggleSort("status", multi)}
                />
              </TableHead>
              <TableHead className="w-[120px]">
                <SortButton
                  label="Urgency"
                  {...sortInfo("urgency")}
                  onClick={(multi) => toggleSort("urgency", multi)}
                />
              </TableHead>
              <TableHead className="w-[110px]">
                <SortButton
                  label="Created"
                  {...sortInfo("created")}
                  onClick={(multi) => toggleSort("created", multi)}
                />
              </TableHead>
              <TableHead className="w-[90px] text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading && items.length === 0 && (
              <TableRow>
                <TableCell colSpan={7}>
                  <div className="space-y-2 py-2">
                    {Array.from({ length: 4 }).map((_, i) => (
                      <Skeleton key={i} className="h-6" />
                    ))}
                  </div>
                </TableCell>
              </TableRow>
            )}
            {!loading && sorted.length === 0 && (
              <TableRow>
                <TableCell colSpan={7} className="text-center text-sm text-muted-foreground py-8">
                  No PIN matches current filters.
                </TableCell>
              </TableRow>
            )}
            {sorted.map((p) => (
              <TableRow
                key={p.key}
                className="cursor-pointer"
                onClick={(e) => {
                  // Let inner links (key/summary/actions) handle their own clicks.
                  if ((e.target as HTMLElement).closest("a")) return;
                  window.open(`/pins/${p.key}`, "_blank", "noopener");
                }}
              >
                <TableCell className="font-mono text-xs">
                  <Link
                    to={`/pins/${p.key}`}
                    target="_blank"
                    rel="noreferrer"
                    className="text-primary hover:underline"
                  >
                    {p.key}
                  </Link>
                </TableCell>
                <TableCell>
                  <Link
                    to={`/pins/${p.key}`}
                    target="_blank"
                    rel="noreferrer"
                    className="hover:underline"
                  >
                    {p.summary || (
                      <span className="text-muted-foreground italic">
                        (no summary)
                      </span>
                    )}
                  </Link>
                </TableCell>
                <TableCell>
                  {p.reporter ? (
                    <div className="flex items-center gap-2">
                      <div className="h-6 w-6 shrink-0 rounded-full bg-muted text-[10px] font-medium text-foreground/70 flex items-center justify-center">
                        {initials(p.reporter)}
                      </div>
                      <span className="text-sm">{p.reporter}</span>
                    </div>
                  ) : (
                    <span className="text-muted-foreground italic text-xs">—</span>
                  )}
                </TableCell>
                <TableCell>
                  <StatusBadge label={p.status} />
                </TableCell>
                <TableCell>
                  {p.urgency ? (
                    <StatusBadge label={p.urgency} kind="urgency" />
                  ) : (
                    <span className="text-muted-foreground">—</span>
                  )}
                </TableCell>
                <TableCell className="text-xs text-muted-foreground">
                  {p.created ? new Date(p.created).toLocaleDateString() : "—"}
                </TableCell>
                <TableCell className="text-right">
                  <div className="inline-flex items-center gap-3">
                    <a
                      href={buildClaudeCodeLink(buildProcessPinPrompt(p, null, null))}
                      title="Open in Claude Code (/process-pin)"
                      className="inline-flex items-center text-xs text-muted-foreground hover:text-foreground"
                    >
                      <TerminalSquare className="h-3.5 w-3.5" />
                    </a>
                    <a
                      href={p.jira_url}
                      target="_blank"
                      rel="noreferrer"
                      title="Open in Jira"
                      className="inline-flex items-center text-xs text-muted-foreground hover:text-foreground"
                    >
                      <ExternalLink className="h-3.5 w-3.5" />
                    </a>
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Card>
    </div>
  );
}
