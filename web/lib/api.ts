/**
 * Tiny fetch wrapper over the FastAPI backend.
 *
 * Base URL selection:
 *   - explicit NEXT_PUBLIC_API_URL wins (escape hatch for unusual setups)
 *   - else: cross-port localhost in dev (Next on :3000, FastAPI on :8000)
 *   - else: empty string in production builds (relative /api/... paths
 *           served same-origin by the FastAPI process that hosts the
 *           static export — required for deploys behind a tunnel).
 *
 * Defaulting via NODE_ENV instead of an env file avoids the deploy
 * footgun where a dev-only ``NEXT_PUBLIC_API_URL=http://localhost:8000``
 * in ``.env.local`` gets baked into the production bundle and breaks
 * cross-device access (browsers on the user's phone would try to fetch
 * the user's own localhost, not the server's).
 */
const API_BASE =
  process.env.NEXT_PUBLIC_API_URL
  ?? (process.env.NODE_ENV === "development" ? "http://127.0.0.1:8000" : "");

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    // credentials: "include" is essential for the Phase 2b-α session
    // cookie to flow on cross-origin dev calls (Next on :3000 →
    // FastAPI on :8000). Same-origin production deploys send cookies
    // anyway, but the flag is harmless there.
    credentials: "include",
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

export interface TrainerProfile {
  id: string;
  email: string;
  name: string;
}

export interface SharePlannedSession {
  slot: number;
  type: string;
  title: string;
  description: string;
  target_duration_min: number | null;
  target_rpe: number | null;
  done: boolean;
}

export interface ShareView {
  client_first_name: string;
  week_of: string;
  recommendation: string;
  rationale: string;
  confidence: number;
  recovery_score: {
    composite: number | null;
    hrv: number | null;
    sleep: number | null;
    rhr: number | null;
    acwr: number | null;
  };
  plan: SharePlannedSession[];
  trainer_message: string | null;
  expires_at: string;
}

export interface ShareCreate {
  token: string;
  expires_at: string;
}

/** Phase 3b — public intake form preflight payload. Mirrors the
 *  backend IntakeViewResponse: just the data the form page needs to
 *  render its header + decide which state to show. trainer_id is
 *  intentionally absent — the token is the bearer credential. */
export interface IntakeView {
  trainer_name: string;
  trainer_message: string | null;
  expires_at: string;
  consumed: boolean;
}

/** Phase 3b — what the trainer's mint endpoint returns. Same shape as
 *  ShareCreate; kept as a distinct type so future divergence (single-
 *  use status, revoke API, etc.) doesn't churn share consumers. */
export interface IntakeMint {
  token: string;
  expires_at: string;
}

