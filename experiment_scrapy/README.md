# experiment_scrapy (retired)

This was a throwaway spike to confirm the Google Careers sitemap could be parsed
for software-engineering roles. It has been **promoted** into the real ingestion
layer:

- Spider: `backend/app/ingestion/spiders/google_careers.py`
- Source: `backend/app/ingestion/sources/google_careers.py`
- Service: `backend/app/ingestion/service.py`
- Entrypoint: `python -m app.ingest` (see `backend/app/ingest.py`)

The throwaway spider in this directory is no longer the source of truth.
