"""Migrate the Entity + DecisionTrace graph from the original Continuum Neo4j
into continuum-nlp Neo4j.

Source: bolt://localhost:7687  (original continuum-neo4j, read-only)
Dest:   bolt://localhost:7688  (continuum-nlp-neo4j, target)

Embeddings are intentionally NOT copied — they are 2048-d NV-EmbedQA vectors
that won't match the 768-d vector index on the dest. `reembed_all.py` fills
them in afterward using nomic-embed-text.

Run from host:
    /tmp/continuum_migrate_venv/bin/python -m apps.api.scripts.migrate_graph

Or from repo root:
    /tmp/continuum_migrate_venv/bin/python apps/api/scripts/migrate_graph.py
"""

from __future__ import annotations

import os
import sys
import time

from neo4j import GraphDatabase

SOURCE_URI = os.environ.get("SOURCE_NEO4J_URI", "bolt://localhost:7687")
DEST_URI = os.environ.get("DEST_NEO4J_URI", "bolt://localhost:7688")
SOURCE_AUTH = (
    os.environ.get("SOURCE_NEO4J_USER", "neo4j"),
    os.environ.get("SOURCE_NEO4J_PASSWORD", "neo4jpassword"),
)
DEST_AUTH = (
    os.environ.get("DEST_NEO4J_USER", "neo4j"),
    os.environ.get("DEST_NEO4J_PASSWORD", "neo4jpassword"),
)

BATCH = 500


def log(msg: str) -> None:
    print(f"[migrate] {msg}", flush=True)


def setup_dest_schema(dest) -> None:
    """Create unique-id constraints on dest so MERGE is cheap and idempotent."""
    with dest.session() as s:
        for label in ("DecisionTrace", "Entity", "Concept", "System", "Technology", "Pattern"):
            s.run(
                f"CREATE CONSTRAINT {label.lower()}_id IF NOT EXISTS "
                f"FOR (n:{label}) REQUIRE n.id IS UNIQUE"
            )
        log("constraints ready on dest")


def copy_nodes(source, dest, label: str) -> int:
    """Copy nodes of one label, dropping the embedding property."""
    with source.session() as src_s:
        # Strip embedding — it will be recomputed. `properties(n)` keeps everything else.
        result = src_s.run(
            f"MATCH (n:{label}) "
            "RETURN n.id AS id, apoc.map.removeKey(properties(n), 'embedding') AS props"
        )
        rows = []
        total = 0
        async_iter = result.__iter__()
        for record in async_iter:
            rows.append({"id": record["id"], "props": record["props"]})
            if len(rows) >= BATCH:
                _write_nodes(dest, label, rows)
                total += len(rows)
                log(f"  copied {total} {label} nodes")
                rows = []
        if rows:
            _write_nodes(dest, label, rows)
            total += len(rows)
    return total


def _write_nodes(dest, label: str, batch: list[dict]) -> None:
    with dest.session() as dst_s:
        dst_s.run(
            f"UNWIND $batch AS row "
            f"MERGE (n:{label} {{id: row.id}}) "
            f"SET n += row.props",
            batch=batch,
        )


def copy_nodes_fallback(source, dest, label: str) -> int:
    """Fallback path when APOC isn't available: strip embedding client-side."""
    with source.session() as src_s:
        result = src_s.run(f"MATCH (n:{label}) RETURN properties(n) AS props")
        rows = []
        total = 0
        for record in result:
            props = dict(record["props"])
            props.pop("embedding", None)
            rows.append({"id": props["id"], "props": props})
            if len(rows) >= BATCH:
                _write_nodes(dest, label, rows)
                total += len(rows)
                log(f"  copied {total} {label} nodes")
                rows = []
        if rows:
            _write_nodes(dest, label, rows)
            total += len(rows)
    return total


def copy_relationships(source, dest, rel_type: str) -> int:
    """Copy relationships (start label, end label) → (start label, end label)."""
    with source.session() as src_s:
        result = src_s.run(
            f"MATCH (a)-[r:{rel_type}]->(b) "
            "RETURN a.id AS a_id, labels(a)[0] AS a_label, "
            "       b.id AS b_id, labels(b)[0] AS b_label, "
            "       properties(r) AS props"
        )
        rows = []
        total = 0
        for record in result:
            rows.append(dict(record))
            if len(rows) >= BATCH:
                _write_rels(dest, rel_type, rows)
                total += len(rows)
                log(f"  copied {total} {rel_type} rels")
                rows = []
        if rows:
            _write_rels(dest, rel_type, rows)
            total += len(rows)
    return total


def _write_rels(dest, rel_type: str, batch: list[dict]) -> None:
    # Dynamic label interpolation is safe here: labels come from source Neo4j
    # node labels which are controlled by us, not user input.
    with dest.session() as dst_s:
        # Group by label pair because Cypher requires labels to be literal.
        by_pair: dict[tuple[str, str], list[dict]] = {}
        for row in batch:
            by_pair.setdefault((row["a_label"], row["b_label"]), []).append(row)
        for (a_label, b_label), sub_batch in by_pair.items():
            dst_s.run(
                f"UNWIND $batch AS row "
                f"MATCH (a:{a_label} {{id: row.a_id}}) "
                f"MATCH (b:{b_label} {{id: row.b_id}}) "
                f"MERGE (a)-[r:{rel_type}]->(b) "
                f"SET r += row.props",
                batch=sub_batch,
            )


def main() -> int:
    t0 = time.time()
    src = GraphDatabase.driver(SOURCE_URI, auth=SOURCE_AUTH)
    dst = GraphDatabase.driver(DEST_URI, auth=DEST_AUTH)
    try:
        log(f"source: {SOURCE_URI}")
        log(f"dest:   {DEST_URI}")

        setup_dest_schema(dst)

        # Check if source has APOC (for efficient property-minus-key query).
        has_apoc = False
        try:
            with src.session() as s:
                s.run("RETURN apoc.version()").single()
            has_apoc = True
        except Exception:
            pass
        log(f"apoc on source: {has_apoc}")
        copy = copy_nodes if has_apoc else copy_nodes_fallback

        # DecisionTrace first, then Entity, so rels can resolve either direction
        for label in ("DecisionTrace", "Entity"):
            n = copy(src, dst, label)
            log(f"{label}: {n} total")

        for rel in ("INVOLVES",):
            n = copy_relationships(src, dst, rel)
            log(f"{rel}: {n} total")

        # Sanity check
        with dst.session() as s:
            row = s.run(
                "MATCH (d:DecisionTrace) WITH count(d) AS decs "
                "MATCH (e:Entity) WITH decs, count(e) AS ents "
                "MATCH ()-[r:INVOLVES]->() RETURN decs, ents, count(r) AS rels"
            ).single()
            log(f"dest totals: {dict(row)}")

        log(f"done in {time.time() - t0:.1f}s")
        return 0
    finally:
        src.close()
        dst.close()


if __name__ == "__main__":
    sys.exit(main())
