import { useState } from "react";
import { ChevronDown, CalendarIcon, X } from "lucide-react";
import { format } from "date-fns";
import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";

export type DateFilterMode = "within" | "more_than" | "in_range";

export interface DateFilterValue {
  mode: DateFilterMode;
  days?: number;
  dateFrom?: string;
  dateTo?: string;
}

function DateRangePicker({
  dateFrom,
  dateTo,
  onChange,
}: {
  dateFrom?: string;
  dateTo?: string;
  onChange: (from: string | undefined, to: string | undefined) => void;
}) {
  const [open, setOpen] = useState(false);
  const from = dateFrom ? new Date(dateFrom + "T12:00:00") : undefined;
  const to = dateTo ? new Date(dateTo + "T12:00:00") : undefined;
  const range = from || to ? { from, to } : undefined;

  function formatDate(d?: Date) {
    return d ? format(d, "MMM d, yyyy") : undefined;
  }

  const label =
    formatDate(from) && formatDate(to)
      ? `${formatDate(from)} – ${formatDate(to)}`
      : formatDate(from)
        ? `Start: ${formatDate(from)}`
        : formatDate(to)
          ? `End: ${formatDate(to)}`
          : undefined;

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          className={cn(
            "flex w-full items-center gap-2 rounded-md border border-input bg-background px-3 py-1.5 text-left text-sm transition-colors hover:bg-accent",
            !label && "text-muted-foreground"
          )}
        >
          <CalendarIcon className="h-3.5 w-3.5 shrink-0 opacity-60" />
          <span className="flex-1">{label ?? "Start Date – End Date"}</span>
          {label && (
            <X
              className="h-3 w-3 shrink-0 opacity-50 hover:opacity-100"
              onClick={(e) => {
                e.stopPropagation();
                onChange(undefined, undefined);
              }}
            />
          )}
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-auto p-0" align="start">
        <Calendar
          mode="range"
          defaultMonth={from}
          selected={range}
          onSelect={(r) => {
            onChange(
              r?.from ? format(r.from, "yyyy-MM-dd") : undefined,
              r?.to ? format(r.to, "yyyy-MM-dd") : undefined,
            );
            if (r?.from && r?.to) setOpen(false);
          }}
          numberOfMonths={2}
          disabled={(date) => date > new Date() || date < new Date("1900-01-01")}
        />
      </PopoverContent>
    </Popover>
  );
}

const MODES: { key: DateFilterMode; label: string }[] = [
  { key: "within", label: "Within the last" },
  { key: "more_than", label: "More than" },
  { key: "in_range", label: "In the range" },
];

function summarize(v: DateFilterValue): string {
  if (v.mode === "within") return `Within ${v.days ?? "?"}d`;
  if (v.mode === "more_than") return `>${v.days ?? "?"}d ago`;
  if (v.mode === "in_range") {
    const from = v.dateFrom ?? "";
    const to = v.dateTo ?? "";
    if (from && to) return `${from} – ${to}`;
    if (from) return `≥ ${from}`;
    if (to) return `≤ ${to}`;
  }
  return "Date";
}

export function DateRangeFilter({
  value,
  onChange,
}: {
  value: DateFilterValue | null;
  onChange: (v: DateFilterValue | null) => void;
}) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<DateFilterValue>({ mode: "within", days: 30 });

  function handleOpen(o: boolean) {
    if (o) setDraft(value ?? { mode: "within", days: 30 });
    setOpen(o);
  }

  function apply() {
    onChange(draft);
    setOpen(false);
  }

  function clear() {
    onChange(null);
    setOpen(false);
  }

  return (
    <Popover open={open} onOpenChange={handleOpen}>
      <PopoverTrigger asChild>
        <Button variant="outline" size="sm" className="gap-1.5">
          <span>{value ? summarize(value) : "Created"}</span>
          {value && (
            <span className="ml-1 inline-flex items-center justify-center rounded bg-primary px-1.5 text-[10px] font-semibold text-primary-foreground">
              1
            </span>
          )}
          <ChevronDown className="h-3.5 w-3.5 opacity-60" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-72 p-3" align="start">
        <RadioGroup
          value={draft.mode}
          onValueChange={(v) => setDraft((d) => ({ ...d, mode: v as DateFilterMode }))}
          className="mb-2"
        >
          {MODES.map((m) => (
            <div
              key={m.key}
              className={cn(
                "flex items-center gap-2 rounded-sm px-2 py-1.5 cursor-pointer transition-colors",
                draft.mode === m.key ? "bg-accent" : "hover:bg-accent/60"
              )}
              onClick={() => setDraft((d) => ({ ...d, mode: m.key }))}
            >
              <RadioGroupItem value={m.key} id={`mode-${m.key}`} />
              <Label htmlFor={`mode-${m.key}`} className="text-sm font-normal cursor-pointer">
                {m.label}
              </Label>
            </div>
          ))}
        </RadioGroup>

        <Separator className="my-2" />

        <div className="space-y-2">
          {(draft.mode === "within" || draft.mode === "more_than") && (
            <div className="flex items-center gap-2">
              <Input
                type="number"
                min={1}
                value={draft.days ?? ""}
                onChange={(e) => setDraft((d) => ({ ...d, days: e.target.value ? Number(e.target.value) : undefined }))}
                className="h-8 text-sm w-24"
                placeholder="30"
              />
              <span className="text-sm text-muted-foreground">days</span>
            </div>
          )}

          {draft.mode === "in_range" && (
            <DateRangePicker
              dateFrom={draft.dateFrom}
              dateTo={draft.dateTo}
              onChange={(from, to) => setDraft((s) => ({ ...s, dateFrom: from, dateTo: to }))}
            />
          )}
        </div>

        <div className="flex items-center justify-between mt-3">
          {value ? (
            <button
              type="button"
              onClick={clear}
              className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
            >
              <X className="h-3 w-3" /> Clear
            </button>
          ) : (
            <span />
          )}
          <Button size="sm" className="h-7 px-3 text-xs" onClick={apply}>
            Apply
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  );
}
