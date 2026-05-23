"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useMemo, useState } from "react";
import type { CSSProperties } from "react";
import { Donut, LoadBars, TrendChart } from "@/components/charts";
import { Chevron, ClientHeader, Sidebar, TopBar, VerdictBadge } from "@/components/chrome";
import { ThresholdsPanel } from "@/components/thresholds-panel";
import type { OverrideRow, Recommendation } from "@/lib/api";
import { api } from "@/lib/api";
import { withAlpha } from "@/lib/accent";
import { acwrSeries, baseline, dailySeries, loadSeries, recentMean } from "@/lib/series";
import { useClientAccent } from "@/lib/use-client-accent";
import { useQueryParam } from "@/lib/use-query-param";

/**
 * Client detail — the surface Claude Design was designed against.
 *
 * Reads ``?id=<client_id>`` from the URL via a useEffect-based hook
 * (see lib/use-query-param.ts) so we sidestep the Next 16 +
 * Turbopack + useSearchParams + Suspense hydration stall on direct
 * URL loads. Client-side nav from the roster already worked; this
 * fix makes bookmarked URLs and page reloads work too.
 */
export default function ClientDetailPage() {
  const clientIdParam = useQueryParam("id");
  // Render nothing until the URL is parsed on the client. Without this
  // initial render flicker the page would briefly show "missing client
  // id" before useEffect fires.
  if (clientIdParam === null) return null;
  return <ClientDetailInner clientId={clientIdParam} />;
}

function ClientDetailInner({ clientId }: { clientId: string }) {
  const missing = !clientId;
  // Hooks must be called unconditionally — pass a stable placeholder
  // when the id is missing; we render a redirect-style message below.
  const [accentHex, setAccentHex] = useClientAccent(clientId || "_unknown");
  const [overrideOpen, setOverrideOpen] = useState(false);
  const [coachMessage, setCoachMessage] = useState("");

  const clientQ = useQuery({
    queryKey: ["client", clientId],
    queryFn: () => api.client(clientId),
    enabled: !missing,
  });
  const rosterQ = useQuery({ queryKey: ["roster"], queryFn: api.roster });
  const recQ = useQuery({
    queryKey: ["rec", clientId],
    queryFn: () => api.recommendation(clientId),
    enabled: !missing,
  });
  const metricsQ = useQuery({
    queryKey: ["metrics", clientId],
    queryFn: () => api.metrics(clientId, 35),
    enabled: !missing,
  });
  const sessionsQ = useQuery({
    queryKey: ["sessions", clientId],
    queryFn: () => api.sessions(clientId, 35),
    enabled: !missing,
  });
  const overridesQ = useQuery({
    queryKey: ["overrides", clientId],
    queryFn: () => api.overrides(clientId, 20),
    enabled: !missing,
  });
  const historyQ = useQuery({
    queryKey: ["rec-history", clientId],
    queryFn: () => api.recommendationHistory(clientId, 12),
    enabled: !missing,
  });

  if (missing) {
    return (
      <main style={{ padding: "40px", color: "var(--text-muted)" }}>
        <p>
          Missing client id. Open a client from the{" "}
          <Link href="/" style={{ color: "var(--accent)" }}>
            roster
          </Link>
          .
        </p>
      </main>
    );
  }

  const accentVars = {
    "--accent": accentHex,
    "--accent-bg": withAlpha(accentHex, 0.10),
  } as CSSProperties;

  const client = clientQ.data as
    | { id?: string; name?: string; goal?: string; age?: number }
    | undefined;
  const clientName = (client?.name as string | undefined) ?? "Loading…";
  const clientGoal = (client?.goal as string | undefined) ?? undefined;
  const clientAge = (client?.age as number | undefined) ?? undefined;

  return (
    <div
      style={{
        ...accentVars,
        display: "flex",
        width: "100%",
        minHeight: "100%",
        background: "var(--surface)",
        color: "var(--text)",
        fontFamily: "var(--font-sans)",
        fontSize: 14,
        lineHeight: 1.5,
        position: "relative",
      }}
    >
      <Sidebar
        roster={rosterQ.data ?? []}
        rosterTotal={rosterQ.data?.length}
        activeClientId={clientId}
        activeNav="client"
        accentHex={accentHex}
      />

      <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
        <TopBar
          breadcrumb={
            <>
              <Link href="/" style={{ color: "var(--text-muted)", textDecoration: "none" }}>
                Roster
              </Link>
              <Chevron />
              <span style={{ color: "var(--text)", fontWeight: 500 }}>{clientName}</span>
              <Chevron />
              <span>This week</span>
            </>
          }
        >
          <Link href={`/clients/upload?id=${clientId}`} className="btn-ghost">
            Upload
          </Link>
          <Link href={`/clients/edit?id=${clientId}`} className="btn-ghost">
            Edit
          </Link>
          <button className="btn-primary" onClick={() => setOverrideOpen((s) => !s)}>
            Override
          </button>
        </TopBar>

        <ClientHeader
          name={clientName}
          goal={clientGoal}
          age={clientAge}
          accentHex={accentHex}
          onAccentChange={setAccentHex}
        />

        <div style={{ padding: "8px 28px 36px", display: "flex", flexDirection: "column", gap: 22 }}>
          <RecommendationCard
            rec={recQ.data}
            isLoading={recQ.isLoading}
            overrides={overridesQ.data ?? []}
          />

          {recQ.data && recQ.data.contraindications.length > 0 && (
            <ContraindicationsCard items={recQ.data.contraindications} />
          )}

          <SendToClient
            clientId={clientId}
            clientName={clientName}
            coachMessage={coachMessage}
            onCoachMessageChange={setCoachMessage}
          />

          <TrendsGrid
            metrics={metricsQ.data ?? []}
            sessions={sessionsQ.data ?? []}
            isLoading={metricsQ.isLoading || sessionsQ.isLoading}
          />

          <SessionsAndHistoryRow
            sessions={sessionsQ.data ?? []}
            overrides={overridesQ.data ?? []}
            history={historyQ.data ?? []}
            currentRec={recQ.data}
          />

          <ThresholdsPanel clientId={clientId} />
        </div>
      </div>

      {overrideOpen && recQ.data && (
        <OverrideDrawer
          clientId={clientId}
          rec={recQ.data}
          onClose={() => setOverrideOpen(false)}
        />
      )}
    </div>
  );
}

