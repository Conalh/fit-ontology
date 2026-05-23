import { useMemo } from "react";
import { VerdictBadge } from "@/components/chrome";
import type { OverrideRow, Recommendation } from "@/lib/api";
import { textToVerdict, trainerVerdictFromOverride, type Verdict } from "./verdict-utils";

export function DecisionHistory({
  overrides,
  history,
  currentRec,
}: {
  overrides: OverrideRow[];
  history: Recommendation[];
  currentRec: Recommendation | undefined;
}) {
  const rows = useMemo(() => {
    type Row = {
      key: string;
      weekOf: string;
      engine: Verdict;
      trainer: Verdict | null;
      confidence: number;
      isCurrent: boolean;
    };

    // Index overrides by week_of for O(1) lookup; if multiple overrides
    // exist for the same week, the most recent one wins.
    const overrideByWeek = new Map<string, OverrideRow>();
    for (const o of [...overrides].sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at))) {
      if (!overrideByWeek.has(o.week_of)) overrideByWeek.set(o.week_of, o);
    }

    // Persisted history is the engine column for every week we've ever
    // computed. Merge in the trainer's override (if any) per week.
    const seen = new Set<string>();
    const out: Row[] = [];
    const currentWeek = currentRec?.week_of;

    for (const h of history) {
      if (seen.has(h.week_of)) continue;
      seen.add(h.week_of);
      const o = overrideByWeek.get(h.week_of);
      out.push({
        key: h.id,
        weekOf: h.week_of,
        engine: textToVerdict(h.recommendation),
        trainer: o ? trainerVerdictFromOverride(o) : null,
        confidence: h.confidence,
        isCurrent: h.week_of === currentWeek,
      });
    }

    // Override-only weeks (override exists but no persisted history row,
    // e.g. from before lazy-persist landed) still surface so the trainer
    // doesn't lose visibility on old decisions.
    for (const [weekOf, o] of overrideByWeek.entries()) {
      if (seen.has(weekOf)) continue;
      seen.add(weekOf);
      out.push({
        key: o.id,
        weekOf,
        engine: textToVerdict(o.system_recommendation),
        trainer: trainerVerdictFromOverride(o),
        confidence: o.system_confidence,
        isCurrent: weekOf === currentWeek,
      });
    }

    // If the current week isn't in either list yet (no override + not
    // persisted), append it from currentRec so the "Now" badge always
    // has a row to attach to.
    if (currentRec && !seen.has(currentRec.week_of)) {
      out.unshift({
        key: `current-${currentRec.week_of}`,
        weekOf: currentRec.week_of,
        engine: textToVerdict(currentRec.recommendation),
        trainer: null,
        confidence: currentRec.confidence,
        isCurrent: true,
      });
    }

    out.sort((a, b) => Date.parse(b.weekOf) - Date.parse(a.weekOf));
    return out.slice(0, 8);
  }, [overrides, history, currentRec]);

  return (
    <section style={{ border: "1px solid var(--border)", borderRadius: 10, background: "var(--surface)", overflow: "hidden" }}>
      <div style={{ padding: "14px 16px", borderBottom: "1px solid var(--border)" }}>
        <h3 style={{ fontSize: 13.5, fontWeight: 600, color: "var(--text)", margin: 0, letterSpacing: "-0.005em" }}>
          Decision history
        </h3>
        <p style={{ fontSize: 11.5, color: "var(--text-muted)", margin: "2px 0 0" }}>
          Engine vs. trainer, recent {rows.length} weeks
        </p>
      </div>
      {rows.length === 0 ? (
        <p style={{ padding: "16px", fontSize: 12.5, color: "var(--text-muted)" }}>
          No decisions logged yet.
        </p>
      ) : (
        <div style={{ padding: "6px 0 8px" }}>
          {rows.map((r) => {
            const overrode = r.trainer && r.trainer !== r.engine;
            return (
              <div
                key={r.key}
                style={{
                  padding: "8px 16px",
                  display: "grid",
                  gridTemplateColumns: "70px 1fr auto",
                  gap: 10,
                  alignItems: "center",
                  fontSize: 12,
                }}
              >
                <span style={{ color: "var(--text-muted)", fontVariantNumeric: "tabular-nums", fontSize: 11.5 }}>
                  {r.weekOf.slice(5)}
                </span>
                <div style={{ display: "flex", alignItems: "center", gap: 6, minWidth: 0 }}>
                  <VerdictBadge verdict={r.engine} />
                  {r.trainer && (
                    <>
                      <svg
                        width="10"
                        height="10"
                        viewBox="0 0 20 20"
                        fill="none"
                        stroke="var(--text-muted)"
                        strokeWidth="1.5"
                      >
                        <line x1="3" y1="10" x2="17" y2="10" />
                        <polyline points="13,6 17,10 13,14" />
                      </svg>
                      <VerdictBadge verdict={r.trainer} />
                    </>
                  )}
                  {overrode && (
                    <span
                      style={{
                        fontSize: 9.5,
                        color: "var(--text-muted)",
                        background: "var(--surface-2)",
                        border: "1px solid var(--border)",
                        padding: "1px 5px",
                        borderRadius: 3,
                        textTransform: "uppercase",
                        letterSpacing: "0.06em",
                        fontWeight: 500,
                      }}
                    >
                      override
                    </span>
                  )}
                  {r.isCurrent && (
                    <span
                      style={{
                        fontSize: 9.5,
                        color: "var(--warn)",
                        background: "var(--warn-bg)",
                        padding: "1px 5px",
                        borderRadius: 3,
                        textTransform: "uppercase",
                        letterSpacing: "0.06em",
                        fontWeight: 600,
                      }}
                    >
                      now
                    </span>
                  )}
                </div>
                <span style={{ color: "var(--text-muted)", fontVariantNumeric: "tabular-nums", fontSize: 11.5 }}>
                  {Math.round(r.confidence * 100)}%
                </span>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
