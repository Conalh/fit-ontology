"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import type { CSSProperties } from "react";
import { api } from "@/lib/api";

/**
 * Per-client reasoning thresholds.
 *
 * Eighteen severity boundaries the trainer can override per client.
 * Marathon runners and powerlifters need different baselines; clients
 * coming back from injury are more reactive than healthy adults. The
 * panel lives inside a <details> at the bottom of the client detail
 * page — collapsed by default because the trainer rarely touches it,
 * but always one click away.
 *
 * UX: every row shows the default greyed-out and the current value as
 * an editable input. The current value either equals the default
 * (unchanged) or is the trainer's stored override. Edits are
 * accumulated locally then batch-saved through a single PATCH, with a
 * per-row "reset" button that nulls the override (revert to default).
 */
export function ThresholdsPanel({ clientId }: { clientId: string }) {
  const qc = useQueryClient();
  const { data, isLoading, error } = useQuery({
    queryKey: ["thresholds", clientId],
    queryFn: () => api.thresholds(clientId),
  });

  // Local edits: name -> new numeric value, or null to revert. Empty
  // means "no pending changes". Trainer clicks Save to flush.
  const [edits, setEdits] = useState<Record<string, number | null>>({});
  const [serverError, setServerError] = useState<string | null>(null);

  const save = useMutation({
    mutationFn: (overrides: Record<string, number | null>) =>
      api.saveThresholds(clientId, overrides),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["thresholds", clientId] });
      qc.invalidateQueries({ queryKey: ["rec", clientId] });
      setEdits({});
    },
    onError: (e: Error) => setServerError(e.message),
  });

  const groups = useMemo(() => GROUPS, []);

  return (
    <details
      style={{
        border: "1px solid var(--border)",
        borderRadius: 10,
        background: "var(--surface)",
        padding: "0",
      }}
    >
      <summary
        style={{
          cursor: "pointer",
          padding: "14px 18px",
          listStyle: "none",
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
        }}
      >
        <div>
          <h3
            style={{
              margin: 0,
              fontSize: 13.5,
              fontWeight: 600,
              color: "var(--text)",
              letterSpacing: "-0.005em",
            }}
          >
            Reasoning thresholds
          </h3>
          <p style={{ margin: "2px 0 0", fontSize: 11.5, color: "var(--text-muted)" }}>
            {data && Object.keys(data.overrides).length > 0
              ? `${Object.keys(data.overrides).length} per-client override${Object.keys(data.overrides).length === 1 ? "" : "s"} active`
              : "Using population defaults"}
            {" · "}advanced — adjust only when a client&apos;s baseline genuinely differs.
          </p>
        </div>
        <span style={{ fontSize: 11, color: "var(--text-muted)" }}>click to expand</span>
      </summary>

      <div style={{ padding: "0 18px 16px" }}>
        {isLoading && (
          <p style={{ fontSize: 12.5, color: "var(--text-muted)", margin: "12px 0" }}>Loading…</p>
        )}
        {error && (
          <p style={{ fontSize: 12.5, color: "var(--danger)", margin: "12px 0" }}>
            {(error as Error).message}
          </p>
        )}

        {data && (
          <>
            {groups.map((g) => (
              <Group
                key={g.title}
                title={g.title}
                description={g.description}
                rows={g.rows}
                data={data}
                edits={edits}
                setEdits={setEdits}
              />
            ))}

            <div
              style={{
                marginTop: 18,
                paddingTop: 14,
                borderTop: "1px solid var(--border)",
                display: "flex",
                alignItems: "center",
                gap: 12,
              }}
            >
              <div style={{ fontSize: 11.5, color: "var(--text-muted)", flex: 1 }}>
                {Object.keys(edits).length > 0
                  ? `${Object.keys(edits).length} pending change${Object.keys(edits).length === 1 ? "" : "s"}`
                  : "No pending changes"}
              </div>
              {serverError && (
                <span style={{ fontSize: 12, color: "var(--danger)" }}>{serverError}</span>
              )}
              <button
                className="btn-ghost"
                onClick={() => {
                  setEdits({});
                  setServerError(null);
                }}
                disabled={Object.keys(edits).length === 0 || save.isPending}
              >
                Discard
              </button>
              <button
                className="btn-primary"
                onClick={() => {
                  setServerError(null);
                  save.mutate(edits);
                }}
                disabled={Object.keys(edits).length === 0 || save.isPending}
              >
                {save.isPending ? "Saving…" : "Save changes"}
              </button>
            </div>
          </>
        )}
      </div>
    </details>
  );
}

