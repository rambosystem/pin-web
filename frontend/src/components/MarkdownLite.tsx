import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeSanitize from "rehype-sanitize";
import { cn } from "@/lib/utils";

/**
 * Renders Markdown content with full GFM support (tables, task lists,
 * strikethrough, auto-links) and HTML sanitization.
 */
export function MarkdownLite({
  text,
  className,
}: {
  text: string;
  className?: string;
}) {
  if (!text) return null;

  return (
    <div
      className={cn(
        "prose prose-sm dark:prose-invert max-w-none",
        "prose-headings:font-semibold prose-headings:text-foreground",
        "prose-p:text-foreground/90 prose-p:leading-relaxed",
        "prose-a:text-primary prose-a:no-underline hover:prose-a:underline",
        "prose-code:bg-muted prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-code:text-[0.8em] prose-code:font-mono prose-code:text-foreground",
        "prose-pre:bg-muted prose-pre:rounded-md prose-pre:overflow-x-auto",
        "prose-ul:pl-5 prose-ol:pl-5",
        "prose-li:marker:text-muted-foreground",
        "prose-blockquote:border-l-2 prose-blockquote:border-primary/40 prose-blockquote:text-muted-foreground prose-blockquote:pl-3 prose-blockquote:not-italic",
        "prose-hr:border-border",
        "prose-strong:text-foreground prose-strong:font-semibold",
        "prose-table:text-sm prose-th:bg-muted/50 prose-th:font-medium prose-td:border prose-th:border",
        className,
      )}
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeSanitize]}
        components={{
          a: ({ href, children }) => (
            <a href={href} target="_blank" rel="noreferrer noopener">
              {children}
            </a>
          ),
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}
