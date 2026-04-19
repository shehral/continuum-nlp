"""Shared fixtures for demo smoke tests.

These tests hit REAL services — do not mock. Intended to run against the
running local docker stack (or a live GCP deploy by setting API_BASE_URL).
"""

import os
import random
from collections.abc import Iterator

import httpx
import pytest
from neo4j import GraphDatabase

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
NEO4J_URI = os.getenv("SMOKE_NEO4J_URI", "bolt://localhost:7688")
NEO4J_USER = os.getenv("SMOKE_NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("SMOKE_NEO4J_PASSWORD", "neo4jpassword")


@pytest.fixture(scope="session")
def api_base_url() -> str:
    return API_BASE_URL


@pytest.fixture(scope="session")
def http_client() -> Iterator[httpx.Client]:
    """Synchronous httpx client reused across smoke tests."""
    with httpx.Client(base_url=API_BASE_URL, timeout=30.0) as client:
        yield client


@pytest.fixture(scope="session")
def neo4j_driver():
    """Live Neo4j driver for direct graph queries (session-scoped)."""
    driver = GraphDatabase.driver(
        NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD)
    )
    try:
        # Verify connectivity up-front so a failed bolt connect fails fast.
        driver.verify_connectivity()
        yield driver
    finally:
        driver.close()


@pytest.fixture(scope="session")
def sample_decision_ids(neo4j_driver) -> list[str]:
    """Return up to 20 random DecisionTrace IDs from the live graph."""
    with neo4j_driver.session() as session:
        result = session.run(
            "MATCH (d:DecisionTrace) RETURN d.id AS id"
        )
        all_ids = [r["id"] for r in result]

    if not all_ids:
        pytest.skip("No DecisionTrace nodes in graph — can't sample.")

    random.seed(6120)  # deterministic subset across test runs
    return random.sample(all_ids, min(20, len(all_ids)))
