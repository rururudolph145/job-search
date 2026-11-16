# PBI 5 — Jobs Dashboard Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the placeholder `DashboardPage` with a filterable, paginated jobs list at `/jobs` and a detail page at `/jobs/:id`, consuming only the PBI 4 read endpoints.

**Architecture:** URL-as-state via React Router's `useSearchParams` (filters `q`/`company`/`location`/`source` + 1-based `page`) drives a single `fetchJobs` call on param change; a `cancelled` flag drops stale responses. A dedicated `/jobs/:id` route fetches one job and links back with the list's query string preserved. No data library, no new dependency, no backend change.

**Tech Stack:** React 18 + TypeScript (strict), React Router v6 (`useSearchParams`, `useParams`, `Link`, `Navigate`), Vitest + Testing Library (`MemoryRouter`, `vi.stubGlobal("fetch", …)`), Tailwind CSS (styling matches existing `NavBar`/`PbiTrackerPage` classes), Vite.

**Spec:** `docs/superpowers/specs/2026-10-18-pbi5-jobs-dashboard-design.md`

## Global Constraints

- Frontend-only: no backend, schema, or dependency change. `package.json` `devDependencies`/`dependencies` stay exactly as they are today.
- `tsconfig.json` runs `strict`, `noUnusedLocals`, `noUnusedParameters` — test files must not import or declare anything unused or `npm run typecheck` fails.
- The `q` filter is a title substring (`ilike`) — it is *not* full-text search (PBI 10 replaces it). No date, salary, remote, or description fields; the UI renders only the eight `Job` fields.
- New route components live in `frontend/src/pages/`; new test files sit next to them as `*.test.tsx`. Style uses the existing Tailwind utility classes (e.g. `text-slate-600`, `bg-slate-900`); no new CSS.
- `typecheck`, `test`, and `build` must all pass before the tracker checkboxes are ticked.

## Review Focus

These are the input classes and failure modes the spec implies but no happy-path test exercises naturally. Each is pinned by a test in its owning task.

1. **A non-numeric `:id` must render not-found *without* a `fetch` call** — `/jobs/abc` should show "Job not found." and never hit the network; otherwise a junk URL triggers a doomed request. Pinned in Task 5 (`resolveParamId` / `test_non_numeric_id_no_fetch`) and Task 6 (`test_non_numeric_id_renders_not_found_without_fetch`).
2. **`formatDate` must not throw on a missing/invalid date** — `first_seen_at`/`last_seen_at`/`updated_at` from the API are `string`, and a null or unparseable value must render "—" rather than "Invalid Date" or a crash. Pinned in Task 3 (`test_format_date_null_and_invalid`).
3. **Page arithmetic must guard against `total === 0`** — the pager is *hidden* when `total` is 0, so "Showing X–Y of N" must never emit `X = offset + 1` into an empty set, and `totalPages = 0` must not render "Page 1 of 0". Pinned in Task 4 (`test_pager_hidden_when_total_zero`).
4. **A card link must round-trip the *entire* current filter string, not just `page`** — opening a card from `?q=engineer&company=Google&page=2` must preserve all three params so Back restores the exact view. Pinned in Task 4 (`test_card_link_preserves_query_string`).
5. **Empty-with-filters vs empty-without-filters must be distinguishable** — "No jobs match your filters." only when a recognized filter param is present; "No jobs yet." otherwise. A filtered-empty result mislabeled as "no jobs yet" is a real bug. Pinned in Task 4 (`test_empty_states`).

---

### Task 1: Extend the API layer

**Files:**
- Modify: `frontend/src/api.ts` (append after `fetchHealth`)
- Test: `frontend/src/api.test.ts` (new)

**Interfaces:**
- Consumes: `BASE` (module const), `request<T>` (existing private fn), `NotFoundError` (existing class).
- Produces:
  - `Job` (interface) — `id: number; source: string; external_job_id: string | null; title: string; company: string | null; location: string | null; first_seen_at: string; last_seen_at: string; updated_at: string;`
  - `JobList` (interface) — `items: Job[]; total: number;`
  - `JobsQuery` (interface) — `q?, company?, location?, source?, offset?` (all optional, strings + optional number)
  - `fetchJobs(query: JobsQuery): Promise<JobList>`
  - `fetchJob(id: number): Promise<Job>`

- [x] **Step 1: Write the failing tests**

Create `frontend/src/api.test.ts`:

