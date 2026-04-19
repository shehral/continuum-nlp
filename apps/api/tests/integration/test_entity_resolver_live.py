"""Sanity check: PostgreSQL entity exists in the live graph.

The /api/entities endpoint returns the first 100 entities alphabetically with no
search param, so the API isn't a useful surface to test "does PostgreSQL exist."
We hit Neo4j directly via the smoke fixture, which is what really matters: the
graph contains the canonical entity that downstream resolution relies on.
"""

import os

import pytest
from neo4j import GraphDatabase

pytestmark = [pytest.mark.integration]

NEO4J_URI = os.getenv("SMOKE_NEO4J_URI", "bolt://localhost:7688")
NEO4J_USER = os.getenv("SMOKE_NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("SMOKE_NEO4J_PASSWORD", "neo4jpassword")


@pytest.fixture(scope="module")
def neo4j_driver():
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    try:
        driver.verify_connectivity()
        yield driver
    finally:
        driver.close()


def test_postgres_entity_exists(neo4j_driver):
    """The canonical PostgreSQL technology entity must be present."""
    with neo4j_driver.session() as session:
        result = session.run(
            """
            MATCH (e:Entity)
            WHERE toLower(e.name) CONTAINS 'postgres'
            RETURN e.name AS name, e.type AS type
            """
        )
        rows = [(r["name"], r["type"]) for r in result]

    assert any("postgres" in name.lower() for name, _ in rows), (
        f"No Postgres-flavored entity found in graph. "
        f"Got {len(rows)} candidates: {rows[:10]}"
    )


def test_postgres_entity_has_decisions(neo4j_driver):
    """PostgreSQL should be involved in real decisions — guards against an
    orphaned entity node that survived migration without its INVOLVES edges."""
    with neo4j_driver.session() as session:
        row = session.run(
            """
            MATCH (e:Entity {name: 'PostgreSQL'})<-[:INVOLVES]-(d:DecisionTrace)
            RETURN count(d) AS n
            """
        ).single()

    assert row and row["n"] >= 5, (
        f"Expected ≥5 decisions involving PostgreSQL, got {row['n'] if row else 0}"
    )
