/**
 * Tiny fetch wrapper over the FastAPI backend.
 *
 * Base URL comes from NEXT_PUBLIC_API_URL — when the Next dev server
 * runs on :3000 and FastAPI on :8000 this routes cross-origin (CORS is
 * enabled on the API). In a bundled deploy the Next.js static export
 * is served by the same FastAPI process, so NEXT_PUBLIC_API_URL is
 * empty and we hit relative `/api/...` paths same-origin.
 */
const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => res.statusText);
    throw new ApiError(res.status, detail || `HTTP ${res.status}`);
  }
  // 204 No Content / empty body.
  const text = await res.text();
  return text ? (JSON.parse(text) as T) : (undefined as T);
}

export interface ClientSummary {
  id: string;
  name: string;
  goal: string;
}

export interface RosterRow {
  client_id: string;
  name: string;
  goal: string;
  label: "Deload" | "Conservative" | "Standard" | "No recent data";
  flags: string[];
  confidence: number | null;
  sources: number;
  last_data_days: number | null;
  stale: boolean;
}

export interface Contraindication {
  kind: string;
  title: string;
  advice: string;
  source_phrase: string;
}

export interface Recommendation {
  id: string;
  client_id: string;
  week_of: string;
  recommendation: string;
  rationale: string;
  source_metric_ids: string[];
  confidence: number;
  generated_at: string;
  contraindications: Contraindication[];
}

export interface MetricRow {
  id: string;
  date: string;
  source: string;
  kind: string;
  value: number;
  unit: string;
}

export interface SessionRow {
  id: string;
  date: string;
  type: string;
  duration_min: number;
  rpe: number;
  notes: string | null;
}

export interface OverrideRow {
  id: string;
  client_id: string;
  week_of: string;
  system_recommendation: string;
  system_confidence: number;
  trainer_action: "accept" | "edit" | "reject";
  applied_load_change_pct: number | null;
  trainer_note: string | null;
  created_at: string;
}

export interface WeeklyAgreement {
  week_of: string;
  total: number;
  accepts: number;
  accept_rate: number;
}

export interface PerClientAgreement {
  client_id: string;
  name: string;
  total: number;
  accepts: number;
  edits: number;
  rejects: number;
  accept_rate: number;
}

export interface CalibrationSuggestion {
  kind: "threshold_tune" | "per_client_drift";
  severity: "info" | "warn";
  message: string;
  target: string | null;
}

export interface CalibrationResponse {
  total: number;
  accept_rate: number;
  edits: number;
  rejects: number;
  /** matrix[system_type][action] -> count */
  matrix: Record<string, Record<string, number>>;
  recent: OverrideRow[];
  by_week: WeeklyAgreement[];
  by_client: PerClientAgreement[];
  suggestions: CalibrationSuggestion[];
}

export interface AskTrace {
  name: string;
  arguments: Record<string, unknown>;
  result_summary: string;
}

export interface ClientFull {
  id: string;
  name: string;
  sex: "M" | "F" | "other";
  age: number;
  height_cm: number;
  weight_kg: number;
  goal: string;
  injury_history: string | null;
}

export interface ClientFormPayload {
  name: string;
  sex: "M" | "F" | "other";
  age: number;
  height_cm: number;
  weight_kg: number;
  goal: string;
  injury_history?: string | null;
}

export interface ThresholdsResponse {
  defaults: Record<string, number>;
  overrides: Record<string, number>;
}

export interface AskResponse {
  answer: string;
  traces: AskTrace[];
  turns_used: number;
  /** Full Anthropic message stream — pass back as `history` next turn. */
  messages: Record<string, unknown>[];
}

export const api = {
  health: () => request<{ ok: boolean }>("/api/health"),
  clients: () => request<ClientSummary[]>("/api/clients"),
  client: (clientId: string) => request<ClientFull>(`/api/clients/${clientId}`),
  createClient: (payload: ClientFormPayload) =>
    request<{ id: string }>("/api/clients", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  updateClient: (clientId: string, payload: Partial<ClientFormPayload>) =>
    request<{ ok: boolean; updated: string[] }>(`/api/clients/${clientId}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  roster: () => request<RosterRow[]>("/api/roster"),
  recommendation: (clientId: string) =>
    request<Recommendation>(`/api/clients/${clientId}/recommendation`),
  recommendationHistory: (clientId: string, limit = 12) =>
    request<Recommendation[]>(`/api/clients/${clientId}/recommendations?limit=${limit}`),
  metrics: (clientId: string, days = 35) =>
    request<MetricRow[]>(`/api/clients/${clientId}/metrics?days=${days}`),
  sessions: (clientId: string, days = 35) =>
    request<SessionRow[]>(`/api/clients/${clientId}/sessions?days=${days}`),
  overrides: (clientId: string, limit = 20) =>
    request<OverrideRow[]>(`/api/clients/${clientId}/overrides?limit=${limit}`),
  saveOverride: (clientId: string, payload: {
    week_of: string;
    system_recommendation: string;
    system_confidence: number;
    trainer_action: "accept" | "edit" | "reject";
    applied_load_change_pct?: number | null;
    trainer_note?: string | null;
  }) =>
    request<OverrideRow>(`/api/clients/${clientId}/overrides`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  calibration: () => request<CalibrationResponse>("/api/calibration"),
  thresholds: (clientId: string) =>
    request<ThresholdsResponse>(`/api/clients/${clientId}/thresholds`),
  saveThresholds: (clientId: string, overrides: Record<string, number | null>) =>
    request<ThresholdsResponse>(`/api/clients/${clientId}/thresholds`, {
      method: "PATCH",
      body: JSON.stringify({ overrides }),
    }),
  upload: async (clientId: string, file: File): Promise<{ inserted: number; kinds: string[] }> => {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(
      `${process.env.NEXT_PUBLIC_API_URL ?? ""}/api/clients/${clientId}/upload`,
      { method: "POST", body: form },
    );
    if (!res.ok) {
      const detail = await res.text().catch(() => res.statusText);
      throw new ApiError(res.status, detail || `HTTP ${res.status}`);
    }
    return res.json();
  },
  ask: (payload: { question: string; history: Record<string, unknown>[]; model?: string }) =>
    request<AskResponse>("/api/ask", { method: "POST", body: JSON.stringify(payload) }),
  downloadPdf: async (clientId: string, coachMessage: string | null): Promise<Blob> => {
    const res = await fetch(
      `${process.env.NEXT_PUBLIC_API_URL ?? ""}/api/clients/${clientId}/pdf`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ coach_message: coachMessage ?? null }),
      },
    );
    if (!res.ok) {
      const detail = await res.text().catch(() => res.statusText);
      throw new ApiError(res.status, detail || `HTTP ${res.status}`);
    }
    return res.blob();
  },
};
