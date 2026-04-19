"""Post-import densification: add SIMILAR_TO edges between DecisionTrace nodes
whose nomic-embed-text embeddings have cosine similarity >= threshold.

Run AFTER reembed_all.py. Idempotent.

Run from host:
    /tmp/continuum_migrate_venv/bin/python apps/api/scripts/densify.py
"""

from __future__ import annotations

import os
import sys
import time

from neo4j import GraphDatabase

NEO4J_URI = os.environ.get("DEST_NEO4J_URI", "bolt://localhost:7688")
NEO4J_AUTH = (
    os.environ.get("DEST_NEO4J_USER", "neo4j"),
    os.environ.get("DEST_NEO4J_PASSWORD", "neo4jpassword"),
)
TOP_K = int(os.environ.get("SIMILAR_TO_TOP_K", "8"))
MIN_SIM = float(os.environ.get("SIMILAR_TO_MIN_SIM", "0.80"))


def log(msg: str) -> None:
    print(f"[densify] {msg}", flush=True)


def main() -> int:
    """kNN approach: for each decision, link it to its TOP_K most similar
    peers above MIN_SIM. Edges are undirected (stored once, with lower id first)
    to keep the visualization clean.

    Why kNN over a threshold: nomic-embed-text embeds these decision texts into
    a tight region, so a flat threshold (0.75) produces ~170 edges per decision.
    kNN bounds per-node degree, giving a readable graph.
    """
    t0 = time.time()
    driver = GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)
    try:
        log(f"neo4j: {NEO4J_URI}  top_k={TOP_K}  min_sim={MIN_SIM}")
        with driver.session() as s:
            # Wipe any stale SIMILAR_TO edges so this script is safely idempotent.
            s.run("MATCH ()-[r:SIMILAR_TO]->() DELETE r").consume()

            result = s.run(
                """
                MATCH (d:DecisionTrace) WHERE d.embedding IS NOT NULL
                WITH collect(d) AS decisions
                UNWIND decisions AS d1
                UNWIND decisions AS d2
                WITH d1, d2 WHERE d1.id < d2.id
                WITH d1, d2,
                     vector.similarity.cosine(d1.embedding, d2.embedding) AS sim
                WHERE sim >= $min_sim
                WITH d1, d2, sim
                ORDER BY sim DESC
                WITH d1, collect({d2: d2, sim: sim})[0..$k] AS top
                UNWIND top AS t
                WITH d1, t.d2 AS d2, t.sim AS sim
                MERGE (d1)-[r:SIMILAR_TO]->(d2)
                SET r.similarity = sim
                RETURN count(r) AS edges_created
                """,
                k=TOP_K,
                min_sim=MIN_SIM,
            )
            row = result.single()
            edges = row["edges_created"]

            # Post-check: degree distribution
            deg = s.run(
                "MATCH (d:DecisionTrace) "
                "OPTIONAL MATCH (d)-[r:SIMILAR_TO]-() "
                "WITH d, count(r) AS deg "
                "RETURN min(deg) AS min_d, avg(deg) AS avg_d, max(deg) AS max_d"
            ).single()

            log(f"created {edges} SIMILAR_TO edges in {time.time() - t0:.1f}s")
            log(f"degree per decision (undirected view): "
                f"min={deg['min_d']} avg={deg['avg_d']:.1f} max={deg['max_d']}")
        return 0
    finally:
        driver.close()


if __name__ == "__main__":
    sys.exit(main())
