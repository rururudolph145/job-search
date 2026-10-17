const BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export class NotFoundError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "NotFoundError";
  }
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const resp = init ? await fetch(url, init) : await fetch(url);
  if (!resp.ok) {
    if (resp.status === 404) {
      throw new NotFoundError(resp.statusText);
    }
    throw new Error(resp.statusText);
  }
  return (await resp.json()) as T;
}

export interface HealthResponse {
  status: string;
}

export async function fetchHealth(): Promise<HealthResponse> {
  return request<HealthResponse>(`${BASE}/health`);
}

export interface Job {
  id: number;
  source: string;
  external_job_id: string | null;
  title: string;
  company: string | null;
  location: string | null;
  first_seen_at: string;
  last_seen_at: string;
  updated_at: string;
}

export interface JobList {
  items: Job[];
  total: number;
}

export interface JobsQuery {
  q?: string;
  company?: string;
  location?: string;
  source?: string;
  offset?: number;
}

export async function fetchJobs(query: JobsQuery): Promise<JobList> {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query) as [string, string | number | undefined][]) {
    if (value === undefined) continue;
    if (typeof value === "string" && value === "") continue;
    params.set(key, String(value));
  }
  const qs = params.toString();
  return request<JobList>(`${BASE}/jobs${qs ? `?${qs}` : ""}`);
}

export async function fetchJob(id: number): Promise<Job> {
  return request<Job>(`${BASE}/jobs/${id}`);
}