```ts
import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchJob, fetchJobs, NotFoundError } from "./api";

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 404 ? "Not Found" : "OK",
    json: async () => body,
  } as Response;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("fetchJobs", () => {
  it("builds the URL from defined, non-empty query fields only", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ items: [], total: 0 }));
    vi.stubGlobal("fetch", fetchMock);

    await fetchJobs({ q: "engineer", company: "Google", location: "", source: undefined });

    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).not.toContain("location");
    expect(url).not.toContain("source");
    expect(url).toContain("q=engineer");
    expect(url).toContain("company=Google");
  });

  it("includes offset when it is a defined number", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ items: [], total: 0 }));
    vi.stubGlobal("fetch", fetchMock);

    await fetchJobs({ offset: 100 });

    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain("offset=100");
  });

  it("omits offset when it is undefined", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ items: [], total: 0 }));
    vi.stubGlobal("fetch", fetchMock);

    await fetchJobs({});

    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).not.toContain("offset");
  });

  it("returns the parsed JobList", async () => {
    const payload = { items: [{ id: 1, title: "Engineer" }], total: 1 };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(payload)));

    const result = await fetchJobs({ q: "engineer" });

    expect(result).toEqual(payload);
  });
});

describe("fetchJob", () => {
  it("fetches /jobs/{id} and returns the Job", async () => {
    const job = { id: 42, title: "Engineer" };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(job));
    vi.stubGlobal("fetch", fetchMock);

    const result = await fetchJob(42);

    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/jobs/42"));
    expect(result).toEqual(job);
  });

  it("rethrows a 404 as NotFoundError", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({}, 404)));

    await expect(fetchJob(999)).rejects.toBeInstanceOf(NotFoundError);
  });
});
```

- [x] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npm test -- api.test.ts` (or `npx vitest run src/api.test.ts`)
Expected: FAIL — `TypeError: fetchJobs is not a function` (no export).

- [x] **Step 3: Write minimal implementation**

Append to `frontend/src/api.ts` (after `fetchHealth`):

```ts
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
```

> Note: `JobsQuery` has no optional `limit`, so `fetchJobs` never sends `limit` — the client relies on the API default of 50, matching the spec §3 "Page size" decision. `0` is allowed as an `offset` value (page 1) and is passed through unchanged because numeric `0` is neither `undefined` nor `""`.

- [x] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npm test -- api.test.ts`
Expected: PASS (7 tests).

- [x] **Step 5: Commit**

```bash
git add frontend/src/api.ts frontend/src/api.test.ts
git commit -m "feat(dashboard): add Job/JobList types and fetchJobs/fetchJob to API layer"
```

---

### Task 2: Add URL-param reading helpers

**Files:**
- Create: `frontend/src/urlParams.ts`
- Test: `frontend/src/urlParams.test.ts` (new)

**Interfaces:**
- Consumes: nothing (pure functions).
- Produces:
  - `readSearchParams(searchParams: URLSearchParams): { q: string; company: string; location: string; source: string; page: number }` — `page` is 1-based, clamped to ≥ 1; absent or non-numeric ⇒ 1.
  - `filterActive(searchParams: URLSearchParams): boolean` — `true` iff any of `q`/`company`/`location`/`source` is a non-empty string.
  - `paramsToQueryString(searchParams: URLSearchParams): string` — `""` when empty, else `"?" + toString()` (used to build the preserved back link).

- [x] **Step 1: Write the failing tests**

Create `frontend/src/urlParams.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import {
  filterActive,
  paramsToQueryString,
  readSearchParams,
} from "./urlParams";

describe("readSearchParams", () => {
  it("maps a full set of params", () => {
    const p = new URLSearchParams("q=engineer&company=Google&location=Tokyo&source=gc&page=3");
    expect(readSearchParams(p)).toEqual({
      q: "engineer",
      company: "Google",
      location: "Tokyo",
      source: "gc",
      page: 3,
    });
  });

  it("defaults missing params", () => {
    const p = new URLSearchParams("");
    expect(readSearchParams(p)).toEqual({
      q: "",
      company: "",
      location: "",
      source: "",
      page: 1,
    });
  });

  it("clamps page to 1 when absent or invalid", () => {
    expect(readSearchParams(new URLSearchParams("")).page).toBe(1);
    expect(readSearchParams(new URLSearchParams("page=abc")).page).toBe(1);
    expect(readSearchParams(new URLSearchParams("page=0")).page).toBe(1);
    expect(readSearchParams(new URLSearchParams("page=-2")).page).toBe(1);
  });
});

describe("filterActive", () => {
  it("is false with no filters", () => {
    expect(filterActive(new URLSearchParams(""))).toBe(false);
  });

  it("is true when any recognized filter is non-empty", () => {
    expect(filterActive(new URLSearchParams("q=x"))).toBe(true);
    expect(filterActive(new URLSearchParams("company=x"))).toBe(true);
    expect(filterActive(new URLSearchParams("location=x"))).toBe(true);
    expect(filterActive(new URLSearchParams("source=x"))).toBe(true);
  });

  it("ignores the page param", () => {
    expect(filterActive(new URLSearchParams("page=3"))).toBe(false);
  });
});

describe("paramsToQueryString", () => {
  it("returns empty string for no params", () => {
    expect(paramsToQueryString(new URLSearchParams(""))).toBe("");
  });

  it("prefixes non-empty params with '?'", () => {
    expect(paramsToQueryString(new URLSearchParams("q=a&page=2"))).toBe("?q=a&page=2");
  });
});
```

- [x] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npm test -- urlParams.test.ts`
Expected: FAIL — `Cannot find module './urlParams'`.

- [x] **Step 3: Write minimal implementation**

Create `frontend/src/urlParams.ts`:

```ts
const FILTER_KEYS = ["q", "company", "location", "source"] as const;

export interface SearchParams {
  q: string;
  company: string;
  location: string;
  source: string;
  page: number;
}