// ─── Recommendation card ─────────────────────────────────────────────

function RecommendationCard({
  rec,
  isLoading,
  overrides,
}: {
  rec: Recommendation | undefined;
  isLoading: boolean;
  overrides: OverrideRow[];
}) {
  const verdict = useMemo(() => {
    if (!rec) return "STANDARD" as const;
    const low = rec.recommendation.toLowerCase();
    if (low.startsWith("deload")) return "DELOAD" as const;
    if (low.startsWith("conservative")) return "CONSERVATIVE" as const;
    return "STANDARD" as const;
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
    // Show the rationale sentence before "Flags:" — that's the part that
    // describes what we saw, not the kinds we tagged.
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
      <div style={{ padding: "22px 24px 20px", display: "flex", gap: 28, alignItems: "flex-start" }}>
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
            {isLoading ? "Computing…" : summary || "Recovery markers look healthy. No flags."}
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

function verdictSubtitle(verdict: "DELOAD" | "CONSERVATIVE" | "STANDARD") {
  if (verdict === "DELOAD") return "Pull back to recover";
  if (verdict === "CONSERVATIVE") return "Hold intensity, reduce volume";
  return "Proceed with planned progression";
}

// ─── Contraindications ("Watch for") ─────────────────────────────────

function ContraindicationsCard({ items }: { items: import("@/lib/api").Contraindication[] }) {
  return (
    <section
      style={{
        border: "1px solid var(--warn-border)",
        background: "var(--warn-bg)",
        borderRadius: 10,
        padding: "16px 20px",
        display: "flex",
        flexDirection: "column",
        gap: 10,
      }}
    >
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between" }}>
        <h3
          style={{
            margin: 0,
            fontSize: 13.5,
            fontWeight: 600,
            color: "var(--text)",
            letterSpacing: "-0.005em",
          }}
        >
          Watch for · {items.length} structural constraint{items.length === 1 ? "" : "s"}
        </h3>
        <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
          From intake — applies regardless of this week&apos;s verdict.
        </span>
      </div>
      <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 8 }}>
        {items.map((c) => (
          <li
            key={c.kind}
            style={{
              display: "grid",
              gridTemplateColumns: "140px 1fr auto",
              gap: 12,
              alignItems: "baseline",
              fontSize: 13,
            }}
          >
            <span style={{ fontWeight: 500, color: "var(--text)" }}>{c.title}</span>
            <span style={{ color: "var(--text)", lineHeight: 1.45 }}>{c.advice}</span>
            <code
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: 11,
                color: "var(--text-muted)",
                background: "var(--surface)",
                border: "1px solid var(--border)",
                borderRadius: 4,
                padding: "1px 6px",
                whiteSpace: "nowrap",
              }}
            >
              {c.source_phrase}
            </code>
          </li>
        ))}
      </ul>
    </section>
  );
}

