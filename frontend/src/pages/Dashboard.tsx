import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Copy, ExternalLink, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import type { PinSummary } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { StatCard } from "@/components/StatCard";
import { DistributionChart } from "@/components/DistributionChart";
import { usePins } from "@/hooks/usePins";
import { api } from "@/api/client";
import { cn, copyText } from "@/lib/utils";
import { useChartTheme } from "@/lib/highcharts-theme";
import Highcharts from "highcharts";
import HighchartsReact from "highcharts-react-official";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

type Weekly = Awaited<ReturnType<typeof api.weeklyReport>>;

function WeeklyReport() {
  const theme = useChartTheme();
  const [data, setData] = useState<Weekly | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function load(refresh = false) {
    setLoading(true);
    setError("");
    try {
      setData(await api.weeklyReport(refresh));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  const last = data?.weeks[data.weeks.length - 1];

  async function copy() {
    if (!last) return;
    const md = `上周新增：${last.created}
已处理：${last.handled}`;
    if (await copyText(md)) toast.success("Copied");
    else toast.error("Copy failed — clipboard unavailable");
  }

  const options = useMemo<Highcharts.Options>(() => {
    const weeks = data?.weeks ?? [];
    return {
      accessibility: { enabled: false },
      credits: { enabled: false },
      chart: {
        type: "line",
        backgroundColor: "transparent",
        spacing: [8, 8, 8, 0],
        style: { fontFamily: "inherit" },
        height: 224,
      },
      title: { text: undefined },
      legend: { itemStyle: { color: theme.muted, fontWeight: "normal" } },
      xAxis: {
        categories: weeks.map((w) => `${w.week_start.slice(5)} ~ ${w.week_end.slice(5)}`),
        lineColor: theme.border,
        tickColor: theme.border,
        labels: { style: { color: theme.muted, fontSize: "11px" } },
      },
      yAxis: {
        title: { text: undefined },
        gridLineColor: theme.border,
        gridLineDashStyle: "Dash",
        labels: { style: { color: theme.muted, fontSize: "11px" } },
        allowDecimals: false,
        min: 0,
      },
      tooltip: { shared: true, style: { fontSize: "12px" } },
      plotOptions: {
        line: { dataLabels: { enabled: true, style: { fontSize: "11px" } } },
      },
      series: [
        { type: "line", name: "New PIN", data: weeks.map((w) => w.created), color: theme.bar },
        { type: "line", name: "Handled", data: weeks.map((w) => w.handled), color: "#f59e0b" },
      ],
    };
  }, [data, theme]);

  return (
    <Card>
      <CardHeader className="pb-2 flex-row items-center justify-between space-y-0">
        <CardTitle className="text-sm">PIN Weekly Report (last 4 weeks)</CardTitle>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => load(true)}
            disabled={loading}
          >
            <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} />
            Refresh
          </Button>
          <Button variant="outline" size="sm" onClick={copy} disabled={!last}>
            <Copy className="h-3.5 w-3.5" /> Copy Markdown
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        {error ? (
          <div className="text-sm text-destructive">{error}</div>
        ) : data ? (
          <HighchartsReact
            highcharts={Highcharts}
            options={options}
            containerProps={{ style: { width: "100%" } }}
          />
        ) : (
          <Skeleton className="h-56" />
        )}
      </CardContent>
    </Card>
  );
}

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

      <WeeklyReport />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <DistributionChart title="Status" data={statusData} />
        <DistributionChart title="Urgency" data={urgencyData} />
      </div>
    </div>
  );
}
