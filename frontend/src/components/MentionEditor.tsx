import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from "react";
import { api } from "@/api/client";
import type { JiraUser } from "@/api/types";
import { cn } from "@/lib/utils";

// A mention stays open across spaces and only closes on Escape, when the "@" is
// deleted, when a user is picked, or when the query grows past this / hits a newline.
const MENTION_MAX_LEN = 80;

const CHIP_CLASS =
  "mention-chip inline rounded px-1 font-medium text-blue-700 bg-blue-100 " +
  "dark:text-blue-300 dark:bg-blue-900/40";

// Hyperlink styling for URL chips in the editor (blue, underlined, atomic).
const LINK_CHIP_CLASS =
  "link-chip cursor-pointer text-blue-600 dark:text-blue-400 underline " +
  "decoration-blue-400/50 underline-offset-2 break-all";

// Bare http(s) URL. Use the global flag form with matchAll for paste handling.
const URL_RE_GLOBAL = /https?:\/\/[^\s<>]+/gi;

function splitTrailingPunct(url: string): { url: string; trailing: string } {
  let trailing = "";
  while (url && ".,;:!?\"')]}".includes(url[url.length - 1])) {
    trailing = url[url.length - 1] + trailing;
    url = url.slice(0, -1);
  }
  return { url, trailing };
}

// Build an atomic, non-editable link chip carrying the full URL.
function makeLinkChip(url: string): HTMLSpanElement {
  const chip = document.createElement("span");
  chip.className = LINK_CHIP_CLASS;
  chip.contentEditable = "false";
  chip.dataset.url = url;
  chip.title = url;
  chip.textContent = url;
  return chip;
}

export interface MentionEditorHandle {
  /** Serialize the editor to plain text plus a displayName -> accountId map. */
  getValue: () => { text: string; mentions: Record<string, string> };
  /** Replace all content with plain text (used by AI streaming and resets). */
  setText: (text: string) => void;
  clear: () => void;
  focus: () => void;
}

interface ActiveMention {
  node: Text;
  at: number;
  end: number;
}

