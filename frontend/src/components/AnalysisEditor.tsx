import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import type { PinAnalysisFields, PinAnalysisLabels } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { MarkdownLite } from "@/components/MarkdownLite";

const FIELDS: { key: keyof PinAnalysisFields; label: string; hint: string }[] = [
  { key: "form_request", label: "Form Request", hint: "User's literal ask from the intake form (2-5 sentences)." },
  { key: "background",   label: "Background",   hint: "Context, customers involved, why now." },
  { key: "problem",      label: "Problem",      hint: "The product issue this PIN aims to solve." },
  { key: "expectation",  label: "Expectation",  hint: "Concrete asks / acceptance hints." },
  { key: "impact",       label: "Business Impact", hint: "What changes if we build it; retention/revenue/efficiency." },
];

function emptyFields(): PinAnalysisFields {
  return { form_request: "", problem: "", background: "", impact: "", expectation: "" };
}

function LabelChips({ labels }: { labels: PinAnalysisLabels }) {
  const module = (labels.module || "").trim();
  const nature = (labels.nature || "").trim();
  if (!module && !nature) return null;
  return (
    <div className="flex flex-wrap items-center gap-2">
      {module && <Badge variant="secondary">{module}</Badge>}
      {nature && <Badge variant="secondary">{nature}</Badge>}
    </div>
  );
}

export function AnalysisEditor({
  pinKey: _pinKey,
  initial,
  labels,
  onUpdate,
  busy = false,
}: {
  pinKey: string;
  initial: Partial<PinAnalysisFields> | undefined;
  labels?: PinAnalysisLabels | null;
  onUpdate?: (v: PinAnalysisFields) => void;
  busy?: boolean;
}) {
  const [values, setValues] = useState<PinAnalysisFields>({ ...emptyFields(), ...(initial || {}) });

  useEffect(() => {
    const next = { ...emptyFields(), ...(initial || {}) };
    setValues(next);
    const hasContent = Object.values(next).some((v) => v.trim());
    if (hasContent) onUpdate?.(next);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initial?.form_request, initial?.problem, initial?.background, initial?.impact, initial?.expectation]);

  const hasContent = Object.values(values).some((v) => v.trim());

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm">LLM Analysis</CardTitle>
        <p className="text-xs text-muted-foreground mt-1">
          Analysis is auto-triggered when viewing a PIN with an intake form.
          Use <strong>Re-analyze</strong> to refresh after form updates.
          Results are cached for 7 days and persisted to disk.
        </p>
      </CardHeader>
      <CardContent className="space-y-4">
        {hasContent && labels && <LabelChips labels={labels} />}
        {!hasContent && busy && (
          <div className="space-y-5 py-2">
            <div className="flex items-center justify-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin text-primary" />
              <span>Generating analysis with LLM…</span>
            </div>
            {FIELDS.map(({ key, label }) => (
              <div key={key} className="space-y-1.5">
                <div className="flex items-baseline justify-between">
                  <Label className="text-sm font-medium text-muted-foreground/80">
                    {label}
                  </Label>
                </div>
                <div className="space-y-2 rounded-md border border-input bg-muted/30 px-3 py-2.5">
                  <Skeleton className="h-3 w-full" />
                  <Skeleton className="h-3 w-[92%]" />
                  <Skeleton className="h-3 w-[78%]" />
                </div>
              </div>
            ))}
          </div>
        )}
        {!hasContent && !busy && (
          <div className="py-6 text-sm text-muted-foreground text-center italic">
            No analysis yet — click <strong>Analyze</strong> to run.
          </div>
        )}
        {hasContent && FIELDS.map(({ key, label, hint }) => {
          const v = (values[key] || "").trim();
          if (!v) return null;
          return (
            <div key={key} className="space-y-1.5">
              <div className="flex items-baseline justify-between">
                <Label className="text-sm font-medium">{label}</Label>
                <span className="text-[11px] text-muted-foreground">{hint}</span>
              </div>
              <div className="rounded-md border border-input bg-muted/30 px-3 py-2 min-h-[2.5rem]">
                <MarkdownLite text={v} />
              </div>
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}

