import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

type Tone = "review" | "backlog" | "neutral" | "high" | "critical" | "medium" | "low";

const TONE_CLASS: Record<Tone, string> = {
  review: "bg-amber-100 text-amber-800 border-amber-200",
  backlog: "bg-slate-100 text-slate-700 border-slate-200",
  neutral: "bg-secondary text-secondary-foreground",
  high: "bg-orange-100 text-orange-700 border-orange-200",
  critical: "bg-rose-100 text-rose-700 border-rose-200",
  medium: "bg-sky-100 text-sky-700 border-sky-200",
  low: "bg-emerald-100 text-emerald-700 border-emerald-200",
};

function statusTone(label: string): Tone {
  const v = label.toLowerCase();
  if (v.includes("ready")) return "review";
  if (v.includes("backlog")) return "backlog";
  return "neutral";
}

function urgencyTone(label: string): Tone {
  const v = label.toLowerCase();
  if (v === "critical") return "critical";
  if (v === "high") return "high";
  if (v === "medium") return "medium";
  if (v === "low") return "low";
  return "neutral";
}

export function StatusBadge({
  label,
  kind = "status",
}: {
  label?: string;
  kind?: "status" | "urgency";
}) {
  if (!label) return null;
  const tone = kind === "urgency" ? urgencyTone(label) : statusTone(label);
  return (
    <Badge variant="outline" className={cn("font-medium", TONE_CLASS[tone])}>
      {label}
    </Badge>
  );
}