// ─── Send to client (PDF export + coach's note) ──────────────────────

function SendToClient({
  clientId,
  clientName,
  coachMessage,
  onCoachMessageChange,
}: {
  clientId: string;
  clientName: string;
  coachMessage: string;
  onCoachMessageChange: (next: string) => void;
}) {
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const download = async () => {
    setDownloading(true);
    setError(null);
    try {
      const blob = await api.downloadPdf(clientId, coachMessage.trim() || null);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${clientName.replace(/\s+/g, "_")}_week.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setDownloading(false);
    }
  };

  return (
    <section
      style={{
        border: "1px solid var(--border)",
        borderRadius: 10,
        background: "var(--surface)",
        padding: "16px 20px",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 18 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <h3
            style={{
              margin: 0,
              fontSize: 13.5,
              fontWeight: 600,
              color: "var(--text)",
              letterSpacing: "-0.005em",
            }}
          >
            Send to client
          </h3>
          <p style={{ margin: "2px 0 0", fontSize: 11.5, color: "var(--text-muted)" }}>
            One-page PDF in client-friendly language. Optional personal note from you.
          </p>
        </div>
        <button
          className="btn-primary"
          onClick={download}
          disabled={downloading}
          style={{ flexShrink: 0 }}
        >
          {downloading ? "Generating…" : "Download PDF"}
        </button>
      </div>
      <textarea
        value={coachMessage}
        onChange={(e) => onCoachMessageChange(e.target.value)}
        placeholder="e.g. 'Tough call this week — your HRV and sleep have been off. Bed by 10pm and we reassess Sunday.'"
        style={{
          marginTop: 12,
          width: "100%",
          minHeight: 70,
          padding: "8px 10px",
          background: "var(--surface-2)",
          border: "1px solid var(--border)",
          borderRadius: 6,
          fontSize: 12.5,
          fontFamily: "inherit",
          color: "var(--text)",
          resize: "vertical",
          boxSizing: "border-box",
        }}
      />
      {error && (
        <p style={{ marginTop: 8, fontSize: 12, color: "var(--danger)" }}>{error}</p>
      )}
    </section>
  );
}

// ─── Trends grid ─────────────────────────────────────────────────────

function TrendsGrid({
  metrics,
  sessions,
  isLoading,
}: {
  metrics: import("@/lib/api").MetricRow[];
  sessions: import("@/lib/api").SessionRow[];
  isLoading: boolean;
}) {
  const today = new Date().toISOString().slice(0, 10);

  const items = useMemo(() => {
    const hrvSeries =
      dailySeries(metrics, "hrv_rmssd", today).length > 0
        ? dailySeries(metrics, "hrv_rmssd", today)
        : dailySeries(metrics, "hrv_sdnn", today);
    const rhr = dailySeries(metrics, "resting_hr", today);
    const sleepH = dailySeries(metrics, "sleep_hours", today);
    const sleepS = dailySeries(metrics, "sleep_score", today);
    const tr = dailySeries(metrics, "training_readiness", today);
    const acwr = acwrSeries(sessions, today);

    return [
      { title: "HRV", sub: "ms", data: hrvSeries, base: baseline(hrvSeries), unit: " ms", invert: false },
      { title: "Resting HR", sub: "bpm", data: rhr, base: baseline(rhr), unit: " bpm", invert: true },
      { title: "Sleep", sub: "hours", data: sleepH, base: baseline(sleepH), unit: " h", invert: false },
      { title: "Sleep score", sub: "0–100", data: sleepS, base: baseline(sleepS), unit: "", invert: false },
      { title: "Readiness", sub: "0–100 composite", data: tr, base: baseline(tr), unit: "", invert: false },
      {
        title: "ACWR",
        sub: "acute:chronic",
        data: acwr,
        base: { mean: 1, sd: 0.2 },
        unit: "",
        invert: true,
        threshold: { value: 1.5, label: "risk" },
      },
    ];
  }, [metrics, sessions, today]);

  const totalLoad7 = useMemo(() => {
    const series = loadSeries(sessions, today).slice(-7);
    return series.reduce((a, b) => a + b.load, 0);
  }, [sessions, today]);
  const totalLoad28 = useMemo(() => {
    const series = loadSeries(sessions, today);
    return series.reduce((a, b) => a + b.load, 0);
  }, [sessions, today]);

  return (
    <section>
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", marginBottom: 12 }}>
        <div>
          <h2 style={{ fontSize: 15, fontWeight: 600, color: "var(--text)", margin: 0, letterSpacing: "-0.01em" }}>
            Trends
          </h2>
          <p style={{ fontSize: 12, color: "var(--text-muted)", margin: "2px 0 0" }}>
            Daily wearable signals, last 28 days. Shaded band = 28d baseline mean ± 1 SD.
          </p>
        </div>
        <div style={{ display: "flex", gap: 4, fontSize: 12 }}>
          {["7d", "28d", "8w"].map((w) => (
            <button key={w} className={w === "28d" ? "btn-chip-on" : "btn-chip"}>
              {w}
            </button>
          ))}
        </div>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(3, 1fr)",
          gap: 1,
          background: "var(--border)",
          border: "1px solid var(--border)",
          borderRadius: 10,
          overflow: "hidden",
        }}
      >
        {items.map((it) => (
          <TrendCell key={it.title} item={it} />
        ))}
      </div>

      <div
        style={{
          marginTop: 14,
          border: "1px solid var(--border)",
          borderRadius: 10,
          padding: "14px 16px 8px",
          background: "var(--surface)",
        }}
      >
        <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between" }}>
          <div>
            <div style={{ fontSize: 12, fontWeight: 600, color: "var(--text)" }}>Daily training load</div>
            <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>
              RPE × duration. Red = high-stress session.
            </div>
          </div>
          <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
            7d sum{" "}
            <span style={{ color: "var(--text)", fontWeight: 600, fontVariantNumeric: "tabular-nums" }}>
              {totalLoad7.toLocaleString()}
            </span>{" "}
            · 28d sum{" "}
            <span style={{ color: "var(--text)", fontWeight: 600, fontVariantNumeric: "tabular-nums" }}>
              {totalLoad28.toLocaleString()}
            </span>
          </div>
        </div>
        <div style={{ marginTop: 6 }}>
          <LoadBars data={loadSeries(sessions, today)} height={80} accent="var(--accent)" />
        </div>
      </div>

      {isLoading && <p style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 8 }}>Loading…</p>}
    </section>
  );
}

