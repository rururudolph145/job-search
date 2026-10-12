from app.main import app
from fastapi.testclient import TestClient

client = TestClient(app)


def test_cors_headers_present() -> None:
    resp = client.get("/health", headers={"Origin": "http://localhost:5173"})
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == "http://localhost:5173"