// ─── Metadata ────────────────────────────────────────────────────────

interface Row {
  name: string;
  label: string;
  unit?: string;
  hint?: string;
  step?: number;
}

interface Section {
  title: string;
  description: string;
  rows: Row[];
}

const GROUPS: Section[] = [
  {
    title: "HRV (RMSSD)",
    description: "SD units below the client's 28-day baseline.",
    rows: [
      { name: "hrv_mild_sd", label: "Mild drop", unit: "SD", step: 0.1 },
      { name: "hrv_moderate_sd", label: "Moderate drop", unit: "SD", step: 0.1 },
      { name: "hrv_severe_sd", label: "Severe drop", unit: "SD", step: 0.1 },
    ],
  },
  {
    title: "Acute:Chronic Workload Ratio",
    description: "Gabbett zones — load the past 7d vs 28d.",
    rows: [
      { name: "acwr_safe_low", label: "Detraining floor", unit: "ratio", step: 0.05 },
      { name: "acwr_safe_high", label: "Mild zone", unit: "ratio", step: 0.05 },
      { name: "acwr_moderate_high", label: "Moderate zone", unit: "ratio", step: 0.05 },
      { name: "acwr_severe_high", label: "Severe zone", unit: "ratio", step: 0.05 },
    ],
  },
  {
    title: "Resting HR drift",
    description: "BPM above the 28-day baseline.",
    rows: [
      { name: "rhr_mild_bpm", label: "Mild rise", unit: "bpm", step: 1 },
      { name: "rhr_moderate_bpm", label: "Moderate rise", unit: "bpm", step: 1 },
      { name: "rhr_severe_bpm", label: "Severe rise", unit: "bpm", step: 1 },
    ],
  },
  {
    title: "Sleep",
    description: "Floor and severe-deficit boundaries; sleep score for Garmin clients.",
    rows: [
      { name: "sleep_floor_hours", label: "Recovery floor", unit: "h", step: 0.1 },
      { name: "sleep_deficit_hours", label: "Severe deficit", unit: "h", step: 0.1 },
      { name: "sleep_score_poor", label: "Poor sleep score", unit: "/100", step: 1 },
    ],
  },
  {
    title: "Session RPE drift",
    description: "Week-over-week mean RPE rise at constant volume.",
    rows: [
      { name: "rpe_rise_mild", label: "Mild rise", unit: "RPE", step: 0.1 },
      { name: "rpe_rise_moderate", label: "Moderate rise", unit: "RPE", step: 0.1 },
    ],
  },
  {
    title: "Garmin Training Readiness",
    description: "Below these is mild/moderate/severe.",
    rows: [
      { name: "tr_mild", label: "Mild cutoff", unit: "/100", step: 1 },
      { name: "tr_moderate", label: "Moderate cutoff", unit: "/100", step: 1 },
      { name: "tr_severe", label: "Severe cutoff", unit: "/100", step: 1 },
    ],
  },
];

// ─── Rendering ───────────────────────────────────────────────────────

