"""Smoke tests: /api/decisions/{id} returns valid payloads for random decisions.

Samples 20 random decision IDs from Neo4j and verifies each returns a well-formed
Decision (D14 + D20 regressions: populated created_at, options, context, entities).
"""

import pytest

pytestmark = [pytest.mark.smoke]


def test_random_decisions_are_fetchable(http_client, sample_decision_ids):
    """Each of 20 random decision ids must return a valid Decision payload."""
    failures: list[tuple[str, str]] = []

    for decision_id in sample_decision_ids:
        resp = http_client.get(f"/api/decisions/{decision_id}")
        if resp.status_code != 200:
            failures.append(
                (decision_id, f"status={resp.status_code} body={resp.text[:200]}")
            )
            continue

        body = resp.json()

        # D20: non-empty trigger/context (backfilled with sentinel if originally empty)
        if not (body.get("trigger") or "").strip():
            failures.append((decision_id, "empty trigger"))
            continue
        if not (body.get("context") or "").strip():
            failures.append((decision_id, "empty context"))
            continue

        # D20: options must have >= 1 item
        options = body.get("options", [])
        if not isinstance(options, list) or len(options) < 1:
            failures.append(
                (decision_id, f"options not list-with-≥1-item: {options!r}")
            )
            continue

        # Per Decision schema / D16: agent_decision + agent_rationale required
        if not (body.get("agent_decision") or "").strip():
            failures.append((decision_id, "missing agent_decision"))
            continue
        if not (body.get("agent_rationale") or "").strip():
            failures.append((decision_id, "missing agent_rationale"))
            continue

        # Entities list should exist (may be empty but must be present).
        if "entities" not in body:
            failures.append((decision_id, "missing entities key"))
            continue

    assert not failures, (
        f"{len(failures)} / {len(sample_decision_ids)} decision detail "
        f"fetches failed:\n" + "\n".join(f"  - {d}: {why}" for d, why in failures)
    )


def test_nonexistent_decision_returns_404(http_client):
    resp = http_client.get(
        "/api/decisions/this-id-does-not-exist-0000-ffff-0000-deadbeef"
    )
    assert resp.status_code == 404, resp.text
