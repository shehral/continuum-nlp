"""Verify Neo4j VECTOR and FULLTEXT indexes exist with correct configs.

GraphRAG hybrid search relies on exactly these four indexes:
- decision_embedding  (VECTOR, 768-d, DecisionTrace)
- entity_embedding    (VECTOR, 768-d, Entity)
- decision_fulltext   (FULLTEXT, DecisionTrace)
- entity_fulltext     (FULLTEXT, Entity)
"""

import pytest

pytestmark = [pytest.mark.smoke]


REQUIRED_VECTOR_INDEXES = {
    "decision_embedding": "DecisionTrace",
    "entity_embedding": "Entity",
}
REQUIRED_FULLTEXT_INDEXES = {
    "decision_fulltext": "DecisionTrace",
    "entity_fulltext": "Entity",
}


def _list_indexes(neo4j_driver):
    with neo4j_driver.session() as session:
        result = session.run("SHOW INDEXES")
        return [dict(r) for r in result]


def test_vector_indexes_exist_and_online(neo4j_driver):
    indexes = _list_indexes(neo4j_driver)
    by_name = {idx.get("name"): idx for idx in indexes}

    for name, label in REQUIRED_VECTOR_INDEXES.items():
        assert name in by_name, (
            f"Missing VECTOR index `{name}`. "
            f"Existing: {sorted(by_name.keys())}"
        )
        idx = by_name[name]
        assert idx.get("type") == "VECTOR", (
            f"Index `{name}` type is {idx.get('type')}, expected VECTOR"
        )
        # Neo4j 5+ uses 'state' ("ONLINE") or similar; only warn if present.
        state = idx.get("state")
        if state is not None:
            assert state == "ONLINE", (
                f"Index `{name}` state is {state}, expected ONLINE"
            )
        # Label coverage
        labels = idx.get("labelsOrTypes") or []
        assert label in labels, (
            f"Index `{name}` covers labels {labels}, expected to include {label}"
        )


def test_fulltext_indexes_exist(neo4j_driver):
    indexes = _list_indexes(neo4j_driver)
    by_name = {idx.get("name"): idx for idx in indexes}

    for name, label in REQUIRED_FULLTEXT_INDEXES.items():
        assert name in by_name, (
            f"Missing FULLTEXT index `{name}`. "
            f"Existing: {sorted(by_name.keys())}"
        )
        idx = by_name[name]
        assert idx.get("type") == "FULLTEXT", (
            f"Index `{name}` type is {idx.get('type')}, expected FULLTEXT"
        )
        state = idx.get("state")
        if state is not None:
            assert state == "ONLINE", (
                f"Index `{name}` state is {state}, expected ONLINE"
            )
        labels = idx.get("labelsOrTypes") or []
        assert label in labels, (
            f"Index `{name}` covers labels {labels}, expected to include {label}"
        )


def test_vector_indexes_are_768_dimensional(neo4j_driver):
    """Config option `vector.dimensions` must be 768, not 2048.

    Neo4j returns the nested options map as a server-side Map object whose
    keys with dots (e.g. `vector.dimensions`) don't survive a plain Python
    dict cast cleanly. Extract the value via Cypher instead.
    """
    with neo4j_driver.session() as session:
        result = session.run(
            """
            SHOW VECTOR INDEXES YIELD name, options
            RETURN name, options.indexConfig.`vector.dimensions` AS dims
            """
        )
        rows = [(r["name"], r["dims"]) for r in result]

    for name, dims in rows:
        if name not in REQUIRED_VECTOR_INDEXES:
            continue
        assert dims == 768, (
            f"Vector index `{name}` dimensions = {dims}, expected 768 "
            f"(D2 regression — stale 2048-d config?)"
        )
