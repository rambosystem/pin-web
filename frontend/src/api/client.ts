import type {
  AnalyzeResult,
  AssessmentDraftResponse,
  AssessmentExplainResponse,
  AssessmentSubmitResponse,
  AttachedFormsResponse,
  CachedAnalysisResponse,
  IntakeFormResult,
  JiraComment,
  JiraCommentsResponse,
  JiraTransitionsResponse,
  JiraUser,
  PinAnalysisFields,
  PinDetail,
  PinListResponse,
  Profile,
  SubmittedFormsResponse,
} from "./types";

const BASE = "/api";

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let detail = "";
    try {
      const body = await res.json();
      detail = body.detail || JSON.stringify(body);
    } catch {
      detail = await res.text().catch(() => "");
    }
    throw new Error(`HTTP ${res.status}: ${detail || res.statusText}`);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  listPins: () => http<PinListResponse>("/pins"),
  getPin: (key: string) => http<PinDetail>(`/pins/${encodeURIComponent(key)}`),
  getPinForm: (key: string, reload = false) =>
    http<IntakeFormResult>(`/pins/${encodeURIComponent(key)}/form${reload ? "?reload=true" : ""}`),
  analyzePin: (key: string, cleanRequirementsText?: string, force = false) =>
    http<AnalyzeResult>(`/pins/${encodeURIComponent(key)}/analyze?force=${force}`, {
      method: "POST",
      body: JSON.stringify({ clean_requirements_text: cleanRequirementsText ?? null }),
    }),
  getCachedAnalysis: async (key: string, cleanRequirementsText?: string) => {
    const params = new URLSearchParams();
    if (cleanRequirementsText !== undefined) {
      const encoded = new TextEncoder().encode(cleanRequirementsText);
      const hashBuf = await crypto.subtle.digest("SHA-256", encoded);
      const hashHex = Array.from(new Uint8Array(hashBuf))
        .map((b) => b.toString(16).padStart(2, "0"))
        .join("")
        .slice(0, 8);
      params.set("clean_text_hash", hashHex);
    }
    return http<CachedAnalysisResponse>(
      `/pins/${encodeURIComponent(key)}/analyze?${params.toString()}`
    );
  },
  listForms: (key: string) =>
    http<AttachedFormsResponse>(`/pins/${encodeURIComponent(key)}/forms`),
  listSubmittedForms: (key: string) =>
    http<SubmittedFormsResponse>(
      `/pins/${encodeURIComponent(key)}/forms/submitted`
    ),
  profile: () => http<Profile>("/profile"),
  listComments: (key: string) =>
    http<JiraCommentsResponse>(`/pins/${encodeURIComponent(key)}/comments`),
  addComment: (
    key: string,
    body: string,
    mentions?: Record<string, string>,
    internal?: boolean
  ) =>
    http<{ ok: boolean; comment: JiraComment }>(
      `/pins/${encodeURIComponent(key)}/comments`,
      { method: "POST", body: JSON.stringify({ body, mentions, internal: internal ?? false }) }
    ),
  searchUsers: (q: string) =>
    http<{ items: JiraUser[] }>(
      `/users/search?q=${encodeURIComponent(q)}`
    ),
  updateAssignee: (key: string, accountId: string) =>
    http<PinDetail>(`/pins/${encodeURIComponent(key)}/assignee`, {
      method: "PUT",
      body: JSON.stringify({ account_id: accountId }),
    }),
  listTransitions: (key: string) =>
    http<JiraTransitionsResponse>(`/pins/${encodeURIComponent(key)}/transitions`, {
      cache: "no-store",
    }),
  doTransition: (key: string, transitionId: string) =>
    http<PinDetail>(`/pins/${encodeURIComponent(key)}/transition`, {
      method: "POST",
      body: JSON.stringify({ transition_id: transitionId }),
    }),
  draftAiReply: (
    key: string,
    prompt: string,
    recentComments?: { author: string; body_text: string; created: string }[],
    analysis?: PinAnalysisFields
  ) =>
    http<{ text: string }>(
      `/pins/${encodeURIComponent(key)}/comments/ai-draft`,
      {
        method: "POST",
        body: JSON.stringify({ prompt, recent_comments: recentComments, analysis }),
      }
    ),
  draftAiReplyStream: async (
    key: string,
    prompt: string,
    recentComments: { author: string; body_text: string; created: string }[] | undefined,
    onDelta: (text: string) => void,
    signal?: AbortSignal,
    analysis?: PinAnalysisFields
  ): Promise<void> => {
    const res = await fetch(
      `${BASE}/pins/${encodeURIComponent(key)}/comments/ai-draft/stream`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt, recent_comments: recentComments, analysis }),
        signal,
      }
    );
    if (!res.ok) {
      let detail = "";
      try {
        const body = await res.json();
        detail = body.detail || JSON.stringify(body);
      } catch {
        detail = await res.text().catch(() => "");
      }
      throw new Error(`HTTP ${res.status}: ${detail || res.statusText}`);
    }
    if (!res.body) throw new Error("Stream response has no body");
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    const consume = (raw: string) => {
      const line = raw.trim();
      if (!line) return;
      let obj: { delta?: string; done?: boolean; error?: string };
      try {
        obj = JSON.parse(line);
      } catch {
        return;
      }
      if (obj.error) throw new Error(obj.error);
      if (typeof obj.delta === "string") onDelta(obj.delta);
    };
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let idx: number;
      while ((idx = buffer.indexOf("\n")) >= 0) {
        const line = buffer.slice(0, idx);
        buffer = buffer.slice(idx + 1);
        consume(line);
      }
    }
    if (buffer) consume(buffer);
  },
  assessmentDraft: (key: string, formId: string) =>
    http<AssessmentDraftResponse>(
      `/pins/${encodeURIComponent(key)}/forms/${encodeURIComponent(formId)}/assessment`,
      { method: "POST" }
    ),
  assessmentExplain: (key: string, formId: string) =>
    http<AssessmentExplainResponse>(
      `/pins/${encodeURIComponent(key)}/forms/${encodeURIComponent(formId)}/assessment/explain`,
      { method: "POST" }
    ),
  submitAssessment: (
    key: string,
    formId: string,
    answers: Record<string, string | string[]>,
    submit = true
  ) =>
    http<AssessmentSubmitResponse>(
      `/pins/${encodeURIComponent(key)}/forms/${encodeURIComponent(formId)}/assessment/submit`,
      { method: "POST", body: JSON.stringify({ answers, submit }) }
    ),
};