function Group({
  title,
  description,
  rows,
  data,
  edits,
  setEdits,
}: {
  title: string;
  description: string;
  rows: Row[];
  data: import("@/lib/api").ThresholdsResponse;
  edits: Record<string, number | null>;
  setEdits: React.Dispatch<React.SetStateAction<Record<string, number | null>>>;
}) {
  return (
    <section style={{ marginTop: 14 }}>
      <div style={{ marginBottom: 6 }}>
        <h4
          style={{
            margin: 0,
            fontSize: 11,
            color: "var(--text-muted)",
            textTransform: "uppercase",
            letterSpacing: "0.08em",
            fontWeight: 500,
          }}
        >
          {title}
        </h4>
        <p style={{ margin: "1px 0 0", fontSize: 11, color: "var(--text-muted)" }}>{description}</p>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {rows.map((r) => (
          <ThresholdRow key={r.name} row={r} data={data} edits={edits} setEdits={setEdits} />
        ))}
      </div>
    </section>
  );
}

function ThresholdRow({
  row,
  data,
  edits,
  setEdits,
}: {
  row: Row;
  data: import("@/lib/api").ThresholdsResponse;
  edits: Record<string, number | null>;
  setEdits: React.Dispatch<React.SetStateAction<Record<string, number | null>>>;
}) {
  const def = data.defaults[row.name];
  const stored = data.overrides[row.name];
  const pending = row.name in edits ? edits[row.name] : undefined;

  // "Current" is the value the reasoning module would use right now:
  // pending edit if there is one, else stored override, else default.
  const current: number = pending === null ? def : (pending ?? stored ?? def);
  const overridden = pending !== undefined ? pending !== null : stored !== undefined;

  const onChange = (raw: string) => {
    const n = Number(raw);
    if (!Number.isFinite(n)) return;
    setEdits((prev) => ({ ...prev, [row.name]: n }));
  };

  const onReset = () => {
    if (stored !== undefined) {
      // Already an override stored — mark this row for delete on save.
      setEdits((prev) => ({ ...prev, [row.name]: null }));
    } else {
      // Only a pending edit — discard the local edit.
      setEdits((prev) => {
        const next = { ...prev };
        delete next[row.name];
        return next;
      });
    }
  };

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "1fr 80px 110px auto",
        gap: 8,
        alignItems: "center",
        padding: "6px 0",
      }}
    >
      <div>
        <div style={{ fontSize: 12.5, fontWeight: 500, color: "var(--text)" }}>{row.label}</div>
        <code
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 10.5,
            color: "var(--text-muted)",
          }}
        >
          {row.name}
        </code>
      </div>
      <div
        style={{
          fontSize: 11.5,
          color: "var(--text-muted)",
          fontVariantNumeric: "tabular-nums",
          textAlign: "right",
        }}
      >
        default {formatVal(def, row.step)}
      </div>
      <div style={{ position: "relative" }}>
        <input
          type="number"
          value={Number.isFinite(current) ? current : ""}
          onChange={(e) => onChange(e.target.value)}
          step={row.step ?? 0.1}
          style={INPUT_STYLE(overridden)}
        />
        {row.unit && (
          <span
            style={{
              position: "absolute",
              right: 8,
              top: "50%",
              transform: "translateY(-50%)",
              fontSize: 10,
              color: "var(--text-muted)",
              pointerEvents: "none",
            }}
          >
            {row.unit}
          </span>
        )}
      </div>
      <button
        className="btn-ghost"
        onClick={onReset}
        disabled={!overridden}
        style={{ fontSize: 11 }}
      >
        Reset
      </button>
    </div>
  );
}

function INPUT_STYLE(overridden: boolean): CSSProperties {
  return {
    width: "100%",
    padding: "5px 28px 5px 8px",
    background: "var(--surface-2)",
    border: overridden ? "1px solid var(--accent)" : "1px solid var(--border)",
    borderRadius: 5,
    fontSize: 12,
    fontFamily: "var(--font-mono)",
    color: "var(--text)",
    fontVariantNumeric: "tabular-nums",
    boxSizing: "border-box",
  };
}

function formatVal(v: number, step: number = 0.1): string {
  // Use the step granularity as a hint for display precision.
  if (step >= 1) return `${Math.round(v)}`;
  if (step >= 0.05) return v.toFixed(2);
  return v.toFixed(1);
}
