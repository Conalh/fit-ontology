import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useToast } from "@/components/toast";
import { api, type PlannedSession } from "@/lib/api";

/**
 * Week plan panel — the structured prescription derived from this
 * week's verdict, with per-slot editing.
 *
 * Display mode is the trainer's scanning view; edit mode opens inline
 * inputs for title / type / description / targets. Saving PATCHes the
 * slot and flips its provenance to "trainer" so future engine
 * regeneration leaves the edit alone (handled server-side; the UI just
 * shows the "Edited" chip once the source flips).
 */
export function PlanPanel({ clientId }: { clientId: string }) {
  const planQ = useQuery({
    queryKey: ["plan", clientId],
    queryFn: () => api.plan(clientId),
  });

  if (planQ.isLoading) {
    return (
      <section
        style={{
          border: "1px solid var(--border)",
          borderRadius: 10,
          background: "var(--surface)",
          padding: "16px 20px",
        }}
      >
        <p style={{ fontSize: 12.5, color: "var(--text-muted)", margin: 0 }}>Loading this week&apos;s plan…</p>
      </section>
    );
  }
  if (planQ.error) {
    return (
      <section
        style={{
          border: "1px solid var(--border)",
          borderRadius: 10,
          background: "var(--surface)",
          padding: "16px 20px",
        }}
      >
        <p style={{ fontSize: 12.5, color: "var(--danger)", margin: 0 }}>
          Could not load plan: {(planQ.error as Error).message}
        </p>
      </section>
    );
  }
  if (!planQ.data || planQ.data.sessions.length === 0) return null;

  const { verdict, sessions } = planQ.data;

  return (
    <section
      style={{
        border: "1px solid var(--border)",
        borderRadius: 10,
        background: "var(--surface)",
        overflow: "hidden",
      }}
    >
      <div
        style={{
          padding: "14px 20px",
          borderBottom: "1px solid var(--border)",
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
        }}
      >
        <div>
          <h2
            style={{
              fontSize: 15,
              fontWeight: 600,
              color: "var(--text)",
              margin: 0,
              letterSpacing: "-0.01em",
            }}
          >
            This week&apos;s plan
          </h2>
          <p style={{ fontSize: 11.5, color: "var(--text-muted)", margin: "2px 0 0" }}>
            Derived from a <strong style={{ color: "var(--text)" }}>{verdictDisplay(verdict)}</strong> verdict ·{" "}
            {sessions.length} session{sessions.length === 1 ? "" : "s"}
          </p>
        </div>
      </div>
      <div style={{ padding: "6px 0 8px" }}>
        {sessions.map((s) => (
          <PlannedSessionRow key={s.id} session={s} clientId={clientId} />
        ))}
      </div>
    </section>
  );
}

function PlannedSessionRow({ session, clientId }: { session: PlannedSession; clientId: string }) {
  const [editing, setEditing] = useState(false);
  return editing ? (
    <PlannedSessionEditor
      session={session}
      clientId={clientId}
      onDone={() => setEditing(false)}
    />
  ) : (
    <PlannedSessionDisplay session={session} onEdit={() => setEditing(true)} />
  );
}

function PlannedSessionDisplay({
  session,
  onEdit,
}: {
  session: PlannedSession;
  onEdit: () => void;
}) {
  return (
    <div
      className="fit-plan-slot"
      style={{
        padding: "14px 20px",
        borderTop: "1px solid var(--border)",
        display: "grid",
        gridTemplateColumns: "40px 1fr 220px",
        gap: 16,
        alignItems: "flex-start",
      }}
    >
      <div
        className="fit-plan-slot-num"
        style={{
          width: 32,
          height: 32,
          borderRadius: 7,
          background: "var(--surface-2)",
          border: "1px solid var(--border)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: 13,
          fontWeight: 600,
          color: "var(--text-muted)",
          fontVariantNumeric: "tabular-nums",
        }}
        title={`Slot ${session.slot}`}
      >
        {session.slot}
      </div>

      <div className="fit-plan-slot-main" style={{ minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
          <span style={{ fontSize: 14, fontWeight: 600, color: "var(--text)" }}>{session.title}</span>
          <SessionTypeChip type={session.type} />
          {session.executed_session_id && <ExecutedChip />}
          {session.source === "trainer" && <TrainerEditedChip />}
        </div>
        <p
          style={{
            margin: "6px 0 0",
            fontSize: 12.5,
            color: "var(--text)",
            lineHeight: 1.55,
            maxWidth: 640,
            whiteSpace: "pre-wrap",
          }}
        >
          {session.description}
        </p>
        {session.contraindications.length > 0 && (
          <div style={{ marginTop: 8, display: "flex", flexWrap: "wrap", gap: 5 }}>
            {session.contraindications.map((c) => (
              <span
                key={c}
                style={{
                  fontSize: 11,
                  padding: "2px 8px",
                  background: "var(--warn-bg)",
                  border: "1px solid var(--warn-border)",
                  color: "var(--warn)",
                  borderRadius: 999,
                  fontWeight: 500,
                }}
              >
                ⚠ {c}
              </span>
            ))}
          </div>
        )}
        <div style={{ marginTop: 10 }}>
          <button className="btn-ghost" onClick={onEdit} style={{ fontSize: 11.5 }}>
            Edit slot
          </button>
        </div>
      </div>

      <div
        className="fit-plan-slot-targets"
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr 1fr",
          gap: 8,
          fontSize: 11,
        }}
      >
        <TargetCell label="Duration" value={session.target_duration_min} unit="m" />
        <TargetCell label="RPE" value={session.target_rpe} unit="/10" decimals={1} />
        <TargetCell label="Load" value={session.target_load_au} unit="AU" />
      </div>
    </div>
  );
}

