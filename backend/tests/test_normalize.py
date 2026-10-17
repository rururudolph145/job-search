from app.ingestion.normalize import (
    normalize_company,
    normalize_external_id,
    normalize_location,
    normalize_source,
    normalize_title,
)


def test_normalize_source_lowercases_and_strips() -> None:
    assert normalize_source("  Google_Careers ") == "google_careers"
    assert normalize_source("GOOGLE_CAREERS") == "google_careers"
    assert normalize_source("google  careers") == "google careers"


def test_normalize_external_id_strips() -> None:
    assert normalize_external_id(" 123 ") == "123"


def test_normalize_external_id_empty_becomes_none() -> None:
    assert normalize_external_id("") is None
    assert normalize_external_id("   ") is None


def test_normalize_title_folds_nbsp_and_collapses_whitespace() -> None:
    assert normalize_title("Software\xa0Engineer") == "Software Engineer"
    assert normalize_title("  Software   Engineer  ") == "Software Engineer"


def test_normalize_title_nfkc_folds_lookalikes() -> None:
    # U+FF26 (fullwidth 'F') normalizes to ASCII 'F' under NFKC.
    assert normalize_title("Ｆull Stack") == "Full Stack"


def test_normalize_company_none_passthrough() -> None:
    assert normalize_company(None) is None
    assert normalize_company("  Google  ") == "Google"


def test_normalize_location_none_passthrough() -> None:
    assert normalize_location(None) is None
    assert normalize_location("  Tokyo\tMetro ") == "Tokyo Metro"
