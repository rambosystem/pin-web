import type { PinAnalysisFields, PinAnalysisLabels, PinSummary } from "@/api/types";

/**
 * Deep link into Claude Desktop's Code tab.
 *
 * `claude://code/new?folder=<path>&q=<prompt>` opens a new Claude Code session
 * rooted at <folder> with <prompt> pre-filled in the composer (the user still
 * presses Enter). The prompt is capped by the app at 14336 characters.
 *
 * The folder is the Jira workspace that holds the `process-pin` skill. It is a
 * per-machine path, so it can be overridden via localStorage.
 */
// Empty by default: in Claude Desktop 2.9939 a folder supplied by an external
// deep link always triggers a "Trust this workspace?" dialog whose approval is
// never honoured on the next launch, and the session then starts in a scratch
// workspace ("No folder") anyway. Picking the folder from the composer's
// folder chip (recent list) passes the trust check without any dialog, so we
// only pre-fill the prompt and let the user pick "Jira" there. Set
// localStorage["pin-web:claude-code-folder"] = "C:/Workspace/Jira" to pass
// the folder again once the Desktop bug is fixed.
const DEFAULT_FOLDER = "";
const FOLDER_STORAGE_KEY = "pin-web:claude-code-folder";
const PROMPT_MAX = 14000;

export function claudeCodeFolder(): string {
  try {
    return localStorage.getItem(FOLDER_STORAGE_KEY) || DEFAULT_FOLDER;
  } catch {
    return DEFAULT_FOLDER;
  }
}

function clip(text: string, max: number): string {
  const t = text.trim();
  return t.length > max ? t.slice(0, max - 1) + "…" : t;
}

/** Prompt that hands the PIN to the Jira workspace's `process-pin` skill, with
 * pin-web's analysis attached as context so the discussion does not start from
 * zero. The skill still reads the PIN from Jira itself. */
export function buildProcessPinPrompt(
  pin: PinSummary,
  analysis: PinAnalysisFields | null,
  labels: PinAnalysisLabels | null
): string {
  // No folder is passed on the deep link (see DEFAULT_FOLDER); the Desktop
  // then opens the composer in the last-used workspace, which is the Jira
  // workspace in practice, so the skill can be invoked directly.
  const lines: string[] = [`/process-pin ${pin.key}`, ""];
  lines.push(`PIN：${pin.key} — ${pin.summary}`);
  const meta = [
    pin.status && `状态 ${pin.status}`,
    pin.urgency && `紧急度 ${pin.urgency}`,
    pin.reporter && `Reporter ${pin.reporter}`,
    pin.jira_url,
  ].filter(Boolean);
  if (meta.length) lines.push(meta.join(" · "));

  const hasAnalysis = analysis && Object.values(analysis).some((v) => v && v.trim());
  if (hasAnalysis) {
    lines.push("", "以下是 pin-web 用 LLM 做的初步分析，供 Step 1 的 KB 讨论和分类参考。它不是 Jira 原文，请仍按 skill 流程读取 PIN 本身，并以 Jira 与模块 KB 为准：");
    if (labels?.module || labels?.nature) {
      lines.push(`- 初步标签：模块 ${labels?.module || "未判定"} / 性质 ${labels?.nature || "未判定"}`);
    }
    const fields: [keyof PinAnalysisFields, string][] = [
      ["form_request", "原始诉求"],
      ["problem", "问题"],
      ["background", "背景"],
      ["impact", "业务影响"],
      ["expectation", "期望与待澄清点"],
    ];
    for (const [k, label] of fields) {
      const v = (analysis?.[k] || "").trim();
      if (!v || v === "暂无描述") continue;
      lines.push("", `### ${label}`, clip(v, 2500));
    }
  } else {
    lines.push("", "pin-web 尚未对该 PIN 做 LLM 分析，请直接按 skill 流程从 Jira 读取并分析。");
  }
  lines.push("", "请从 Step 1 开始：先基于模块 KB 和我讨论需求与范围，再决定分类。");
  return clip(lines.join("\n"), PROMPT_MAX);
}

export function buildClaudeCodeLink(prompt: string, folder = claudeCodeFolder()): string {
  const params = new URLSearchParams();
  if (folder) params.set("folder", folder);
  params.set("q", prompt);
  return `claude://code/new?${params.toString()}`;
}

/** Open the deep link. Uses an anchor click so the browser's protocol-handler
 * prompt behaves the same as a normal link. */
export function openInClaudeCode(prompt: string): void {
  const a = document.createElement("a");
  a.href = buildClaudeCodeLink(prompt);
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
}