export interface CoachDraft {
  draft: string;
  model: string;
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

export interface RecoveryScore {
  composite: number | null;
  hrv: number | null;
  sleep: number | null;
  rhr: number | null;
  acwr: number | null;
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
  recovery_score?: RecoveryScore | null;
  /** Flag kind -> source authority (e.g. "Plews & Laursen 2017"). */
  flag_citations?: Record<string, string>;
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
  kind: "threshold_tune" | "per_client_drift" | "plan_adherence";
  severity: "info" | "warn";
  message: string;
  target: string | null;
}

export interface ConfidenceBucket {
  low: number;
  high: number;
  total: number;
  accepts: number;
  accept_rate: number;
}

export interface PlanAdherenceRow {
  client_id: string;
  name: string;
  total_slots: number;
  matched_slots: number;
  match_rate: number;
  load_delta_pct: number | null;
  rpe_delta: number | null;
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
  confidence_audit: ConfidenceBucket[];
  plan_adherence: PlanAdherenceRow[];
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

export interface BaselineWindowSuggestion {
  days: number;
  stable: boolean;
  reason: string;
}

export interface ThresholdsResponse {
  defaults: Record<string, number>;
  overrides: Record<string, number>;
  baseline_window_suggestion?: BaselineWindowSuggestion | null;
}

export interface PlannedSession {
  id: string;
  client_id: string;
  week_of: string;
  slot: number;
  /** SessionType — "strength" | "cardio" | "mobility" | "mixed". */
  type: string;
  title: string;
  description: string;
  target_duration_min: number | null;
  target_load_au: number | null;
  target_rpe: number | null;
  contraindications: string[];
  /** "engine" on initial generation, "trainer" once any field is patched. */
  source: "engine" | "trainer" | string;
  generated_at: string;
  executed_session_id: string | null;
}

export interface PlanResponse {
  week_of: string;
  /** Uppercase verdict — "DELOAD" | "CONSERVATIVE" | "STANDARD". */
  verdict: string;
  sessions: PlannedSession[];
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
  // Phase 2b-β auth surface — the only routes that intentionally
  // return 401 without redirecting (the SPA's auth-guard does that).
  me: () => request<TrainerProfile>("/api/auth/me"),
  login: (email: string, password: string) =>
    request<TrainerProfile>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  logout: () => request<{ ok: boolean }>("/api/auth/logout", { method: "POST" }),
  // Phase 3a share-link surface. createShare is trainer-scoped (carries
  // the session cookie); shareView is the public client-portal read.
  createShare: (clientId: string, trainerMessage: string | null) =>
    request<ShareCreate>(`/api/clients/${clientId}/share`, {
      method: "POST",
      body: JSON.stringify({ trainer_message: trainerMessage }),
    }),
  shareView: (token: string) => request<ShareView>(`/api/share/${encodeURIComponent(token)}`),
  // Phase 3b intake-link surface. mintIntake is trainer-scoped (carries
  // the session cookie); getIntake + submitIntake are public — no
  // cookie required, the token in the URL is the bearer credential.
  mintIntake: (trainerMessage: string | null) =>
    request<IntakeMint>("/api/clients/intake/mint", {
      method: "POST",
      body: JSON.stringify({ trainer_message: trainerMessage }),
    }),
  getIntake: (token: string) =>
    request<IntakeView>(`/api/intake/${encodeURIComponent(token)}`),
  submitIntake: (token: string, payload: ClientFormPayload) =>
    request<{ ok: boolean; id: string }>(`/api/intake/${encodeURIComponent(token)}`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  draftCoachMessage: (clientId: string) =>
    request<CoachDraft>(`/api/clients/${clientId}/coach-message/draft`, {
      method: "POST",
    }),
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
  plan: (clientId: string) => request<PlanResponse>(`/api/clients/${clientId}/plan`),
  patchPlannedSession: (
    clientId: string,
    slot: number,
    payload: Partial<{
      type: string;
      title: string;
      description: string;
      target_duration_min: number;
      target_load_au: number;
      target_rpe: number;
    }>,
  ) =>
    request<PlannedSession>(`/api/clients/${clientId}/plan/${slot}`, {
      method: "PATCH",
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
    // Use API_BASE (which has the localhost dev fallback) rather than
    // reading the env var directly — otherwise dev calls would post to
    // the relative path and miss the FastAPI server. credentials:
    // "include" carries the session cookie cross-origin.
    const res = await fetch(`${API_BASE}/api/clients/${clientId}/upload`, {
      method: "POST",
      body: form,
      credentials: "include",
    });
    if (!res.ok) {
      const detail = await res.text().catch(() => res.statusText);
      throw new ApiError(res.status, detail || `HTTP ${res.status}`);
    }
    return res.json();
  },
  ask: (payload: { question: string; history: Record<string, unknown>[]; model?: string }) =>
    request<AskResponse>("/api/ask", { method: "POST", body: JSON.stringify(payload) }),
  downloadPdf: async (clientId: string, coachMessage: string | null): Promise<Blob> => {
    const res = await fetch(`${API_BASE}/api/clients/${clientId}/pdf`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ coach_message: coachMessage ?? null }),
      credentials: "include",
    });
    if (!res.ok) {
      const detail = await res.text().catch(() => res.statusText);
      throw new ApiError(res.status, detail || `HTTP ${res.status}`);
    }
    return res.blob();
  },
};
