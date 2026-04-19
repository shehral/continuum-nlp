"""/health + /health/ready smoke tests against live API."""

import pytest


pytestmark = [pytest.mark.smoke]


def test_health_returns_healthy(http_client):
    resp = http_client.get("/health")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("status") == "healthy"


def test_health_ready_all_deps_healthy(http_client):
    """Readiness: all three dependencies (postgres/neo4j/redis) must be healthy."""
    resp = http_client.get("/health/ready")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("ready") is True
    checks = body.get("checks", {})
    for dep in ("postgres", "neo4j", "redis"):
        assert checks.get(dep) == "healthy", f"{dep} unhealthy: {body}"


def test_health_live(http_client):
    resp = http_client.get("/health/live")
    assert resp.status_code == 200
    assert resp.json().get("alive") is True
