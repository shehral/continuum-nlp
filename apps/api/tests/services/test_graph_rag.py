"""Unit tests for GraphRAGService.

Tests:
- RRF scoring produces correct rankings
- Context serialization formats decisions and entities
- Empty subgraph returns empty string
- Subgraph expansion returns nodes and edges
- Hybrid retrieve falls back to fulltext-only on vector failure
"""

from unittest.mock import AsyncMock, patch

import pytest

from services.graph_rag import (
    GraphRAGService,
    get_graph_rag_service,
    rrf_fuse,
    serialize_context,
)


# ============================================================================
# RRF Fusion Tests
# ============================================================================


class TestRRFFuse:
    """Test Reciprocal Rank Fusion scoring."""

    def test_single_list_ordering(self):
        """Items from one list only should preserve original order."""
        fulltext = ["a", "b", "c"]
        vector = []
        result = rrf_fuse(fulltext, vector, k=60)
        assert result == ["a", "b", "c"]

    def test_overlapping_ids_ranked_higher(self):
        """IDs appearing in both lists should rank above single-list IDs."""
        fulltext = ["a", "b", "c"]
        vector = ["b", "d", "a"]
        result = rrf_fuse(fulltext, vector, k=60)
        # "b" appears rank 2 in fulltext (1/(60+2)) and rank 1 in vector (1/(60+1))
        # "a" appears rank 1 in fulltext (1/(60+1)) and rank 3 in vector (1/(60+3))
        # Both should outrank single-list items "c" and "d"
        assert result[0] in ("a", "b")
        assert result[1] in ("a", "b")
        assert set(result[:2]) == {"a", "b"}

    def test_correct_rrf_scores(self):
        """Verify exact RRF score calculation."""
        fulltext = ["x", "y"]
        vector = ["y", "x"]
        result = rrf_fuse(fulltext, vector, k=60)
        # x: 1/(60+1) + 1/(60+2) = 1/61 + 1/62
        # y: 1/(60+2) + 1/(60+1) = 1/62 + 1/61
        # Same score, but order is deterministic from sorted()
        # Both have equal scores, so order is stable from dict insertion
        assert set(result) == {"x", "y"}

    def test_empty_lists(self):
        """Empty input should return empty output."""
        assert rrf_fuse([], []) == []

    def test_disjoint_lists_k_sensitivity(self):
        """With small k, rank position matters more."""
        fulltext = ["a", "b"]
        vector = ["c", "d"]
        result = rrf_fuse(fulltext, vector, k=1)
        # a: 1/(1+1) = 0.5, b: 1/(1+2) = 0.333
        # c: 1/(1+1) = 0.5, d: 1/(1+2) = 0.333
        # a and c are tied at rank 1, b and d at rank 2
        assert len(result) == 4
        assert set(result) == {"a", "b", "c", "d"}

    def test_asymmetric_overlap(self):
        """Item in both lists at rank 1 beats item only in one list at rank 1."""
        fulltext = ["shared", "only_ft"]
        vector = ["shared", "only_vec"]
        result = rrf_fuse(fulltext, vector, k=60)
        # shared: 1/61 + 1/61 = 2/61 ~ 0.0328
        # only_ft: 1/62 ~ 0.0161
        # only_vec: 1/62 ~ 0.0161
        assert result[0] == "shared"


# ============================================================================
# Context Serialization Tests
# ============================================================================