function PlannedSessionEditor({
  session,
  clientId,
  onDone,
}: {
  session: PlannedSession;
  clientId: string;
  onDone: () => void;
}) {
  // Initial capture of the session's current values. A background
  // refetch that mutates the session prop mid-edit doesn't disturb the
  // trainer's draft — they keep editing what they saw, and save against
  // the latest server state when they hit Save. To force a re-mount on
  // session change, callers can pass session.generated_at as the key.
  const [draft, setDraft] = useState({
    type: session.type,
    title: session.title,
    description: session.description,
    target_duration_min: session.target_duration_min ?? 0,
    target_rpe: session.target_rpe ?? 0,
    target_load_au: session.target_load_au ?? 0,
  });

  const qc = useQueryClient();
  const toast = useToast();
  const save = useMutation({
    mutationFn: () =>
      api.patchPlannedSession(clientId, session.slot, {
        type: draft.type,
        title: draft.title,
        description: draft.description,
        target_duration_min: draft.target_duration_min,
        target_rpe: draft.target_rpe,
        target_load_au: draft.target_load_au,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["plan", clientId] });
      toast.show(`Slot ${session.slot} updated.`);
      onDone();
    },
    onError: (e: Error) => {
      toast.show(`Could not save: ${e.message}`, "error");
    },
  });

  return (
    <div
      style={{
        padding: "16px 20px",
        borderTop: "1px solid var(--border)",
        background: "var(--surface-2)",
        display: "flex",
        flexDirection: "column",
        gap: 12,
      }}
    >
      <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
        <span
          style={{
            fontSize: 10,
            color: "var(--text-muted)",
            textTransform: "uppercase",
            letterSpacing: "0.08em",
            fontWeight: 500,
          }}
        >
          Slot {session.slot} · editing
        </span>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 160px",
          gap: 10,
        }}
      >
        <Field label="Title">
          <input
            type="text"
            value={draft.title}
            onChange={(e) => setDraft({ ...draft, title: e.target.value })}
            style={INPUT_STYLE}
          />
        </Field>
        <Field label="Type">
          <select
            value={draft.type}
            onChange={(e) => setDraft({ ...draft, type: e.target.value })}
            style={INPUT_STYLE}
          >
            <option value="strength">Strength</option>
            <option value="cardio">Conditioning</option>
            <option value="mobility">Mobility</option>
            <option value="mixed">Mixed</option>
          </select>
        </Field>
      </div>

      <Field label="Description">
        <textarea
          value={draft.description}
          onChange={(e) => setDraft({ ...draft, description: e.target.value })}
          rows={5}
          style={{
            ...INPUT_STYLE,
            minHeight: 96,
            resize: "vertical",
            lineHeight: 1.5,
          }}
        />
      </Field>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr 1fr",
          gap: 10,
        }}
      >
        <Field label="Duration (min)">
          <input
            type="number"
            min={5}
            max={300}
            value={draft.target_duration_min}
            onChange={(e) => setDraft({ ...draft, target_duration_min: Number(e.target.value) })}
            style={INPUT_STYLE}
          />
        </Field>
        <Field label="Target RPE">
          <input
            type="number"
            min={1}
            max={10}
            step={0.5}
            value={draft.target_rpe}
            onChange={(e) => setDraft({ ...draft, target_rpe: Number(e.target.value) })}
            style={INPUT_STYLE}
          />
        </Field>
        <Field label="Target load (AU)">
          <input
            type="number"
            min={0}
            value={draft.target_load_au}
            onChange={(e) => setDraft({ ...draft, target_load_au: Number(e.target.value) })}
            style={INPUT_STYLE}
          />
        </Field>
      </div>

      {save.error && (
        <div style={{ fontSize: 12, color: "var(--danger)" }}>
          {(save.error as Error).message}
        </div>
      )}

      <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
        <button
          className="btn-ghost"
          onClick={onDone}
          disabled={save.isPending}
        >
          Cancel
        </button>
        <button
          className="btn-primary"
          onClick={() => save.mutate()}
          disabled={save.isPending}
        >
          {save.isPending ? "Saving…" : "Save changes"}
        </button>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 4,
        fontSize: 11,
        color: "var(--text-muted)",
        textTransform: "uppercase",
        letterSpacing: "0.06em",
        fontWeight: 500,
      }}
    >
      {label}
      {children}
    </label>
  );
}