export function readSearchParams(searchParams: URLSearchParams): SearchParams {
  const rawPage = Number.parseInt(searchParams.get("page") ?? "", 10);
  const page = Number.isNaN(rawPage) || rawPage < 1 ? 1 : rawPage;

  return {
    q: searchParams.get("q") ?? "",
    company: searchParams.get("company") ?? "",
    location: searchParams.get("location") ?? "",
    source: searchParams.get("source") ?? "",
    page,
  };
}

export function filterActive(searchParams: URLSearchParams): boolean {
  return FILTER_KEYS.some((key) => (searchParams.get(key) ?? "").trim() !== "");
}

export function paramsToQueryString(searchParams: URLSearchParams): string {
  const s = searchParams.toString();
  return s ? `?${s}` : "";
}
```

- [x] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npm test -- urlParams.test.ts`
Expected: PASS (8 tests).

- [x] **Step 5: Commit**

```bash
git add frontend/src/urlParams.ts frontend/src/urlParams.test.ts
git commit -m "feat(dashboard): add url-param reading helpers"
```

---

### Task 3: Add the `formatDate` helper

**Files:**
- Create: `frontend/src/formatDate.ts`
- Test: `frontend/src/formatDate.test.ts` (new)

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `formatDate(iso: string | null, now: Date): string` — renders "—" for null/invalid and for impossible timestamps; else a relative phrase ("Just now", "Xm ago", "Xh ago", or "X days ago") like "Updated <phrase>". Absolute ISO is not baked into the string — callers put it in a `title` attribute. The `now` parameter is injected to keep the function pure and testable (see below).
  - `isValidIsoDate(iso: string | null): boolean` — exported for reuse by the pager, return-type guarded.

- [x] **Step 1: Write the failing tests**

Create `frontend/src/formatDate.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { formatDate, isValidIsoDate } from "./formatDate";

const NOW = new Date("2026-10-18T12:00:00.000Z");

function minutesAgo(mins: number): Date {
  return new Date(NOW.getTime() - mins * 60_000);
}

describe("formatDate", () => {
  it("renders an em-dash for null", () => {
    expect(formatDate(null, NOW)).toBe("—");
  });

  it("renders an em-dash for an invalid date", () => {
    expect(formatDate("not-a-date", NOW)).toBe("—");
  });

  it("renders an em-dash for an impossible (overflowing) date", () => {
    expect(formatDate("2026-99-99T00:00:00Z", NOW)).toBe("—");
  });

  it("renders 'Just now' for a very recent timestamp", () => {
    expect(formatDate(minutesAgo(0.5).toISOString(), NOW)).toContain("now");
  });

  it("renders a minutes-ago phrase under an hour", () => {
    expect(formatDate(minutesAgo(30).toISOString(), NOW)).toBe("30m ago");
  });

  it("renders an hours-ago phrase under a day", () => {
    expect(formatDate(minutesAgo(60 * 5).toISOString(), NOW)).toBe("5h ago");
  });

  it("renders a days-ago phrase at a day or more", () => {
    expect(formatDate(minutesAgo(60 * 24 * 3).toISOString(), NOW)).toBe("3 days ago");
  });
});

describe("isValidIsoDate", () => {
  it("accepts a valid ISO string and rejects garbage", () => {
    expect(isValidIsoDate("2026-10-18T12:00:00Z")).toBe(true);
    expect(isValidIsoDate(null)).toBe(false);
    expect(isValidIsoDate("x")).toBe(false);
  });
});
```

- [x] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npm test -- formatDate.test.ts`
Expected: FAIL — `Cannot find module './formatDate'`.

- [x] **Step 3: Write minimal implementation**

Create `frontend/src/formatDate.ts`:

```ts
const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

export function isValidIsoDate(iso: string | null): boolean {
  if (iso === null) return false;
  const t = Date.parse(iso);
  return !Number.isNaN(t);
}

/**
 * Relative display of an ISO timestamp, or "—" when it is missing/invalid or
 * in the future (impossible for a job's "seen" timestamp). `now` is injected so
 * callers and tests control the reference instant; the absolute date is left to
 * the caller's `title` attribute.
 */
export function formatDate(iso: string | null, now: Date): string {
  if (!isValidIsoDate(iso)) return "—";
  const then = Date.parse(iso as string);
  const diff = now.getTime() - then;
  if (diff < 0) return "—";
  if (diff < MINUTE) return "Just now";
  if (diff < HOUR) return `${Math.floor(diff / MINUTE)}m ago`;
  if (diff < DAY) return `${Math.floor(diff / HOUR)}h ago`;
  return `${Math.floor(diff / DAY)} days ago`;
}
```

- [x] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npm test -- formatDate.test.ts`
Expected: PASS (9 tests).

- [x] **Step 5: Commit**

```bash
git add frontend/src/formatDate.ts frontend/src/formatDate.test.ts
git commit -m "feat(dashboard): add formatDate relative-date helper"
```

---

### Task 4: Add the `JobsPage` list + filter bar + pager

**Files:**
- Create: `frontend/src/pages/JobsPage.tsx`
- Test: `frontend/src/pages/JobsPage.test.tsx` (new)

**Interfaces:**
- Consumes: `fetchJobs`, `Job`, `JobList` (Task 1); `readSearchParams`, `filterActive` (Task 2); `formatDate` (Task 3); `Link`, `useSearchParams` (react-router-dom).
- Produces: `JobsPage` (default-ish named export `export function JobsPage()`), rendering `<h1>Jobs</h1>`, the filter `<form>`, the card `<ul>`, and the pager. This is what `App.tsx` mounts at `/jobs`.

