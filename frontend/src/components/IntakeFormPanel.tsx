import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { MarkdownLite } from "@/components/MarkdownLite";
import { StatusBadge } from "@/components/StatusBadge";
import { TranslatedText } from "@/components/TranslatedText";
import type { CleanFormFields } from "@/api/types";

const REQUIREMENT_SECTIONS: {
  key: keyof CleanFormFields;
  title: string;
  field: string;
}[] = [
  { key: "\u95ee\u9898", title: "Problem", field: "problem" },
  {
    key: "\u80cc\u666f\u4e0e\u5ba2\u6237\u6d1e\u5bdf",
    title: "Context & Insight",
    field: "context",
  },
  {
    key: "\u9700\u6c42\u8be6\u60c5",
    title: "Requested Solution",
    field: "solution",
  },
  {
    key: "\u4e1a\u52a1\u76ee\u6807",
    title: "Business Outcome",
    field: "outcome",
  },
];

const META_FIELDS: { key: keyof CleanFormFields; label: string }[] = [
  { key: "\u5ba2\u6237", label: "Client(s)" },
  { key: "\u5e73\u53f0", label: "Retailer" },
  { key: "\u4ea7\u54c1\u6a21\u5757", label: "Product" },
  { key: "\u7d27\u6025\u5ea6", label: "Urgency" },
];

export function IntakeFormPanel({
  clean,
  fallbackText,
  notLoadedYet,
  pinKey = "",
  translationVersion = 0,
}: {
  clean: CleanFormFields;
  fallbackText?: string;
  notLoadedYet?: boolean;
  pinKey?: string;
  translationVersion?: number;
}) {
  const hasStructured = REQUIREMENT_SECTIONS.some((s) =>
    (clean?.[s.key] || "").trim(),
  );

  if (!hasStructured) {
    if (notLoadedYet) {
      return (
        <Card>
          <CardContent className="py-12 text-sm text-muted-foreground text-center">
            Loading intake form from Jira&hellip;
          </CardContent>
        </Card>
      );
    }
    if (!fallbackText) {
      return (
        <Card>
          <CardContent className="py-12 text-sm text-muted-foreground text-center">
            No intake form available for this PIN.
          </CardContent>
        </Card>
      );
    }
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Intake Form (raw)</CardTitle>
        </CardHeader>
        <CardContent>
          <MarkdownLite text={fallbackText} />
          <TranslatedText
            text={fallbackText}
            pinKey={pinKey}
            field="form_raw"
            version={translationVersion}
          />
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="pt-4 pb-3">
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
            {META_FIELDS.map(({ key, label }) => {
              const value = clean?.[key];
              if (!value) return null;
              return (
                <div key={key} className="flex items-baseline gap-2">
                  <dt className="min-w-[70px] text-xs uppercase tracking-wide text-muted-foreground">
                    {label}
                  </dt>
                  <dd className="font-medium">
                    {key === "\u5ba2\u6237" || key === "\u5e73\u53f0" ? (
                      value
                        .split(",")
                        .map((v) => v.trim())
                        .filter(Boolean)
                        .map((v) => (
                          <Badge
                            key={v}
                            variant="secondary"
                            className="mr-1 mb-1 font-normal"
                          >
                            {v}
                          </Badge>
                        ))
                    ) : key === "\u7d27\u6025\u5ea6" ? (
                      <StatusBadge label={value} kind="urgency" />
                    ) : (
                      value
                    )}
                  </dd>
                </div>
              );
            })}
          </dl>
        </CardContent>
      </Card>

      {REQUIREMENT_SECTIONS.map(({ key, title, field }) => {
        const value = (clean?.[key] || "").trim();
        if (!value) return null;
        return (
          <Card key={key}>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">{title}</CardTitle>
            </CardHeader>
            <CardContent>
              <MarkdownLite text={value} />
              <TranslatedText
                text={value}
                pinKey={pinKey}
                field={field}
                version={translationVersion}
              />
            </CardContent>
          </Card>
        );
      })}

      <Separator />
      <div className="text-xs text-muted-foreground">
        Source: Jira ProForma <code>Feature Request Intake Form</code>
      </div>
    </div>
  );
}
