"""/api/ask SSE pipeline smoke tests.

Posts the 6 canned demo queries to the streaming endpoint and validates the
event contract:  one `context` (with seeds) → ≥1 `token` → one `done` → zero `error`.

NOTE: each call takes ~30-60s on host Ollama. Keep the query list short and
don't parallelize — we want sequential so one at a time loads the LLM.
"""

import json

import httpx
import pytest

pytestmark = [pytest.mark.smoke]

DEMO_QUERIES = [
    "What are the trade-offs between PostgREST, Hasura, and Supabase?",
    "Why might a team pick Marten on Postgres for event sourcing?",
    "Summarize the decisions that involve FastAPI.",
    "Which decisions involve Amazon SQS and what were the alternatives?",
    "Show me Rust-related architectural decisions.",
    "What patterns show up around caching with Redis?",
]


def _parse_sse_stream(text: str) -> list[tuple[str, dict]]:
    """Parse raw SSE text into a list of (event_type, data_dict)."""
    events: list[tuple[str, dict]] = []
    current_event = None
    for raw_line in text.split("\n"):
        line = raw_line.rstrip("\r")
        if line.startswith("event: "):
            current_event = line[len("event: "):].strip()
        elif line.startswith("data: ") and current_event is not None:
            data_str = line[len("data: "):]
            try:
                events.append((current_event, json.loads(data_str)))
            except json.JSONDecodeError:
                events.append((current_event, {"_raw": data_str}))
            current_event = None
    return events


@pytest.mark.parametrize("query", DEMO_QUERIES)
def test_ask_pipeline_for_demo_queries(api_base_url, query):
    """Each demo query must emit a well-formed SSE stream."""
    # Use long-timeout client because LLM generation can take 60s+.
    with httpx.Client(timeout=httpx.Timeout(180.0, connect=10.0)) as client:
        resp = client.get(
            f"{api_base_url}/api/ask",
            params={"q": query},
            headers={"Accept": "text/event-stream"},
        )

    assert resp.status_code == 200, f"Got {resp.status_code}: {resp.text[:300]}"
    events = _parse_sse_stream(resp.text)
    event_types = [e[0] for e in events]

    # Structure: context first, then >=1 token, then exactly one done, zero errors.
    assert event_types.count("error") == 0, (
        f"Got error events for {query!r}: "
        f"{[e[1] for e in events if e[0] == 'error']}"
    )
    assert event_types.count("context") == 1, (
        f"Expected exactly 1 context event, got {event_types.count('context')} "
        f"for {query!r}"
    )
    assert event_types.count("done") == 1, (
        f"Expected exactly 1 done event, got {event_types.count('done')}"
    )
    assert event_types.count("token") >= 1, (
        f"Expected >=1 token event, got {event_types.count('token')}"
    )

    # Event ordering: context must precede first token, tokens must precede done.
    assert event_types.index("context") < event_types.index("token"), (
        f"context must come before first token for {query!r}"
    )
    assert event_types.index("token") < event_types.index("done"), (
        f"tokens must come before done for {query!r}"
    )

    # Context event must include at least one seed id.
    context_payload = next(e[1] for e in events if e[0] == "context")
    assert len(context_payload.get("seed_ids", [])) >= 1, (
        f"No seed_ids in context for {query!r}"
    )

    nodes = context_payload.get("nodes", [])
    decision_nodes = [n for n in nodes if n.get("type") == "decision"]
    assert len(decision_nodes) >= 1, (
        f"Expected at least 1 decision source node for {query!r}, "
        f"got {len(decision_nodes)} (total={len(nodes)})"
    )

    # Accumulated answer must be substantive.
    answer = "".join(
        e[1].get("text", "") for e in events if e[0] == "token"
    )
    assert len(answer) > 50, (
        f"Answer for {query!r} was only {len(answer)} chars: {answer!r}"
    )


def test_ask_context_has_no_raw_uuid_similar_to_lines(api_base_url):
    """D19 regression guard: the /ask context must NOT leak raw uuid SIMILAR_TO lines.

    Before D19 fix, the LLM context contained lines like
    `uuid-a --[SIMILAR_TO]--> uuid-b` which the LLM would refuse to answer
    about. This test re-runs a known-failing-before-D19 query and asserts
    the response stream contains real decision references, not uuid noise.
    """
    with httpx.Client(timeout=httpx.Timeout(180.0, connect=10.0)) as client:
        resp = client.get(
            f"{api_base_url}/api/ask",
            params={"q": "Summarize the decisions that involve FastAPI."},
        )
    assert resp.status_code == 200
    events = _parse_sse_stream(resp.text)

    # Combine all tokens into the complete answer.
    answer = "".join(
        e[1].get("text", "") for e in events if e[0] == "token"
    )

    # The LLM should not be declining to answer because the context is noise.
    refusal_phrases = [
        "no mention of FastAPI in the provided text",
        "summary of various similarity relationships",
    ]
    for phrase in refusal_phrases:
        assert phrase.lower() not in answer.lower(), (
            f"D19 regression — LLM refused / cited uuid similarity noise: "
            f"{phrase!r} found in answer"
        )


def test_ask_rejects_too_short_query(api_base_url):
    """Validation: q must be >=3 chars."""
    with httpx.Client(timeout=10.0) as client:
        resp = client.get(f"{api_base_url}/api/ask", params={"q": "ab"})
    assert resp.status_code == 422