- [x] **Step 1: Write the failing tests**

Create `frontend/src/pages/JobsPage.test.tsx`. This file also needs the `Job` factory helper used later in Task 6, so define it here and export nothing unused — tests import it from `../test-utils`. To keep a single source of truth, create the shared factory in a tiny helper module first (it is exercised *by this task's tests*, so it is not unused code):

Create `frontend/src/test-utils.ts` (new, alongside the page) with a `makeJob` factory and a fake `JobList`:

```ts
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
```

Now create `frontend/src/pages/JobsPage.test.tsx`:

```tsx
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import type { JobList } from "../api";
import { makeJob } from "../test-utils";
import { JobsPage } from "./JobsPage";

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderWithRouter(path = "/jobs") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <JobsPage />
    </MemoryRouter>,
  );
}

describe("JobsPage", () => {
  it("renders each job's title from the fetched list", async () => {
    const list: JobList = {
      items: [makeJob({ title: "Software Engineer" }), makeJob({ id: 2, title: "Data Analyst" })],
      total: 2,
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true, status: 200, statusText: "OK", json: async () => list,
    } as Response));

    renderWithRouter();

    expect(await screen.findByText("Software Engineer")).toBeInTheDocument();
    expect(screen.getByText("Data Analyst")).toBeInTheDocument();
  });

  it("shows the loading state before the fetch resolves", async () => {
    let resolve!: (r: Response) => void;
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise<Response>((r) => { resolve = r; })));

    renderWithRouter();

    expect(screen.getByRole("status")).toHaveTextContent("Loading jobs…");
    resolve({ ok: true, status: 200, statusText: "OK", json: async () => ({ items: [], total: 0 }) } as Response);
    expect(await screen.findByText("No jobs yet.")).toBeInTheDocument();
  });

  it("distinguishes empty-with-filters from empty-without-filters", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true, status: 200, statusText: "OK", json: async () => ({ items: [], total: 0 }),
    } as Response));

    const { unmount } = renderWithRouter();
    expect(await screen.findByText("No jobs yet.")).toBeInTheDocument();
    unmount();

    renderWithRouter("/jobs?q=zzz");
    expect(await screen.findByText("No jobs match your filters.")).toBeInTheDocument();
  });

  it("shows Retry on error and re-fetches on click", async () => {
    const success: JobList = { items: [makeJob({ title: "Software Engineer" })], total: 1 };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({ ok: false, status: 500, statusText: "Server Error", json: async () => ({}) } as Response)
      .mockResolvedValueOnce({ ok: true, status: 200, statusText: "OK", json: async () => success } as Response);
    vi.stubGlobal("fetch", fetchMock);

    renderWithRouter();

    expect(await screen.findByText("Couldn't load jobs.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("Software Engineer")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("submits the form with all filters and a reset page", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, status: 200, statusText: "OK", json: async () => ({ items: [], total: 0 }),
    } as Response);
    vi.stubGlobal("fetch", fetchMock);

    renderWithRouter();

    await userEvent.type(screen.getByLabelText("Title"), "engineer");
    await userEvent.type(screen.getByLabelText("Company"), "Google");
    await userEvent.type(screen.getByLabelText("Location"), "Tokyo");
    await userEvent.type(screen.getByLabelText("Source"), "google_careers");
    await userEvent.click(screen.getByRole("button", { name: "Apply" }));

    const url = fetchMock.mock.calls[fetchMock.mock.calls.length - 1][0] as string;
    expect(url).toContain("q=engineer");
    expect(url).toContain("company=Google");
    expect(url).toContain("location=Tokyo");
    expect(url).toContain("source=google_careers");
    expect(url).toContain("offset=0");
  });

  it("clear filters resets all params", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, status: 200, statusText: "OK", json: async () => ({ items: [], total: 0 }),
    } as Response);
    vi.stubGlobal("fetch", fetchMock);

    renderWithRouter("/jobs?q=engineer");

    await userEvent.click(screen.getByRole("button", { name: "Clear filters" }));

    const url = fetchMock.mock.calls[fetchMock.mock.calls.length - 1][0] as string;
    expect(url).not.toContain("q=");
  });

  it("disables Prev on page 1 and Next on the last page", async () => {
    const list: JobList = { items: [makeJob()], total: 2 };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true, status: 200, statusText: "OK", json: async () => list,
    } as Response));

    // First render: page 1 — Prev disabled.
    const { unmount } = renderWithRouter();
    await screen.findByText("Software Engineer");
    const prev1 = screen.getByRole("button", { name: "Prev" }) as HTMLButtonElement;
    expect(prev1.disabled).toBe(true);
    unmount();

    // Page 2 is the last of 2 — Next disabled.
    renderWithRouter("/jobs?page=2");
    await screen.findByText("Software Engineer");
    const next2 = screen.getByRole("button", { name: "Next" }) as HTMLButtonElement;
    expect(next2.disabled).toBe(true);
  });

  it("shows 'Showing X–Y of N' and 'Page P of T' from total", async () => {
    const list: JobList = {
      items: [makeJob({ id: 51 })] ,
      total: 101,
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true, status: 200, statusText: "OK", json: async () => list,
    } as Response));

    renderWithRouter("/jobs?page=2"); // offset = 50, items.length = 1

    await screen.findByText("Software Engineer");
    expect(screen.getByText("Showing 51–51 of 101")).toBeInTheDocument();
    expect(screen.getByText("Page 2 of 3")).toBeInTheDocument();
  });

  it("a card links to /jobs/{id} preserving the current query string", async () => {
    const list: JobList = { items: [makeJob({ id: 42 })] , total: 1 };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true, status: 200, statusText: "OK", json: async () => list,
    } as Response));

    renderWithRouter("/jobs?q=engineer&page=2");

    const link = await screen.findByRole("link", { name: /Software Engineer/ });
    expect(link).toHaveAttribute("href", "/jobs/42?q=engineer&page=2");
  });

  it("hides the pager when total is 0", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true, status: 200, statusText: "OK", json: async () => ({ items: [], total: 0 }),
    } as Response));

    renderWithRouter();
    expect(await screen.findByText("No jobs yet.")).toBeInTheDocument();
    expect(screen.queryByText(/Showing/)).not.toBeInTheDocument();
  });
});
```

- [x] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npm test -- JobsPage.test.tsx`
Expected: FAIL — `Cannot find module './JobsPage'`.

- [x] **Step 3: Write minimal implementation**

Create `frontend/src/pages/JobsPage.tsx`. Key implementation notes:

- **Params as source of truth:** `readSearchParams(searchParams)` returns the canonical `{q, company, location, source, page}`; `offset = (page - 1) * 50`.
- **Filter inputs uncontrolled** with `defaultValue` from the params — typing does not re-render. Give each a `<label>` whose text is "Title", "Company", "Location", "Source" so the `getByLabelText` queries above resolve.
- **Submit** reads each input's value, trims it, and calls `setSearchParams` with only the non-empty filters plus `page: "1"`. **Clear filters** calls `setSearchParams({})`.
- **Effect** keyed on `searchParams.toString()` + a `reload` counter; `cancelled` flag in cleanup drops stale flights.
- **Render states** are mutually exclusive and in place of the list.
- **Pager** only when `total > 0`.

```tsx
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { fetchJobs, type JobList } from "../api";
import { filterActive, readSearchParams } from "../urlParams";
import { formatDate } from "../formatDate";

const PAGE_SIZE = 50;

const FILTER_FIELDS = [
  { key: "q", label: "Title" },
  { key: "company", label: "Company" },
  { key: "location", label: "Location" },
  { key: "source", label: "Source" },
] as const;

type Status = "loading" | "error" | "done";

export function JobsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [reload, setReload] = useState(0);
  const [status, setStatus] = useState<Status>("loading");
  const [data, setData] = useState<JobList | null>(null);

  const { q, company, location, source, page } = readSearchParams(searchParams);
  const offset = (page - 1) * PAGE_SIZE;

  useEffect(() => {
    let cancelled = false;
    setStatus("loading");
    fetchJobs({ q, company, location, source, offset })
      .then((result) => {
        if (!cancelled) {
          setData(result);
          setStatus("done");
        }
      })
      .catch(() => {
        if (!cancelled) setStatus("error");
      });
    return () => {
      cancelled = true;
    };
  }, [searchParams.toString(), reload, offset, q, company, location, source]);

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const next: Record<string, string> = {};
    for (const { key } of FILTER_FIELDS) {
      const value = (form.elements.namedItem(key) as HTMLInputElement).value.trim();
      if (value) next[key] = value;
    }
    next.page = "1";
    setSearchParams(next);
  }

  function handleClear() {
    setSearchParams({});
  }

  // Build a params object that drops empty filter values — reused so Prev/Next
  // preserve only the active filters (empty strings would otherwise pollute the URL).
  function filtersToParams(): Record<string, string> {
    const next: Record<string, string> = {};
    const entries: [string, string][] = [
      ["q", q],
      ["company", company],
      ["location", location],
      ["source", source],
    ];
    for (const [key, value] of entries) {
      if (value.trim() !== "") next[key] = value;
    }
    return next;
  }

  const totalPages = data ? Math.ceil(data.total / PAGE_SIZE) : 0;

  return (
    <main className="max-w-4xl mx-auto px-6 py-10">
      <h1 className="text-2xl font-bold mb-4">Jobs</h1>

      <form onSubmit={handleSubmit} className="flex flex-wrap items-end gap-3 mb-6">
        {FILTER_FIELDS.map(({ key, label }) => (
          <label key={key} className="flex flex-col text-sm text-slate-600">
            {label}
            <input
              name={key}
              defaultValue={searchParams.get(key) ?? ""}
              className="mt-1 border border-slate-300 rounded px-2 py-1"
            />
          </label>
        ))}
        <button type="submit" className="bg-slate-800 text-white px-4 py-1 rounded">
          Apply
        </button>
        <button type="button" onClick={handleClear} className="text-slate-600 px-2 py-1">
          Clear filters
        </button>
      </form>

      {status === "loading" && (
        <p role="status">Loading jobs…</p>
      )}

      {status === "error" && (
        <div>
          <p>Couldn't load jobs.</p>
          <button type="button" onClick={() => setReload((n) => n + 1)}>
            Retry
          </button>
        </div>
      )}

      {status === "done" && data && data.total === 0 && (
        <p>{filterActive(searchParams) ? "No jobs match your filters." : "No jobs yet."}</p>
      )}

      {status === "done" && data && data.total > 0 && (
        <>
          <ul className="space-y-3">
            {data.items.map((job) => (
              <li key={job.id}>
                <Link
                  to={`/jobs/${job.id}${searchParams.toString() ? `?${searchParams.toString()}` : ""}`}
                  className="block border border-slate-200 rounded p-4 hover:border-slate-400"
                >
                  <span className="font-semibold block">{job.title}</span>
                  <span className="text-slate-500 text-sm">
                    {job.company ?? "—"} · {job.location ?? "—"}
                  </span>
                  <span className="block text-slate-400 text-xs mt-2">
                    {job.source} · Updated {formatDate(job.updated_at, new Date())}{" "}
                    <span title={job.updated_at}>({job.updated_at})</span>
                  </span>
                </Link>
              </li>
            ))}
          </ul>

          <div className="flex items-center justify-between mt-6 text-sm text-slate-600">
            <span>
              Showing {offset + 1}–{offset + data.items.length} of {data.total}
            </span>
            <span>
              Page {page} of {totalPages}
            </span>
            <span className="flex gap-2">
              <button
                type="button"
                disabled={offset <= 0}
                onClick={() =>
                  setSearchParams({ ...filtersToParams(), page: String(page - 1) })
                }
              >
                Prev
              </button>
              <button
                type="button"
                disabled={page >= totalPages}
                onClick={() =>
                  setSearchParams({ ...filtersToParams(), page: String(page + 1) })
                }
              >
                Next
              </button>
            </span>
          </div>
        </>
      )}
    </main>
  );
}
```

- [x] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npm test -- JobsPage.test.tsx`
Expected: PASS (10 tests).

