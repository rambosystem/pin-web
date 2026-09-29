import { memo, useEffect, useMemo, useRef, useState } from "react";
import { Loader2 } from "lucide-react";
import type { PinAnalysisFields, PinAnalysisLabels } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { MarkdownLite } from "@/components/MarkdownLite";
import { useSmoothText } from "@/hooks/useSmoothText";
import { cn } from "@/lib/utils";

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

function FieldSkeleton({ label }: { label: string }) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between">
        <Label className="text-sm font-medium text-muted-foreground/80">{label}</Label>
      </div>
      <div className="space-y-2 rounded-md border border-input bg-muted/30 px-3 py-2.5">
        <Skeleton className="h-3 w-full" />
        <Skeleton className="h-3 w-[92%]" />
        <Skeleton className="h-3 w-[78%]" />
      </div>
    </div>
  );
}

/**
 * One rendered field. Memoised so that, while one field is being typed at
 * 60 fps, the other four do not re-parse their Markdown every frame.
 */
const FieldBox = memo(function FieldBox({
  label,
  hint,
  text,
  typing = false,
}: {
  label: string;
  hint: string;
  text: string;
  typing?: boolean;
}) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between">
        <Label className="text-sm font-medium">{label}</Label>
        <span className="text-[11px] text-muted-foreground">{hint}</span>
      </div>
      <div
        className={cn(
          "rounded-md border border-input bg-muted/30 px-3 py-2 min-h-[2.5rem]",
          typing && "typing-caret",
        )}
      >
        <MarkdownLite text={text} />
      </div>
    </div>
  );
});

export function AnalysisEditor({
  pinKey: _pinKey,
  initial,
  labels,
  onUpdate,
  busy = false,
  streaming = null,
}: {
  pinKey: string;
  initial: Partial<PinAnalysisFields> | undefined;
  labels?: PinAnalysisLabels | null;
  onUpdate?: (v: PinAnalysisFields) => void;
  busy?: boolean;
  /**
   * Growing snapshot of the fields while the LLM streams (typewriter mode).
   * Keys appear in the order the model writes them; the last key is the one
   * currently being typed. Null when not streaming.
   */
  streaming?: Partial<PinAnalysisFields> | null;
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
  const receiving = busy && streaming !== null;

  // ---- typewriter smoothing -------------------------------------------
  // While receiving, the smoothing target is the streamed snapshot. When the
  // stream ends we keep the typewriter view ("settling") until the displayed
  // text has caught up with the final result, then switch to the static view
  // so there is no visible jump at the end.
  const [settling, setSettling] = useState(false);
  const prevReceivingRef = useRef(false);
  const typingKeyRef = useRef<keyof PinAnalysisFields | null>(null);

  // Derived during render (not in an effect) so the very first render after
  // the stream ends already shows the typewriter view — no one-frame flash of
  // the static/empty view before an effect could flip `settling`.
  if (receiving !== prevReceivingRef.current) {
    prevReceivingRef.current = receiving;
    if (!receiving) setSettling(true);
  }
  if (receiving) {
    const keys = Object.keys(streaming as object) as (keyof PinAnalysisFields)[];
    if (keys.length) typingKeyRef.current = keys[keys.length - 1];
  }

  const target = useMemo<Record<string, string>>(() => {
    if (receiving) {
      const out: Record<string, string> = {};
      for (const { key } of FIELDS) {
        const v = (streaming as Partial<PinAnalysisFields>)[key];
        if (v !== undefined) out[key] = v;
      }
      return out;
    }
    if (settling) {
      // Use `initial` (the final result) directly: `values` lags one render
      // behind it, and we want the target to be final on the first settling
      // render so the tail types out to exactly what the static view shows.
      const out: Record<string, string> = {};
      for (const { key } of FIELDS) {
        const v = (initial?.[key] || "").trim();
        if (v) out[key] = v;
      }
      return out;
    }
    return {};
  }, [receiving, settling, streaming, initial]);

  const { displayed, settled } = useSmoothText(target);

  useEffect(() => {
    if (settling && !receiving && settled) setSettling(false);
  }, [settling, receiving, settled]);

  const typewriter = receiving || settling;
  const typingKey = typewriter ? typingKeyRef.current : null;

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
        {typewriter && (
          <div className="space-y-5 py-2">
            {receiving && (
              <div className="flex items-center justify-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin text-primary" />
                <span>Generating analysis with LLM…</span>
              </div>
            )}
            {FIELDS.map(({ key, label, hint }) => {
              if (!(key in target)) {
                return receiving ? <FieldSkeleton key={key} label={label} /> : null;
              }
              const text = displayed[key] ?? "";
              // Caret stays on the field being written for the whole stream
              // (even while the display has momentarily caught up), and during
              // settling only until the tail has finished typing out.
              const isTyping =
                key === typingKey && (receiving || text.length < (target[key]?.length ?? 0));
              return <FieldBox key={key} label={label} hint={hint} text={text} typing={isTyping} />;
            })}
          </div>
        )}
        {!typewriter && !busy && hasContent && labels && <LabelChips labels={labels} />}
        {!typewriter && busy && (
          <div className="space-y-5 py-2">
            <div className="flex items-center justify-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin text-primary" />
              <span>Generating analysis with LLM…</span>
            </div>
            {FIELDS.map(({ key, label }) => (
              <FieldSkeleton key={key} label={label} />
            ))}
          </div>
        )}
        {!typewriter && !hasContent && !busy && (
          <div className="py-6 text-sm text-muted-foreground text-center italic">
            No analysis yet — click <strong>Analyze</strong> to run.
          </div>
        )}
        {!typewriter && !busy && hasContent && FIELDS.map(({ key, label, hint }) => {
          const v = (values[key] || "").trim();
          if (!v) return null;
          return <FieldBox key={key} label={label} hint={hint} text={v} />;
        })}
      </CardContent>
    </Card>
  );
}
