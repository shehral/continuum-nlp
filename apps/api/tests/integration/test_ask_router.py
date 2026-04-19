"""Integration tests for /api/ask SSE event ordering + contract.

Hits the live FastAPI app via httpx (localhost:8000). Asserts ordering:
context → token(s) → done, and that shaped nodes match the frontend contract.
"""

import json
import os

import httpx
import pytest

pytestmark = [pytest.mark.integration]

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    current_event = None
    for line in text.split("\n"):
        line = line.rstrip("\r")
        if line.startswith("event: "):
            current_event = line[len("event: "):].strip()
        elif line.startswith("data: ") and current_event is not None:
            try:
                events.append((current_event, json.loads(line[len("data: "):])))
            except json.JSONDecodeError:
                pass
            current_event = None
    return events


def test_ask_sse_ordering_context_tokens_done():
    with httpx.Client(timeout=httpx.Timeout(180.0, connect=10.0)) as client:
        resp = client.get(
            f"{API_BASE_URL}/api/ask",
            params={"q": "Summarize the decisions that involve FastAPI."},
        )
    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    types = [e[0] for e in events]

    # First event must be context.
    assert types[0] == "context", f"First event is {types[0]!r}, expected context"
    # Last substantive event is done (may be followed by nothing).
    assert types[-1] == "done", f"Last event is {types[-1]!r}, expected done"
    # At least one token event between them.
    token_positions = [i for i, t in enumerate(types) if t == "token"]
    assert token_positions, "No token events emitted"
    assert 0 < token_positions[0] < types.index("done")


def test_ask_shaped_nodes_match_frontend_contract():
    """Context nodes must include type, is_seed, and a data dict."""
    with httpx.Client(timeout=httpx.Timeout(180.0, connect=10.0)) as client:
        resp = client.get(
            f"{API_BASE_URL}/api/ask",
            params={"q": "decisions about Redis caching"},
        )
    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    context_payloads = [e[1] for e in events if e[0] == "context"]
    assert len(context_payloads) == 1

    payload = context_payloads[0]
    assert "nodes" in payload
    assert "edges" in payload
    assert "seed_ids" in payload

    for node in payload["nodes"]:
        assert "id" in node
        assert node["type"] in ("decision", "entity"), (
            f"Unexpected node type: {node.get('type')!r}"
        )
        assert "is_seed" in node
        assert "data" in node
        assert isinstance(node["data"], dict)
