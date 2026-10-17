import type { Job } from "./api";

export function makeJob(overrides: Partial<Job> = {}): Job {
  const base: Job = {
    id: 1,
    source: "google_careers",
    external_job_id: "123",
    title: "Software Engineer",
    company: "Google",
    location: "Tokyo",
    first_seen_at: "2026-10-01T00:00:00Z",
    last_seen_at: "2026-10-17T00:00:00Z",
    updated_at: "2026-10-17T00:00:00Z",
    ...overrides,
  };
  return base;
}
