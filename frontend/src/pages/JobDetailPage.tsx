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
