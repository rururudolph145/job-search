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
