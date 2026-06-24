import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { Link, useParams } from "react-router-dom";
import {
  ArrowLeft,
  ChevronDown,
  ExternalLink,
  FileText,
  Paperclip,
  RefreshCw,
  Search,
  Sparkles,
  UserRound,
  X,
} from "lucide-react";
import { toast } from "sonner";
import { api } from "@/api/client";
import type {
  IntakeFormResult,
  JiraTransition,
  JiraUser,
  PinAnalysisFields,
  PinAnalysisLabels,
} from "@/api/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Skeleton } from "@/components/ui/skeleton";
import { AnalysisEditor } from "@/components/AnalysisEditor";
import { AttachedFormsPanel } from "@/components/AttachedFormsPanel";
import { CommentsPanel } from "@/components/CommentsPanel";
import { IntakeFormPanel } from "@/components/IntakeFormPanel";
import { MarkdownLite } from "@/components/MarkdownLite";
import { StatusBadge } from "@/components/StatusBadge";
import { TranslatedText } from "@/components/TranslatedText";
import { formatFileSize } from "@/lib/utils";
import { usePinDetail } from "@/hooks/usePinDetail";

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

export function PinDetail() {
  const { key = "" } = useParams();
  const { data, setData, loading, error } = usePinDetail(key);
  const [formBusy, setFormBusy] = useState(false);
  const [formResult, setFormResult] = useState<IntakeFormResult | null>(null);
  const [analyzeBusy, setAnalyzeBusy] = useState(false);
  const [analysis, setAnalysis] = useState<PinAnalysisFields | null>(null);
  const [labels, setLabels] = useState<PinAnalysisLabels | null>(null);
  const [transitions, setTransitions] = useState<JiraTransition[]>([]);
  const [transitionsBusy, setTransitionsBusy] = useState(false);
  const [transitionOpen, setTransitionOpen] = useState(false);
  const [transitioning, setTransitioning] = useState(false);
  const [formsRefreshKey, setFormsRefreshKey] = useState(0);
  const [assigneeOpen, setAssigneeOpen] = useState(false);
  const [assigneeQuery, setAssigneeQuery] = useState("");
  const [assigneeResults, setAssigneeResults] = useState<JiraUser[]>([]);
  const [assigneeSearchBusy, setAssigneeSearchBusy] = useState(false);
  const [assigneeSaving, setAssigneeSaving] = useState(false);
  const [lightboxSrc, setLightboxSrc] = useState<string | null>(null);

  const [translationVersion, setTranslationVersion] = useState(0);

  async function loadForm(
    silent = false,
    reload = false,
  ): Promise<IntakeFormResult | null> {
    setFormBusy(true);
    const tid = silent
      ? null
      : toast.loading(`Loading intake form for ${key}…`);
    try {
      const result = await api.getPinForm(key, reload);
      setFormResult(result);
      if (reload) setTranslationVersion((v) => v + 1);
      if (!silent) {
        if (!result.available) {
          toast.info("No intake form found for this PIN", {
            id: tid ?? undefined,
          });
        } else {
          toast.success("Intake form loaded", { id: tid ?? undefined });
        }
      }
      return result;
    } catch (e) {
      if (!silent)
        toast.error(e instanceof Error ? e.message : String(e), {
          id: tid ?? undefined,
        });
      return null;
    } finally {
      setFormBusy(false);
    }
  }

  useEffect(() => {
    if (!key) return;
    setAnalysis(null);
    setLabels(null);
    setFormResult(null);
    let cancelled = false;
    (async () => {
      // Show cached analysis & form immediately (both ~10 ms when cached).
      const [cached, formCached] = await Promise.all([
        api.getCachedAnalysis(key).catch(() => ({ cached: false } as const)),
        api.getPinForm(key, false).catch(() => null),
      ]);
      if (cancelled) return;

      if (cached.cached && cached.result) {
        const { labels: lbl, ...fields } = cached.result;
        setAnalysis(fields);
        setLabels(lbl ?? null);
      }
      if (formCached !== null) {
        setFormResult(formCached);
      }

      // If form cache was empty (first visit), load from Jira in background.
      if (formCached === null) {
        await loadForm(true);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  async function runAnalysis(force = false, formRes?: IntakeFormResult | null) {
    setAnalyzeBusy(true);
    try {
      const formToUse = formRes ?? formResult;
      const cleanText =
        formToUse && formToUse.available
          ? formToUse.clean_requirements_text
          : undefined;
      const result = await api.analyzePin(key, cleanText, force);
      const { labels: lbl, ...fields } = result;
      setAnalysis(fields);
      setLabels(lbl ?? null);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setAnalyzeBusy(false);
    }
  }

  async function loadTransitions() {
    setTransitionsBusy(true);
    try {
      const result = await api.listTransitions(key);
      setTransitions(result.items);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setTransitionsBusy(false);
    }
  }

  async function applyTransition(transition: JiraTransition) {
    setTransitioning(true);
    setTransitionOpen(false);
    const tid = toast.loading(`Transitioning to "${transition.to_status}"…`);
    try {
      const updated = await api.doTransition(key, transition.id);
      setData(updated);
      toast.success(`Status updated to "${updated.status}"`, { id: tid });
      if (updated.status === "Ready for Technical Review") {
        setFormsRefreshKey((k) => k + 1);
      }
    } catch (e) {
      // Strip the transport "HTTP 400:" prefix — the backend already returns a
      // human-readable Jira message (e.g. unsubmitted forms).
      const msg = (e instanceof Error ? e.message : String(e)).replace(/^HTTP \d+:\s*/, "");
      const jiraUrl = data?.jira_url;
      toast.error(msg, {
        id: tid,
        action: jiraUrl
          ? {
              label: "Open in Jira",
              onClick: () => window.open(jiraUrl, "_blank", "noopener,noreferrer"),
            }
          : undefined,
      });
    } finally {
      setTransitioning(false);
    }
  }

  useEffect(() => {
    if (!assigneeOpen) {
      setAssigneeQuery("");
      setAssigneeResults([]);
      return;
    }
    if (!assigneeQuery.trim()) {
      setAssigneeResults([]);
      return;
    }
    const timer = setTimeout(() => {
      setAssigneeSearchBusy(true);
      api.searchUsers(assigneeQuery)
        .then((r) => setAssigneeResults(r.items))
        .catch(() => setAssigneeResults([]))
        .finally(() => setAssigneeSearchBusy(false));
    }, 300);
    return () => clearTimeout(timer);
  }, [assigneeQuery, assigneeOpen]);

  async function applyAssignee(user: JiraUser) {
    setAssigneeSaving(true);
    setAssigneeOpen(false);
    const tid = toast.loading(`Assigning to ${user.display_name}…`);
    try {
      const updated = await api.updateAssignee(key, user.account_id);
      setData(updated);
      toast.success(`Assigned to ${user.display_name}`, { id: tid });
    } catch (e) {
      const msg = (e instanceof Error ? e.message : String(e)).replace(/^HTTP \d+:\s*/, "");
      toast.error(msg, { id: tid });
    } finally {
      setAssigneeSaving(false);
    }
  }

  if (loading && !data) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-64" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-4">
        <Button asChild variant="ghost" size="sm">
          <Link to="/pins">
            <ArrowLeft /> Back to list
          </Link>
        </Button>
        <div className="rounded-md border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
          {error}
        </div>
      </div>
    );
  }

  if (!data) return null;

  const intakeForm =
    formResult && formResult.available ? formResult : undefined;

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div className="space-y-1">
          <Button
            asChild
            variant="ghost"
            size="sm"
            className="-ml-2 h-7 text-muted-foreground"
          >
            <Link to="/pins">
              <ArrowLeft /> Back to list
            </Link>
          </Button>
          <div className="flex items-center gap-3">
            <h1 className="text-xl font-semibold font-mono">{data.key}</h1>
            {data.reporter && (
              <div className="flex items-center gap-1.5">
                <div className="h-5 w-5 shrink-0 rounded-full bg-muted text-[9px] font-medium text-foreground/70 flex items-center justify-center">
                  {initials(data.reporter)}
                </div>
                <span className="text-xs text-muted-foreground">{data.reporter}</span>
              </div>
            )}
            <Popover
              open={assigneeOpen}
              onOpenChange={(open) => { setAssigneeOpen(open); }}
            >
              <PopoverTrigger asChild>
                <button
                  type="button"
                  disabled={assigneeSaving}
                  className="flex items-center gap-1.5 rounded px-1.5 py-0.5 hover:bg-muted/60 transition-colors disabled:opacity-50"
                  title="Click to reassign"
                >
                  <UserRound className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                  <span className="text-xs text-muted-foreground">
                    {data.assignee || "Unassigned"}
                  </span>
                  <ChevronDown className="h-3 w-3 text-muted-foreground/60" />
                </button>
              </PopoverTrigger>
              <PopoverContent align="start" className="w-64 p-2">
                <div className="relative mb-2">
                  <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
                  <input
                    autoFocus
                    type="text"
                    placeholder="Search users…"
                    value={assigneeQuery}
                    onChange={(e) => setAssigneeQuery(e.target.value)}
                    className="w-full rounded-md border border-input bg-background pl-7 pr-2 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
                  />
                </div>
                {assigneeSearchBusy ? (
                  <div className="px-2 py-1.5 text-xs text-muted-foreground">Searching…</div>
                ) : assigneeQuery.trim() && assigneeResults.length === 0 ? (
                  <div className="px-2 py-1.5 text-xs text-muted-foreground">No users found</div>
                ) : (
                  <ul>
                    {assigneeResults.map((u) => (
                      <li key={u.account_id}>
                        <button
                          type="button"
                          className="w-full flex items-center gap-2 rounded-sm px-2 py-1.5 text-left text-sm hover:bg-accent hover:text-accent-foreground focus:outline-none"
                          onClick={() => void applyAssignee(u)}
                        >
                          {u.avatar_url ? (
                            <img src={u.avatar_url} alt="" className="h-5 w-5 rounded-full shrink-0" />
                          ) : (
                            <div className="h-5 w-5 shrink-0 rounded-full bg-muted text-[9px] font-medium flex items-center justify-center">
                              {initials(u.display_name)}
                            </div>
                          )}
                          <div className="min-w-0">
                            <div className="truncate font-medium">{u.display_name}</div>
                            {u.email && <div className="truncate text-xs text-muted-foreground">{u.email}</div>}
                          </div>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </PopoverContent>
            </Popover>
            <StatusBadge label={data.status} />
            <StatusBadge label={data.urgency} kind="urgency" />
            <a
              href={data.jira_url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
            >
              <ExternalLink className="h-3.5 w-3.5" /> Open in Jira
            </a>
          </div>
          {data.summary && (
            <div className="text-sm text-foreground max-w-3xl">
              {data.summary}
            </div>
          )}
        </div>
        <div className="flex items-center gap-2">
          <Popover
            open={transitionOpen}
            onOpenChange={(open) => {
              setTransitionOpen(open);
              // Always refetch on open — available transitions change after each
              // status change, so a cached list goes stale on consecutive clicks.
              if (open && !transitionsBusy) void loadTransitions();
            }}
          >
            <PopoverTrigger asChild>
              <Button
                variant="outline"
                size="sm"
                disabled={transitioning}
                className="gap-1.5"
              >
                <span className="text-muted-foreground text-xs">Status</span>
                <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
              </Button>
            </PopoverTrigger>
            <PopoverContent align="end" className="w-56 p-1">
              {transitionsBusy ? (
                <div className="px-3 py-2 text-xs text-muted-foreground">
                  Loading…
                </div>
              ) : transitions.length === 0 ? (
                <div className="px-3 py-2 text-xs text-muted-foreground">
                  No transitions available
                </div>
              ) : (
                <ul>
                  {transitions.map((t) => (
                    <li key={t.id}>
                      <button
                        type="button"
                        className="w-full rounded-sm px-3 py-1.5 text-left text-sm hover:bg-accent hover:text-accent-foreground focus:outline-none"
                        onClick={() => void applyTransition(t)}
                      >
                        {t.to_status || t.name}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </PopoverContent>
          </Popover>
          <Button
            variant="outline"
            size="sm"
            onClick={() => void loadForm(false, true)}
            disabled={formBusy || analyzeBusy}
          >
            <RefreshCw className={formBusy ? "animate-spin" : ""} />
            {formBusy ? "Loading…" : "Reload Form"}
          </Button>
          <Button
            size="sm"
            onClick={() =>
              void runAnalysis(
                !!(analysis && Object.values(analysis).some((v) => v.trim())),
              )
            }
            disabled={analyzeBusy || formBusy}
          >
            <Sparkles className={analyzeBusy ? "animate-pulse" : ""} />
            {analyzeBusy
              ? "Analyzing…"
              : analysis && Object.values(analysis).some((v) => v.trim())
                ? "Re-analyze"
                : "Analyze"}
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 items-start">
        <section className="space-y-4 min-w-0">
          <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Original Request
          </div>
          {(data.description_text || (data.description_media_items && data.description_media_items.length > 0)) && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">Description</CardTitle>
              </CardHeader>
              <CardContent>
                {data.description_media_items && data.description_media_items.length > 0 && (
                  <div className="flex flex-wrap gap-2 mb-3">
                    {data.description_media_items.map((m, i) => {
                      if (m.type !== "file") return null;
                      const src = `/api/media/${encodeURIComponent(m.media_id)}?filename=${encodeURIComponent(m.filename || '')}&alt=${encodeURIComponent(m.alt || '')}`;
                      return (
                        <button
                          key={m.media_id || i}
                          type="button"
                          onClick={() => setLightboxSrc(src)}
                          className="cursor-zoom-in"
                        >
                          <img
                            src={src}
                            alt={m.alt || m.filename || "attachment"}
                            loading="lazy"
                            style={{
                              width: m.width ?? undefined,
                              height: m.height ?? undefined,
                              maxWidth: "100%",
                              objectFit: "contain",
                            }}
                            className="rounded-md border border-border bg-muted/30"
                          />
                        </button>
                      );
                    })}
                  </div>
                )}
                {data.description_text && (
                  <MarkdownLite text={data.description_text} />
                )}
                {data.description_text && (
                  <TranslatedText
                    text={data.description_text}
                    pinKey={data.key}
                    field="description"
                    version={translationVersion}
                  />
                )}
              </CardContent>
            </Card>
          )}
          {data.attachments && data.attachments.length > 0 && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm flex items-center gap-1.5">
                  <Paperclip className="h-3.5 w-3.5" />
                  Attachments
                  <span className="text-xs font-normal text-muted-foreground">
                    ({data.attachments.length})
                  </span>
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="flex flex-wrap gap-3">
                  {data.attachments.map((att) => {
                    const isImage = /^image\/(png|jpe?g|gif|webp|svg\+xml|bmp)/i.test(
                      att.mime_type,
                    );
                    if (isImage) {
                      const fullSrc = `/api/media/${encodeURIComponent(att.id)}?filename=${encodeURIComponent(att.filename)}`;
                      const thumbSrc = `/api/media/${encodeURIComponent(att.id)}/thumbnail?filename=${encodeURIComponent(att.filename)}`;
                      return (
                        <button
                          key={att.id}
                          type="button"
                          onClick={() => setLightboxSrc(fullSrc)}
                          className="w-[180px] rounded-md border border-border bg-muted/20 overflow-hidden group shrink-0 relative cursor-zoom-in text-left"
                        >
                          <div className="h-[120px] flex items-center justify-center bg-muted/10">
                            <img
                              src={thumbSrc}
                              alt={att.filename}
                              loading="lazy"
                              className="w-full h-full object-cover"
                            />
                          </div>
                          <div className="absolute inset-x-0 bottom-0 bg-black/60 text-white text-[11px] px-2 py-1 truncate opacity-0 group-hover:opacity-100 transition-opacity">
                            {att.filename}
                          </div>
                        </button>
                      );
                    }
                    return (
                      <div
                        key={att.id}
                        className="w-[180px] rounded-md border border-border shrink-0 flex items-center gap-2 px-2.5 py-2"
                      >
                        <FileText className="h-4 w-4 text-muted-foreground shrink-0" />
                        <div className="flex-1 min-w-0">
                          <span className="text-[11px] font-medium truncate block" title={att.filename}>
                            {att.filename}
                          </span>
                          <span className="text-[10px] text-muted-foreground">
                            {formatFileSize(att.size)}
                          </span>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </CardContent>
            </Card>
          )}
          <AttachedFormsPanel
            pinKey={data.key}
            highlightFormId={intakeForm?.form_id}
            refreshTrigger={formsRefreshKey}
          />
          <IntakeFormPanel
            pinKey={data.key}
            clean={intakeForm?.clean_fields ?? {}}
            fallbackText={intakeForm?.clean_requirements_text}
            notLoadedYet={!formResult}
            translationVersion={translationVersion}
          />
        </section>

        <section className="space-y-4 min-w-0">
          <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            LLM Analysis
          </div>
          <AnalysisEditor
            pinKey={data.key}
            initial={analysis ?? undefined}
            labels={labels}
            onUpdate={setAnalysis}
            busy={analyzeBusy}
          />
        </section>
      </div>

      <CommentsPanel
        pinKey={data.key}
        analysis={analysis ?? undefined}
        defaultMention={
          data.reporter_account_id && data.reporter
            ? {
                account_id: data.reporter_account_id,
                display_name: data.reporter,
                email: data.reporter_email ?? "",
                avatar_url: "",
              }
            : undefined
        }
        onPreviewImage={setLightboxSrc}
      />

      {/* Lightbox overlay — rendered via portal to avoid parent CSS interference */}
      {lightboxSrc &&
        createPortal(
          <div
            className="fixed inset-0 z-50 bg-black/80 flex items-center justify-center p-4"
            onClick={() => setLightboxSrc(null)}
          >
            <button
              type="button"
              className="absolute top-4 right-4 text-white/70 hover:text-white transition-colors"
              onClick={() => setLightboxSrc(null)}
            >
              <X className="h-6 w-6" />
            </button>
            <img
              src={lightboxSrc}
              alt="Preview"
              className="max-w-full max-h-full object-contain rounded-lg"
              onClick={(e) => e.stopPropagation()}
            />
          </div>,
          document.body,
        )}
    </div>
  );
}
