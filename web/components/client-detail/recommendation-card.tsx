import { useMemo } from "react";
import { Donut } from "@/components/charts";
import { InfoPopover } from "@/components/info-popover";
import { Skeleton } from "@/components/skeleton";
import type { OverrideRow, Recommendation } from "@/lib/api";
import { citationMeta, flagMeta } from "@/lib/citation-meta";
import { flagDisplay } from "@/lib/flag-display";
import type { Verdict } from "./verdict-utils";

/**
 * Recommendation card — the hero of the detail page.
 *
 * The weekly verdict (Deload / Conservative / Standard) is THE answer
 * the trainer is here for. Visual treatment reflects that: a 4px
 * verdict-colored left rail, a display-size headline in the verdict's
 * color, the rationale in generous reading type underneath, and the
 * engine + agreement donuts off to the right rather than competing
 * for the eye.
 */
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
    // Parse only the comma-list immediately after "Flags:" up to the
    // first period — anything after that period is additional prose
    // (e.g. the E4 "Recovery composite N — N trend signals
    // downweighted" sentence) and must not be treated as flag names.
    const afterFlags = rec.rationale.split("Flags:", 2)[1] ?? "";
    const flagsList = afterFlags.split(".", 1)[0];
    return flagsList
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
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

  const verdictColor = verdictColorFor(verdict);

  // Sources to surface as a small methodology footer — only those that
  // actually fed *this* recommendation, deduped. Cited mid-sentence used
  // to break reading flow; this puts them where the trainer can see
  // them when curious without crowding the rationale.
  const sources = useMemo(() => {
    if (!rec?.flag_citations) return [] as string[];
    const seen = new Set<string>();
    for (const flag of flags) {
      const s = rec.flag_citations[flag];
      if (s) seen.add(s);
    }
    return [...seen];
  }, [rec, flags]);

  return (
    <section
      style={{
        border: "1px solid var(--border)",
        borderLeft: `4px solid ${verdictColor}`,
        borderRadius: 10,
        background: "var(--surface)",
        overflow: "hidden",
        transition: "border-color 220ms ease",
      }}
    >
      <div
        className="fit-rec-card"
        style={{
          padding: "24px 28px 22px",
          display: "flex",
          gap: 32,
          alignItems: "flex-start",
        }}
      >
        <div style={{ flex: 1, minWidth: 0 }}>
          <div
            style={{
              fontSize: 10.5,
              color: "var(--text-muted)",
              textTransform: "uppercase",
              letterSpacing: "0.1em",
              fontWeight: 500,
              marginBottom: 12,
            }}
          >
            {rec ? `Week of ${rec.week_of}` : "Loading"} · This week&apos;s call
          </div>

          <div
            style={{
              display: "flex",
              alignItems: "baseline",
              gap: 14,
              flexWrap: "wrap",
              marginBottom: 16,
            }}
          >
            <h2
              style={{
                margin: 0,
                fontSize: 34,
                fontWeight: 700,
                letterSpacing: "-0.035em",
                color: verdictColor,
                lineHeight: 1,
                transition: "color 220ms ease",
              }}
            >
              {verdictLabel(verdict)}
            </h2>
            <span
              style={{
                fontSize: 14,
                color: "var(--text-muted)",
                fontWeight: 400,
              }}
            >
              {verdictSubtitle(verdict)}
            </span>
          </div>

          <p
            style={{
              fontSize: 14.5,
              color: "var(--text)",
              margin: 0,
              maxWidth: 640,
              lineHeight: 1.6,
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
                marginTop: 18,
                padding: "11px 14px",
                background: "var(--surface-2)",
                border: "1px solid var(--border)",
                borderRadius: 7,
                fontSize: 13,
                color: "var(--text)",
                display: "flex",
                gap: 10,
                alignItems: "center",
              }}
            >
              <svg
                width="15"
                height="15"
                viewBox="0 0 20 20"
                fill="none"
                stroke={verdictColor}
                strokeWidth="1.6"
                style={{ flexShrink: 0, transition: "stroke 220ms ease" }}
              >
                <circle cx="10" cy="10" r="7" />
                <path d="M10 6v4l3 2" strokeLinecap="round" />
              </svg>
              <span style={{ flex: 1, lineHeight: 1.4 }}>{rec.recommendation}</span>
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
              paddingLeft: 28,
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

      {sources.length > 0 && (
        <div
          style={{
            padding: "8px 28px",
            borderTop: "1px solid var(--border)",
            fontSize: 10.5,
            color: "var(--text-muted)",
            letterSpacing: "0.02em",
            display: "flex",
            alignItems: "center",
            gap: 8,
            flexWrap: "wrap",
          }}
        >
          <span style={{ textTransform: "uppercase", letterSpacing: "0.1em", fontWeight: 500 }}>
            Methodology
          </span>
          {sources.map((source, idx) => {
            const meta = citationMeta(source);
            return (
              <span key={source} style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
                {idx > 0 && <span aria-hidden>·</span>}
                <InfoPopover
                  trigger={source}
                  title={meta.title}
                  body={meta.description}
                  href={meta.href}
                  ariaLabel={`About citation: ${source}`}
                  triggerStyle={{
                    background: "transparent",
                    border: "none",
                    padding: 0,
                    color: "var(--text-muted)",
                    textDecoration: "underline dotted",
                    textUnderlineOffset: 3,
                    letterSpacing: "0.02em",
                    fontSize: 10.5,
                  }}
                />
              </span>
            );
          })}
        </div>
      )}
      {flags.length > 0 && (
        <div
          style={{
            padding: "12px 28px",
            background: "var(--surface-2)",
            borderTop: "1px solid var(--border)",
            display: "flex",
            alignItems: "center",
            gap: 8,
            fontSize: 12.5,
            color: "var(--text-muted)",
          }}
        >
          <span style={{ color: "var(--text)", fontWeight: 500 }}>
            {flags.length} signal{flags.length === 1 ? "" : "s"} fired
          </span>
          <span>·</span>
          <span style={{ display: "flex", gap: 5, flexWrap: "wrap" }}>
            {flags.map((f) => {
              const source = rec?.flag_citations?.[f];
              const fm = flagMeta(f);
              const sourceMeta = source ? citationMeta(source) : null;
              const detail = rec?.trend_details?.[f];
              const windowBadge = detail ? trendWindowBadge(detail) : null;
              const trigger = windowBadge ? (
                <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                  {flagDisplay(f)}
                  <span
                    style={{
                      fontSize: 9.5,
                      fontFamily: "var(--font-mono)",
                      color: "var(--text-muted)",
                      letterSpacing: "0.02em",
                      padding: "0 5px",
                      borderRadius: 4,
                      background: "color-mix(in oklab, var(--text) 6%, transparent)",
                    }}
                  >
                    {windowBadge}
                  </span>
                </span>
              ) : (
                flagDisplay(f)
              );
              const body = detail ? (
                <TrendPopoverBody description={fm.description} detail={detail} />
              ) : (
                fm.description
              );
              return (
                <InfoPopover
                  key={f}
                  trigger={trigger}
                  title={flagDisplay(f)}
                  body={body}
                  href={sourceMeta?.href}
                  footer={source ? `Source: ${source}` : undefined}
                  ariaLabel={`About signal: ${flagDisplay(f)}`}
                  triggerStyle={{
                    fontSize: 11.5,
                    padding: "2px 8px",
                    background: "var(--surface)",
                    border: "1px solid var(--border)",
                    borderRadius: 999,
                    color: "var(--text)",
                    fontWeight: 500,
                  }}
                />
              );
            })}
          </span>
        </div>
      )}
    </section>
  );
}

