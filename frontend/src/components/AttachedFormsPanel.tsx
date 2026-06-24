import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { CheckCircle2, Circle, FileText, Lock, RefreshCw, Send, Sparkles, X } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import type { AssessmentField, AttachedForm } from "@/api/types";

/** The form whose simplified assessment panel we drive. */
const ASSESSMENT_FORM_NAME = "Technical Assessment Form";

type SelMap = Record<string, string | string[]>;

type DraftCacheEntry = { fields: AssessmentField[]; selections: SelMap };
// In-memory (session) cache of unsubmitted assessment edits, keyed by pin+form.
// Lets a closed/reopened draft restore in-progress answers (incl. the AI
// explanation). Cleared on submit; lost on full page reload — intentionally
// temporary, not persisted.
const draftCache = new Map<string, DraftCacheEntry>();
const cacheKey = (pinKey: string, formId: string) => `${pinKey}::${formId}`;

function fmtRelative(iso: string): string {
  if (!iso) return "";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return iso;
  const diff = (Date.now() - t) / 1000;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  if (diff < 86400 * 30) return `${Math.floor(diff / 86400)}d ago`;
  return new Date(t).toLocaleDateString();
}

function labelForId(field: AssessmentField, id: string): string {
  return field.options.find((o) => o.id === id)?.label ?? "";
}

/**
 * Seed the form state. A submitted form is seeded from its saved answers (read
 * only view); a draft starts as an empty template — choice defaults selected,
 * text fields (incl. the AI explanation) blank.
 */
function seedSelections(fields: AssessmentField[], submitted: boolean): SelMap {
  const sel: SelMap = {};
  for (const f of fields) {
    if (submitted) {
      sel[f.id] = f.value;
    } else if (f.kind === "single") {
      const opt = f.options.find((o) => o.label === f.default) ?? f.options[0];
      sel[f.id] = opt ? opt.id : "";
    } else if (f.kind === "multi") {
      const opt = f.options.find((o) => o.label === f.default) ?? f.options[0];
      sel[f.id] = opt ? [opt.id] : [];
    } else {
      sel[f.id] = "";
    }
  }
  return sel;
}

interface Props {
  pinKey: string;
  /** Highlight the form whose id matches (e.g. the locally cached intake form). */
  highlightFormId?: string;
  /** Increment to trigger a forms list reload from outside (e.g. after a status transition). */
  refreshTrigger?: number;
}

