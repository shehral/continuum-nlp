"""Embedding dimensionality regression — all nodes must be 768-d (nomic-embed-text).

This catches both:
- D2: dimension mismatch if a stale 2048-d index or leftover embedding survives.
- Any node missing an embedding (breaks vector search → breaks /ask).
"""

import pytest

pytestmark = [pytest.mark.smoke]


def test_decision_trace_embeddings_are_768d(neo4j_driver):
    with neo4j_driver.session() as session:
        result = session.run(
            """
            MATCH (d:DecisionTrace)
            WITH count(d) AS total,
                 count(d.embedding) AS with_embedding,
                 min(size(d.embedding)) AS min_dim,
                 max(size(d.embedding)) AS max_dim
            RETURN total, with_embedding, min_dim, max_dim
            """
        ).single()

    assert result is not None
    total = result["total"]
    with_embedding = result["with_embedding"]
    min_dim = result["min_dim"]
    max_dim = result["max_dim"]

    assert total > 0, "No DecisionTrace nodes — graph is empty"
    assert with_embedding == total, (
        f"{total - with_embedding} / {total} DecisionTrace nodes missing embeddings"
    )
    assert min_dim == 768, f"DecisionTrace min embedding dim = {min_dim}, expected 768"
    assert max_dim == 768, f"DecisionTrace max embedding dim = {max_dim}, expected 768"


def test_entity_embeddings_are_768d(neo4j_driver):
    with neo4j_driver.session() as session:
        result = session.run(
            """
            MATCH (e:Entity)
            WITH count(e) AS total,
                 count(e.embedding) AS with_embedding,
                 min(size(e.embedding)) AS min_dim,
                 max(size(e.embedding)) AS max_dim
            RETURN total, with_embedding, min_dim, max_dim
            """
        ).single()

    assert result is not None
    total = result["total"]
    with_embedding = result["with_embedding"]
    min_dim = result["min_dim"]
    max_dim = result["max_dim"]

    assert total > 0, "No Entity nodes — graph is empty"
    assert with_embedding == total, (
        f"{total - with_embedding} / {total} Entity nodes missing embeddings"
    )
    assert min_dim == 768, f"Entity min embedding dim = {min_dim}, expected 768"
    assert max_dim == 768, f"Entity max embedding dim = {max_dim}, expected 768"