- [x] **Step 5: Commit**

```bash
git add frontend/src/test-utils.ts frontend/src/pages/JobsPage.tsx frontend/src/pages/JobsPage.test.tsx
git commit -m "feat(dashboard): add filterable, paginated JobsPage at /jobs"
```

---

### Task 5: Add the `JobDetailPage`

**Files:**
- Create: `frontend/src/pages/JobDetailPage.tsx`
- Test: `frontend/src/pages/JobDetailPage.test.tsx` (new)

**Interfaces:**
- Consumes: `fetchJob`, `Job`, `NotFoundError` (Task 1); `formatDate` (Task 3); `useParams`, `useSearchParams`, `Link` (react-router-dom).
- Produces: `JobDetailPage` (named export), rendering the definition-style card, the not-found UI, and the back link. Mounted at `/jobs/:id`.

- [x] **Step 1: Write the failing tests**

Create `frontend/src/pages/JobDetailPage.test.tsx`:

```tsx
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { NotFoundError } from "../api";
import { makeJob } from "../test-utils";
import { JobDetailPage } from "./JobDetailPage";

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/jobs/:id" element={<JobDetailPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("JobDetailPage", () => {
  it("renders every field including external job ID", async () => {
    const job = makeJob({ id: 42, external_job_id: "EXT-42", company: "Google", location: "Tokyo" });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true, status: 200, statusText: "OK", json: async () => job,
    } as Response));

    renderAt("/jobs/42");

    expect(await screen.findByRole("heading", { name: "Software Engineer" })).toBeInTheDocument();
    expect(screen.getByText("Google")).toBeInTheDocument();
    expect(screen.getByText("Tokyo")).toBeInTheDocument();
    expect(screen.getByText("google_careers")).toBeInTheDocument();
    expect(screen.getByText("EXT-42")).toBeInTheDocument();
  });

  it("renders an em-dash for null company and location", async () => {
    const job = makeJob({ company: null, location: null, external_job_id: null });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true, status: 200, statusText: "OK", json: async () => job,
    } as Response));

    renderAt("/jobs/42");
    await screen.findByRole("heading", { name: "Software Engineer" });

    const dashes = screen.getAllByText("—");
    expect(dashes.length).toBeGreaterThanOrEqual(3); // company, location, external_job_id
  });

  it("shows 'Job not found.' without a Retry button on 404", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new NotFoundError("Not Found")));

    renderAt("/jobs/999999");

    expect(await screen.findByText("Job not found.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /jobs/i })).toBeInTheDocument();
  });

  it("shows Retry on a non-404 error", async () => {
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValueOnce({ ok: true, status: 200, statusText: "OK", json: async () => makeJob() } as Response);
    vi.stubGlobal("fetch", fetchMock);

    renderAt("/jobs/42");

    expect(await screen.findByText("Couldn't load this job.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("heading", { name: "Software Engineer" })).toBeInTheDocument();
  });

  it("renders not-found without fetching for a non-numeric id", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    renderAt("/jobs/abc");

    expect(await screen.findByText("Job not found.")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("preserves the list query string in the Back link", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true, status: 200, statusText: "OK", json: async () => makeJob({ id: 42 }),
    } as Response));

    renderAt("/jobs/42?q=engineer&page=2");

    const backLink = await screen.findByRole("link", { name: /Back/ });
    expect(backLink).toHaveAttribute("href", "/jobs?q=engineer&page=2");
  });

  it("links to bare /jobs when there is no query string", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true, status: 200, statusText: "OK", json: async () => makeJob({ id: 42 }),
    } as Response));

    renderAt("/jobs/42");

    const backLink = await screen.findByRole("link", { name: /Back/ });
    expect(backLink).toHaveAttribute("href", "/jobs");
  });
});
```

