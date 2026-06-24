export interface PinAnalysisFields {
  form_request: string;
  problem: string;
  background: string;
  impact: string;
  expectation: string;
}

/** Auto-labels attached during analysis (Defenders team, controlled vocab). */
export interface PinAnalysisLabels {
  module: string;
  nature: string;
}

/** Full result of POST /api/pins/{key}/analyze: the 5 fields plus optional labels. */
export interface AnalyzeResult extends PinAnalysisFields {
  labels?: PinAnalysisLabels;
}

export interface CleanFormFields {
  问题?: string;
  背景与客户洞察?: string;
  需求详情?: string;
  业务目标?: string;
  客户?: string;
  平台?: string;
  产品模块?: string;
  紧急度?: string;
  [key: string]: string | undefined;
}

/** Lightweight PIN item returned by GET /api/pins */
/** ADF media (image/attachment) extracted server-side. */
export interface MediaItem {
  media_id: string;
  type: string;
  width?: number | null;
  height?: number | null;
  filename?: string | null;
  alt?: string | null;
}

/** Jira issue attachment (downloaded file, not inline). */
export interface AttachmentInfo {
  id: string;
  filename: string;
  size: number;
  mime_type: string;
  author: string;
  created: string;
}

export interface PinSummary {
  key: string;
  status: string;
  summary: string;
  reporter: string;
  reporter_account_id?: string;
  reporter_email?: string;
  assignee?: string;
  assignee_account_id?: string;
  jira_url: string;
  urgency: string;
  created: string;
  description_text?: string;
  description_media_items?: MediaItem[];
  attachments?: AttachmentInfo[];
}

export interface PinListResponse {
  items: PinSummary[];
}

/** Intake form result from GET /api/pins/{key}/form */
export type IntakeFormResult =
  | { available: false }
  | {
      available: true;
      form_id: string;
      form_name: string;
      fields: Record<string, string>;
      clean_fields: CleanFormFields;
      clean_requirements_text: string;
    };

/** Full detail returned by GET /api/pins/{key} (same shape as PinSummary) */
export type PinDetail = PinSummary;

export interface Profile {
  base_url: string;
  account_id: string;
  email: string;
}

export interface JiraComment {
  id: string;
  author: string;
  author_email: string;
  account_id: string;
  created: string;
  updated: string;
  body_text: string;
  media_items?: MediaItem[];
  internal?: boolean;
}

export interface JiraCommentsResponse {
  items: JiraComment[];
  total: number;
}

export interface JiraUser {
  account_id: string;
  display_name: string;
  email: string;
  avatar_url: string;
}

export interface AttachedForm {
  id: string;
  name: string;
  submitted: boolean;
  lock: boolean;
  internal: boolean;
  updated: string;
  form_template_id: string;
}

export interface AttachedFormsResponse {
  key: string;
  items: AttachedForm[];
}

export interface AssessmentOption {
  id: string;
  label: string;
}

/** Branch gating: this field applies only when `by`'s answer is in `values`. */
export interface AssessmentGate {
  by: string;
  values: string[];
}

/** One required field of the Technical Assessment Form. */
export interface AssessmentField {
  id: string;
  label: string;
  kind: "single" | "multi" | "text" | "date";
  options: AssessmentOption[];
  /** Pre-selected option label for choice fields ("" for text/date). */
  default: string;
  gate: AssessmentGate | null;
  /** True for the field the AI fills (Add a short explanation). */
  ai: boolean;
  /** Current answer on the form: choice ids / text / date. For read-only view. */
  value: string | string[];
}

export interface AssessmentDraftResponse {
  fields: AssessmentField[];
  explanation_label: string;
}

export interface AssessmentExplainResponse {
  /** AI-written "Add a short explanation", grounded only in the PIN's comments. */
  explanation: string;
}

export interface AssessmentSubmitResponse {
  ok: boolean;
  submitted: boolean;
  status?: string;
  key: string;
  form_id: string;
}

export interface SubmittedFormSummary {
  form_id: string;
  form_name: string;
  submitted: boolean;
  lock: boolean;
  updated: string;
  fields: Record<string, string>;
  clean_text: string;
}

export interface SubmittedFormsResponse {
  key: string;
  items: SubmittedFormSummary[];
}

export interface CachedAnalysisResponse {
  cached: boolean;
  result?: AnalyzeResult;
}

export interface JiraTransition {
  id: string;
  name: string;
  to_status: string;
}

export interface JiraTransitionsResponse {
  items: JiraTransition[];
}