// Inspect the live selection and return the in-progress "@query" if the caret
// sits inside one. Spaces are allowed inside the query; the trigger "@" must be
// at the start of its text node or preceded by whitespace.
function readActiveMention(
  editor: HTMLElement
): { node: Text; at: number; end: number; query: string } | null {
  const sel = window.getSelection();
  if (!sel || !sel.isCollapsed || sel.rangeCount === 0) return null;
  const node = sel.anchorNode;
  if (!node || node.nodeType !== Node.TEXT_NODE || !editor.contains(node)) return null;
  const textNode = node as Text;
  const offset = sel.anchorOffset;
  const before = textNode.data.slice(0, offset);
  const at = before.lastIndexOf("@");
  if (at < 0) return null;
  if (at > 0 && !/\s/.test(before[at - 1])) return null;
  const query = before.slice(at + 1);
  if (query.includes("\n") || query.length > MENTION_MAX_LEN) return null;
  return { node: textNode, at, end: offset, query };
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

export const MentionEditor = forwardRef<
  MentionEditorHandle,
  {
    placeholder?: string;
    disabled?: boolean;
    internal?: boolean;
    /** Shown as the first candidate when "@" opens (e.g. the PIN reporter). */
    defaultUser?: JiraUser;
    onSubmit?: () => void;
    onEmptyChange?: (empty: boolean) => void;
  }
>(function MentionEditor(
  { placeholder, disabled, internal, defaultUser, onSubmit, onEmptyChange },
  ref
) {
  const editorRef = useRef<HTMLDivElement | null>(null);
  const activeMentionRef = useRef<ActiveMention | null>(null);
  // Query string the user dismissed with Escape, so it won't immediately reopen.
  const dismissedRef = useRef<string | null>(null);
  // Kept in a ref so the search effect can read the latest default without
  // re-running on every parent render (the prop is often a fresh object).
  const defaultUserRef = useRef(defaultUser);
  defaultUserRef.current = defaultUser;

  const [query, setQuery] = useState<string | null>(null);
  const [users, setUsers] = useState<JiraUser[]>([]);
  const [activeIdx, setActiveIdx] = useState(0);
  const [searching, setSearching] = useState(false);
  const [empty, setEmpty] = useState(true);

  const emitEmpty = useCallback(() => {
    const editor = editorRef.current;
    if (!editor) return;
    const isEmpty =
      !editor.textContent?.trim() &&
      !editor.querySelector("[data-account-id], [data-url]");
    setEmpty(isEmpty);
    onEmptyChange?.(isEmpty);
  }, [onEmptyChange]);

  const detect = useCallback(() => {
    const editor = editorRef.current;
    if (!editor) return;
    const m = readActiveMention(editor);
    if (!m) {
      activeMentionRef.current = null;
      dismissedRef.current = null;
      setQuery(null);
      return;
    }
    activeMentionRef.current = { node: m.node, at: m.at, end: m.end };
    if (dismissedRef.current !== null && m.query === dismissedRef.current) {
      setQuery(null);
      return;
    }
    dismissedRef.current = null;
    setQuery(m.query);
  }, []);

  // Debounced user search driven by the active query. With no query yet, the
  // default user (PIN reporter) is offered as the sole first candidate.
  useEffect(() => {
    if (query === null) {
      setUsers([]);
      return;
    }
    const fallback = defaultUserRef.current;
    const q = query.trim();
    if (!q) {
      setUsers(fallback ? [fallback] : []);
      setActiveIdx(0);
      return;
    }
    let cancelled = false;
    const t = setTimeout(async () => {
      setSearching(true);
      try {
        const res = await api.searchUsers(q);
        if (cancelled) return;
        let list = res.items;
        // Keep the default user pinned first when it matches the query.
        if (fallback) {
          const ql = q.toLowerCase();
          if (
            fallback.display_name.toLowerCase().includes(ql) ||
            fallback.email.toLowerCase().includes(ql)
          ) {
            list = [fallback, ...list.filter((u) => u.account_id !== fallback.account_id)];
          }
        }
        setUsers(list);
        setActiveIdx(0);
      } catch {
        if (!cancelled) setUsers(fallback ? [fallback] : []);
      } finally {
        if (!cancelled) setSearching(false);
      }
    }, 200);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [query, defaultUser?.account_id]);

  function insertTextAtCaret(str: string) {
    const sel = window.getSelection();
    if (!sel || sel.rangeCount === 0) return;
    const range = sel.getRangeAt(0);
    range.deleteContents();
    const tn = document.createTextNode(str);
    range.insertNode(tn);
    range.setStartAfter(tn);
    range.collapse(true);
    sel.removeAllRanges();
    sel.addRange(range);
  }

  function insertFragmentAtCaret(frag: DocumentFragment) {
    const editor = editorRef.current;
    if (!editor) return;
    const sel = window.getSelection();
    let range: Range;
    if (sel && sel.rangeCount > 0 && sel.anchorNode && editor.contains(sel.anchorNode)) {
      range = sel.getRangeAt(0);
    } else {
      range = document.createRange();
      range.selectNodeContents(editor);
      range.collapse(false);
    }
    range.deleteContents();
    const lastNode = frag.lastChild;
    range.insertNode(frag);
    if (lastNode) {
      const after = document.createRange();
      after.setStartAfter(lastNode);
      after.collapse(true);
      sel?.removeAllRanges();
      sel?.addRange(after);
    }
    editor.focus();
  }

  // Paste as plain text, turning any URLs into link chips along the way.
  function onPaste(e: React.ClipboardEvent<HTMLDivElement>) {
    const text = e.clipboardData?.getData("text/plain");
    if (!text) return;
    e.preventDefault();
    const frag = document.createDocumentFragment();
    let last = 0;
    for (const m of text.matchAll(URL_RE_GLOBAL)) {
      const raw = m[0];
      const idx = m.index ?? 0;
      if (idx > last) frag.appendChild(document.createTextNode(text.slice(last, idx)));
      const { url, trailing } = splitTrailingPunct(raw);
      if (url) {
        frag.appendChild(makeLinkChip(url));
        frag.appendChild(document.createTextNode(" "));
      } else {
        frag.appendChild(document.createTextNode(raw));
      }
      if (trailing) frag.appendChild(document.createTextNode(trailing));
      last = idx + raw.length;
    }
    if (last < text.length) frag.appendChild(document.createTextNode(text.slice(last)));
    insertFragmentAtCaret(frag);
    setQuery(null);
    emitEmpty();
  }

  // If the word immediately before the caret is a clean URL, replace it with a
  // link chip. Returns true when a conversion happened.
  function linkifyBeforeCaret(): boolean {
    const editor = editorRef.current;
    const sel = window.getSelection();
    if (!editor || !sel || !sel.isCollapsed || sel.rangeCount === 0) return false;
    const node = sel.anchorNode;
    if (!node || node.nodeType !== Node.TEXT_NODE || !editor.contains(node)) return false;
    const textNode = node as Text;
    const offset = sel.anchorOffset;
    const token = (textNode.data.slice(0, offset).match(/\S+$/) || [""])[0];
    if (!/^https?:\/\//i.test(token)) return false;
    const { url, trailing } = splitTrailingPunct(token);
    if (trailing || !url) return false; // only convert clean URLs
    const range = document.createRange();
    range.setStart(textNode, offset - token.length);
    range.setEnd(textNode, offset);
    range.deleteContents();
    const chip = makeLinkChip(url);
    range.insertNode(chip);
    const after = document.createRange();
    after.setStartAfter(chip);
    after.collapse(true);
    sel.removeAllRanges();
    sel.addRange(after);
    return true;
  }

  const insertMention = useCallback(
    (user: JiraUser) => {
      const editor = editorRef.current;
      const m = activeMentionRef.current;
      if (!editor || !m || !user.display_name) return;
      const range = document.createRange();
      try {
        range.setStart(m.node, m.at);
        range.setEnd(m.node, m.end);
      } catch {
        return;
      }
      range.deleteContents();

      const chip = document.createElement("span");
      chip.className = CHIP_CLASS;
      chip.contentEditable = "false";
      chip.dataset.accountId = user.account_id;
      chip.dataset.name = user.display_name;
      chip.textContent = `@${user.display_name}`;
      range.insertNode(chip);

      // Trailing non-breaking space so the caret has somewhere to land after the chip.
      const space = document.createTextNode(" ");
      chip.parentNode?.insertBefore(space, chip.nextSibling);

      const after = document.createRange();
      after.setStartAfter(space);
      after.collapse(true);
      const sel = window.getSelection();
      sel?.removeAllRanges();
      sel?.addRange(after);

      activeMentionRef.current = null;
      dismissedRef.current = null;
      setQuery(null);
      editor.focus();
      emitEmpty();
    },
    [emitEmpty]
  );

  function onKeyDown(e: React.KeyboardEvent<HTMLDivElement>) {
    if (query !== null) {
      if (e.key === "Escape") {
        e.preventDefault();
        dismissedRef.current = query;
        setQuery(null);
        return;
      }
      if (users.length > 0) {
        if (e.key === "ArrowDown") {
          e.preventDefault();
          setActiveIdx((i) => Math.min(i + 1, users.length - 1));
          return;
        }
        if (e.key === "ArrowUp") {
          e.preventDefault();
          setActiveIdx((i) => Math.max(i - 1, 0));
          return;
        }
        if (e.key === "Enter" || e.key === "Tab") {
          e.preventDefault();
          insertMention(users[activeIdx]);
          return;
        }
      } else if (e.key === "Enter" && !e.metaKey && !e.ctrlKey) {
        // Dropdown open but nothing matched: drop it and treat Enter as a newline.
        e.preventDefault();
        setQuery(null);
        insertTextAtCaret("\n");
        emitEmpty();
        return;
      }
    }
    if (e.key === " " && query === null) {
      // Typing a space after a URL turns it into a link chip.
      if (linkifyBeforeCaret()) {
        e.preventDefault();
        insertTextAtCaret(" ");
        emitEmpty();
      }
      return;
    }
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      e.preventDefault();
      onSubmit?.();
      return;
    }
    if (e.key === "Enter" && !e.metaKey && !e.ctrlKey) {
      e.preventDefault();
      linkifyBeforeCaret();
      insertTextAtCaret("\n");
      emitEmpty();
    }
  }

  // Open a link chip in a new tab when clicked (it's a non-editable atom).
  function onClick(e: React.MouseEvent<HTMLDivElement>) {
    const chip = (e.target as HTMLElement | null)?.closest?.("[data-url]") as
      | HTMLElement
      | null;
    const url = chip?.dataset.url;
    if (url) {
      e.preventDefault();
      window.open(url, "_blank", "noopener,noreferrer");
    }
  }

  const NAV_KEYS = ["ArrowDown", "ArrowUp", "Enter", "Tab", "Escape"];
  function onKeyUp(e: React.KeyboardEvent<HTMLDivElement>) {
    if (query !== null && NAV_KEYS.includes(e.key)) return;
    detect();
  }

  useImperativeHandle(
    ref,
    () => ({
      getValue: () => {
        const editor = editorRef.current;
        const mentions: Record<string, string> = {};
        let text = "";
        if (!editor) return { text, mentions };
        const walk = (parent: Node) => {
          parent.childNodes.forEach((child) => {
            if (child.nodeType === Node.TEXT_NODE) {
              text += (child as Text).data.replace(/ /g, " ");
            } else if (child.nodeType === Node.ELEMENT_NODE) {
              const el = child as HTMLElement;
              if (el.dataset.url) {
                text += el.dataset.url;
              } else if (el.dataset.accountId) {
                const name = el.dataset.name || el.textContent?.replace(/^@/, "") || "";
                text += `@${name}`;
                if (name) mentions[name] = el.dataset.accountId;
              } else if (el.tagName === "BR") {
                text += "\n";
              } else {
                if (text && !text.endsWith("\n")) text += "\n";
                walk(el);
              }
            }
          });
        };
        walk(editor);
        return { text, mentions };
      },
      setText: (value: string) => {
        const editor = editorRef.current;
        if (!editor) return;
        editor.textContent = value;
        activeMentionRef.current = null;
        dismissedRef.current = null;
        setQuery(null);
        emitEmpty();
      },
      clear: () => {
        const editor = editorRef.current;
        if (!editor) return;
        editor.textContent = "";
        activeMentionRef.current = null;
        dismissedRef.current = null;
        setQuery(null);
        emitEmpty();
      },
      focus: () => editorRef.current?.focus(),
    }),
    [emitEmpty]
  );

  return (
    <div className="relative">
      <div
        ref={editorRef}
        role="textbox"
        aria-multiline="true"
        contentEditable={!disabled}
        suppressContentEditableWarning
        onInput={() => {
          detect();
          emitEmpty();
        }}
        onKeyDown={onKeyDown}
        onKeyUp={onKeyUp}
        onMouseUp={detect}
        onClick={onClick}
        onPaste={onPaste}
        onBlur={() => setQuery(null)}
        className={cn(
          "min-h-[72px] max-h-40 w-full overflow-y-auto whitespace-pre-wrap break-words",
          "rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-sm",
          "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
          disabled && "cursor-not-allowed opacity-50",
          internal &&
            "border-amber-400 bg-amber-50/40 dark:bg-amber-950/20 focus-visible:ring-amber-400"
        )}
      />
      {empty && (
        <div className="pointer-events-none absolute left-0 top-0 px-3 py-2 text-sm text-muted-foreground">
          {placeholder}
        </div>
      )}

      {query !== null && (
        <div className="absolute left-0 right-0 top-full mt-1 z-20 max-h-56 overflow-y-auto rounded-md border bg-popover text-popover-foreground shadow-md">
          {users.length === 0 && !query.trim() ? (
            <div className="px-3 py-2 text-xs text-muted-foreground">Type to search users…</div>
          ) : users.length === 0 && searching ? (
            <div className="px-3 py-2 text-xs text-muted-foreground">Searching…</div>
          ) : users.length === 0 ? (
            <div className="px-3 py-2 text-xs text-muted-foreground">
              No users match “{query}”
            </div>
          ) : (
            users.map((u, i) => (
              <button
                key={u.account_id || u.display_name}
                type="button"
                onMouseDown={(e) => {
                  e.preventDefault();
                  insertMention(u);
                }}
                onMouseEnter={() => setActiveIdx(i)}
                className={cn(
                  "w-full flex items-center gap-2 px-3 py-1.5 text-left",
                  i === activeIdx ? "bg-accent text-accent-foreground" : "hover:bg-accent/60"
                )}
              >
                <div className="h-6 w-6 shrink-0 rounded-full bg-muted text-[10px] font-medium flex items-center justify-center">
                  {initials(u.display_name)}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5">
                    <span className="text-xs font-medium truncate">{u.display_name}</span>
                    {defaultUser && u.account_id === defaultUser.account_id && (
                      <span className="shrink-0 rounded bg-blue-100 px-1 text-[9px] font-medium text-blue-700 dark:bg-blue-900/40 dark:text-blue-300">
                        Reporter
                      </span>
                    )}
                  </div>
                  {u.email && (
                    <div className="text-[10px] text-muted-foreground truncate">{u.email}</div>
                  )}
                </div>
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
});
