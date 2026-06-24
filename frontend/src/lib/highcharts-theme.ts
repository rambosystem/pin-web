import { useEffect, useState } from "react";

export interface ChartTheme {
  text: string;
  muted: string;
  border: string;
  accent: string;
  bar: string;
}

function readVar(name: string, fallback: string): string {
  if (typeof window === "undefined") return fallback;
  const raw = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return raw ? `hsl(${raw})` : fallback;
}

function snapshot(): ChartTheme {
  return {
    text: readVar("--foreground", "hsl(222 47% 11%)"),
    muted: readVar("--muted-foreground", "hsl(215 16% 47%)"),
    border: readVar("--border", "hsl(214 32% 91%)"),
    accent: readVar("--accent", "hsl(210 40% 96%)"),
    bar: readVar("--chart-2", "hsl(173 58% 39%)"),
  };
}

export function useChartTheme(): ChartTheme {
  const [theme, setTheme] = useState<ChartTheme>(() => snapshot());

  useEffect(() => {
    const apply = () => setTheme(snapshot());
    apply();
    const mo = new MutationObserver(apply);
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
    return () => mo.disconnect();
  }, []);

  return theme;
}
