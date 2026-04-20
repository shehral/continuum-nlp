"""Programmatic GraphRAG retrieval evaluation against the live demo endpoint.

Computes Recall and MRR over a 6-query demo set using entity-presence ground
truth. Hits HTTP `/api/ask` (hybrid mode); ablations require a backend that
exposes per-mode retrieval (not added here to avoid touching the live demo).

Usage:
    python -m scripts.eval_retrieval                       # default: live GCP
    API_BASE=http://localhost:8000 python -m scripts.eval_retrieval

Methodology:
    Ground truth for each query is the set of decisions whose
    involved-entity names contain any key entity OR whose
    trigger/context/decision/rationale text contains any key term.
    This is an automated proxy for "hand-labeled relevant decisions";
    the report should disclose the methodology change accordingly.

    Two recall flavors are reported:
      - recall_seeds  = |GT ∩ top_K seed decisions| / min(|GT|, K)
      - recall_subgraph = |GT ∩ all decisions in expanded subgraph| / |GT|
    MRR is computed over the seed ranking (1 / rank of first relevant seed).
"""

from __future__ import annotations

import asyncio
import json
import os
import statistics
import sys
from dataclasses import dataclass

import httpx

API_BASE = os.environ.get("API_BASE", "http://34.57.46.203:8000")
TOP_K = 5
HTTP_TIMEOUT = 180.0


@dataclass
class QuerySpec:
    text: str
    pattern: str
    key_entities: list[str]
    key_terms: list[str]


# Mirrors the six demo queries documented in the report (Table 5).
QUERIES: list[QuerySpec] = [
    QuerySpec(
        text="Trade-offs between PostgREST, Hasura, and Supabase",
        pattern="Comparative",
        key_entities=["PostgREST", "Hasura", "Supabase"],
        key_terms=[],
    ),
    QuerySpec(
        text="Marten on Postgres for event sourcing",
        pattern="Decision lookup",
        key_entities=["Marten", "PostgreSQL", "Postgres"],
        key_terms=["event sourcing"],
    ),
    QuerySpec(
        text="Summarize decisions involving FastAPI",
        pattern="Aggregation",
        key_entities=["FastAPI"],
        key_terms=[],
    ),
    QuerySpec(
        text="Decisions involving Amazon SQS and alternatives",
        pattern="Entity-pivot",
        key_entities=["Amazon SQS", "SQS"],
        key_terms=[],
    ),
    QuerySpec(
        text="Rust-related architectural decisions",
        pattern="Domain filter",
        key_entities=["Rust"],
        key_terms=[],
    ),
    QuerySpec(
        text="Patterns around caching with Redis",
        pattern="Pattern lookup",
        key_entities=["Redis"],
        key_terms=["cache", "caching", "memoization"],
    ),
]


async def fetch_all_decisions(client: httpx.AsyncClient) -> list[dict]:
    out: list[dict] = []
    for offset in range(0, 1000, 100):
        r = await client.get(
            f"{API_BASE}/api/decisions",
            params={"limit": 100, "offset": offset},
        )
        r.raise_for_status()
        page = r.json()
        if not page:
            break
        out.extend(page)
        if len(page) < 100:
            break
    return out


def build_ground_truth(
    decisions: list[dict], spec: QuerySpec
) -> set[str]:
    rel: set[str] = set()
    ents = {e.lower() for e in spec.key_entities}
    terms = [t.lower() for t in spec.key_terms]

    for d in decisions:
        entity_names = {(e.get("name") or "").lower() for e in d.get("entities", [])}
        if entity_names & ents:
            rel.add(d["id"])
            continue
        text_blob = " ".join(
            [
                d.get("trigger") or "",
                d.get("context") or "",
                d.get("agent_decision") or "",
                d.get("agent_rationale") or "",
            ]
        ).lower()
        if any(t in text_blob for t in terms):
            rel.add(d["id"])
            continue
        # Loose fallback: entity name appears as substring in decision text
        # (catches decisions where the resolver missed but the text mentions it).
        if any(e in text_blob for e in ents):
            rel.add(d["id"])
    return rel


async def query_ask(
    client: httpx.AsyncClient, q: str, top_k: int = TOP_K
) -> tuple[list[str], list[dict]]:
    """Hit /api/ask, capture only the `event: context` payload, then break out
    of the stream so we don't wait for full LLM generation."""
    seed_ids: list[str] = []
    nodes: list[dict] = []
    event_type: str | None = None
    async with client.stream(
        "GET",
        f"{API_BASE}/api/ask",
        params={"q": q, "top_k": top_k},
        timeout=HTTP_TIMEOUT,
    ) as resp:
        resp.raise_for_status()
        async for line in resp.aiter_lines():
            if not line:
                continue
            if line.startswith("event:"):
                event_type = line.split(":", 1)[1].strip()
            elif line.startswith("data:") and event_type == "context":
                payload = json.loads(line.split(":", 1)[1].strip())
                seed_ids = list(payload.get("seed_ids", []))
                nodes = list(payload.get("nodes", []))
                break  # we only need the seed/context event
    return seed_ids, nodes


