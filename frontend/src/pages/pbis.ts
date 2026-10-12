import type { Pbi } from "../types";

// Mirrors implementation_checklist/pbi_tracker.md — keep the two in sync.
export const PBIS: Pbi[] = [
  // Stage 1 — MVP
  {
    id: "1",
    stage: "mvp",
    title: "Jobs schema",
    description:
      "jobs, companies, job_sources tables + Alembic migration + repositories.",
    depends_on: [],
  },
  {
    id: "2",
    stage: "mvp",
    title: "Source ingestion",
    description:
      "Fetch from official job APIs / permitted feeds only (no bot-protection bypass).",
    depends_on: ["1"],
  },
  {
    id: "3",
    stage: "mvp",
    title: "Normalization + dedup keys",
    description:
      "Canonical job identity across URLs and ATS providers.",
    depends_on: ["1"],
  },
  {
    id: "4",
    stage: "mvp",
    title: "Query routes",
    description: "List/detail/filter endpoints for jobs.",
    depends_on: ["1", "3"],
  },
  {
    id: "5",
    stage: "mvp",
    title: "Jobs dashboard page",
    description: "Browse, filter, and open job details.",
    depends_on: ["4"],
  },
  // Stage 2 — Production engineering
  {
    id: "6",
    stage: "engineering",
    title: "Crawl scheduler",
    description:
      "Crawl scheduling + per-host rate limits + robots.txt/policy compliance.",
    depends_on: ["2"],
  },
  {
    id: "7",
    stage: "engineering",
    title: "Failure recovery",
    description: "Retry with exponential backoff; idempotent writes on retry.",
    depends_on: ["2", "3"],
  },
  {
    id: "8",
    stage: "engineering",
    title: "\"Disappeared job\" detection",
    description:
      "Repeated-confirmation rule; distinguish a failed fetch from a successful empty response.",
    depends_on: ["3", "6"],
  },
  {
    id: "9",
    stage: "engineering",
    title: "Observability",
    description: "Crawl success, freshness, latency, and error metrics.",
    depends_on: ["6", "7"],
  },
  // Stage 3 — Search & ranking
  {
    id: "10",
    stage: "search",
    title: "Keyword full-text search",
    description: "Full-text search over job postings.",
    depends_on: ["3"],
  },
  {
    id: "11",
    stage: "search",
    title: "Embeddings + pgvector",
    description:
      "Semantic retrieval; incremental re-indexing of changed documents.",
    depends_on: ["10"],
  },
  {
    id: "12",
    stage: "search",
    title: "Hybrid ranking + resume matching",
    description:
      "Hybrid ranking + resume-to-job matching; explainable ranking and filters.",
    depends_on: ["11"],
  },
  {
    id: "13",
    stage: "search",
    title: "Retrieval-quality evaluation",
    description:
      "Retrieval-quality evaluation + index-freshness measurement.",
    depends_on: ["12"],
  },
];
