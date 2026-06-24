import { useMemo, useState } from "react";
import { ChevronDown, Search, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Separator } from "@/components/ui/separator";

export function MultiFilter({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: string[];
  value: string[];
  onChange: (next: string[]) => void;
}) {
  const [search, setSearch] = useState("");

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return options;
    return options.filter((o) => o.toLowerCase().includes(q));
  }, [options, search]);

  const selected = new Set(value);
  const toggle = (opt: string) => {
    const next = new Set(selected);
    if (next.has(opt)) next.delete(opt);
    else next.add(opt);
    onChange(Array.from(next));
  };

  return (
    <Popover onOpenChange={(open) => { if (!open) setSearch(""); }}>
      <PopoverTrigger asChild>
        <Button variant="outline" size="sm" className="gap-1.5">
          <span>{label}</span>
          {value.length > 0 && (
            <span className="ml-1 inline-flex items-center justify-center rounded bg-primary px-1.5 text-[10px] font-semibold text-primary-foreground">
              {value.length}
            </span>
          )}
          <ChevronDown className="h-3.5 w-3.5 opacity-60" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-64 p-2" align="start">
        <div className="relative mb-1">
          <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
          <Input
            placeholder={`Search ${label.toLowerCase()}…`}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-7 h-8 text-xs"
          />
        </div>
        <div className="flex items-center justify-between px-2 py-1.5 text-xs text-muted-foreground">
          {value.length > 0 ? (
            <button
              type="button"
              onClick={() => onChange([])}
              className="inline-flex items-center gap-1 hover:text-foreground"
            >
              <X className="h-3 w-3" /> Clear
            </button>
          ) : (
            <span>{filtered.length} options</span>
          )}
        </div>
        <Separator />
        <div className="max-h-72 overflow-auto py-1 scrollbar-thin">
          {filtered.length === 0 ? (
            <div className="px-2 py-3 text-xs text-muted-foreground">
              {search.trim() ? "No matches" : "No options"}
            </div>
          ) : (
            filtered.map((opt) => {
              const id = `${label}-${opt}`;
              return (
                <Label
                  key={opt}
                  htmlFor={id}
                  className="flex cursor-pointer items-center gap-2 rounded-sm px-2 py-1.5 text-sm font-normal hover:bg-accent"
                >
                  <Checkbox
                    id={id}
                    checked={selected.has(opt)}
                    onCheckedChange={() => toggle(opt)}
                  />
                  <span className="truncate">{opt}</span>
                </Label>
              );
            })
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}
