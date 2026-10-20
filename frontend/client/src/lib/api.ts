/**
 * Typed client for the Re.Think backend.
 *
 * Every call goes to this app's own server (`/api/rethink/*`). That server
 * holds the shared API key and attaches the verified OAuth identity, so no
 * secret and no user id is ever hardcoded in the browser.
 */

const PROXY_BASE = "/api/rethink";

export class ApiError extends Error {
  status: number;
  retryAfterSeconds: number | null;
  code: string | null;

  constructor(
    status: number,
    message: string,
    options?: { retryAfterSeconds?: number | null; code?: string | null }
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.retryAfterSeconds = options?.retryAfterSeconds ?? null;
    this.code = options?.code ?? null;
  }

  get isUnauthorized() {
    return this.status === 401;
  }

  get isRateLimited() {
    return this.status === 429;
  }

  get isUnavailable() {
    return this.status === 503;
  }
}

function parseRetryAfter(value: string | null): number | null {
  if (!value) return null;
  const seconds = Number(value);
  if (Number.isFinite(seconds)) return Math.max(0, Math.round(seconds));
  const date = Date.parse(value);
  if (Number.isFinite(date)) {
    return Math.max(0, Math.round((date - Date.now()) / 1000));
  }
  return null;
}

async function readDetail(response: Response): Promise<string> {
  try {
    const text = await response.text();
    if (!text) return "";
    try {
      const parsed = JSON.parse(text) as { detail?: unknown; error?: unknown };
      if (typeof parsed.detail === "string") return parsed.detail;
      if (parsed.detail) return JSON.stringify(parsed.detail);
      if (typeof parsed.error === "string") return parsed.error;
      return text;
    } catch {
      return text;
    }
  } catch {
    return "";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${PROXY_BASE}${path}`, {
      credentials: "include",
      headers: {
        Accept: "application/json",
        ...(init?.body ? { "Content-Type": "application/json" } : {}),
        ...(init?.headers ?? {}),
      },
      ...init,
    });
  } catch {
    throw new ApiError(
      0,
      "Network error: the Re.Think server could not be reached.",
      { code: "network_error" }
    );
  }

  if (response.status === 401) {
    throw new ApiError(401, "Your session expired. Please sign in again.");
  }

  if (response.status === 429) {
    const retryAfterSeconds = parseRetryAfter(response.headers.get("retry-after"));
    const detail = await readDetail(response);
    const retryText =
      retryAfterSeconds != null ? ` Retry after ${retryAfterSeconds}s.` : "";
    throw new ApiError(
      429,
      `${detail || "The coach is receiving too many requests."}${retryText}`,
      { retryAfterSeconds }
    );
  }

  if (response.status === 503) {
    const detail = await readDetail(response);
    throw new ApiError(
      503,
      detail || "The backend is temporarily unavailable.",
      { code: "service_unavailable" }
    );
  }

  if (!response.ok) {
    const detail = await readDetail(response);
    throw new ApiError(
      response.status,
      detail || `Request failed with status ${response.status}.`
    );
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

function query(params: Record<string, string | number | undefined | null>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") {
      search.set(key, String(value));
    }
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

// ── Types ───────────────────────────────────────────────────────────────────

export type User = {
  id: number;
  username: string;
  external_id: string | null;
  created_at: string;
};

export type SessionUser = {
  externalId: string;
  name: string;
  backendUserId: number;
  username: string;
};

export type AuthConfig = {
  oauthEnabled: boolean;
  devLoginEnabled: boolean;
  defaultExternalId: string;
};

export type PlatformLink = {
  id: number;
  user_id: number;
  platform: string;
  handle: string;
  last_synced_at: string | null;
  sync_status: "idle" | "queued" | "syncing" | "synced" | "failed";
  sync_error: string | null;
  created_at: string;
};

export type AnalyticsSummary = {
  user_id: number;
  computed_at: string;
  total_problems_solved: number;
  total_problems_attempted: number;
  total_submissions: number;
  overall_completion_rate: number;
  overall_efficiency: number;
  strengths: string[];
  weaknesses: string[];
  stale_topics: string[];
  contest_summary: Record<string, unknown>;
};

export type TopicAnalytics = {
  tag: string;
  demonstrated_level: number | null;
  freshness_days: number | null;
  sample_size: number;
  rated_sample_size: number;
  attempted_count: number;
  confident: boolean;
  low_confidence: boolean;
  solve_completion_rate: number;
  submission_efficiency: number;
  avg_attempts_per_solve: number;
  last_solved_at: string | null;
};

export type DifficultyBucket = { rating_range: string; count: number };

export type ContestMetrics = {
  user_id: number;
  current_rating: number | null;
  max_rating: number | null;
  contest_count: number;
  best_rank: number | null;
  avg_rank: number | null;
  avg_delta: number | null;
  rating_volatility: number | null;
  recent_contests: Array<Record<string, unknown>>;
};

export type ContestPerformance = {
  id: number;
  user_id: number;
  platform: string;
  contest_id: number;
  contest_name: string;
  rating_before: number;
  rating_after: number;
  rank: number;
  contest_date: string;
};

export type Submission = {
  id: number;
  user_id: number;
  problem_id: number;
  platform: string;
  platform_sub_id: number;
  verdict: string;
  language: string | null;
  submitted_at: string;
  time_ms: number | null;
  memory_bytes: number | null;
  contest_id: number | null;
  participant_type: string | null;
  passed_test_count: number | null;
};

export type CoachSessionListItem = {
  id: number;
  problem_id: number;
  problem_title: string | null;
  current_level: number;
  coach_mode: string;
  outcome: string;
  started_at: string;
  last_activity_at: string;
};

export type HintMessage = {
  id: number;
  session_id: number;
  role: string;
  hint_level: number | null;
  content: string;
  code_snapshot: string | null;
  tier1_blocked: boolean;
  created_at: string;
};

export type CoachSession = {
  id: number;
  user_id: number;
  problem_id: number;
  current_level: number;
  coach_mode: string;
  user_stated_approach: string | null;
  outcome: string;
  knowledge_confidence: string | null;
  started_at: string;
  last_activity_at: string;
  solved_at: string | null;
  messages: HintMessage[];
};

export type Recommendation = {
  id: number;
  recommendation_type: string;
  topic: string;
  reason: string;
  status: string;
  created_at: string;
  target_rating_min: number | null;
  target_rating_max: number | null;
  problem: {
    id: number;
    platform_id: string;
    title: string;
    rating: number | null;
    tags: string[];
    url: string | null;
  } | null;
};

export type Reflection = {
  id: number;
  date: string;
  content: string;
  metrics: Record<string, unknown>;
  generated_at: string | null;
};

export type Problem = {
  id: number;
  platform: string;
  platform_id: string;
  contest_id: number | null;
  problem_index: string | null;
  title: string;
  rating: number | null;
  difficulty_label: string | null;
  tags: string[] | null;
  solved_count: number;
  url: string | null;
};

export type ProblemKnowledge = {
  id: number;
  problem_id: number;
  source_type: string;
  extraction_method: string;
  validation_status: string;
  approach_summary: string | null;
  key_insight: string | null;
  techniques: string[];
  common_pitfalls: string[];
  editorial_url: string | null;
  coach_mode: string | null;
  created_at: string;
};

export type SyncResult = {
  status: string;
  link_id: number;
  user_id: number;
  submissions_fetched: number;
  submissions_newly_inserted: number;
  contests_fetched: number;
  contests_newly_inserted: number;
  problems_upserted: number;
  submissions_synced: number;
  contests_synced: number;
};

export type RecommendationResult = {
  status: "problem" | "study" | "insufficient_data" | "no_candidates";
  recommendation_id: number | null;
  topic: string | null;
  reason: string | null;
  problem: {
    id: number;
    platform_id: string;
    title: string;
    rating: number | null;
    tags: string[];
    url: string | null;
  } | null;
  resource_url: string | null;
};

// ── Auth (served by this app, not the backend proxy) ────────────────────────

async function authRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    credentials: "include",
    headers: init?.body ? { "Content-Type": "application/json" } : undefined,
    ...init,
  });
  if (!response.ok) {
    const detail = await readDetail(response);
    throw new ApiError(response.status, detail || `Auth request failed (${response.status})`);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const authApi = {
  config: () => authRequest<AuthConfig>("/api/auth/config"),
  me: () => authRequest<{ user: SessionUser }>("/api/auth/me"),
  login: (externalId: string, name?: string) =>
    authRequest<{ user: SessionUser }>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ external_id: externalId, name }),
    }),
  logout: () => authRequest<{ status: string }>("/api/auth/logout", { method: "POST" }),
  oauthStartUrl: "/api/auth/oauth/start",
};

// ── Backend endpoints ────────────────────────────────────────────────────────

export const api = {
  me: () => request<User>("/users/me"),
  user: (userId: number) => request<User>(`/users/${userId}`),

  analyticsSummary: (userId: number) =>
    request<AnalyticsSummary>(`/analytics/${userId}/summary`),
  recomputeAnalytics: (userId: number) =>
    request<{ status: string; user_id: number; computed_at: string }>(
      `/analytics/${userId}/recompute`,
      { method: "POST" }
    ),
  topics: (userId: number, minSamples = 0) =>
    request<TopicAnalytics[]>(
      `/analytics/${userId}/topics${query({ min_samples: minSamples })}`
    ),
  difficulty: (userId: number) =>
    request<{ user_id: number; buckets: DifficultyBucket[] }>(
      `/analytics/${userId}/difficulty`
    ),
  contestMetrics: (userId: number) =>
    request<ContestMetrics>(`/analytics/${userId}/contests`),

  submissions: (userId: number, limit = 50) =>
    request<Submission[]>(`/submissions${query({ user_id: userId, limit })}`),
  contests: (userId: number, limit = 50) =>
    request<ContestPerformance[]>(`/contests${query({ user_id: userId, limit })}`),

  platforms: (userId: number) =>
    request<PlatformLink[]>(`/platforms${query({ user_id: userId })}`),
  createPlatformLink: (
    userId: number,
    platform: string,
    handle: string,
    authToken?: string
  ) =>
    request<PlatformLink>("/platforms/link", {
      method: "POST",
      body: JSON.stringify({
        user_id: userId,
        platform,
        handle,
        auth_token: authToken || null,
      }),
    }),
  platformStatus: (linkId: number) =>
    request<PlatformLink>(`/platforms/${linkId}/status`),
  syncPlatform: (linkId: number) =>
    request<SyncResult>(`/platforms/${linkId}/sync`, { method: "POST" }),
  unlinkPlatform: (linkId: number) =>
    request<void>(`/platforms/${linkId}`, { method: "DELETE" }),

  coachSessions: (userId: number) =>
    request<CoachSessionListItem[]>(`/coach/sessions${query({ user_id: userId })}`),
  coachSession: (sessionId: number) =>
    request<CoachSession>(`/coach/sessions/${sessionId}`),
  createCoachSession: (userId: number, problemId: number) =>
    request<CoachSession>("/coach/sessions", {
      method: "POST",
      body: JSON.stringify({ user_id: userId, problem_id: problemId }),
    }),
  sendCoachMessage: (
    sessionId: number,
    message: string,
    currentCode?: string,
    requestEscalation = false
  ) =>
    request<{
      coach_message: HintMessage;
      current_level: number;
      coach_mode: string;
      user_stated_approach: string | null;
    }>(`/coach/sessions/${sessionId}/message`, {
      method: "POST",
      body: JSON.stringify({
        user_message: message,
        current_code: currentCode || null,
        request_escalation: requestEscalation,
      }),
    }),
  concludeCoachSession: (sessionId: number, outcome: string) =>
    request<CoachSession>(`/coach/sessions/${sessionId}/conclude`, {
      method: "POST",
      body: JSON.stringify({ outcome }),
    }),

  recommendations: (userId: number) =>
    request<Recommendation[]>(`/recommendations/${userId}`),
  generateRecommendation: (userId: number) =>
    request<RecommendationResult>(`/recommendations/${userId}/problem`, {
      method: "POST",
    }),
  dismissRecommendation: (recommendationId: number) =>
    request<{ status: string }>(`/recommendations/${recommendationId}/dismiss`, {
      method: "POST",
    }),

  reflections: (userId: number, from?: string, to?: string) =>
    request<Reflection[]>(`/reflections${query({ user_id: userId, from, to })}`),
  generateReflection: (userId: number, date?: string) =>
    request<{
      status: string;
      reflection: {
        id: number;
        user_id: number;
        date: string;
        content: string;
        metrics: Record<string, unknown>;
        generated_at: string | null;
      } | null;
      reason: string | null;
    }>(`/reflections/${userId}/generate${query({ date })}`, { method: "POST" }),

  problems: (limit = 100) => request<Problem[]>(`/problems${query({ limit })}`),
  knowledge: (problemId: number) =>
    request<ProblemKnowledge>(`/knowledge/${problemId}`),
  verifyKnowledge: (knowledgeId: number, status: "user_verified" | "user_rejected") =>
    request<ProblemKnowledge>(`/knowledge/${knowledgeId}/verify`, {
      method: "POST",
      body: JSON.stringify({ status }),
    }),
};
