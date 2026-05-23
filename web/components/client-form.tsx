"use client";

import { useState } from "react";
import type { CSSProperties, FormEvent } from "react";
import type { ClientFormPayload, ClientFull } from "@/lib/api";

/**
 * Shared client form used by /clients/new and /clients/edit.
 *
 * Edit mode (``initial`` provided) prefills the inputs and labels the
 * submit button "Save changes"; create mode shows blank inputs and
 * "Create client". Validation matches the Pydantic ranges on
 * api.ClientCreate so the API rejection paths are mostly unreachable
 * from the UI.
 */
export interface ClientFormProps {
  initial?: ClientFull;
  submitLabel: string;
  submittingLabel: string;
  /** Server-side error to display under the form (e.g. 503 DB busy). */
  serverError?: string | null;
  onSubmit: (payload: ClientFormPayload) => Promise<void> | void;
  onCancel?: () => void;
  isPending?: boolean;
}

export function ClientForm({
  initial,
  submitLabel,
  submittingLabel,
  serverError,
  onSubmit,
  onCancel,
  isPending,
}: ClientFormProps) {
  const [name, setName] = useState(initial?.name ?? "");
  const [sex, setSex] = useState<"M" | "F" | "other">(initial?.sex ?? "other");
  const [age, setAge] = useState<string>(initial ? String(initial.age) : "");
  const [heightCm, setHeightCm] = useState<string>(initial ? String(initial.height_cm) : "");
  const [weightKg, setWeightKg] = useState<string>(initial ? String(initial.weight_kg) : "");
  const [goal, setGoal] = useState(initial?.goal ?? "");
  const [injury, setInjury] = useState(initial?.injury_history ?? "");

  const [localErrors, setLocalErrors] = useState<string[]>([]);

  const validate = (): { ok: boolean; payload?: ClientFormPayload } => {
    const errs: string[] = [];
    const ageNum = Number(age);
    const heightNum = Number(heightCm);
    const weightNum = Number(weightKg);
    if (!name.trim()) errs.push("Name is required.");
    if (!goal.trim()) errs.push("Goal is required.");
    if (!Number.isFinite(ageNum) || ageNum < 10 || ageNum > 100)
      errs.push("Age must be 10–100.");
    if (!Number.isFinite(heightNum) || heightNum <= 100 || heightNum >= 230)
      errs.push("Height must be between 100 and 230 cm.");
    if (!Number.isFinite(weightNum) || weightNum <= 30 || weightNum >= 250)
      errs.push("Weight must be between 30 and 250 kg.");
    if (errs.length > 0) {
      setLocalErrors(errs);
      return { ok: false };
    }
    setLocalErrors([]);
    return {
      ok: true,
      payload: {
        name: name.trim(),
        sex,
        age: ageNum,
        height_cm: heightNum,
        weight_kg: weightNum,
        goal: goal.trim(),
        injury_history: injury.trim() || null,
      },
    };
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (isPending) return;
    const v = validate();
    if (!v.ok || !v.payload) return;
    await onSubmit(v.payload);
  };

  return (
    <form
      onSubmit={handleSubmit}
      style={{
        border: "1px solid var(--border)",
        borderRadius: 10,
        background: "var(--surface)",
        padding: "20px 22px",
        display: "flex",
        flexDirection: "column",
        gap: 16,
      }}
    >
      <Field label="Name" required>
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. Ben Okafor"
          autoFocus={!initial}
          style={INPUT_STYLE}
        />
      </Field>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr", gap: 12 }}>
        <Field label="Sex" required>
          <select value={sex} onChange={(e) => setSex(e.target.value as "M" | "F" | "other")} style={INPUT_STYLE}>
            <option value="F">Female</option>
            <option value="M">Male</option>
            <option value="other">Other</option>
          </select>
        </Field>
        <Field label="Age" required>
          <input
            type="number"
            value={age}
            onChange={(e) => setAge(e.target.value)}
            min={10}
            max={100}
            style={INPUT_STYLE}
          />
        </Field>
        <Field label="Height (cm)" required>
          <input
            type="number"
            value={heightCm}
            onChange={(e) => setHeightCm(e.target.value)}
            min={101}
            max={229}
            step="0.1"
            style={INPUT_STYLE}
          />
        </Field>
        <Field label="Weight (kg)" required>
          <input
            type="number"
            value={weightKg}
            onChange={(e) => setWeightKg(e.target.value)}
            min={31}
            max={249}
            step="0.1"
            style={INPUT_STYLE}
          />
        </Field>
      </div>

      <Field label="Goal" required>
        <input
          type="text"
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
          placeholder="e.g. Sub-3:15 Chicago, Oct 11"
          style={INPUT_STYLE}
        />
      </Field>

      <Field label="Injury history" hint="Free text — recognized keywords (knee, lumbar, ACL, shoulder, tendinopathy, hip) feed into contraindications.">
        <textarea
          value={injury}
          onChange={(e) => setInjury(e.target.value)}
          placeholder="e.g. R meniscus repair 2024; lower back stiffness on heavy days"
          rows={3}
          style={{ ...INPUT_STYLE, resize: "vertical", minHeight: 64 }}
        />
      </Field>

      {(localErrors.length > 0 || serverError) && (
        <ul
          style={{
            margin: 0,
            padding: "10px 14px",
            background: "var(--danger-bg)",
            border: "1px solid var(--danger)",
            borderRadius: 6,
            fontSize: 12.5,
            color: "var(--danger)",
            listStyle: "none",
          }}
        >
          {localErrors.map((m) => (
            <li key={m}>{m}</li>
          ))}
          {serverError && <li>{serverError}</li>}
        </ul>
      )}

      <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
        {onCancel && (
          <button type="button" className="btn-ghost" onClick={onCancel} disabled={isPending}>
            Cancel
          </button>
        )}
        <button type="submit" className="btn-primary" disabled={isPending}>
          {isPending ? submittingLabel : submitLabel}
        </button>
      </div>
    </form>
  );
}

const INPUT_STYLE: CSSProperties = {
  width: "100%",
  padding: "7px 10px",
  background: "var(--surface-2)",
  border: "1px solid var(--border)",
  borderRadius: 6,
  fontSize: 13,
  fontFamily: "inherit",
  color: "var(--text)",
  boxSizing: "border-box",
};

function Field({
  label,
  required,
  hint,
  children,
}: {
  label: string;
  required?: boolean;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <label style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <span style={{ fontSize: 11.5, fontWeight: 500, color: "var(--text)" }}>
        {label}
        {required && <span style={{ color: "var(--text-muted)" }}> *</span>}
      </span>
      {children}
      {hint && (
        <span style={{ fontSize: 11, color: "var(--text-muted)", lineHeight: 1.4 }}>{hint}</span>
      )}
    </label>
  );
}
