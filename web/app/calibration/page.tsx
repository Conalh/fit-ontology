"use client";

import { useQuery } from "@tanstack/react-query";
import type { CSSProperties } from "react";
import { Sidebar, TopBar } from "@/components/chrome";
import { ConfidenceAudit } from "@/components/calibration/confidence-audit";
import { EmptyState } from "@/components/calibration/empty-state";
import { Headline } from "@/components/calibration/headline";
import { Matrix } from "@/components/calibration/matrix";
import { PerClient } from "@/components/calibration/per-client";
import { PlanAdherence } from "@/components/calibration/plan-adherence";
import { Recent } from "@/components/calibration/recent";
import { Suggestions } from "@/components/calibration/suggestions";
import { WeeklyTrend } from "@/components/calibration/weekly-trend";
import { withAlpha } from "@/lib/accent";
import { api } from "@/lib/api";

/**
 * Calibration — does the system agree with the trainer?
 *
 * Reads /api/calibration which gives the headline counts + the
 * system-vs-trainer matrix + the recent overrides. Layout matches the
 * design language: same sidebar + top bar, surface cards with thin
 * borders, monospace numbers, status colors on the matrix.
 */
export default function CalibrationPage() {
  const rosterQ = useQuery({ queryKey: ["roster"], queryFn: api.roster });
  const calQ = useQuery({ queryKey: ["calibration"], queryFn: api.calibration });

  const accentHex = "#4F46E5";
  const accentVars = {
    "--accent": accentHex,
    "--accent-bg": withAlpha(accentHex, 0.10),
  } as CSSProperties;

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
      }}
    >
      <Sidebar roster={rosterQ.data ?? []} activeNav="calibration" accentHex={accentHex} />

      <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
        <TopBar breadcrumb={<span style={{ color: "var(--text)", fontWeight: 500 }}>Calibration</span>} />

        <div style={{ padding: "28px 28px 36px", display: "flex", flexDirection: "column", gap: 22 }}>
          <header>
            <h1 style={{ fontSize: 22, fontWeight: 600, letterSpacing: "-0.02em", margin: 0, color: "var(--text)" }}>
              Calibration
            </h1>
            <p style={{ margin: "4px 0 0", fontSize: 12.5, color: "var(--text-muted)" }}>
              How often the system agrees with the trainer&apos;s actual decision.
            </p>
          </header>

          {calQ.isLoading && <p style={{ fontSize: 12.5, color: "var(--text-muted)" }}>Loading…</p>}
          {calQ.error && <p style={{ fontSize: 12.5, color: "var(--danger)" }}>Could not load calibration.</p>}

          {calQ.data && calQ.data.total === 0 && <EmptyState />}

          {calQ.data && calQ.data.total > 0 && (
            <>
              {calQ.data.suggestions.length > 0 && (
                <Suggestions items={calQ.data.suggestions} />
              )}
              <Headline data={calQ.data} />
              {calQ.data.by_week.length >= 2 && <WeeklyTrend rows={calQ.data.by_week} />}
              <Matrix data={calQ.data} />
              {calQ.data.confidence_audit && calQ.data.confidence_audit.length > 0 && (
                <ConfidenceAudit buckets={calQ.data.confidence_audit} />
              )}
              {calQ.data.plan_adherence && calQ.data.plan_adherence.length > 0 && (
                <PlanAdherence rows={calQ.data.plan_adherence} />
              )}
              {calQ.data.by_client.length > 0 && (
                <PerClient rows={calQ.data.by_client} />
              )}
              <Recent rows={calQ.data.recent} />
            </>
          )}
        </div>
      </div>
    </div>
  );
}
