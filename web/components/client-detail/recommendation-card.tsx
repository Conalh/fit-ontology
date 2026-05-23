import { useMemo } from "react";
import { Donut } from "@/components/charts";
import { VerdictBadge } from "@/components/chrome";
import { Skeleton } from "@/components/skeleton";
import type { OverrideRow, Recommendation } from "@/lib/api";
import type { Verdict } from "./verdict-utils";

export function RecommendationCard({
  rec,
  isLoading,
  overrides,
}: {
  rec: Recommendation | undefined;
  isLoading: boolean;
  overrides: OverrideRow[];
}) {
  const verdict = useMemo<Verdict>(() => {
    if (!rec) return "STANDARD";
    const low = rec.recommendation.toLowerCase();
    if (low.startsWith("deload")) return "DELOAD";
    if (low.startsWith("conservative")) return "CONSERVATIVE";
    return "STANDARD";
  }, [rec]);

  const flags = useMemo(() => {
    if (!rec || !rec.rationale.includes("Flags:")) return [] as string[];
    return rec.rationale
      .split("Flags:", 2)[1]
      ?.replace(/\.$/, "")
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean) ?? [];
  }, [rec]);

  const summary = useMemo(() => {
    if (!rec) return "";
    return rec.rationale.split("Flags:")[0].trim();
  }, [rec]);

  const agreement = useMemo(() => {
    if (!overrides.length) return null;
    const sameType = overrides.filter((o) => {
      const ot = o.system_recommendation.toLowerCase();
      if (ot.startsWith("deload")) return verdict === "DELOAD";
      if (ot.startsWith("conservative")) return verdict === "CONSERVATIVE";
      return verdict === "STANDARD";
    });
    if (sameType.length === 0) return null;
    const agreed = sameType.filter((o) => o.trainer_action === "accept").length;
    return { rate: agreed / sameType.length, agreed, total: sameType.length };
  }, [overrides, verdict]);

  return (
    <section
      style={{
        border: "1px solid var(--border)",
        borderRadius: 10,
        background: "var(--surface)",
        overflow: "hidden",
      }}
    >
      <div className="fit-rec-card" style={{ padding: "22px 24px 20px", display: "flex", gap: 28, alignItems: "flex-start" }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div
            style={{
              fontSize: 10.5,
              color: "var(--text-muted)",
              textTransform: "uppercase",
              letterSpacing: "0.08em",
              fontWeight: 500,
              marginBottom: 8,
            }}
          >
            {rec ? `Week of ${rec.week_of}` : "Loading"} · Recommendation
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
            <VerdictBadge verdict={verdict} size="lg" />
            <span style={{ fontSize: 12.5, color: "var(--text-muted)" }}>
              {verdictSubtitle(verdict)}
            </span>
          </div>
          <p
            style={{
              fontSize: 15,
              color: "var(--text)",
              margin: "6px 0 0",
              maxWidth: 640,
              lineHeight: 1.5,
              letterSpacing: "-0.005em",
            }}
          >
            {isLoading ? (
              <span style={{ display: "inline-flex", flexDirection: "column", gap: 6, width: "100%" }}>
                <Skeleton width="80%" height={15} />
                <Skeleton width="55%" height={15} />
              </span>
            ) : (
              summary || "Recovery markers look healthy. No flags."
            )}
          </p>
          {rec && (
            <div
              style={{
                marginTop: 14,
                padding: "10px 12px",
                background: "var(--surface-2)",
                border: "1px solid var(--border)",
                borderRadius: 6,
                fontSize: 13,
                color: "var(--text)",
                display: "flex",
                gap: 8,
              }}
            >
              <svg
                width="14"
                height="14"
                viewBox="0 0 20 20"
                fill="none"
                stroke="var(--text-muted)"
                strokeWidth="1.5"
                style={{ flexShrink: 0, marginTop: 2 }}
              >
                <circle cx="10" cy="10" r="7" />
                <path d="M10 6v4l3 2" strokeLinecap="round" />
              </svg>
              <span style={{ flex: 1 }}>{rec.recommendation}</span>
            </div>
          )}
        </div>

        {rec && (
          <div
            className="fit-rec-card-divider"
            style={{
              display: "flex",
              gap: 24,
              alignItems: "center",
              paddingLeft: 24,
              borderLeft: "1px solid var(--border)",
            }}
          >
            <div style={{ textAlign: "center" }}>
              <Donut
                value={rec.confidence}
                size={84}
                stroke={7}
                color="var(--accent)"
                label={`${Math.round(rec.confidence * 100)}%`}
                sublabel="conf"
              />
              <div
                style={{
                  fontSize: 11,
                  color: "var(--text-muted)",
                  marginTop: 8,
                  textAlign: "center",
                  maxWidth: 84,
                  lineHeight: 1.3,
                }}
              >
                Engine confidence
              </div>
            </div>
            {agreement && (
              <div style={{ textAlign: "center" }}>
                <Donut
                  value={agreement.rate}
                  size={84}
                  stroke={7}
                  color="var(--text)"
                  label={`${Math.round(agreement.rate * 100)}%`}
                  sublabel="agree"
                />
                <div
                  style={{
                    fontSize: 11,
                    color: "var(--text-muted)",
                    marginTop: 8,
                    textAlign: "center",
                    maxWidth: 90,
                    lineHeight: 1.3,
                  }}
                >
                  You agreed on this verdict
                  <br />
                  <span style={{ fontVariantNumeric: "tabular-nums" }}>
                    {agreement.agreed} of {agreement.total}
                  </span>{" "}
                  times
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {flags.length > 0 && (
        <div
          style={{
            padding: "11px 24px",
            background: "var(--surface-2)",
            borderTop: "1px solid var(--border)",
            display: "flex",
            alignItems: "center",
            gap: 8,
            fontSize: 12.5,
            color: "var(--text-muted)",
          }}
        >
          <span style={{ color: "var(--text)", fontWeight: 500 }}>{flags.length} signal{flags.length === 1 ? "" : "s"} fired</span>
          <span>·</span>
          <span style={{ display: "flex", gap: 5, flexWrap: "wrap" }}>
            {flags.map((f) => (
              <code
                key={f}
                style={{
                  fontFamily: "var(--font-mono)",
                  fontSize: 11,
                  padding: "1px 6px",
                  background: "var(--surface)",
                  border: "1px solid var(--border)",
                  borderRadius: 4,
                  color: "var(--text)",
                }}
              >
                {f}
              </code>
            ))}
          </span>
        </div>
      )}
    </section>
  );
}

function verdictSubtitle(verdict: Verdict) {
  if (verdict === "DELOAD") return "Pull back to recover";
  if (verdict === "CONSERVATIVE") return "Hold intensity, reduce volume";
  return "Proceed with planned progression";
}