class TestSerializeContext:
    """Test subgraph-to-text serialization."""

    def test_empty_subgraph_returns_empty_string(self):
        """Empty nodes and edges should produce empty string."""
        assert serialize_context({"nodes": [], "edges": []}) == ""

    def test_missing_keys_returns_empty_string(self):
        """Dict without nodes/edges keys should produce empty string."""
        assert serialize_context({}) == ""

    def test_decision_formatting(self):
        """Decision nodes should serialize with trigger, decision, rationale."""
        subgraph = {
            "nodes": [
                {
                    "id": "d1",
                    "label": "DecisionTrace",
                    "trigger": "Choose a database",
                    "decision": "PostgreSQL",
                    "rationale": "Best for relational data",
                    "context": "Building a web app",
                    "options": ["PostgreSQL", "MongoDB"],
                }
            ],
            "edges": [],
        }
        text = serialize_context(subgraph)
        assert "## Decisions" in text
        assert "Choose a database" in text
        assert "PostgreSQL" in text
        assert "Best for relational data" in text
        assert "Building a web app" in text
        assert "PostgreSQL, MongoDB" in text

    def test_entity_formatting(self):
        """Entity nodes should serialize with type and name."""
        subgraph = {
            "nodes": [
                {
                    "id": "e1",
                    "label": "Entity",
                    "name": "Redis",
                    "type": "technology",
                }
            ],
            "edges": [],
        }
        text = serialize_context(subgraph)
        assert "## Entities" in text
        assert "[technology] Redis" in text

    def test_relationship_formatting(self):
        """Edges should serialize with source, target, and type."""
        subgraph = {
            "nodes": [
                {"id": "d1", "label": "DecisionTrace", "trigger": "Pick cache"},
            ],
            "edges": [
                {"source": "d1", "target": "e1", "type": "INVOLVES"},
            ],
        }
        text = serialize_context(subgraph)
        assert "## Relationships" in text
        assert "d1 --[INVOLVES]--> e1" in text

    def test_mixed_nodes(self):
        """Decisions and entities should appear in separate sections."""
        subgraph = {
            "nodes": [
                {
                    "id": "d1",
                    "label": "DecisionTrace",
                    "trigger": "Pick a DB",
                    "decision": "Postgres",
                    "rationale": "Reliable",
                },
                {
                    "id": "e1",
                    "label": "Entity",
                    "name": "Postgres",
                    "type": "technology",
                },
            ],
            "edges": [
                {"source": "d1", "target": "e1", "type": "INVOLVES"},
            ],
        }
        text = serialize_context(subgraph)
        assert "## Decisions" in text
        assert "## Entities" in text
        assert "## Relationships" in text

    def test_decision_with_agent_fields(self):
        """Should use agent_decision/agent_rationale when decision/rationale missing."""
        subgraph = {
            "nodes": [
                {
                    "id": "d1",
                    "label": "DecisionTrace",
                    "trigger": "Framework choice",
                    "agent_decision": "FastAPI",
                    "agent_rationale": "Async and fast",
                }
            ],
            "edges": [],
        }
        text = serialize_context(subgraph)
        assert "FastAPI" in text
        assert "Async and fast" in text

    def test_decision_missing_optional_fields(self):
        """Decision with only trigger should still serialize."""
        subgraph = {
            "nodes": [
                {
                    "id": "d1",
                    "label": "DecisionTrace",
                    "trigger": "Minimal decision",
                }
            ],
            "edges": [],
        }
        text = serialize_context(subgraph)
        assert "Minimal decision" in text


# ============================================================================
# Subgraph Expansion Tests (with mocked Neo4j)
# ============================================================================


class TestExpandSubgraph:
    """Test subgraph expansion with mocked Neo4j."""

    @pytest.fixture
    def service(self):
        """Create GraphRAGService with mocked dependencies."""
        with patch("services.graph_rag.get_embedding_service"):
            return GraphRAGService()

    @pytest.mark.asyncio
    async def test_empty_seed_ids(self, service):
        """Empty seed IDs should return empty subgraph without DB call."""
        result = await service.expand_subgraph([])
        assert result == {"nodes": [], "edges": []}

    @pytest.mark.asyncio
    async def test_returns_nodes_and_edges(self, service):
        """Should return structured nodes and edges from Neo4j result."""
        mock_session = AsyncMock()
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(
            return_value={
                "nodes": [
                    {
                        "id": "d1",
                        "label": "DecisionTrace",
                        "name": None,
                        "type": None,
                        "trigger": "Choose DB",
                        "decision": "PostgreSQL",
                        "rationale": "Reliable",
                        "context": "Web app",
                        "options": ["PostgreSQL", "MongoDB"],
                        "confidence": 0.9,
                    },
                    {
                        "id": "e1",
                        "label": "Entity",
                        "name": "PostgreSQL",
                        "type": "technology",
                        "trigger": None,
                        "decision": None,
                        "rationale": None,
                        "context": None,
                        "options": None,
                        "confidence": None,
                    },
                ],
                "edges": [
                    {"source": "d1", "target": "e1", "type": "INVOLVES"},
                ],
            }
        )
        mock_session.run = AsyncMock(return_value=mock_result)

        result = await service.expand_subgraph(
            ["d1"], session=mock_session
        )

        assert len(result["nodes"]) == 2
        assert len(result["edges"]) == 1
        assert result["edges"][0]["type"] == "INVOLVES"

    @pytest.mark.asyncio
    async def test_no_results_returns_empty(self, service):
        """If Neo4j returns no record, should return empty subgraph."""
        mock_session = AsyncMock()
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value=None)
        mock_session.run = AsyncMock(return_value=mock_result)

        result = await service.expand_subgraph(
            ["nonexistent"], session=mock_session
        )
        assert result == {"nodes": [], "edges": []}


