from pathlib import Path

import yaml
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent
# backend/.env, anchored absolutely so config resolves from any working directory
# (make test runs pytest from the repo root, not from backend/).
DEFAULT_ENV_FILE = str(BASE_DIR.parents[1] / ".env")


class Settings(BaseSettings):
    """Environment-driven settings, loaded from backend/.env when present."""

    app_env: str = "development"

    model_config = SettingsConfigDict(
        env_file=DEFAULT_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )


class AppInfo(BaseModel):
    name: str
    env: str


def load_app_config(path: Path = BASE_DIR / "config.yml") -> AppInfo:
    """Load the small static YAML config (app metadata only in this pass)."""
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return AppInfo.model_validate(data["app"])


settings = Settings()
app_config = load_app_config()
