"""Re-embed all DecisionTrace and Entity nodes in continuum-nlp Neo4j with
nomic-embed-text via Ollama. Idempotent: safe to rerun.

Run from host:
    /tmp/continuum_migrate_venv/bin/python apps/api/scripts/reembed_all.py
"""

from __future__ import annotations

import os
import sys
import time

import ollama
from neo4j import GraphDatabase

NEO4J_URI = os.environ.get("DEST_NEO4J_URI", "bolt://localhost:7688")
NEO4J_AUTH = (
    os.environ.get("DEST_NEO4J_USER", "neo4j"),
    os.environ.get("DEST_NEO4J_PASSWORD", "neo4jpassword"),
)
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11435")
EMBEDDING_MODEL = os.environ.get("OLLAMA_EMBEDDING_MODEL", "nomic-embed-text")


def log(msg: str) -> None:
    print(f"[reembed] {msg}", flush=True)


def embed(client: ollama.Client, text: str) -> list[float]:
    # ollama-py returns {'embedding': [...]}
    resp = client.embeddings(model=EMBEDDING_MODEL, prompt=text)
    return list(resp["embedding"])


def reembed_decisions(driver, client) -> int:
    with driver.session() as s:
        result = s.run(
            "MATCH (d:DecisionTrace) "
            "RETURN d.id AS id, d.decision AS decision, d.context AS context, "
            "       d.rationale AS rationale, d.trigger AS trigger"
        )
        rows = [dict(r) for r in result]

    log(f"embedding {len(rows)} decisions…")
    t0 = time.time()
    for i, r in enumerate(rows):
        text = " ".join(
            filter(None, [r.get("decision"), r.get("context"), r.get("rationale"), r.get("trigger")])
        ).strip()
        if not text:
            continue
        vec = embed(client, text)
        with driver.session() as s:
            s.run(
                "MATCH (d:DecisionTrace {id: $id}) SET d.embedding = $vec",
                id=r["id"],
                vec=vec,
            )
        if (i + 1) % 50 == 0:
            log(f"  decisions: {i + 1}/{len(rows)} ({time.time() - t0:.1f}s elapsed)")
    log(f"decisions done in {time.time() - t0:.1f}s")
    return len(rows)


def reembed_entities(driver, client) -> int:
    with driver.session() as s:
        result = s.run("MATCH (e:Entity) RETURN e.id AS id, e.name AS name, e.type AS type")
        rows = [dict(r) for r in result]

    log(f"embedding {len(rows)} entities…")
    t0 = time.time()
    for i, r in enumerate(rows):
        text = f"{r['name']} ({r['type']})" if r.get("type") else r["name"]
        vec = embed(client, text)
        with driver.session() as s:
            s.run(
                "MATCH (e:Entity {id: $id}) SET e.embedding = $vec",
                id=r["id"],
                vec=vec,
            )
        if (i + 1) % 100 == 0:
            log(f"  entities: {i + 1}/{len(rows)} ({time.time() - t0:.1f}s elapsed)")
    log(f"entities done in {time.time() - t0:.1f}s")
    return len(rows)


def main() -> int:
    t0 = time.time()
    driver = GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)
    client = ollama.Client(host=OLLAMA_HOST)
    try:
        log(f"neo4j: {NEO4J_URI}")
        log(f"ollama: {OLLAMA_HOST} model={EMBEDDING_MODEL}")

        # Quick probe: one embedding to confirm model works + gets expected dims
        probe = embed(client, "probe")
        log(f"embedding dim: {len(probe)} (expect 768)")
        if len(probe) != 768:
            log(f"!!! unexpected embedding dimension {len(probe)} — aborting")
            return 2

        d = reembed_decisions(driver, client)
        e = reembed_entities(driver, client)

        # Post-check: all embeddings present, all 768-d
        with driver.session() as s:
            check = s.run(
                "MATCH (n) WHERE n:DecisionTrace OR n:Entity "
                "RETURN labels(n)[0] AS lbl, "
                "       count(n) AS total, "
                "       count(n.embedding) AS with_emb, "
                "       min(size(n.embedding)) AS min_dim, "
                "       max(size(n.embedding)) AS max_dim"
            )
            for row in check:
                log(f"  {dict(row)}")

        log(f"total {d + e} nodes re-embedded in {time.time() - t0:.1f}s")
        return 0
    finally:
        driver.close()


if __name__ == "__main__":
    sys.exit(main())
