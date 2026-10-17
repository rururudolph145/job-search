# PBI 5 — Jobs Dashboard Page: Design Spec

> Status: draft for review
> Date: 2026-10-18
> Depends on: PBI 4 (`GET /jobs`, `GET /jobs/{job_id}`)
> Blocks: nothing in Stage 1 — this completes the MVP. PBI 10 later reuses the `q`
> filter slot for full-text search.

## 1. Purpose

Give the ingested jobs a human-facing surface. PBIs 1–3 built the table, filled it,
and gave it identity; PBI 4 exposed it over HTTP. PBI 5 is the first time a person
can use any of it: browse the jobs, narrow them with filters, page through them,
and open a single job's details.

**Scope, in one line:** replace the placeholder `DashboardPage` with a filterable,
paginated jobs list at `/jobs` and a detail page at `/jobs/:id`, consuming only the
PBI 4 read endpoints.

This is a **frontend-only PBI**. No backend change, no schema change, no new
dependency.

## 2. Why this shape

PBI 4's contract was deliberately narrow: eight displayable fields, four exact/
substring filters, and a `{items, total}` envelope. The dashboard is likewise
narrow — it renders exactly what the contract offers and invents nothing. Two
choices are worth calling out:

- **URL as state.** Filters and page live in the query string via React Router's
  `useSearchParams`. This gives shareable links, correct browser back/forward,
  and — the motivating case — a Back link from a job detail that restores the
  exact filtered page the user came from.
- **No data library.** The app fetches on mount and on param change. There is no
  cross-page cache worth a dependency (TanStack Query/SWR were considered and
  rejected). Navigating back re-fetches one page of 50 rows, which is fine.

## 3. Scope decisions (locked during design)

| Decision | Choice |
|---|---|
| Filter bar | **Always visible**, single `<form>` row. Applied on submit, not per keystroke. "Clear filters" resets all. |
| Filter fields | `q` (title substring), `company`, `location` (exact) — text inputs; `source` — **text input** (exact match). |
| Source field | Text input, not a `<select>`. PBI 4 has no sources endpoint; hardcoding source values is brittle. A sources endpoint / select is out of scope. |
| Page size | **50** (the API default). The client does not send `limit`. |
| Pagination UI | Prev/Next buttons + "Showing X–Y of N" + "Page P of T", `T = ceil(total / 50)`. Hidden when `total` is 0. |
| Detail view | **Dedicated route** `/jobs/:id` backed by `GET /jobs/{job_id}`. |
| Back navigation | Detail's Back link returns to `/jobs` **with the list's query string preserved**; falls back to bare `/jobs`. |
| List layout | **Responsive cards** — one card per job, stacked single-column, each a single link to its detail. |
| Dashboard home | `/` **redirects** to `/jobs`. `DashboardPage.tsx` is deleted. |
| NavBar | "Dashboard" links to `/jobs`; logo still links to `/` (which redirects). "PBI Tracker" unchanged. |
| Backend | **Untouched.** |
| New dependencies | **None.** |

## 4. Components

### 4.1 API layer — `frontend/src/api.ts`

Extend the existing module. `request<T>` is unchanged; the new functions call it.

```ts
export interface Job {
  id: number;
  source: string;
  external_job_id: string | null;
  title: string;
  company: string | null;
  location: string | null;
  first_seen_at: string;   // ISO 8601 from the API
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

export async function fetchJobs(query: JobsQuery): Promise<JobList>;
export async function fetchJob(id: number): Promise<Job>;
```

- `fetchJobs`: serializes only defined, non-empty fields into `URLSearchParams`,
  appends to `/jobs`. A `404` (which the list endpoint does not produce, but the
  wrapper maps) and any other non-OK status surface as `NotFoundError` / `Error`
  exactly as `request<T>` already does.
- `fetchJob`: `GET /jobs/{id}`; the wrapper's `NotFoundError` distinguishes the
  404 case for the detail page.

Dates stay as ISO strings in the API layer; formatting is a UI concern.

### 4.2 Routing — `frontend/src/App.tsx`

```tsx
{
  path: "/",
  element: <Navigate to="/jobs" replace />,
},
{
  path: "/jobs",
  element: (<><NavBar /><JobsPage /></>),
},
{
  path: "/jobs/:id",
  element: (<><NavBar /><JobDetailPage /></>),
},
// /pbi unchanged
```

`DashboardPage.tsx` and its import are removed. `NavBar.tsx` updates the
"Dashboard" link to `/jobs`.

### 4.3 `frontend/src/pages/JobsPage.tsx` (new)

Single file; the filter bar, card list, and pager are local JSX, not extracted
components (one consumer today — extract when PBI 10 needs the filter bar).

**State and params.** `useSearchParams()` is the source of truth. Recognized
params: `q`, `company`, `location`, `source`, `page` (1-based integer; absent or
invalid ⇒ 1). `offset = (page - 1) * 50`. Filter inputs are uncontrolled
(`defaultValue` from the params) so typing does not re-render.

**Fetching.** A `useEffect` keyed on `searchParams.toString()` and a `reload`
counter calls `fetchJobs({ q, company, location, source, offset })`. Stale
responses are dropped via a `cancelled` flag in the effect cleanup (no
`AbortController`; one flight at a time). The `reload` counter powers Retry.

**Render states** (mutually exclusive, in place of the list):
- **Loading:** `role="status"`, text "Loading jobs…".
- **Error:** "Couldn't load jobs." + **Retry** button.
- **Empty with filters:** "No jobs match your filters."
- **Empty without filters:** "No jobs yet."
- **Populated:** the card list and pager.

