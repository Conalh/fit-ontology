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

export interface Recommendation {
  id: string;
  client_id: string;
  week_of: string;
  recommendation: string;
  rationale: string;
  source_metric_ids: string[];
  confidence: number;
  generated_at: string;
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

export const api = {
  health: () => request<{ ok: boolean }>("/api/health"),
  clients: () => request<ClientSummary[]>("/api/clients"),
  client: (clientId: string) => request<Record<string, unknown>>(`/api/clients/${clientId}`),
  roster: () => request<RosterRow[]>("/api/roster"),
  recommendation: (clientId: string) =>
    request<Recommendation>(`/api/clients/${clientId}/recommendation`),
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
};
