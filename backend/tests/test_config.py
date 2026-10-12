from app.core.config import Settings, app_config


def test_settings_defaults() -> None:
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.app_env == "development"


def test_app_config_loaded() -> None:
    assert app_config.name == "job-search"
    assert app_config.env == "development"
