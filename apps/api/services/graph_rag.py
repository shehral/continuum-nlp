"""GraphRAG service — hybrid retrieval + subgraph expansion for LLM context.

Combines fulltext and vector search with Reciprocal Rank Fusion (RRF),
then expands the top-K results into a local subgraph for rich LLM context.
"""

import asyncio
from typing import Optional

from db.neo4j import get_neo4j_session
from services.embeddings import get_embedding_service
from utils.logging import get_logger

logger = get_logger(__name__)

# RRF constant (standard value from Cormack et al.)
RRF_K = 60

# Cap subgraph expansion to prevent context explosion
MAX_CONTEXT_NODES = 50

# Default K-hop depth for subgraph traversal
DEFAULT_HOP_DEPTH = 2


def _user_filter(alias: str = "node") -> str:
    """Return a Cypher WHERE clause fragment for user isolation."""
    return f"({alias}.user_id = $user_id OR {alias}.user_id IS NULL)"


def rrf_fuse(
    fulltext_ids: list[str],
    vector_ids: list[str],
    k: int = RRF_K,
) -> list[str]:
    """Fuse two ranked lists using Reciprocal Rank Fusion.

    Score(d) = 1/(k + rank_fulltext) + 1/(k + rank_vector)

    Args:
        fulltext_ids: IDs ranked by fulltext relevance (best first).
        vector_ids: IDs ranked by vector similarity (best first).
        k: Smoothing constant (default 60).

    Returns:
        IDs sorted by fused score, descending.
    """
    scores: dict[str, float] = {}

    for rank, doc_id in enumerate(fulltext_ids, start=1):
        scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)

    for rank, doc_id in enumerate(vector_ids, start=1):
        scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)

    return sorted(scores, key=lambda d: scores[d], reverse=True)


def serialize_context(subgraph: dict) -> str:
    """Serialize a subgraph dict into structured text for LLM consumption.

    Args:
        subgraph: Dict with "nodes" and "edges" lists.

    Returns:
        Human-readable string describing decisions, entities, and relationships.
    """
    nodes = subgraph.get("nodes", [])
    edges = subgraph.get("edges", [])

    if not nodes and not edges:
        return ""

    parts: list[str] = []

    # Build a decision_id -> list of entity names map from INVOLVES edges.
    # Attaches entity info directly to each decision block below instead of
    # serializing raw uuid edges, which the LLM treats as noise.
    entity_by_id = {n["id"]: n for n in nodes if n.get("label") == "Entity"}
    decision_entities: dict[str, list[str]] = {}
    for edge in edges:
        if edge.get("type") != "INVOLVES":
            continue
        src = edge.get("source")
        tgt = edge.get("target")
        # INVOLVES is DecisionTrace -> Entity, but endpoint order isn't guaranteed
        # by the expansion query, so handle both.
        if tgt in entity_by_id and src not in entity_by_id:
            decision_entities.setdefault(src, []).append(entity_by_id[tgt]["name"])
        elif src in entity_by_id and tgt not in entity_by_id:
            decision_entities.setdefault(tgt, []).append(entity_by_id[src]["name"])

    # Serialize decision nodes with their involved entities inline.
    decisions = [n for n in nodes if n.get("label") == "DecisionTrace"]
    if decisions:
        parts.append("## Decisions\n")
        for d in decisions:
            lines = [f"- **{d.get('trigger', 'Unknown trigger')}**"]
            decision_text = d.get("decision") or d.get("agent_decision", "")
            if decision_text:
                lines.append(f"  Decision: {decision_text}")
            rationale_text = d.get("rationale") or d.get("agent_rationale", "")
            if rationale_text:
                lines.append(f"  Rationale: {rationale_text}")
            context_text = d.get("context", "")
            if context_text:
                lines.append(f"  Context: {context_text}")
            options = d.get("options")
            if options:
                if isinstance(options, list):
                    lines.append(f"  Options: {', '.join(options)}")
                else:
                    lines.append(f"  Options: {options}")
            involved = decision_entities.get(d.get("id"), [])
            if involved:
                lines.append(f"  Involves: {', '.join(sorted(set(involved)))}")
            parts.append("\n".join(lines))

    # Serialize entity nodes as a reference list (no uuid edges — they're
    # already associated with decisions above via "Involves:" lines).
    entities = [n for n in nodes if n.get("label") == "Entity"]
    if entities:
        parts.append("\n## Entities mentioned\n")
        for e in entities:
            etype = e.get("type", "unknown")
            ename = e.get("name", "unnamed")
            parts.append(f"- [{etype}] {ename}")

    return "\n".join(parts)


