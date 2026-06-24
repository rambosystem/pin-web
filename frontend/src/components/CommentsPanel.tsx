import { useCallback, useEffect, useRef, useState } from "react";
import { Lock, MessageSquare, RefreshCw, Send, Sparkles, Users, X } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/api/client";
import type { JiraComment, JiraUser, PinAnalysisFields } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { MarkdownLite } from "@/components/MarkdownLite";
import { MentionEditor, type MentionEditorHandle } from "@/components/MentionEditor";
import { cn } from "@/lib/utils";

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

function formatTime(iso: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString();
}

export function CommentsPanel({
  pinKey,
  analysis,
  defaultMention,
  onPreviewImage,
}: {
  pinKey: string;
  analysis?: PinAnalysisFields;
  defaultMention?: JiraUser;
  onPreviewImage?: (src: string) => void;
}) {
  const [items, setItems] = useState<JiraComment[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [posting, setPosting] = useState(false);
  const [showAi, setShowAi] = useState(false);
  const [aiPrompt, setAiPrompt] = useState("");
  const [generating, setGenerating] = useState(false);
  const [isInternal, setIsInternal] = useState(false);
  const [editorEmpty, setEditorEmpty] = useState(true);

  const editorRef = useRef<MentionEditorHandle | null>(null);

  const load = useCallback(async () => {
    if (!pinKey) return;
    setLoading(true);
    setError(null);
    try {
      const res = await api.listComments(pinKey);
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

  async function submit() {
    if (posting) return;
    const { text, mentions } = editorRef.current?.getValue() ?? { text: "", mentions: {} };
    const body = text.trim();
    if (!body) return;
    setPosting(true);
    const tid = toast.loading("Posting comment...");
    try {
      const usedMentions: Record<string, string> = {};
      for (const [name, id] of Object.entries(mentions)) {
        if (body.includes(`@${name}`)) usedMentions[name] = id;
      }
      const res = await api.addComment(
        pinKey,
        body,
        Object.keys(usedMentions).length ? usedMentions : undefined,
        isInternal
      );
      setItems((prev) => [...prev, res.comment]);
      editorRef.current?.clear();
      toast.success(isInternal ? "Internal note added" : "Comment posted", { id: tid });
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e), { id: tid });
    } finally {
      setPosting(false);
    }
  }

  async function generate() {
    const prompt = aiPrompt.trim();
    if (!prompt || generating) return;
    setGenerating(true);
    editorRef.current?.setText("");
    const tid = toast.loading("Drafting reply with AI...");
    try {
      const recent = items.slice(-10).map((c) => ({
        author: c.author,
        body_text: c.body_text,
        created: c.created,
      }));
      let accumulated = "";
      await api.draftAiReplyStream(
        pinKey,
        prompt,
        recent,
        (delta) => {
          accumulated += delta;
          editorRef.current?.setText(accumulated);
        },
        undefined,
        analysis
      );
      if (!accumulated.trim()) {
        throw new Error("LLM returned empty content");
      }
      toast.success("Draft ready – review then Reply", { id: tid });
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e), { id: tid });
    } finally {
      setGenerating(false);
    }
  }

  function onAiPromptKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      e.preventDefault();
      void generate();
    }
  }

  return (
    <Card className="flex flex-col max-h-[calc(100vh-220px)]">
      <CardHeader className="flex flex-row items-start justify-between space-y-0 shrink-0">
        <div>
          <CardTitle className="text-sm flex items-center gap-2">
            <MessageSquare className="h-4 w-4" />
            Comments
            <span className="text-xs font-normal text-muted-foreground">
              ({items.length})
            </span>
          </CardTitle>
          <p className="text-xs text-muted-foreground mt-1">
            Live from Jira. New replies post directly to the PIN ticket.
          </p>
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => void load()}
          disabled={loading}
          className="h-7 px-2 text-xs"
        >
          <RefreshCw className={loading ? "animate-spin" : ""} />
          Refresh
        </Button>
      </CardHeader>
      <CardContent className="flex-1 flex flex-col gap-4 min-h-0">
        <div className="space-y-2 shrink-0">
          <MentionEditor
            ref={editorRef}
            disabled={posting || generating}
            internal={isInternal}
            defaultUser={defaultMention}
            onSubmit={() => void submit()}
            onEmptyChange={setEditorEmpty}
            placeholder={
              generating
                ? "AI is drafting…"
                : isInternal
                ? "Internal note (visible to agents only)… (Ctrl/Cmd + Enter to send)"
                : "Reply to customer… Type @ to mention. (Ctrl/Cmd + Enter to send)"
            }
          />
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-1 rounded-md border p-0.5 bg-muted/50">
              <button
                type="button"
                onClick={() => setIsInternal(false)}
                className={cn(
                  "flex items-center gap-1 rounded px-2 py-1 text-xs font-medium transition-colors",
                  !isInternal ? "bg-background shadow-sm text-foreground" : "text-muted-foreground hover:text-foreground"
                )}
              >
                <Users className="h-3 w-3" />
                Reply to customer
              </button>
              <button
                type="button"
                onClick={() => setIsInternal(true)}
                className={cn(
                  "flex items-center gap-1 rounded px-2 py-1 text-xs font-medium transition-colors",
                  isInternal ? "bg-amber-100 shadow-sm text-amber-800 dark:bg-amber-900/40 dark:text-amber-300" : "text-muted-foreground hover:text-foreground"
                )}
              >
                <Lock className="h-3 w-3" />
                Internal note
              </button>
            </div>
            <div className="flex items-center gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setShowAi((v) => !v)}
                disabled={posting}
                title="Draft with AI"
                className={cn(showAi && "ring-1 ring-primary/40")}
              >
                <Sparkles className="h-4 w-4" />
                AI
              </Button>
              <Button
                size="sm"
                onClick={() => void submit()}
                disabled={posting || generating || editorEmpty}
                className={cn(isInternal && "bg-amber-500 hover:bg-amber-600 text-white")}
              >
                <Send className={posting ? "animate-pulse" : ""} />
                {posting ? "Posting…" : isInternal ? "Add note" : "Reply"}
              </Button>
            </div>
          </div>

          {showAi && (
            <div className="rounded-md border border-primary/30 bg-primary/5 p-2.5 space-y-2">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1.5 text-xs font-medium">
                  <Sparkles className="h-3.5 w-3.5 text-primary" />
                  AI draft prompt
                </div>
                <button
                  type="button"
                  onClick={() => setShowAi(false)}
                  className="text-muted-foreground hover:text-foreground"
                  aria-label="Close AI prompt"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
              <Textarea
                value={aiPrompt}
                onChange={(e) => setAiPrompt(e.target.value)}
                onKeyDown={onAiPromptKeyDown}
                rows={2}
                disabled={generating}
                placeholder="e.g. Ask for clarification on urgency and target customers; suggest next steps..."
                className="text-sm bg-background"
              />
              <div className="flex items-center justify-between gap-2">
                <span className="text-[11px] text-muted-foreground">
                  Generated text fills the reply box for review.
                </span>
                <Button
                  size="sm"
                  onClick={() => void generate()}
                  disabled={generating || !aiPrompt.trim()}
                >
                  <Sparkles className={generating ? "animate-pulse" : ""} />
                  {generating ? "Generating…" : "Generate"}
                </Button>
              </div>
            </div>
          )}
        </div>

        <div className="flex-1 min-h-0 overflow-y-auto -mr-2 pr-2 space-y-3">
          {error && (
            <div className="rounded-md border border-destructive/30 bg-destructive/5 p-3 text-xs text-destructive">
              {error}
            </div>
          )}

          {loading && items.length === 0 ? (
            <div className="space-y-2">
              <Skeleton className="h-16 w-full" />
              <Skeleton className="h-16 w-full" />
            </div>
          ) : items.length === 0 && !error ? (
            <div className="text-center text-xs text-muted-foreground py-6">
              No comments yet on this PIN.
            </div>
          ) : (
            items.map((c) => (
              <div key={c.id} className={cn("flex gap-3 rounded-md p-1.5 -mx-1.5", c.internal && "bg-amber-50/60 dark:bg-amber-950/20 border border-amber-200/60 dark:border-amber-800/40")}>
                <div className="h-7 w-7 shrink-0 rounded-full bg-muted text-[11px] font-medium text-foreground/70 flex items-center justify-center">
                  {initials(c.author)}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-baseline gap-2 flex-wrap">
                    <span className="text-sm font-medium">{c.author}</span>
                    <span className="text-[11px] text-muted-foreground">
                      {formatTime(c.created)}
                      {c.updated && c.updated !== c.created && (
                        <span className="ml-1">(edited)</span>
                      )}
                    </span>
                    {c.internal && (
                      <span className="inline-flex items-center gap-0.5 rounded px-1 py-0.5 text-[10px] font-medium bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300">
                        <Lock className="h-2.5 w-2.5" />
                        Internal note
                      </span>
                    )}
                  </div>
                  {c.media_items && c.media_items.length > 0 && (
                    <div className="mt-1.5 flex flex-wrap gap-2">
                      {c.media_items.map((m, i) => {
                        if (m.type !== "file") return null;
                        const src = `/api/media/${encodeURIComponent(m.media_id)}?filename=${encodeURIComponent(m.filename || '')}&alt=${encodeURIComponent(m.alt || '')}`;
                        const imgEl = (
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
                        );
                        if (onPreviewImage) {
                          return (
                            <button
                              key={m.media_id || i}
                              type="button"
                              onClick={() => onPreviewImage(src)}
                              className="cursor-zoom-in"
                            >
                              {imgEl}
                            </button>
                          );
                        }
                        return <span key={m.media_id || i}>{imgEl}</span>;
                      })}
                    </div>
                  )}
                  <div className="mt-0.5 min-w-0">
                    {c.body_text ? (
                      <MarkdownLite text={c.body_text} className="text-foreground/90" />
                    ) : (
                      <span className="text-sm italic text-muted-foreground">
                        (empty)
                      </span>
                    )}
                  </div>
                </div>
              </div>
            ))
          )}
        </div>
      </CardContent>
    </Card>
  );
}