const INPUT_STYLE: React.CSSProperties = {
  padding: "6px 10px",
  background: "var(--surface)",
  border: "1px solid var(--border)",
  borderRadius: 5,
  fontSize: 13,
  fontFamily: "inherit",
  color: "var(--text)",
  letterSpacing: 0,
  textTransform: "none",
  fontWeight: 400,
};

function TargetCell({
  label,
  value,
  unit,
  decimals = 0,
}: {
  label: string;
  value: number | null;
  unit: string;
  decimals?: number;
}) {
  return (
    <div style={{ textAlign: "right" }}>
      <div
        style={{
          fontSize: 9.5,
          color: "var(--text-muted)",
          textTransform: "uppercase",
          letterSpacing: "0.08em",
          fontWeight: 500,
        }}
      >
        {label}
      </div>
      <div
        style={{
          marginTop: 2,
          fontSize: 13,
          fontWeight: 600,
          color: value === null ? "var(--text-muted)" : "var(--text)",
          fontVariantNumeric: "tabular-nums",
          letterSpacing: "-0.01em",
        }}
      >
        {value === null
          ? "—"
          : decimals > 0
          ? value.toFixed(decimals)
          : Math.round(value).toLocaleString()}
        <span style={{ fontSize: 10, fontWeight: 400, color: "var(--text-muted)", marginLeft: 2 }}>
          {value === null ? "" : unit}
        </span>
      </div>
    </div>
  );
}

function SessionTypeChip({ type }: { type: string }) {
  const { label } = typeStyle(type);
  return (
    <span
      style={{
        fontSize: 10,
        padding: "2px 7px",
        background: "var(--surface-2)",
        color: "var(--text)",
        borderRadius: 4,
        fontWeight: 600,
        textTransform: "uppercase",
        letterSpacing: "0.06em",
        fontFamily: "var(--font-mono)",
      }}
    >
      {label}
    </span>
  );
}

function ExecutedChip() {
  return (
    <span
      title="This session has been logged. Plan-vs-execution telemetry is now closed for this slot."
      style={{
        fontSize: 9.5,
        padding: "1px 7px",
        background: "var(--ok-bg)",
        color: "var(--ok)",
        border: "1px solid var(--ok)",
        borderRadius: 3,
        fontWeight: 600,
        textTransform: "uppercase",
        letterSpacing: "0.06em",
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
      }}
    >
      ✓ Done
    </span>
  );
}

function TrainerEditedChip() {
  return (
    <span
      title="You've edited this slot — engine regeneration won't overwrite it."
      style={{
        fontSize: 9.5,
        padding: "1px 6px",
        background: "var(--accent-bg)",
        color: "var(--accent)",
        border: "1px solid var(--accent)",
        borderRadius: 3,
        fontWeight: 600,
        textTransform: "uppercase",
        letterSpacing: "0.06em",
      }}
    >
      Edited
    </span>
  );
}

function typeStyle(type: string): { label: string } {
  switch (type) {
    case "strength":  return { label: "Strength" };
    case "cardio":    return { label: "Conditioning" };
    case "mobility":  return { label: "Mobility" };
    case "mixed":     return { label: "Mixed" };
    default:          return { label: type };
  }
}

function verdictDisplay(v: string): string {
  if (v === "DELOAD") return "Deload";
  if (v === "CONSERVATIVE") return "Conservative";
  if (v === "STANDARD") return "Standard";
  return v;
}
