# experiment_scrapy

Throwaway spike: a minimal Scrapy spider to discover Software Engineering jobs in
Japan from Google's public careers sitemap.

## Compliance

- **Source:** `https://careers.google.com/jobs/sitemap` — a publicly exposed XML
  sitemap (not covered by any `robots.txt` disallow). This is the *permitted feed*.
- **Job detail pages redirect** from `careers.google.com/jobs/results/{id}-{slug}/`
  to `www.google.com/about/careers/applications/jobs/results/{id}-{slug}/`. That
  redirect target falls under Google's `Disallow: /about/careers/applications/jobs/results`
  prefix (robots.txt line ~249). The sitemap itself is clean; fetching individual
  detail pages for a low-volume, personal job-hunt experiment is the documented
  intent here. Treat this as a gray area — scale/politeness constraints belong to
  PBI 6–7, not this probe.
- **Not scraped:** the paginated search/list results URL (the primary `Disallow`ed
  page) is never fetched; we enumerate jobs from the sitemap only.

## How it works

1. Fetch the sitemap, parse `<loc>` + `<lastmod>` for every job URL.
2. Filter to URLs whose slug contains `software-engineer` (the slug encodes the
   role, so no need to fetch a page to classify it).
3. Fetch each matching job page, extracting:
   - `title` — from `og:title` / `<title>`
   - `url` — the job URL
   - `location` — best-effort text match for Japan city/prefecture names in the
     rendered page body (fuzzy; see limitations)
4. Print/yield an item per job.

## Run

```bash
# from the repo root (scrapy is a dev dependency)
uv run scrapy runspider experiment_scrapy/google_careers_spider.py \
  -s DOWNLOAD_DELAY=1.0 \
  -s AUTOTHROTTLE_ENABLED=True \
  -L WARNING
```

Limit scope during a spike with `-s CLOSESPIDER_ITEMCOUNT=10`.

## Limitations (spike — honest notes)

- **Location is fuzzy.** The job page is a JS-heavy SPA without JSON-LD; the
  server-rendered text includes the location, but there's no clean structured
  `location` field. We match known Japan terms, which can miss or mis-assign.
- **No dedup/idempotency, backoff, or rate-policy layers** — those belong to PBI 6–7,
  not this probe.
- This is throwaway code to answer "can we get SWE-in-Japan listings legally and
  at minimum effort?" — not part of the product.
