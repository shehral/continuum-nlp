"""Tests for the ask router (SSE streaming endpoint)."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import ask


@pytest.fixture
def app():
    """Create a test FastAPI app with the ask router mounted."""
    test_app = FastAPI()
    test_app.include_router(ask.router, prefix="/api/ask")
    return test_app


@pytest.fixture
def client(app):
    """Create a test client."""
    return TestClient(app)


class TestAskEndpoint:
    """Tests for GET /api/ask."""

    def test_missing_q_param_returns_422(self, client):
        """Missing required `q` parameter should return 422."""
        response = client.get("/api/ask")
        assert response.status_code == 422

    def test_q_too_short_returns_422(self, client):
        """Query shorter than 3 characters should return 422."""
        response = client.get("/api/ask", params={"q": "ab"})
        assert response.status_code == 422

    def test_valid_query_returns_event_stream(self, client):
        """Valid query should return text/event-stream content type."""
        mock_subgraph = {"nodes": [], "edges": []}
        mock_context_text = ""
        mock_seed_ids = []

        with (
            patch(
                "routers.ask.get_graph_rag_service",
            ) as mock_rag,
            patch(
                "routers.ask.get_current_user_id",
                new_callable=AsyncMock,
                return_value="test-user",
            ),
        ):
            service = AsyncMock()
            service.retrieve_context = AsyncMock(
                return_value=(mock_subgraph, mock_context_text, mock_seed_ids)
            )
            mock_rag.return_value = service

            response = client.get("/api/ask", params={"q": "What database do we use?"})

            assert response.status_code == 200
            assert "text/event-stream" in response.headers["content-type"]

    def test_valid_query_streams_context_event(self, client):
        """Valid query should stream a context event first."""
        mock_subgraph = {
            "nodes": [{"id": "n1", "label": "Entity", "name": "PostgreSQL", "type": "technology"}],
            "edges": [],
        }
        mock_context_text = ""
        mock_seed_ids = ["n1"]

        with (
            patch("routers.ask.get_graph_rag_service") as mock_rag,
            patch(
                "routers.ask.get_current_user_id",
                new_callable=AsyncMock,
                return_value="test-user",
            ),
        ):
            service = AsyncMock()
            service.retrieve_context = AsyncMock(
                return_value=(mock_subgraph, mock_context_text, mock_seed_ids)
            )
            mock_rag.return_value = service

            response = client.get("/api/ask", params={"q": "What database do we use?"})

            body = response.text
            assert "event: context" in body
            assert "event: done" in body
            # Verify reshaped node structure
            assert '"type": "entity"' in body
            assert '"is_seed": true' in body
            assert '"entity_type": "technology"' in body

    def test_depth_out_of_range_returns_422(self, client):
        """Depth parameter outside [1, 3] should return 422."""
        response = client.get("/api/ask", params={"q": "test query", "depth": 5})
        assert response.status_code == 422

    def test_top_k_out_of_range_returns_422(self, client):
        """top_k parameter outside [1, 10] should return 422."""
        response = client.get("/api/ask", params={"q": "test query", "top_k": 20})
        assert response.status_code == 422
