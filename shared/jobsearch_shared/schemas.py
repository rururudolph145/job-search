from datetime import datetime

from pydantic import BaseModel, ConfigDict


class HealthResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    status: str


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str
    external_job_id: str | None
    title: str
    company: str | None
    location: str | None
    first_seen_at: datetime
    last_seen_at: datetime
    updated_at: datetime
