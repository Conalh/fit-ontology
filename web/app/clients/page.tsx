"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import type { CSSProperties } from "react";
import { Chevron, ClientHeader, Sidebar, TopBar } from "@/components/chrome";
import { ContraindicationsCard } from "@/components/client-detail/contraindications-card";
import { DecisionHistory } from "@/components/client-detail/decision-history";
import { NoDataBanner } from "@/components/client-detail/no-data-banner";
import { OverrideDrawer } from "@/components/client-detail/override-drawer";
import { PlanPanel } from "@/components/client-detail/plan-panel";
import { RecommendationCard } from "@/components/client-detail/recommendation-card";
import { RecoveryGauge } from "@/components/client-detail/recovery-gauge";
import { SendToClient } from "@/components/client-detail/send-to-client";
import { SyncStatus } from "@/components/client-detail/sync-status";
import { SessionsTable } from "@/components/client-detail/sessions-table";
import { TrendsGrid } from "@/components/client-detail/trends-grid";
import { ThresholdsPanel } from "@/components/thresholds-panel";
import { TourCoachMark } from "@/components/tour";
import { api } from "@/lib/api";
import { withAlpha } from "@/lib/accent";
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
    // 60 days covers the trends-grid's 8w window (56d) plus a small
    // buffer for the baseline windows that look back 28d from "today
    // minus the chart's leftmost day" without ever asking the API
    // for more data on window change.
    queryFn: () => api.metrics(clientId, 60),
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

        <SyncStatus metrics={metricsQ.data ?? []} />

        <div className="fit-page-body fit-fade-in-up" style={{ padding: "8px 28px 36px", display: "flex", flexDirection: "column", gap: 22 }}>
          {!metricsQ.isLoading && !sessionsQ.isLoading &&
            (metricsQ.data ?? []).length === 0 && (sessionsQ.data ?? []).length === 0 && (
              <NoDataBanner clientId={clientId} />
            )}

          <RecoveryGauge score={recQ.data?.recovery_score ?? null} />

          <div id="fit-tour-rec-anchor">
            <RecommendationCard
              rec={recQ.data}
              isLoading={recQ.isLoading}
              overrides={overridesQ.data ?? []}
            />
          </div>

          {recQ.data && recQ.data.contraindications.length > 0 && (
            <ContraindicationsCard items={recQ.data.contraindications} />
          )}

          <PlanPanel clientId={clientId} />

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

          <div className="fit-sessions-row" style={{ display: "grid", gridTemplateColumns: "1.4fr 1fr", gap: 22 }}>
            <SessionsTable sessions={sessionsQ.data ?? []} />
            <DecisionHistory
              overrides={overridesQ.data ?? []}
              history={historyQ.data ?? []}
              currentRec={recQ.data}
            />
          </div>

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

      <TourCoachMark clientName={clientName} />
    </div>
  );
}
