import { useMemo } from "react";
import { Link } from "react-router-dom";
import { ExternalLink } from "lucide-react";
import type { PinSummary } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { StatCard } from "@/components/StatCard";
import { DistributionChart } from "@/components/DistributionChart";
import { usePins } from "@/hooks/usePins";

function tally(
  items: PinSummary[],
  pick: (p: PinSummary) => string | string[],
) {
  const counts = new Map<string, number>();
  for (const p of items) {
    const v = pick(p);
    const list = Array.isArray(v) ? v : [v];
    for (const x of list) {
      const k = (x || "").trim();
      if (!k) continue;
      counts.set(k, (counts.get(k) ?? 0) + 1);
    }
  }
  return Array.from(counts.entries())
    .map(([name, value]) => ({ name, value }))
    .sort((a, b) => b.value - a.value)
    .slice(0, 10);
}

export function Dashboard() {
  const { items, loading, error } = usePins();

  const stats = useMemo(() => {
    const total = items.length;
    const ready = items.filter(
      (p) => p.status === "Ready for Technical Review",
    ).length;
    const backlog = items.filter((p) => p.status === "Backlog").length;
    const high = items.filter((p) =>
      ["High", "Critical"].includes(p.urgency),
    ).length;
    return { total, ready, backlog, high };
  }, [items]);

  const statusData = useMemo(() => tally(items, (p) => p.status), [items]);
  const urgencyData = useMemo(() => tally(items, (p) => p.urgency), [items]);

  if (loading && items.length === 0) {
    return (
      <div className="grid grid-cols-4 gap-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-28" />
        ))}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Dashboard</h1>
        <Button asChild variant="outline" size="sm">
          <Link to="/pins">
            Open list <ExternalLink className="h-3.5 w-3.5" />
          </Link>
        </Button>
      </div>

      {error && (
        <div className="rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard label="Total PINs" value={stats.total} />
        <StatCard
          label="Ready for Tech Review"
          value={stats.ready}
          tone="warn"
        />
        <StatCard label="Backlog" value={stats.backlog} />
        <StatCard label="High / Critical" value={stats.high} tone="danger" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <DistributionChart title="Status" data={statusData} />
        <DistributionChart title="Urgency" data={urgencyData} />
      </div>
    </div>
  );
}
