# PBI Tracker — Job Search Intelligence Platform

> Backend-first build order. Each stage produces working, tested software before the next begins.
> The frontend renders this roadmap at `/pbi` from `frontend/src/pages/pbis.ts` — keep the two in sync.

---

## Stage 1 — MVP (the useful tool)

> Goal: ingest job postings from permitted feeds, store them with a canonical identity, and browse them in a dashboard.

- [ ] **PBI 1 — Jobs schema**
  - `jobs`, `companies`, `job_sources` tables + Alembic migration + repositories.
  - Depends on: —
- [ ] **PBI 2 — Source ingestion**
  - Fetch from official job APIs / permitted feeds only (no bot-protection bypass).
  - Depends on: PBI 1
- [ ] **PBI 3 — Normalization + dedup keys**
  - Canonical job identity across URLs and ATS providers.
  - Depends on: PBI 1
- [ ] **PBI 4 — Query routes**
  - List/detail/filter endpoints for jobs.
  - Depends on: PBI 1, 3
- [ ] **PBI 5 — Jobs dashboard page**
  - Browse, filter, and open job details.
  - Depends on: PBI 4

## Stage 2 — Production engineering

> Goal: make the crawler reliable, efficient, and correct — the engineering that carries the portfolio narrative.

- [ ] **PBI 6 — Crawl scheduler**
  - Crawl scheduling + per-host rate limits + robots.txt/policy compliance.
  - Depends on: PBI 2
- [ ] **PBI 7 — Failure recovery**
  - Retry with exponential backoff; idempotent writes on retry.
  - Depends on: PBI 2, 3
- [ ] **PBI 8 — "Disappeared job" detection**
  - Repeated-confirmation rule; distinguish a failed fetch from a successful empty response.
  - Depends on: PBI 3, 6
- [ ] **PBI 9 — Observability**
  - Crawl success, freshness, latency, and error metrics.
  - Depends on: PBI 6, 7

## Stage 3 — Search & ranking

> Goal: keyword + semantic retrieval with explainable ranking and measured quality.

- [ ] **PBI 10 — Keyword full-text search**
  - Full-text search over job postings.
  - Depends on: PBI 3
- [ ] **PBI 11 — Embeddings + pgvector**
  - Semantic retrieval; incremental re-indexing of changed documents.
  - Depends on: PBI 10
- [ ] **PBI 12 — Hybrid ranking + resume matching**
  - Hybrid ranking + resume-to-job matching; explainable ranking and filters.
  - Depends on: PBI 11
- [ ] **PBI 13 — Retrieval-quality evaluation**
  - Retrieval-quality evaluation + index-freshness measurement.
  - Depends on: PBI 12
