import { useEffect, useState } from "react";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { MarkdownLite } from "@/components/MarkdownLite";

async function fetchTranslation(text: string, pinKey: string, field: string): Promise<string> {
  const params = new URLSearchParams({ text, to: "zh" });
  if (pinKey) params.set("pin_key", pinKey);
  if (field) params.set("field", field);
  const res = await fetch(`/api/translate?${params.toString()}`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const data = await res.json() as { translated: string };
  return data.translated ?? "";
}

/** Returns true when the text is predominantly non-Chinese (worth translating). */
function needsTranslation(text: string): boolean {
  if (!text.trim()) return false;
  const letters = text.replace(/\s/g, "");
  if (!letters.length) return false;
  const chineseChars = (letters.match(/[\u4e00-\u9fff\u3400-\u4dbf]/g) ?? []).length;
  return chineseChars / letters.length < 0.3;
}

export function TranslatedText({
  text,
  pinKey = "",
  field = "",
  version = 0,
}: {
  text: string;
  pinKey?: string;
  field?: string;
  version?: number;
}) {
  const [translated, setTranslated] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!needsTranslation(text)) return;
    let cancelled = false;
    setTranslated(null);
    setLoading(true);
    fetchTranslation(text, pinKey, field)
      .then((t) => { if (!cancelled) setTranslated(t); })
      .catch(() => { /* silently ignore translation errors */ })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [text, pinKey, field, version]);

  if (!needsTranslation(text)) return null;

  return (
    <div className="mt-3">
      <Separator className="mb-3" />
      {loading && (
        <div className="space-y-1.5">
          <Skeleton className="h-3 w-full" />
          <Skeleton className="h-3 w-[90%]" />
          <Skeleton className="h-3 w-[75%]" />
        </div>
      )}
      {!loading && translated && (
        <MarkdownLite text={translated} />
      )}
    </div>
  );
}