function TrendCell({
  item,
}: {
  item: {
    title: string;
    sub: string;
    data: { day: number; value: number }[];
    base: { mean: number; sd: number };
    unit: string;
    invert: boolean;
    threshold?: { value: number; label: string };
  };
}) {
  if (item.data.length === 0) {
    return (
      <div style={{ background: "var(--surface)", padding: "14px 14px", minHeight: 152 }}>
        <div style={{ fontSize: 12, fontWeight: 600, color: "var(--text)", letterSpacing: "-0.005em" }}>
          {item.title}
        </div>
        <div style={{ fontSize: 10.5, color: "var(--text-muted)" }}>{item.sub}</div>
        <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 28 }}>no data</div>
      </div>
    );
  }
  const last = item.data[item.data.length - 1].value;
  const last7 = (recentMean(item.data, 7) ?? last) - item.base.mean;
  const deltaPct = item.base.mean > 0 ? (last7 / item.base.mean) * 100 : 0;
  const isBad = item.invert ? last7 > 0 : last7 < 0;
  const isFlag = Math.abs(last7) > item.base.sd * 0.5;
  return (
    <div style={{ background: "var(--surface)", padding: "14px 14px 8px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
        <div>
          <div style={{ fontSize: 12, fontWeight: 600, color: "var(--text)", letterSpacing: "-0.005em" }}>
            {item.title}
          </div>
          <div style={{ fontSize: 10.5, color: "var(--text-muted)" }}>{item.sub}</div>
        </div>
        <div style={{ textAlign: "right" }}>
          <div
            style={{
              fontSize: 16,
              fontWeight: 600,
              color: "var(--text)",
              fontVariantNumeric: "tabular-nums",
              letterSpacing: "-0.02em",
              lineHeight: 1,
            }}
          >
            {last.toFixed(last < 10 ? 1 : 0)}
            <span style={{ fontSize: 11, fontWeight: 400, color: "var(--text-muted)", marginLeft: 2 }}>
              {item.unit}
            </span>
          </div>
          <div
            style={{
              fontSize: 10.5,
              marginTop: 3,
              color: isFlag ? (isBad ? "var(--danger)" : "var(--ok)") : "var(--text-muted)",
              fontVariantNumeric: "tabular-nums",
              fontWeight: 500,
            }}
          >
            {last7 > 0 ? "+" : ""}
            {deltaPct.toFixed(1)}% vs base
          </div>
        </div>
      </div>
      <div style={{ marginTop: 6, marginLeft: -4, marginRight: -4 }}>
        <TrendChart
          data={item.data}
          baseline={item.base}
          unit={item.unit}
          height={110}
          width={300}
          accent="var(--accent)"
          showAxis={false}
          showLastValue={false}
          threshold={item.threshold}
        />
      </div>
    </div>
  );
}

// ─── Sessions + decision history ─────────────────────────────────────

function SessionsAndHistoryRow({
  sessions,
  overrides,
  history,
  currentRec,
}: {
  sessions: import("@/lib/api").SessionRow[];
  overrides: OverrideRow[];
  history: Recommendation[];
  currentRec: Recommendation | undefined;
}) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1.4fr 1fr", gap: 22 }}>
      <SessionsTable sessions={sessions} />
      <DecisionHistory overrides={overrides} history={history} currentRec={currentRec} />
    </div>
  );
}

