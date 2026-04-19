"""Integration tests for GraphRAGService against the live Neo4j stack.

Targets the exact regression D19 documented in DECISION_LOG.md:
- `serialize_context` must NOT emit raw uuid SIMILAR_TO lines.
- Subgraph expansion must be filtered to INVOLVES.
- retrieve_context must return seed ids, subgraph, and context text.

Requires running neo4j at bolt://localhost:7688 and working embedding service.
"""

import pytest

pytestmark = [pytest.mark.integration]


@pytest.fixture
async def _neo4j_lifecycle():
    """Initialize the global Neo4j driver per async test.

    Function-scoped because pytest-asyncio creates a new event loop for each
    test by default; the Neo4j driver binds to whichever loop opened it, so a
    module-scoped fixture trips "Future attached to a different loop" errors
    on the second test. Re-initing per test keeps the driver bound to the
    same loop the test runs on.

    Only async tests that touch the live driver request this fixture; the pure
    `serialize_context` unit test below does NOT request it.
    """
    from db.neo4j import close_neo4j, init_neo4j

    await init_neo4j()
    yield
    await close_neo4j()


@pytest.fixture
def queries():
    return [
        "Summarize the decisions that involve FastAPI.",
        "What are the trade-offs between Postgres and MongoDB?",
        "Which decisions involve Amazon SQS?",
    ]


@pytest.mark.asyncio
async def test_retrieve_context_returns_well_formed_payload(_neo4j_lifecycle, queries):
    """Seeds non-empty, subgraph has nodes, context string has structure."""
    from services.graph_rag import get_graph_rag_service

    svc = get_graph_rag_service()
    for q in queries:
        subgraph, context_text, seed_ids = await svc.retrieve_context(
            query=q, user_id="anonymous", top_k=5, depth=2
        )

        assert len(seed_ids) >= 1, f"No seeds retrieved for {q!r}"
        assert len(subgraph.get("nodes", [])) >= 1, (
            f"Subgraph empty for {q!r}"
        )
        # Context text must at least mention Decisions section header.
        assert "## Decisions" in context_text, (
            f"Context missing Decisions header for {q!r}"
        )


@pytest.mark.asyncio
async def test_context_does_not_leak_raw_similar_to_uuid_lines(_neo4j_lifecycle, queries):
    """D19 regression: no raw `uuid --[SIMILAR_TO]--> uuid` lines in LLM context."""
    from services.graph_rag import get_graph_rag_service

    svc = get_graph_rag_service()
    for q in queries:
        _, context_text, _ = await svc.retrieve_context(
            query=q, user_id="anonymous", top_k=5, depth=2
        )
        # Historical bug: serialize_context emitted bare uuid edge lines.
        assert "-[SIMILAR_TO]->" not in context_text, (
            f"D19 regression: raw SIMILAR_TO arrow lines in context for {q!r}"
        )
        assert "--[SIMILAR_TO]-->" not in context_text
        assert "## Relationships" not in context_text, (
            f"D19 regression: raw Relationships section in context for {q!r}"
        )


@pytest.mark.asyncio
async def test_context_attaches_entities_inline_per_decision(_neo4j_lifecycle):
    """Entities should be listed inline under each decision block (Involves: ...)."""
    from services.graph_rag import get_graph_rag_service

    svc = get_graph_rag_service()
    _, context_text, _ = await svc.retrieve_context(
        query="decisions about FastAPI and Python APIs",
        user_id="anonymous",
        top_k=5,
        depth=2,
    )

    # After D19, entities are shown inline on decisions, not as uuid edges.
    assert "Involves:" in context_text, (
        "Expected inline `Involves:` entity attachment per D19 fix"
    )


def test_serialize_context_drops_similar_to_edges():
    """Unit-level check on serialize_context itself — no external deps needed."""
    from services.graph_rag import serialize_context

    subgraph = {
        "nodes": [
            {
                "id": "dec-1",
                "label": "DecisionTrace",
                "trigger": "Pick a DB",
                "decision": "Use Postgres",
                "rationale": "Strong ACID",
                "options": ["Postgres", "Mongo"],
            },
            {
                "id": "ent-1",
                "label": "Entity",
                "name": "Postgres",
                "type": "technology",
            },
            {
                "id": "dec-2",
                "label": "DecisionTrace",
                "trigger": "Pick a cache",
                "decision": "Use Redis",
            },
        ],
        "edges": [
            {"source": "dec-1", "target": "ent-1", "type": "INVOLVES"},
            # This edge must NOT leak as a raw uuid line post-D19.
            {"source": "dec-1", "target": "dec-2", "type": "SIMILAR_TO"},
        ],
    }
    text = serialize_context(subgraph)
    assert "Postgres" in text
    assert "Involves: Postgres" in text
    # SIMILAR_TO must not show up as a raw uuid arrow line.
    assert "SIMILAR_TO" not in text
    assert "dec-1" not in text  # uuids should not appear at all
    assert "dec-2" not in text