/** E5: turn a trend's dual-detector flags into a compact badge label.
 *  Reads which windows fired (acute = 7d OLS, chronic = 28d EWMA) and
 *  picks one of: "7d" (acute-only — often noise), "28d" (chronic-only
 *  — slow drift below the acute threshold), or "7d + 28d" (both
 *  detectors agree — the strongest signal). Returns null if no detail
 *  was supplied (non-trend flag). */
function trendWindowBadge(detail: import("@/lib/api").TrendDetail): string | null {
  const a = detail.acute_fired;
  const c = detail.chronic_fired;
  if (a && c) return "7d + 28d";
  if (a) return "7d";
  if (c) return "28d";
  return null;
}

/** E5: extended popover body for a trend signal. Shows the standard
 *  flag description on top, then a small two-row mini-table of the
 *  acute (7d) and chronic (28d) numbers so a trainer can audit which
 *  window is actually firing. */
function TrendPopoverBody({
  description,
  detail,
}: {
  description: string;
  detail: import("@/lib/api").TrendDetail;
}) {
  const acuteNum = detail.acute_sd_per_day != null
    ? `${detail.acute_sd_per_day.toFixed(2)} SD/day`
    : "—";
  const chronicNum = detail.chronic_sd_per_day != null
    ? `${detail.chronic_sd_per_day.toFixed(2)} SD/day`
    : "—";
  return (
    <>
      <p style={{ margin: 0 }}>{description}</p>
      <div
        style={{
          marginTop: 10,
          padding: "8px 10px",
          background: "color-mix(in oklab, var(--text) 4%, transparent)",
          borderRadius: 6,
          fontSize: 11.5,
          lineHeight: 1.55,
          color: "var(--text)",
          fontFamily: "var(--font-mono)",
        }}
      >
        <DetailRow
          window="7d acute"
          value={acuteNum}
          fired={detail.acute_fired}
        />
        <DetailRow
          window="28d chronic"
          value={chronicNum}
          fired={detail.chronic_fired}
          dim={detail.chronic_confidence_weight < 1.0}
        />
      </div>
      <p style={{ margin: "8px 0 0", fontSize: 11, color: "var(--text-muted)", lineHeight: 1.45 }}>
        Both windows are checked; the verdict combiner trusts agreement and
        demotes acute-only firing. See <em>engine v2</em> in ARCHITECTURE.
      </p>
    </>
  );
}

function DetailRow({
  window: w,
  value,
  fired,
  dim,
}: {
  window: string;
  value: string;
  fired: boolean;
  dim?: boolean;
}) {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        opacity: dim ? 0.6 : 1,
        marginTop: 1,
      }}
    >
      <span style={{ color: "var(--text-muted)" }}>{w}</span>
      <span
        style={{
          color: fired ? "var(--text)" : "var(--text-muted)",
          fontWeight: fired ? 600 : 400,
        }}
      >
        {value}
        {fired ? "  ⚑" : ""}
      </span>
    </div>
  );
}

function verdictColorFor(verdict: Verdict): string {
  if (verdict === "DELOAD") return "var(--danger)";
  if (verdict === "CONSERVATIVE") return "var(--warn)";
  if (verdict === "STANDARD") return "var(--ok)";
  return "var(--text-muted)";
}

function verdictLabel(verdict: Verdict): string {
  if (verdict === "DELOAD") return "Deload";
  if (verdict === "CONSERVATIVE") return "Conservative";
  if (verdict === "STANDARD") return "Standard";
  return "No data";
}

function verdictSubtitle(verdict: Verdict) {
  if (verdict === "DELOAD") return "Pull back to recover";
  if (verdict === "CONSERVATIVE") return "Hold intensity, reduce volume";
  if (verdict === "STANDARD") return "Proceed with planned progression";
  return "Awaiting wearable data";
}
