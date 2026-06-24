import { useMemo } from "react";
import Highcharts from "highcharts";
import HighchartsReact from "highcharts-react-official";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useChartTheme } from "@/lib/highcharts-theme";

export function DistributionChart({
  title,
  data,
}: {
  title: string;
  data: { name: string; value: number }[];
}) {
  const theme = useChartTheme();

  const options = useMemo<Highcharts.Options>(() => {
    const rotate = data.length > 5;
    return {
      accessibility: { enabled: false },
      credits: { enabled: false },
      chart: {
        type: "column",
        backgroundColor: "transparent",
        spacing: [8, 8, 8, 0],
        style: { fontFamily: "inherit" },
        height: 224,
      },
      title: { text: undefined },
      legend: { enabled: false },
      xAxis: {
        categories: data.map((d) => d.name),
        lineColor: theme.border,
        tickColor: theme.border,
        labels: {
          style: { color: theme.muted, fontSize: "11px" },
          rotation: rotate ? -20 : 0,
          align: rotate ? "right" : "center",
          y: rotate ? 14 : 16,
        },
      },
      yAxis: {
        title: { text: undefined },
        gridLineColor: theme.border,
        gridLineDashStyle: "Dash",
        labels: { style: { color: theme.muted, fontSize: "11px" } },
        allowDecimals: false,
        min: 0,
      },
      tooltip: {
        backgroundColor: "rgba(255,255,255,0.98)",
        borderColor: theme.border,
        borderRadius: 6,
        shadow: false,
        style: { color: theme.text, fontSize: "12px" },
        useHTML: true,
        headerFormat: '<div style="font-weight:600">{point.key}</div>',
        pointFormat: '<div style="opacity:0.8">{series.name}: <b>{point.y}</b></div>',
      },
      plotOptions: {
        column: {
          borderRadius: 4,
          borderWidth: 0,
          color: theme.bar,
          states: { hover: { brightness: -0.05 } },
        },
      },
      series: [
        {
          type: "column",
          name: "Count",
          data: data.map((d) => d.value),
        },
      ],
    };
  }, [data, theme]);

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">{title}</CardTitle>
      </CardHeader>
      <CardContent>
        {data.length === 0 ? (
          <div className="h-56 flex items-center justify-center text-sm text-muted-foreground">
            No data
          </div>
        ) : (
          <HighchartsReact
            highcharts={Highcharts}
            options={options}
            containerProps={{ style: { width: "100%" } }}
          />
        )}
      </CardContent>
    </Card>
  );
}
