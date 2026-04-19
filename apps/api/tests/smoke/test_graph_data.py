"""Smoke tests for /api/graph shape + content.

Demo-critical: the /graph page + /ask source cards both rely on /api/graph
returning nodes with both legacy `decision` and new `agent_decision` keys.
"""

import pytest

pytestmark = [pytest.mark.smoke]


def test_graph_returns_decisions_and_entities(http_client):
    resp = http_client.get("/api/graph", params={"page_size": 20})
    assert resp.status_code == 200, resp.text
    body = resp.json()

    nodes = body.get("nodes", [])
    edges = body.get("edges", [])
    assert len(nodes) > 0, "Graph should have at least one decision node"
    assert len(edges) > 0, "Graph should have at least one edge"

    types = {n.get("type") for n in nodes}
    assert "decision" in types, f"Expected decision nodes, got types: {types}"
    # Entities show up as connected nodes when decisions involve them.
    assert "entity" in types, f"Expected entity nodes too, got: {types}"


def test_graph_decision_nodes_have_both_decision_keys(http_client):
    """D16 regression guard: both `decision` and `agent_decision` must be populated."""
    resp = http_client.get("/api/graph", params={"page_size": 30})
    assert resp.status_code == 200
    body = resp.json()

    decisions = [n for n in body.get("nodes", []) if n.get("type") == "decision"]
    assert len(decisions) >= 5, "Need several decisions to validate shape"

    decisions_with_both = 0
    for d in decisions:
        data = d.get("data") or {}
        # Both keys must exist on every decision (even if value is empty for legacy nodes).
        assert "decision" in data, f"Missing `decision` key on {d.get('id')}"
        assert "agent_decision" in data, f"Missing `agent_decision` key on {d.get('id')}"
        assert "rationale" in data
        assert "agent_rationale" in data
        # At least the migrated decisions should have non-empty decision text.
        if (data.get("decision") or "").strip():
            decisions_with_both += 1

    assert decisions_with_both >= 1, "At least one decision should have populated text"


def test_graph_edges_include_involves(http_client):
    resp = http_client.get("/api/graph", params={"page_size": 50})
    body = resp.json()
    edge_types = {e.get("relationship") for e in body.get("edges", [])}
    # INVOLVES is the backbone relation; SIMILAR_TO is opt-in via include_similarity
    assert "INVOLVES" in edge_types, (
        f"Expected INVOLVES edges, got: {edge_types}"
    )


def test_graph_edges_include_similar_to_when_requested(http_client):
    """SIMILAR_TO must be present when include_similarity=true (default)."""
    resp = http_client.get(
        "/api/graph",
        params={"page_size": 100, "include_similarity": "true"},
    )
    body = resp.json()
    edge_types = {e.get("relationship") for e in body.get("edges", [])}
    # 2,840 SIMILAR_TO edges exist per DECISION_LOG D8 — at least one should
    # land inside a 100-page slice.
    assert "SIMILAR_TO" in edge_types, (
        f"Expected SIMILAR_TO edges with include_similarity=true, got: {edge_types}"
    )