export function AttachedFormsPanel({ pinKey, highlightFormId, refreshTrigger }: Props) {
  const [items, setItems] = useState<AttachedForm[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Technical Assessment form modal. Opening shows the empty template (choice
  // defaults, blank text) for a draft, or the saved answers (read-only) for a
  // submitted form. "Add a short explanation" is drafted on demand by the AI
  // button inside its textarea; Submit writes + finalizes the Jira form.
  const [genForm, setGenForm] = useState<AttachedForm | null>(null);
  const [fields, setFields] = useState<AssessmentField[]>([]);
  const [selections, setSelections] = useState<SelMap>({});
  const [genBusy, setGenBusy] = useState(false);
  const [explaining, setExplaining] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [genError, setGenError] = useState<string | null>(null);
  const reqIdRef = useRef(0);

  const readOnly = !!genForm && (genForm.submitted || genForm.lock);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.listForms(pinKey);
      setItems(res.items);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [pinKey]);

  useEffect(() => {
    void load();
  }, [load]);

  const isFirstRender = useRef(true);
  useEffect(() => {
    if (isFirstRender.current) { isFirstRender.current = false; return; }
    if (refreshTrigger === undefined) return;
    void load();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshTrigger]);

  function cleanErr(e: unknown): string {
    return (e instanceof Error ? e.message : String(e)).replace(/^HTTP \d+:\s*/, "");
  }

  async function openForm(form: AttachedForm) {
    const reqId = ++reqIdRef.current;
    setGenForm(form);
    setGenError(null);

    // Drafts: restore any in-progress edits from the session cache (instant,
    // no refetch). Submitted/locked forms always show the saved Jira answers.
    const editable = !form.submitted && !form.lock;
    const cached = editable ? draftCache.get(cacheKey(pinKey, form.id)) : undefined;
    if (cached) {
      setFields(cached.fields);
      setSelections(cached.selections);
      setGenBusy(false);
      return;
    }

    setFields([]);
    setSelections({});
    setGenBusy(true);
    try {
      const res = await api.assessmentDraft(pinKey, form.id);
      if (reqIdRef.current !== reqId) return; // stale (closed / reopened)
      setFields(res.fields);
      setSelections(seedSelections(res.fields, form.submitted));
    } catch (e) {
      if (reqIdRef.current !== reqId) return;
      setGenError(cleanErr(e));
    } finally {
      if (reqIdRef.current === reqId) setGenBusy(false);
    }
  }

  // Persist in-progress draft edits to the session cache so a reopened modal
  // restores them. Only for editable (unsubmitted) forms with a loaded model.
  useEffect(() => {
    if (genForm && !readOnly && fields.length) {
      draftCache.set(cacheKey(pinKey, genForm.id), { fields, selections });
    }
  }, [genForm, readOnly, fields, selections, pinKey]);

  // Draft / re-draft the "Add a short explanation" text from PIN comments.
  async function generateExplain() {
    if (!genForm) return;
    const ai = fields.find((f) => f.ai);
    if (!ai) return;
    setExplaining(true);
    setGenError(null);
    try {
      const res = await api.assessmentExplain(pinKey, genForm.id);
      setSelections((s) => ({ ...s, [ai.id]: res.explanation }));
      if (!res.explanation.trim()) toast.message("No comments to draft from");
    } catch (e) {
      setGenError(cleanErr(e));
    } finally {
      setExplaining(false);
    }
  }

  function closeGen() {
    reqIdRef.current++; // invalidate any in-flight request
    setGenForm(null);
    setFields([]);
    setSelections({});
    setGenError(null);
    setGenBusy(false);
    setExplaining(false);
    setSubmitting(false);
  }

  /** A field applies only when its gating question's answer is in gate.values. */
  function isVisible(f: AssessmentField): boolean {
    if (!f.gate) return true;
    const gating = fields.find((g) => g.label === f.gate!.by);
    if (!gating) return true;
    const sel = selections[gating.id];
    const labels = Array.isArray(sel)
      ? sel.map((id) => labelForId(gating, id))
      : [labelForId(gating, sel as string)];
    return f.gate.values.some((v) => labels.includes(v));
  }

  function isEmpty(f: AssessmentField): boolean {
    const v = selections[f.id];
    return f.kind === "multi"
      ? !(Array.isArray(v) && v.length)
      : !(typeof v === "string" ? v.trim() : v);
  }

  async function submit() {
    if (!genForm) return;
    const visible = fields.filter(isVisible);
    const missing = visible.find(isEmpty);
    if (missing) {
      toast.error(`Please fill “${missing.label}”`);
      return;
    }
    const answers: Record<string, string | string[]> = {};
    for (const f of visible) answers[f.id] = selections[f.id];
    setSubmitting(true);
    setGenError(null);
    try {
      await api.submitAssessment(pinKey, genForm.id, answers, true);
      draftCache.delete(cacheKey(pinKey, genForm.id)); // submitted — drop the draft
      toast.success("Assessment submitted to Jira");
      closeGen();
      void load();
    } catch (e) {
      setGenError(cleanErr(e));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <>
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-3">
        <CardTitle className="text-sm flex items-center gap-2">
          <FileText className="h-4 w-4 text-muted-foreground" />
          Attached Forms
          {items && (
            <span className="text-xs text-muted-foreground font-normal">
              ({items.length})
            </span>
          )}
        </CardTitle>
        <Button
          variant="ghost"
          size="sm"
          className="h-7 px-2 text-xs text-muted-foreground"
          onClick={load}
          disabled={loading}
        >
          <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} />
          Refresh
        </Button>
      </CardHeader>
      <CardContent className="pt-0">
        {loading && !items && (
          <div className="space-y-2">
            <Skeleton className="h-10" />
            <Skeleton className="h-10" />
          </div>
        )}

        {error && (
          <div className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive">
            {error}
          </div>
        )}

        {items && items.length === 0 && !error && (
          <div className="py-2 text-xs text-muted-foreground">
            No ProForma forms attached to this issue.
          </div>
        )}

        {items && items.length > 0 && (
          <ul className="divide-y divide-border -mx-2">
            {items.map((f) => {
              const isHighlighted =
                highlightFormId && f.id === highlightFormId;
              // Only the Technical Assessment Form opens our panel; the Draft
              // badge is the trigger (drafts edit, submitted view read-only).
              const openable = f.name === ASSESSMENT_FORM_NAME;
              return (
                <li
                  key={f.id}
                  className={cn(
                    "flex items-center justify-between gap-3 px-2 py-2 text-sm",
                    isHighlighted && "bg-muted/40 rounded-md"
                  )}
                >
                  <div className="flex items-center gap-2 min-w-0">
                    {f.submitted ? (
                      <CheckCircle2 className="h-4 w-4 text-emerald-600 dark:text-emerald-500 shrink-0" />
                    ) : (
                      <Circle className="h-4 w-4 text-muted-foreground shrink-0" />
                    )}
                    <span className="font-medium truncate">{f.name || "(unnamed form)"}</span>
                    {f.lock && (
                      <Lock
                        className="h-3 w-3 text-muted-foreground shrink-0"
                        aria-label="Locked"
                      />
                    )}
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    {openable ? (
                      <button
                        type="button"
                        onClick={() => void openForm(f)}
                        disabled={genBusy && genForm?.id === f.id}
                        title={f.submitted ? "View submitted assessment" : "Open assessment form"}
                      >
                        <Badge
                          variant={f.submitted ? "default" : "outline"}
                          className="font-normal cursor-pointer hover:opacity-80"
                        >
                          {f.submitted ? "Submitted" : "Draft"}
                        </Badge>
                      </button>
                    ) : (
                      <Badge
                        variant={f.submitted ? "default" : "outline"}
                        className="font-normal"
                      >
                        {f.submitted ? "Submitted" : "Draft"}
                      </Badge>
                    )}
                    {f.updated && (
                      <span
                        className="text-xs text-muted-foreground tabular-nums"
                        title={f.updated}
                      >
                        {fmtRelative(f.updated)}
                      </span>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </CardContent>
    </Card>

    {genForm &&
      createPortal(
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
          onClick={closeGen}
        >
          <div
            className="flex w-full max-w-2xl max-h-[85vh] flex-col rounded-lg border bg-background shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between gap-2 border-b px-4 py-3">
              <div className="flex items-center gap-2 text-sm font-medium min-w-0">
                <FileText className="h-4 w-4 text-muted-foreground shrink-0" />
                <span className="truncate">{genForm.name || "Form"}</span>
                {readOnly && (
                  <Badge variant="secondary" className="font-normal">Read only</Badge>
                )}
                {genBusy && (
                  <RefreshCw className="h-3.5 w-3.5 animate-spin text-muted-foreground shrink-0" />
                )}
              </div>
              <button
                type="button"
                onClick={closeGen}
                className="text-muted-foreground hover:text-foreground"
                aria-label="Close"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="flex-1 min-h-0 overflow-y-auto px-4 py-3 space-y-4">
              {genError && (
                <div className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive whitespace-pre-wrap">
                  {genError}
                </div>
              )}

              {genBusy && fields.length === 0 ? (
                <div className="space-y-3">
                  <Skeleton className="h-9" />
                  <Skeleton className="h-9" />
                  <Skeleton className="h-20" />
                </div>
              ) : (
                fields.filter(isVisible).map((f) => {
                  const sel = selections[f.id];
                  return (
                    <div key={f.id} className="space-y-1.5">
                      <Label className="text-xs font-semibold">
                        {f.label}
                        {f.ai && (
                          <span className="ml-1 font-normal text-muted-foreground">(AI)</span>
                        )}
                      </Label>

                      {f.kind === "single" && (
                        <select
                          className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-60"
                          value={typeof sel === "string" ? sel : ""}
                          disabled={readOnly}
                          onChange={(e) =>
                            setSelections((s) => ({ ...s, [f.id]: e.target.value }))
                          }
                        >
                          {f.options.map((o) => (
                            <option key={o.id} value={o.id}>
                              {o.label}
                            </option>
                          ))}
                        </select>
                      )}

                      {f.kind === "multi" && (
                        <div className="flex flex-wrap gap-x-4 gap-y-2 pt-0.5">
                          {f.options.map((o) => {
                            const arr = Array.isArray(sel) ? sel : [];
                            return (
                              <label
                                key={o.id}
                                className={cn(
                                  "flex items-center gap-2 text-sm",
                                  readOnly ? "opacity-70" : "cursor-pointer"
                                )}
                              >
                                <Checkbox
                                  checked={arr.includes(o.id)}
                                  disabled={readOnly}
                                  onCheckedChange={(c) =>
                                    setSelections((s) => {
                                      const cur = Array.isArray(s[f.id]) ? (s[f.id] as string[]) : [];
                                      return {
                                        ...s,
                                        [f.id]: c
                                          ? [...cur, o.id]
                                          : cur.filter((x) => x !== o.id),
                                      };
                                    })
                                  }
                                />
                                {o.label}
                              </label>
                            );
                          })}
                        </div>
                      )}

                      {f.kind === "text" && (
                        <div className="relative">
                          <Textarea
                            className={cn("min-h-[80px] text-sm", f.ai && !readOnly && "pb-9")}
                            value={typeof sel === "string" ? sel : ""}
                            readOnly={readOnly}
                            placeholder={f.ai && !readOnly ? "Click AI Draft to generate from comments, or type here." : ""}
                            onChange={(e) =>
                              setSelections((s) => ({ ...s, [f.id]: e.target.value }))
                            }
                          />
                          {f.ai && !readOnly && (
                            <Button
                              type="button"
                              variant="outline"
                              size="sm"
                              className="absolute bottom-2 right-2 h-6 gap-1 px-1.5 text-[11px]"
                              onClick={() => void generateExplain()}
                              disabled={explaining}
                              title="Draft this from the PIN's comments"
                            >
                              {explaining ? (
                                <RefreshCw className="h-3 w-3 animate-spin" />
                              ) : (
                                <Sparkles className="h-3 w-3" />
                              )}
                              {explaining ? "Drafting…" : "AI Draft"}
                            </Button>
                          )}
                        </div>
                      )}

                      {f.kind === "date" && (
                        <input
                          type="date"
                          className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:opacity-60"
                          value={typeof sel === "string" ? sel : ""}
                          disabled={readOnly}
                          onChange={(e) =>
                            setSelections((s) => ({ ...s, [f.id]: e.target.value }))
                          }
                        />
                      )}
                    </div>
                  );
                })
              )}
            </div>

            <div className="flex items-center justify-between gap-2 border-t px-4 py-3">
              <span className="text-[11px] text-muted-foreground">
                {readOnly
                  ? "This form is already submitted — read only."
                  : "Submitting writes these answers to Jira and finalizes the form."}
              </span>
              {!readOnly && (
                <Button
                  size="sm"
                  onClick={() => void submit()}
                  disabled={genBusy || submitting || explaining || fields.length === 0}
                >
                  <Send className={cn("h-3.5 w-3.5", submitting && "animate-pulse")} />
                  {submitting ? "Submitting…" : "Submit"}
                </Button>
              )}
            </div>
          </div>
        </div>,
        document.body
      )}
    </>
  );
}
