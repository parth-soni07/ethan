"""HTTP contract tests through FastAPI's TestClient (no network)."""
import pytest
from fastapi.testclient import TestClient

from backend.app import SECURITY_HEADERS, app, dist

client = TestClient(app)


def test_day_shape():
    r = client.get("/api/day", params={"date": "2026-01-15", "cutoff": "09:00"})
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"date", "metrics", "points"} and body["date"] == "2026-01-15"
    assert set(body["points"][0]) == {"startTime", "actual", "forecast", "publishTime"}
    assert set(body["metrics"]) == {"n", "mae", "rmse", "bias", "mape", "p90_shortfall"}


def test_accuracy_shape_and_default_cutoff():
    r = client.get("/api/accuracy")
    assert r.status_code == 200
    body = r.json()
    assert body["cutoff"] == "09:00"
    assert set(body) == {"cutoff", "overall", "by_day", "by_hour", "by_lead", "by_level", "histogram"}
    assert "NaN" not in r.text and "Infinity" not in r.text


@pytest.mark.parametrize("params", [
    {"date": "2025-12-31"}, {"date": "2026-02-01"}, {"date": "2026-01-32"}, {"date": "garbage"}, {},
    {"date": "2026-01-15", "cutoff": "24:00"}, {"date": "2026-01-15", "cutoff": "9:00"},
    {"date": "2026-01-15", "cutoff": "09:60"}, {"date": "2026-01-15", "cutoff": ""},
    {"date": "2026-01-15", "cutoff": "09:00\n"},
])
def test_day_rejects_bad_input(params):
    assert client.get("/api/day", params=params).status_code == 422


def test_out_of_range_date_says_why():
    r = client.get("/api/day", params={"date": "2026-02-01"})
    assert "2026-01-01" in r.text and "2026-01-31" in r.text


@pytest.mark.parametrize("cutoff", ["24:00", "9:00", "ab:cd"])
def test_accuracy_rejects_bad_cutoff(cutoff):
    assert client.get("/api/accuracy", params={"cutoff": cutoff}).status_code == 422


def test_unknown_api_route_is_404():
    assert client.get("/api/nope").status_code == 404


@pytest.mark.parametrize("path", ["/api/accuracy", "/api/nope"])
def test_security_headers(path):
    headers = client.get(path).headers
    assert all(headers[k] == v for k, v in SECURITY_HEADERS.items())


@pytest.mark.skipif(not dist.is_dir(), reason="frontend not built (cd frontend && npm run build)")
def test_built_ui_is_served_and_cannot_escape_its_directory():
    assert client.get("/").headers["content-type"].startswith("text/html")
    assert client.get("/../backend/app.py").status_code == 404