- [x] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npm test -- JobDetailPage.test.tsx`
Expected: FAIL — `Cannot find module './JobDetailPage'`.

- [x] **Step 3: Write minimal implementation**

Create `frontend/src/pages/JobDetailPage.tsx`:

```tsx
import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { fetchJob, NotFoundError, type Job } from "../api";
import { paramsToQueryString } from "../urlParams";
import { formatDate } from "../formatDate";

type Status = "loading" | "error" | "notfound" | "done";

export function JobDetailPage() {
  const { id } = useParams();
  const [searchParams] = useSearchParams();
  const [reload, setReload] = useState(0);
  const [status, setStatus] = useState<Status>("loading");
  const [job, setJob] = useState<Job | null>(null);

  const numericId = id !== undefined ? Number(id) : Number.NaN;

  useEffect(() => {
    if (Number.isNaN(numericId)) {
      setStatus("notfound");
      return;
    }
    let cancelled = false;
    setStatus("loading");
    fetchJob(numericId)
      .then((result) => {
        if (!cancelled) {
          setJob(result);
          setStatus("done");
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setStatus(err instanceof NotFoundError ? "notfound" : "error");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [numericId, reload]);

  const backHref = `/jobs${paramsToQueryString(searchParams)}`;

  if (status === "notfound") {
    return (
      <main className="max-w-4xl mx-auto px-6 py-10">
        <p className="mb-4">Job not found.</p>
        <Link to="/jobs">Back to jobs</Link>
      </main>
    );
  }

  return (
    <main className="max-w-4xl mx-auto px-6 py-10">
      <Link to={backHref} className="text-slate-600 text-sm mb-4 inline-block">
        ← Back
      </Link>

      {status === "loading" && <p role="status">Loading job…</p>}

      {status === "error" && (
        <div>
          <p>Couldn't load this job.</p>
          <button type="button" onClick={() => setReload((n) => n + 1)}>
            Retry
          </button>
        </div>
      )}

      {status === "done" && job && (
        <div className="border border-slate-200 rounded p-6">
          <h1 className="text-2xl font-bold mb-4">{job.title}</h1>
          <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
            <dt className="text-slate-500">Company</dt>
            <dd>{job.company ?? "—"}</dd>
            <dt className="text-slate-500">Location</dt>
            <dd>{job.location ?? "—"}</dd>
            <dt className="text-slate-500">Source</dt>
            <dd>{job.source}</dd>
            <dt className="text-slate-500">External job ID</dt>
            <dd>{job.external_job_id ?? "—"}</dd>
            <dt className="text-slate-500">First seen</dt>
            <dd title={job.first_seen_at}>{formatDate(job.first_seen_at, new Date())}</dd>
            <dt className="text-slate-500">Last seen</dt>
            <dd title={job.last_seen_at}>{formatDate(job.last_seen_at, new Date())}</dd>
            <dt className="text-slate-500">Updated</dt>
            <dd title={job.updated_at}>{formatDate(job.updated_at, new Date())}</dd>
          </dl>
        </div>
      )}
    </main>
  );
}
```

- [x] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npm test -- JobDetailPage.test.tsx`
Expected: PASS (7 tests).

- [x] **Step 5: Commit**

```bash
git add frontend/src/pages/JobDetailPage.tsx frontend/src/pages/JobDetailPage.test.tsx
git commit -m "feat(dashboard): add JobDetailPage at /jobs/:id"
```

---

### Task 6: Wire routing and delete the placeholder

**Files:**
- Modify: `frontend/src/App.tsx` (remove `DashboardPage` import, add `Navigate` + `JobsPage` + `JobDetailPage`)
- Delete: `frontend/src/pages/DashboardPage.tsx`
- Modify: `frontend/src/components/NavBar.tsx` (Dashboard link → `/jobs`)

**Interfaces:**
- Consumes: `JobsPage` (Task 4), `JobDetailPage` (Task 5).
- Produces: app routes `/` → redirect, `/jobs`, `/jobs/:id`, `/pbi` (unchanged).

- [x] **Step 1: Verify the current placeholder route (the "failing" state)**

No test file exists at the routing level; the change is asserted by `npm run typecheck` + `npm run build` + the manual smoke. Confirm the current `App.tsx` still imports `./pages/DashboardPage` (it does — read in the investigation) so that removing the file without updating `App.tsx` would break the build. This is the regression the next steps must prevent.

- [x] **Step 2: Update `App.tsx`**

Replace the top import block and the `path: "/"` route. New `frontend/src/App.tsx`:

```tsx
import { createBrowserRouter, Navigate, RouterProvider } from "react-router-dom";
import { NavBar } from "./components/NavBar";
import { JobsPage } from "./pages/JobsPage";
import { JobDetailPage } from "./pages/JobDetailPage";
import { PbiTrackerPage } from "./pages/PbiTrackerPage";

const router = createBrowserRouter([
  {
    path: "/",
    element: <Navigate to="/jobs" replace />,
  },
  {
    path: "/jobs",
    element: (
      <>
        <NavBar />
        <JobsPage />
      </>
    ),
  },
  {
    path: "/jobs/:id",
    element: (
      <>
        <NavBar />
        <JobDetailPage />
      </>
    ),
  },
  {
    path: "/pbi",
    element: (
      <>
        <NavBar />
        <PbiTrackerPage />
      </>
    ),
  },
]);

export function App() {
  return <RouterProvider router={router} />;
}
```

- [x] **Step 3: Update `NavBar.tsx`**

Change the "Dashboard" link target from `to="/"` to `to="/jobs"`:

```tsx
import { Link } from "react-router-dom";

export function NavBar() {
  return (
    <nav className="bg-slate-900 text-slate-100 px-6 py-4">
      <div className="flex items-center gap-6">
        <Link to="/" className="font-semibold text-lg">
          Job Search
        </Link>
        <Link to="/jobs" className="hover:text-white">
          Dashboard
        </Link>
        <Link to="/pbi" className="hover:text-white">
          PBI Tracker
        </Link>
      </div>
    </nav>
  );
}
```

(The logo `Link to="/"` stays; `/` now redirects to `/jobs`, per the spec §3 "NavBar" row.)

- [x] **Step 4: Delete `DashboardPage.tsx`**

Run: `cd /home/jason/job-search && git rm frontend/src/pages/DashboardPage.tsx`
Expected: the placeholder page is removed from the working tree and index. No remaining import references it after Step 2.

- [x] **Step 5: Run typecheck + tests + build**

Run:
```bash
cd /home/jason/job-search/frontend && npm run typecheck
cd /home/jason/job-search/frontend && npm test
cd /home/jason/job-search/frontend && npm run build
```
Expected: typecheck clean (no unused-import errors → confirms `DashboardPage` fully removed), all suites pass (new `JobsPage`/`JobDetailPage`/`urlParams`/`formatDate`/`api` + existing `PbiTrackerPage`), `vite build` succeeds.

- [x] **Step 6: Commit**

```bash
git add frontend/src/App.tsx frontend/src/components/NavBar.tsx frontend/src/pages/DashboardPage.tsx
git commit -m "feat(dashboard): route / to /jobs, add /jobs/:id, delete placeholder page"
```

---

### Task 7: Tick the tracker and reconcile `pbis.ts`

**Files:**
- Modify: `implementation_checklist/pbi_tracker.md` (tick PBI 5)
- Modify: `frontend/src/pages/pbis.ts` (mark PBI 5 complete — its description/`depends_on` are unchanged; see note)

**Interfaces:**
- Consumes: all prior tasks (must be green first).

- [x] **Step 1: Run the full frontend verification**

Run (from `frontend/`):
```bash
npm test
npm run typecheck
npm run build
```
Expected: all green. (This is the definition-of-done gate; do not tick below until these pass.)

- [x] **Step 2: Tick PBI 5 in the tracker**

In `implementation_checklist/pbi_tracker.md`, change:

```markdown
- [x] **PBI 5 — Jobs dashboard page**
```

to:

```markdown
- [x] **PBI 5 — Jobs dashboard page**
```

- [x] **Step 3: Reconcile `pbis.ts`**

`pbis.ts` has no completion field — it renders a checkbox glyph `☐` in `PbiTrackerPage.tsx` with no per-PBI state, so there is nothing to tick there (the spec §8 item 5's "matching entry in `pbis.ts`" refers to keeping the *title/description* in sync). Confirm PBI 5's `title` ("Jobs dashboard page") and `description` ("Browse, filter, and open job details.") already match the tracker line; no edit expected, but re-read `pbis.ts` and reconcile if the wording drifted.

- [x] **Step 4: Commit**

```bash
git add implementation_checklist/pbi_tracker.md
git commit -m "docs(pbi5): tick PBI 5 jobs dashboard complete"
```

---

### Task 8: Manual smoke against the real backend (optional)

**Files:**
- None.

**Interfaces:**
- Consumes: live backend (`make dev`) + frontend (`npm run dev`).

- [ ] **Step 1: Start the stack**

Run: `make db-up && make migrate && make dev` (terminal 1), `cd frontend && npm run dev` (terminal 2)
Expected: backend at `http://localhost:8000`, frontend at `http://localhost:5173`.

- [ ] **Step 2: Smoke `/` redirect + list**

Open `http://localhost:5173/` → redirects to `/jobs`; cards render from real data.

- [ ] **Step 3: Smoke filters + pager**

Set Title/Company/Location/Source filters → URL reflects them; Prev/Next advance pages; "Showing X–Y of N" / "Page P of T" count right; reload + Back/forward preserve filter+page.

- [ ] **Step 4: Smoke detail round-trip**

Open a card → `/jobs/:id` details correct → Back returns to the same filtered page. Then `/jobs/999999` → "Job not found."

- [ ] **Step 5: Tear down**

Run: `make db-down` (leave `make dev`/`npm run dev` running only if you continue iterating).