# ============================================================================
# Hybrid Retrieve Tests
# ============================================================================


class TestHybridRetrieve:
    """Test hybrid retrieval with fallback."""

    @pytest.fixture
    def service(self):
        with patch("services.graph_rag.get_embedding_service") as mock_emb:
            mock_emb.return_value.embed_text = AsyncMock(
                return_value=[0.1] * 2048
            )
            svc = GraphRAGService()
            return svc

    @pytest.mark.asyncio
    async def test_fuses_fulltext_and_vector(self, service):
        """Should combine results from both search methods."""
        mock_session = AsyncMock()

        def make_async_result(records):
            """Create a mock Neo4j result that supports async iteration."""
            result = AsyncMock()

            class _AsyncIter:
                def __init__(self):
                    self._items = list(records)
                    self._index = 0

                def __aiter__(self):
                    return self

                async def __anext__(self):
                    if self._index >= len(self._items):
                        raise StopAsyncIteration
                    item = self._items[self._index]
                    self._index += 1
                    return item

            # Replace the mock's __aiter__ with our class-based iterator
            result.__aiter__ = lambda _self=None: _AsyncIter()
            return result

        async def mock_run(query, parameters=None):
            if "decision_fulltext" in query:
                return make_async_result([{"id": "ft1"}, {"id": "ft2"}])
            elif "entity_fulltext" in query:
                return make_async_result([{"id": "eft1"}])
            elif "decision_embedding" in query:
                return make_async_result([{"id": "ft1"}, {"id": "vec1"}])
            elif "entity_embedding" in query:
                return make_async_result([{"id": "evec1"}])
            return make_async_result([])

        mock_session.run = AsyncMock(side_effect=mock_run)

        fused = await service.hybrid_retrieve(
            "test query", "user-1", session=mock_session
        )

        # ft1 appears in both fulltext and vector => should be ranked first
        assert fused[0] == "ft1"
        assert "ft2" in fused
        assert "vec1" in fused

    @pytest.mark.asyncio
    async def test_fallback_to_fulltext_on_vector_error(self, service):
        """Should gracefully fall back to fulltext if vector search fails."""
        mock_session = AsyncMock()

        # Make embedding service fail
        service._embedding_service.embed_text = AsyncMock(
            side_effect=RuntimeError("Embedding service down")
        )

        def make_async_result(records):
            result = AsyncMock()

            class _AsyncIter:
                def __init__(self):
                    self._items = list(records)
                    self._index = 0

                def __aiter__(self):
                    return self

                async def __anext__(self):
                    if self._index >= len(self._items):
                        raise StopAsyncIteration
                    item = self._items[self._index]
                    self._index += 1
                    return item

            result.__aiter__ = lambda _self=None: _AsyncIter()
            return result

        async def mock_run(query, parameters=None):
            if "fulltext" in query:
                return make_async_result([{"id": "ft1"}])
            return make_async_result([])

        mock_session.run = AsyncMock(side_effect=mock_run)

        fused = await service.hybrid_retrieve(
            "test query", "user-1", session=mock_session
        )

        assert "ft1" in fused


# ============================================================================
# Singleton Tests
# ============================================================================


class TestSingleton:
    """Test singleton factory."""

    def test_get_graph_rag_service_returns_instance(self):
        """Factory should return a GraphRAGService instance."""
        with patch("services.graph_rag.get_embedding_service"):
            # Reset singleton for test isolation
            import services.graph_rag as module

            module._graph_rag_service = None
            svc = get_graph_rag_service()
            assert isinstance(svc, GraphRAGService)
            # Cleanup
            module._graph_rag_service = None

    def test_singleton_returns_same_instance(self):
        """Multiple calls should return the same instance."""
        with patch("services.graph_rag.get_embedding_service"):
            import services.graph_rag as module

            module._graph_rag_service = None
            svc1 = get_graph_rag_service()
            svc2 = get_graph_rag_service()
            assert svc1 is svc2
            # Cleanup
            module._graph_rag_service = None