def compute_metrics(
    seed_ids: list[str], nodes: list[dict], gt: set[str], top_k: int
) -> dict:
    # Decision IDs only (entity seeds aren't in our GT).
    decision_node_ids = {n["id"] for n in nodes if n.get("type") == "decision"}
    seed_decision_ids = [s for s in seed_ids if s in decision_node_ids]

    # Recall@K over seeds (capped denominator: min(|GT|, K))
    seeds_top_k = seed_decision_ids[:top_k]
    seed_hits = len(set(seeds_top_k) & gt)
    denom_seeds = min(len(gt), top_k) if gt else 1
    recall_seeds = seed_hits / denom_seeds if gt else 0.0

    # Recall over full expanded subgraph decisions
    subgraph_hits = len(decision_node_ids & gt)
    recall_subgraph = subgraph_hits / len(gt) if gt else 0.0

    # MRR over seed ranking
    mrr = 0.0
    for rank, sid in enumerate(seed_decision_ids, start=1):
        if sid in gt:
            mrr = 1.0 / rank
            break

    return {
        "gt_size": len(gt),
        "seed_count": len(seed_decision_ids),
        "subgraph_decisions": len(decision_node_ids),
        "recall_seeds": round(recall_seeds, 3),
        "recall_subgraph": round(recall_subgraph, 3),
        "mrr": round(mrr, 3),
    }


async def main() -> int:
    print(f"GraphRAG eval against {API_BASE}")
    print("-" * 80)
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        # Health check
        r = await client.get(f"{API_BASE}/health")
        if r.status_code != 200:
            print(f"FAIL: health check returned {r.status_code}")
            return 1

        print("Fetching all decisions for ground-truth construction...")
        decisions = await fetch_all_decisions(client)
        print(f"  loaded {len(decisions)} decisions")
        print()

        rows = []
        for spec in QUERIES:
            gt = build_ground_truth(decisions, spec)
            try:
                seed_ids, nodes = await query_ask(client, spec.text, top_k=TOP_K)
            except Exception as e:
                print(f"  ERROR querying {spec.text!r}: {e}")
                continue
            m = compute_metrics(seed_ids, nodes, gt, TOP_K)
            rows.append((spec, m))
            print(
                f"  [{spec.pattern:14s}] {spec.text[:50]:50s} "
                f"GT={m['gt_size']:3d} R_seeds={m['recall_seeds']:.2f} "
                f"R_subgraph={m['recall_subgraph']:.2f} MRR={m['mrr']:.2f}"
            )

        if not rows:
            print("No successful queries; aborting summary.")
            return 1

        print()
        print("=" * 80)
        recall_seeds = [m["recall_seeds"] for _, m in rows]
        recall_subgraph = [m["recall_subgraph"] for _, m in rows]
        mrrs = [m["mrr"] for _, m in rows]
        print(
            f"Mean Recall@{TOP_K} (seeds, capped denom)   : "
            f"{statistics.mean(recall_seeds):.3f} "
            f"(min {min(recall_seeds):.2f}, max {max(recall_seeds):.2f})"
        )
        print(
            f"Mean Recall (full expanded subgraph)        : "
            f"{statistics.mean(recall_subgraph):.3f} "
            f"(min {min(recall_subgraph):.2f}, max {max(recall_subgraph):.2f})"
        )
        print(
            f"Mean MRR (over seed ranking)                : "
            f"{statistics.mean(mrrs):.3f} "
            f"(min {min(mrrs):.2f}, max {max(mrrs):.2f})"
        )

        # Emit machine-readable JSON for the report patch.
        out = {
            "api_base": API_BASE,
            "top_k": TOP_K,
            "queries": [
                {
                    "query": spec.text,
                    "pattern": spec.pattern,
                    **m,
                }
                for spec, m in rows
            ],
            "summary": {
                "mean_recall_seeds_at_k": round(statistics.mean(recall_seeds), 3),
                "mean_recall_subgraph": round(statistics.mean(recall_subgraph), 3),
                "mean_mrr": round(statistics.mean(mrrs), 3),
            },
        }
        out_path = os.environ.get(
            "EVAL_OUT", "/tmp/continuum_eval_results.json"
        )
        with open(out_path, "w") as f:
            json.dump(out, f, indent=2)
        print(f"\nWrote results to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