class GraphRAGService:
    """Hybrid retrieval-augmented generation over the knowledge graph.

    Pipeline:
    1. hybrid_retrieve — fulltext + vector search, fused with RRF
    2. expand_subgraph — K-hop traversal from seed nodes via APOC
    3. serialize_context — structured text for LLM prompt
    """

    def __init__(self):
        self._embedding_service = get_embedding_service()

    async def _fulltext_search(
        self,
        session,
        query: str,
        user_id: str,
        limit: int = 20,
    ) -> list[str]:
        """Run fulltext search across decision and entity indexes.

        Returns list of node IDs ranked by fulltext score.
        """
        ids: list[str] = []

        # Search decisions
        result = await session.run(
            f"""
            CALL db.index.fulltext.queryNodes('decision_fulltext', $query)
            YIELD node, score
            WHERE {_user_filter('node')}
            RETURN node.id AS id
            ORDER BY score DESC
            LIMIT $limit
            """,
            parameters={"query": query, "user_id": user_id, "limit": limit},
        )
        async for record in result:
            ids.append(record["id"])

        # Search entities (scoped to user's decisions)
        result = await session.run(
            """
            CALL db.index.fulltext.queryNodes('entity_fulltext', $query)
            YIELD node, score
            WHERE EXISTS {
                MATCH (d:DecisionTrace)-[:INVOLVES]->(node)
                WHERE d.user_id = $user_id OR d.user_id IS NULL
            }
            RETURN node.id AS id
            ORDER BY score DESC
            LIMIT $limit
            """,
            parameters={"query": query, "user_id": user_id, "limit": limit},
        )
        async for record in result:
            if record["id"] not in ids:
                ids.append(record["id"])

        return ids

    async def _vector_search(
        self,
        session,
        query: str,
        user_id: str,
        limit: int = 20,
    ) -> list[str]:
        """Run vector search across decision and entity indexes.

        Returns list of node IDs ranked by vector similarity.
        """
        embedding = await self._embedding_service.embed_text(
            query, input_type="query"
        )

        ids: list[str] = []

        # Search decisions
        result = await session.run(
            f"""
            CALL db.index.vector.queryNodes('decision_embedding', $top_k, $embedding)
            YIELD node, score
            WHERE {_user_filter('node')}
            RETURN node.id AS id
            ORDER BY score DESC
            """,
            parameters={
                "embedding": embedding,
                "user_id": user_id,
                "top_k": limit,
            },
        )
        async for record in result:
            ids.append(record["id"])

        # Search entities (scoped to user's decisions)
        result = await session.run(
            """
            CALL db.index.vector.queryNodes('entity_embedding', $top_k, $embedding)
            YIELD node, score
            WHERE EXISTS {
                MATCH (d:DecisionTrace)-[:INVOLVES]->(node)
                WHERE d.user_id = $user_id OR d.user_id IS NULL
            }
            RETURN node.id AS id
            ORDER BY score DESC
            """,
            parameters={
                "embedding": embedding,
                "user_id": user_id,
                "top_k": limit,
            },
        )
        async for record in result:
            if record["id"] not in ids:
                ids.append(record["id"])

        return ids

    async def hybrid_retrieve(
        self,
        query: str,
        user_id: str,
        limit: int = 20,
        session=None,
    ) -> list[str]:
        """Run hybrid retrieval: fulltext + vector search fused with RRF.

        Falls back to fulltext-only if vector search fails (e.g. embedding
        service unavailable).

        Args:
            query: User search query.
            user_id: Scoping user ID.
            limit: Max results per search method.
            session: Optional Neo4j session (created if not provided).

        Returns:
            Fused list of node IDs, best first.
        """
        if session is not None:
            # Caller-provided session: use it directly (no concurrency)
            try:
                fulltext_ids = await self._fulltext_search(
                    session, query, user_id, limit
                )
            except Exception as e:
                logger.warning(f"Fulltext search failed: {e}")
                fulltext_ids = []

            try:
                vector_ids = await self._vector_search(
                    session, query, user_id, limit
                )
            except Exception as e:
                logger.warning(
                    f"Vector search failed, falling back to fulltext-only: {e}"
                )
                vector_ids = []

            fused = rrf_fuse(fulltext_ids, vector_ids)
            logger.info(
                f"Hybrid retrieve: {len(fulltext_ids)} fulltext, "
                f"{len(vector_ids)} vector, {len(fused)} fused"
            )
            return fused

        # No session provided: create two separate sessions for concurrent use
        # (Neo4j AsyncSession is NOT safe for concurrent use)
        session_ft = await get_neo4j_session()
        session_vec = await get_neo4j_session()
        try:
            try:
                fulltext_ids, vector_ids = await asyncio.gather(
                    self._fulltext_search(session_ft, query, user_id, limit),
                    self._vector_search(session_vec, query, user_id, limit),
                )
            except Exception as e:
                # Fallback: fulltext only
                logger.warning(
                    f"Vector search failed, falling back to fulltext-only: {e}"
                )
                fulltext_ids = await self._fulltext_search(
                    session_ft, query, user_id, limit
                )
                vector_ids = []

            fused = rrf_fuse(fulltext_ids, vector_ids)
            logger.info(
                f"Hybrid retrieve: {len(fulltext_ids)} fulltext, "
                f"{len(vector_ids)} vector, {len(fused)} fused"
            )
            return fused
        finally:
            await session_ft.close()
            await session_vec.close()

    async def expand_subgraph(
        self,
        seed_ids: list[str],
        depth: int = DEFAULT_HOP_DEPTH,
        max_nodes: int = MAX_CONTEXT_NODES,
        session=None,
    ) -> dict:
        """Expand seed nodes into a local subgraph via K-hop traversal.

        Uses apoc.path.subgraphAll for efficient graph expansion.

        Args:
            seed_ids: Starting node IDs.
            depth: Max traversal hops.
            max_nodes: Cap on returned nodes.
            session: Optional Neo4j session.

        Returns:
            Dict with "nodes" and "edges" lists.
        """
        if not seed_ids:
            return {"nodes": [], "edges": []}

        close_session = False
        if session is None:
            session = await get_neo4j_session()
            close_session = True

        try:
            result = await session.run(
                """
                UNWIND $seed_ids AS seedId
                MATCH (seed) WHERE seed.id = seedId
                // Restrict expansion to INVOLVES only. SIMILAR_TO edges
                // (2.8k post-densification) otherwise dominate the subgraph with
                // low-signal decision→decision similarity pairs, starving the
                // LLM context of actual decision text.
                CALL apoc.path.subgraphAll(seed, {
                    maxLevel: $depth,
                    relationshipFilter: 'INVOLVES'
                })
                YIELD nodes, relationships
                UNWIND nodes AS n
                WITH COLLECT(DISTINCT n) AS allNodes,
                     COLLECT(DISTINCT relationships) AS allRels
                UNWIND allNodes AS node
                WITH allNodes, allRels, node
                LIMIT $max_nodes
                WITH COLLECT(node) AS limitedNodes, allRels
                UNWIND allRels AS relList
                UNWIND relList AS rel
                WITH limitedNodes, COLLECT(DISTINCT rel) AS allRelsList
                RETURN
                    [n IN limitedNodes | {
                        id: n.id,
                        label: HEAD(LABELS(n)),
                        name: n.name,
                        type: n.type,
                        trigger: n.trigger,
                        decision: COALESCE(n.agent_decision, n.decision),
                        rationale: COALESCE(n.agent_rationale, n.rationale),
                        context: n.context,
                        options: n.options,
                        confidence: n.confidence
                    }] AS nodes,
                    [r IN allRelsList WHERE
                        startNode(r) IN limitedNodes AND endNode(r) IN limitedNodes |
                    {
                        source: startNode(r).id,
                        target: endNode(r).id,
                        type: TYPE(r)
                    }] AS edges
                """,
                parameters={
                    "seed_ids": seed_ids,
                    "depth": depth,
                    "max_nodes": max_nodes,
                },
            )

            record = await result.single()
            if record is None:
                return {"nodes": [], "edges": []}

            nodes = record["nodes"] if record["nodes"] else []
            edges = record["edges"] if record["edges"] else []

            logger.info(
                f"Subgraph expansion: {len(seed_ids)} seeds -> "
                f"{len(nodes)} nodes, {len(edges)} edges"
            )
            return {"nodes": list(nodes), "edges": list(edges)}
        finally:
            if close_session:
                await session.close()

    async def retrieve_context(
        self,
        query: str,
        user_id: str,
        top_k: int = 5,
        depth: int = DEFAULT_HOP_DEPTH,
        session=None,
    ) -> tuple[dict, str, list[str]]:
        """Full RAG pipeline: retrieve -> expand -> serialize.

        Args:
            query: User question.
            user_id: Scoping user ID.
            top_k: Number of seed nodes to expand.
            depth: K-hop traversal depth.
            session: Optional Neo4j session.

        Returns:
            Tuple of (subgraph_dict, context_string, seed_ids).
        """
        close_session = False
        if session is None:
            session = await get_neo4j_session()
            close_session = True

        try:
            # Step 1: Hybrid retrieval
            fused_ids = await self.hybrid_retrieve(
                query, user_id, session=session
            )
            seed_ids = fused_ids[:top_k]

            if not seed_ids:
                logger.info("No results from hybrid retrieval")
                return {"nodes": [], "edges": []}, "", []

            # Step 2: Subgraph expansion
            subgraph = await self.expand_subgraph(
                seed_ids, depth=depth, session=session
            )

            # Step 3: Serialize for LLM
            context_str = serialize_context(subgraph)

            return subgraph, context_str, seed_ids
        finally:
            if close_session:
                await session.close()


# Singleton
_graph_rag_service: Optional[GraphRAGService] = None


def get_graph_rag_service() -> GraphRAGService:
    """Get the GraphRAG service singleton."""
    global _graph_rag_service
    if _graph_rag_service is None:
        _graph_rag_service = GraphRAGService()
    return _graph_rag_service
