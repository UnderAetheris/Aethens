const BASE = (import.meta as ImportMeta & { env?: { VITE_AETHERIS_API?: string } }).env?.VITE_AETHERIS_API ?? "http://127.0.0.1:8000";

export interface TaskOut {
  id: string;
  task: string;
  state: string;
  detail: string;
  priority: number;
  created_at: number;
  updated_at: number;
}

export interface EventOut {
  ts: number;
  kind: string;
  data: Record<string, unknown>;
}

export interface EvalSummaryOut {
  passed: number;
  total: number;
  pass_rate: number;
  ts: number | null;
  available: boolean;
}

export interface KnowledgeOut {
  id: string;
  title: string;
  source: string;
  summary: string;
  tags: string[];
  confidence: number;
  created_at: number;
}

export interface ExperienceOut {
  id: string;
  problem: string;
  cause: string;
  fix: string;
  evidence: string;
  related_task: string | null;
  related_eval_case: string | null;
  confidence: number;
  created_at: number;
}

export interface LearnedStepOut {
  intent: string;
  keyword: string;
  from_case: string;
  created_at: number;
}

export interface LearningStateOut {
  extra_keywords: Record<string, string[]>;
  steps: LearnedStepOut[];
}

export interface HealthOut {
  status: string;
  queued: number;
  active: number;
  settled: number;
}

export type ApiErrorKind = "network" | "http" | "timeout";

export class ApiError extends Error {
  constructor(public kind: ApiErrorKind, public status?: number, public detail?: string) {
    super(detail ?? kind);
    this.name = "ApiError";
  }
}

async function req<T>(path: string, init?: RequestInit, timeoutMs = 4000): Promise<T> {
  const ctrl = new AbortController();
  const timer = window.setTimeout(() => ctrl.abort(), timeoutMs);
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      ...init,
      signal: ctrl.signal,
      headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
    });
  } catch (error) {
    window.clearTimeout(timer);
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new ApiError("timeout");
    }
    throw new ApiError("network");
  }
  window.clearTimeout(timer);
  if (!res.ok) {
    let detail: string | undefined;
    try {
      const body = await res.json();
      detail = typeof body?.detail === "string" ? body.detail : undefined;
    } catch {
      // ignore
    }
    throw new ApiError("http", res.status, detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => req<HealthOut>("/health"),
  listTasks: () => req<TaskOut[]>("/tasks"),
  getTask: (id: string) => req<TaskOut>(`/tasks/${encodeURIComponent(id)}`),
  submitTask: (task: string, priority = 0) =>
    req<TaskOut>("/tasks", { method: "POST", body: JSON.stringify({ task, priority }) }),
  recentEvents: (limit = 50) => req<EventOut[]>(`/events/recent?limit=${limit}`),
  evalSummary: () => req<EvalSummaryOut>("/evaluation/summary"),
  knowledge: () => req<KnowledgeOut[]>("/memory/knowledge"),
  experience: () => req<ExperienceOut[]>("/memory/experience"),
  learningState: () => req<LearningStateOut>("/learning/state"),
};