**Filter bar.** `<form>` with labeled fields: Title (`q`), Company, Location,
Source. Submit handler writes the trimmed, non-empty values plus `page=1` to the
search params and drops empty ones. **Clear filters** calls
`setSearchParams({})`. Native form submit only — no validation beyond trimming.

**Card list.** `<ul>` of `<li>`; each `<li>` contains a single `<Link to={"/jobs/" + id + "?" + currentSearch}>` wrapping the card. Shown per card:
- `title` — bold, the accessible link text.
- `company` · `location` — muted; each null renders "—".
- Footer: `source` and "Updated <relative date>" with the absolute ISO date in a
  `title` attribute. A local `formatDate` helper handles absolute/relative
  display; null/impossible dates render "—".

**Pager.** Shown only when `total > 0`:
- "Showing X–Y of N" where `X = total === 0 ? 0 : offset + 1`, `Y = offset + items.length`.
- **Prev** (`offset > 0`) and **Next** (`page < totalPages`) buttons using the
  `disabled` attribute; each sets `page ± 1` while preserving the filter params.
- "Page P of T", `T = Math.ceil(total / 50)`.

**Heading.** `<h1>Jobs</h1>` above the filter bar.

### 4.4 `frontend/src/pages/JobDetailPage.tsx` (new)

**Loading the job.** `useParams().id` → `Number(id)`. A non-finite value renders
the not-found UI without a request. Otherwise `fetchJob(id)` in a `useEffect`
with the same `cancelled`-flag pattern.

**Render states:**
- **Loading:** `role="status"`, "Loading job…".
- **Not found** (`NotFoundError` or non-numeric id): "Job not found." + link to
  `/jobs`. No Retry — retrying a 404 is pointless.
- **Other error:** "Couldn't load this job." + **Retry**.
- **Loaded:** definition-style card with every `Job` field:
  `title` as `<h1>`; Company, Location, Source, External job ID, First seen,
  Last seen, Updated. Null fields render "—". Dates use the same `formatDate`
  helper as the list.

**Back link.** Reads `useSearchParams()` and links to
`/jobs${search ? "?" + search : ""}`, so a job opened from a filtered page
returns to that page.

## 5. Data flow

```
User submits filter form
  → setSearchParams({q, company, location, source, page: "1"})
  → useSearchParams changes → effect runs
  → fetchJobs(...) → GET /jobs?q=...&offset=0
  → {items, total} → render cards + pager

User clicks a card
  → <Link to="/jobs/42?q=engineer&page=2">
  → JobDetailPage → fetchJob(42) → GET /jobs/42
  → render fields; Back link → /jobs?q=engineer&page=2
```

## 6. Error handling

| Situation | Behavior |
|---|---|
| Network / 5xx on list or detail | Error message + Retry button (re-runs the effect). |
| 404 on `GET /jobs/{id}` | "Job not found." + link to list. No Retry. |
| Non-numeric `:id` | Same not-found UI, no request made. |
| Stale response after params change | Dropped by the `cancelled` cleanup flag. |
| Empty result set | Distinguishes "no matches" (filters active) from "no jobs yet". |

## 7. Testing

Vitest + Testing Library, page-level, `fetch` stubbed with
`vi.stubGlobal("fetch", ...)`, pages rendered in `MemoryRouter` with
`initialEntries`. No live backend, no mocking library.

**`JobsPage.test.tsx`**
1. Renders each job's title from a fake `JobList`.
2. Shows the loading state before the fetch resolves.
3. Empty + filters → "No jobs match your filters."; empty without filters →
   "No jobs yet."
4. Error → Retry shown; clicking it re-fetches.
5. Submitting the form requests `/jobs` with `q`, `company`, `location`, `source`
   and `offset=0` (page reset).
6. Clear filters removes all params from the request.
7. Prev disabled on page 1; Next disabled on the last page.
8. Pager shows "Showing X–Y of N" and "Page P of T" from `total`.
9. A card links to `/jobs/{id}` preserving the current query string.

**`JobDetailPage.test.tsx`**
1. Renders every field, including external job ID.
2. Null company/location render "—".
3. 404 → "Job not found." and no Retry.
4. Non-404 error → Retry shown.
5. Non-numeric id → not-found UI without a fetch call.
6. Back link preserves the list query string; bare `/jobs` with no params.

Request-shape assertions (URL and params) are explicit: URL building is the only
thing the backend depends on.

**Backend tests:** none — no backend change.

## 8. Verification (definition of done)

1. `cd frontend && npm test` — all suites pass (new + existing `PbiTrackerPage`).
2. `npm run typecheck` — clean.
3. `npm run build` — succeeds.
4. Manual smoke against the real backend:
   `make dev` + `cd frontend && npm run dev`, then:
   - `/` redirects to `/jobs`; jobs render.
   - Each filter narrows the list; the URL reflects it.
   - Prev/Next move through pages; pager counts match.
   - Filters + page survive reload and Back/forward.
   - Open a job → details correct → Back returns to the same filtered page.
   - `/jobs/999999` shows "Job not found."
5. Tick **PBI 5** in `implementation_checklist/pbi_tracker.md` and the matching
   entry in `frontend/src/pages/pbis.ts` (the two files are kept in sync) — only
   after steps 1–4 pass.

## 9. Out of scope

- Any backend change, including a sources endpoint or a `<select>` for source.
- Full-text / semantic search (the `q` field remains a title substring; PBI 10
  replaces it).
- Saved jobs, application tracking, charts, observability UI.
- Auth.
- A data-fetching library, form library, or date library.
- Server-side rendering or code splitting.
