"use client";

import { useState } from "react";
import type { CSSProperties, FormEvent } from "react";
import type { ClientFormPayload, ClientFull } from "@/lib/api";

/**
 * Shared client form used by /clients/new and /clients/edit.
 *
 * UI shows American units (ft·in for height, lb for weight) — what
 * trainers in the US actually use day-to-day. Storage stays SI (kg,
 * cm) so the engine, the wearable adapters, and the literature
 * citations all line up. Conversion happens at the form layer on
 * input + submit. Standard pattern.
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

// Conversion factors. Keep these here rather than importing — single
// source of truth for the form, the only place these appear.
const KG_PER_LB = 0.45359237;
const CM_PER_IN = 2.54;

function kgToLb(kg: number): number {
  return kg / KG_PER_LB;
}
function lbToKg(lb: number): number {
  return lb * KG_PER_LB;
}
function cmToFtIn(cm: number): { ft: number; inches: number } {
  const totalIn = cm / CM_PER_IN;
  const ft = Math.floor(totalIn / 12);
  const inches = totalIn - ft * 12;
  return { ft, inches };
}
function ftInToCm(ft: number, inches: number): number {
  return (ft * 12 + inches) * CM_PER_IN;
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
  // Initial conversions: DB stores cm/kg; we display ft·in and lb.
  const initialHeight = initial ? cmToFtIn(initial.height_cm) : null;
  const initialWeightLb = initial ? kgToLb(initial.weight_kg) : null;

  const [name, setName] = useState(initial?.name ?? "");
  const [sex, setSex] = useState<"M" | "F" | "other">(initial?.sex ?? "other");
  const [age, setAge] = useState<string>(initial ? String(initial.age) : "");
  const [heightFt, setHeightFt] = useState<string>(initialHeight ? String(initialHeight.ft) : "");
  const [heightIn, setHeightIn] = useState<string>(
    initialHeight ? initialHeight.inches.toFixed(1) : "",
  );
  const [weightLb, setWeightLb] = useState<string>(
    initialWeightLb !== null ? initialWeightLb.toFixed(1) : "",
  );
  const [goal, setGoal] = useState(initial?.goal ?? "");
  const [injury, setInjury] = useState(initial?.injury_history ?? "");

  const [localErrors, setLocalErrors] = useState<string[]>([]);

  const validate = (): { ok: boolean; payload?: ClientFormPayload } => {
    const errs: string[] = [];
    const ageNum = Number(age);
    const ftNum = Number(heightFt);
    const inNum = Number(heightIn);
    const lbNum = Number(weightLb);

    if (!name.trim()) errs.push("Name is required.");
    if (!goal.trim()) errs.push("Goal is required.");
    if (!Number.isFinite(ageNum) || ageNum < 10 || ageNum > 100)
      errs.push("Age must be 10–100.");
    if (
      !Number.isFinite(ftNum) || !Number.isFinite(inNum) ||
      ftNum < 3 || ftNum > 7 || inNum < 0 || inNum >= 12
    )
      errs.push("Height must be 3 ft 0 in to 7 ft 6 in.");
    // Backend rejects exactly 30 kg / 250 kg as boundary values; mirror
    // that here in lb so the API never bounces a valid-looking input.
    if (!Number.isFinite(lbNum) || lbNum <= 66.1 || lbNum >= 551.2)
      errs.push("Weight must be between 67 and 550 lb.");

    if (errs.length > 0) {
      setLocalErrors(errs);
      return { ok: false };
    }

    // Convert to SI for the API. Round to 1 decimal — the DB stores
    // DOUBLE so we don't need more precision than a kitchen scale.
    const heightCm = Number(ftInToCm(ftNum, inNum).toFixed(1));
    const weightKg = Number(lbToKg(lbNum).toFixed(1));

    // Edge-case: the conversion can produce values right at the API's
    // open-interval bounds (>100, <230, >30, <250). Defensive rounding
    // back into range.
    const safeHeight = Math.max(100.1, Math.min(229.9, heightCm));
    const safeWeight = Math.max(30.1, Math.min(249.9, weightKg));

    setLocalErrors([]);
    return {
      ok: true,
      payload: {
        name: name.trim(),
        sex,
        age: ageNum,
        height_cm: safeHeight,
        weight_kg: safeWeight,
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

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1.2fr 1fr", gap: 12 }}>
        <Field label="Sex" required>
          <select
            value={sex}
            onChange={(e) => setSex(e.target.value as "M" | "F" | "other")}
            style={INPUT_STYLE}
          >
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
        <Field label="Height" required>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
            <div style={{ position: "relative" }}>
              <input
                type="number"
                value={heightFt}
                onChange={(e) => setHeightFt(e.target.value)}
                min={3}
                max={7}
                placeholder="ft"
                style={INPUT_WITH_SUFFIX}
              />
              <UnitSuffix>ft</UnitSuffix>
            </div>
            <div style={{ position: "relative" }}>
              <input
                type="number"
                value={heightIn}
                onChange={(e) => setHeightIn(e.target.value)}
                min={0}
                max={11.99}
                step="0.5"
                placeholder="in"
                style={INPUT_WITH_SUFFIX}
              />
              <UnitSuffix>in</UnitSuffix>
            </div>
          </div>
        </Field>
        <Field label="Weight" required>
          <div style={{ position: "relative" }}>
            <input
              type="number"
              value={weightLb}
              onChange={(e) => setWeightLb(e.target.value)}
              min={67}
              max={550}
              step="0.5"
              placeholder="lb"
              style={INPUT_WITH_SUFFIX}
            />
            <UnitSuffix>lb</UnitSuffix>
          </div>
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

const INPUT_WITH_SUFFIX: CSSProperties = {
  ...INPUT_STYLE,
  paddingRight: 26,
};

function UnitSuffix({ children }: { children: React.ReactNode }) {
  return (
    <span
      style={{
        position: "absolute",
        right: 8,
        top: "50%",
        transform: "translateY(-50%)",
        fontSize: 10.5,
        color: "var(--text-muted)",
        pointerEvents: "none",
        letterSpacing: "0.02em",
      }}
    >
      {children}
    </span>
  );
}

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