function SessionsTable({ sessions }: { sessions: import("@/lib/api").SessionRow[] }) {
  const today = new Date().toISOString().slice(0, 10);
  const recent = useMemo(() => {
    return [...sessions]
      .filter((s) => {
        const day = Math.round((Date.parse(s.date) - Date.parse(today)) / 86_400_000);
        return day >= -10;
      })
      .sort((a, b) => Date.parse(b.date) - Date.parse(a.date));
  }, [sessions, today]);

  return (
    <section style={{ border: "1px solid var(--border)", borderRadius: 10, background: "var(--surface)", overflow: "hidden" }}>
      <div
        style={{
          padding: "14px 16px",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
          borderBottom: "1px solid var(--border)",
        }}
      >
        <div>
          <h3 style={{ fontSize: 13.5, fontWeight: 600, color: "var(--text)", margin: 0, letterSpacing: "-0.005em" }}>
            Recent sessions
          </h3>
          <p style={{ fontSize: 11.5, color: "var(--text-muted)", margin: "2px 0 0" }}>
            Last 11 days · {recent.length} entries
          </p>
        </div>
      </div>
      {recent.length === 0 ? (
        <p style={{ padding: "16px", fontSize: 12.5, color: "var(--text-muted)" }}>No sessions logged.</p>
      ) : (
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12.5 }}>
          <thead>
            <tr style={{ fontSize: 10.5, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.08em" }}>
              <th style={{ textAlign: "left", padding: "8px 16px", fontWeight: 500 }}>Date</th>
              <th style={{ textAlign: "left", padding: "8px 0", fontWeight: 500 }}>Session</th>
              <th style={{ textAlign: "right", padding: "8px 0", fontWeight: 500 }}>Dur</th>
              <th style={{ textAlign: "right", padding: "8px 0", fontWeight: 500 }}>RPE</th>
              <th style={{ textAlign: "right", padding: "8px 16px", fontWeight: 500 }}>Load</th>
            </tr>
          </thead>
          <tbody>
            {recent.map((s) => {
              const load = s.duration_min * s.rpe;
              const day = Math.round((Date.parse(s.date) - Date.parse(today)) / 86_400_000);
              return (
                <tr key={s.id} style={{ borderTop: "1px solid var(--border)" }}>
                  <td style={{ padding: "9px 16px", color: "var(--text-muted)", fontVariantNumeric: "tabular-nums", width: 60 }}>
                    d{day}
                  </td>
                  <td style={{ padding: "9px 0", color: "var(--text)" }}>
                    <div style={{ fontWeight: 500 }}>{s.type}</div>
                    {s.notes && <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 1 }}>{s.notes}</div>}
                  </td>
                  <td style={{ padding: "9px 0", textAlign: "right", color: "var(--text)", fontVariantNumeric: "tabular-nums" }}>
                    {s.duration_min}m
                  </td>
                  <td style={{ padding: "9px 0", textAlign: "right", color: "var(--text)", fontVariantNumeric: "tabular-nums" }}>
                    {s.rpe}
                  </td>
                  <td
                    style={{
                      padding: "9px 16px",
                      textAlign: "right",
                      color: load > 800 ? "var(--danger)" : "var(--text)",
                      fontVariantNumeric: "tabular-nums",
                      fontWeight: load > 800 ? 600 : 400,
                    }}
                  >
                    {load}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </section>
  );
}

function DecisionHistory({
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
      engine: "DELOAD" | "CONSERVATIVE" | "STANDARD";
      trainer: "DELOAD" | "CONSERVATIVE" | "STANDARD" | null;
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

function textToVerdict(text: string): "DELOAD" | "CONSERVATIVE" | "STANDARD" {
  const low = text.toLowerCase();
  if (low.startsWith("deload")) return "DELOAD";
  if (low.startsWith("conservative")) return "CONSERVATIVE";
  return "STANDARD";
}

function oppositeVerdict(v: "DELOAD" | "CONSERVATIVE" | "STANDARD"): "DELOAD" | "CONSERVATIVE" | "STANDARD" {
  // Rejecting a Deload trends "more aggressive" → STANDARD; rejecting
  // STANDARD → DELOAD; rejecting CONSERVATIVE we don't know — treat as
  // STANDARD by default.
  if (v === "DELOAD") return "STANDARD";
  if (v === "STANDARD") return "DELOAD";
  return "STANDARD";
}

function trainerVerdictFromOverride(o: OverrideRow): "DELOAD" | "CONSERVATIVE" | "STANDARD" {
  const engine = textToVerdict(o.system_recommendation);
  if (o.trainer_action === "accept") return engine;
  if (o.trainer_action === "reject") return oppositeVerdict(engine);
  return engine; // 'edit' keeps the same direction; load_change_pct captures the magnitude
}

// ─── Override drawer ─────────────────────────────────────────────────

function OverrideDrawer({
  clientId,
  rec,
  onClose,
}: {
  clientId: string;
  rec: Recommendation;
  onClose: () => void;
}) {
  const verdict = textToVerdict(rec.recommendation);
  const [chosen, setChosen] = useState<"DELOAD" | "CONSERVATIVE" | "STANDARD">(verdict);
  const [reasons, setReasons] = useState<Set<string>>(new Set());
  const [conf, setConf] = useState(70);
  const [rationale, setRationale] = useState("");

  const qc = useQueryClient();
  const save = useMutation({
    mutationFn: async () => {
      const action = chosen === verdict ? "accept" : "reject";
      return api.saveOverride(clientId, {
        week_of: rec.week_of,
        system_recommendation: rec.recommendation,
        system_confidence: rec.confidence,
        trainer_action: action,
        applied_load_change_pct: null,
        trainer_note: [
          Array.from(reasons).join(", "),
          rationale ? `— ${rationale}` : "",
          ` (conf ${conf}%)`,
        ]
          .filter(Boolean)
          .join(" ")
          .trim() || null,
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["overrides", clientId] });
      onClose();
    },
  });

  const toggleReason = (r: string) => {
    const next = new Set(reasons);
    if (next.has(r)) next.delete(r);
    else next.add(r);
    setReasons(next);
  };

  const reasonOpts = [
    "Felt fresh in person",
    "Life stress",
    "Travel",
    "Comp prep",
    "Recent illness",
    "Equipment limit",
    "Trainer judgment",
  ];

  return (
    <div
      style={{
        position: "fixed",
        top: 0,
        right: 0,
        bottom: 0,
        width: 380,
        background: "var(--surface)",
        borderLeft: "1px solid var(--border)",
        display: "flex",
        flexDirection: "column",
        boxShadow: "-6px 0 24px var(--shadow-md)",
        zIndex: 50,
      }}
    >
      <div
        style={{
          padding: "16px 20px",
          borderBottom: "1px solid var(--border)",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
        }}
      >
        <div>
          <div
            style={{
              fontSize: 10.5,
              color: "var(--text-muted)",
              textTransform: "uppercase",
              letterSpacing: "0.08em",
              fontWeight: 500,
            }}
          >
            This week&apos;s call
          </div>
          <h3 style={{ fontSize: 15, fontWeight: 600, color: "var(--text)", margin: "4px 0 0" }}>
            Override
          </h3>
        </div>
        <button onClick={onClose} className="btn-icon">
          <svg width="14" height="14" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8">
            <line x1="5" y1="5" x2="15" y2="15" />
            <line x1="15" y1="5" x2="5" y2="15" />
          </svg>
        </button>
      </div>

      <div style={{ flex: 1, overflow: "auto", padding: 20, display: "flex", flexDirection: "column", gap: 18 }}>
        <div>
          <div style={{ fontSize: 11.5, color: "var(--text-muted)", marginBottom: 4 }}>Engine recommended</div>
          <VerdictBadge verdict={verdict} size="lg" />
        </div>

        <div>
          <label style={{ fontSize: 12, fontWeight: 500, color: "var(--text)", display: "block", marginBottom: 8 }}>
            Your call
          </label>
          <div style={{ display: "flex", gap: 6 }}>
            {(["DELOAD", "CONSERVATIVE", "STANDARD"] as const).map((v) => (
              <button
                key={v}
                onClick={() => setChosen(v)}
                style={{
                  flex: 1,
                  padding: "8px 0",
                  border: chosen === v ? "1px solid var(--accent)" : "1px solid var(--border)",
                  background: chosen === v ? "var(--accent-bg)" : "var(--surface)",
                  borderRadius: 6,
                  cursor: "pointer",
                  fontSize: 11,
                  fontWeight: 600,
                  color: chosen === v ? "var(--accent)" : "var(--text-muted)",
                  letterSpacing: "0.04em",
                  textTransform: "uppercase",
                  fontFamily: "inherit",
                }}
              >
                {v}
              </button>
            ))}
          </div>
        </div>

        <div>
          <label style={{ fontSize: 12, fontWeight: 500, color: "var(--text)", display: "block", marginBottom: 8 }}>
            Reasons <span style={{ color: "var(--text-muted)", fontWeight: 400 }}>(tagged)</span>
          </label>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
            {reasonOpts.map((r) => (
              <button
                key={r}
                onClick={() => toggleReason(r)}
                style={{
                  padding: "5px 9px",
                  border: reasons.has(r) ? "1px solid var(--accent)" : "1px solid var(--border)",
                  background: reasons.has(r) ? "var(--accent-bg)" : "var(--surface)",
                  color: reasons.has(r) ? "var(--accent)" : "var(--text)",
                  borderRadius: 4,
                  cursor: "pointer",
                  fontSize: 11.5,
                  fontFamily: "inherit",
                }}
              >
                {r}
              </button>
            ))}
          </div>
        </div>

        <div>
          <label
            style={{
              fontSize: 12,
              fontWeight: 500,
              color: "var(--text)",
              display: "flex",
              justifyContent: "space-between",
              marginBottom: 8,
            }}
          >
            <span>Your confidence</span>
            <span style={{ color: "var(--text-muted)", fontVariantNumeric: "tabular-nums" }}>{conf}%</span>
          </label>
          <input
            type="range"
            min="0"
            max="100"
            value={conf}
            onChange={(e) => setConf(+e.target.value)}
            style={{ width: "100%", accentColor: "var(--accent)" }}
          />
        </div>

        <div>
          <label style={{ fontSize: 12, fontWeight: 500, color: "var(--text)", display: "block", marginBottom: 8 }}>
            Rationale
          </label>
          <textarea
            value={rationale}
            onChange={(e) => setRationale(e.target.value)}
            placeholder="e.g. saw her at Tuesday session, gait was solid…"
            style={{
              width: "100%",
              minHeight: 90,
              padding: "8px 10px",
              background: "var(--surface-2)",
              border: "1px solid var(--border)",
              borderRadius: 6,
              fontSize: 12.5,
              fontFamily: "inherit",
              color: "var(--text)",
              resize: "vertical",
              boxSizing: "border-box",
            }}
          />
        </div>

        {save.error && (
          <div style={{ color: "var(--danger)", fontSize: 12 }}>
            Could not save: {(save.error as Error).message}
          </div>
        )}
      </div>

      <div style={{ padding: "12px 20px", borderTop: "1px solid var(--border)", display: "flex", gap: 8 }}>
        <button className="btn-ghost" onClick={onClose} style={{ flex: 1 }}>
          Cancel
        </button>
        <button className="btn-primary" style={{ flex: 1 }} disabled={save.isPending} onClick={() => save.mutate()}>
          {save.isPending ? "Saving…" : "Save call"}
        </button>
      </div>
    </div>
  );
}
