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
