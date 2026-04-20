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


# Lucene reserved characters that must be escaped in fulltext queries to
# avoid silent parse failures (which previously caused fulltext to return
# nothing for queries like "C++ vs Rust" or "Redis (caching)").
_LUCENE_SPECIALS = r'+-&|!(){}[]^"~*?:\/'


def escape_lucene(query: str) -> str:
    """Escape Lucene special characters in a free-text user query.

    Returns a copy where each Lucene operator is preceded by a backslash so
    Neo4j's db.index.fulltext.queryNodes treats them as literals rather than
    syntax. Whitespace, alphanumerics and other punctuation pass through.
    """
    out = []
    for ch in query:
        if ch in _LUCENE_SPECIALS:
            out.append("\\")
        out.append(ch)
    return "".join(out)


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


# Cap on citation-numbered decisions shown to the LLM. Matches the size of
# the source-card strip on the chat UI so [N] markers emitted by the model
# always resolve to a visible card.
MAX_CITATIONS = 10


def serialize_context(
    subgraph: dict, seed_ids: list[str] | None = None
) -> tuple[str, list[str]]:
    """Serialize a subgraph dict into structured text for LLM consumption.

    Numbers up to ``MAX_CITATIONS`` decisions with bracketed indices
    (``[1]``, ``[2]``, ...) so the LLM can emit inline citations the
    frontend can resolve to source cards. Seed decisions are numbered
    first (in ``seed_ids`` order), then remaining expansion decisions in
    their arrival order.

    Args:
        subgraph: Dict with "nodes" and "edges" lists.
        seed_ids: Optional list of seed node IDs controlling citation
            ordering. When None, decisions are numbered in subgraph
            arrival order.

    Returns:
        Tuple ``(context_string, citation_ids)`` where ``citation_ids[i]``
        is the decision ID that index ``i+1`` in the context refers to
        (i.e. the decision cited by ``[i+1]``). The frontend uses this
        to render inline citations.
    """
    nodes = subgraph.get("nodes", [])
    edges = subgraph.get("edges", [])

    if not nodes and not edges:
        return "", []

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

    # Order decisions: seed decisions (in seed_ids order) first, then
    # remaining expansion decisions in their arrival order. This is the
    # canonical citation order shared with the frontend.
    decisions = [n for n in nodes if n.get("label") == "DecisionTrace"]
    decision_by_id = {d.get("id"): d for d in decisions}
    ordered_decisions: list[dict] = []
    seed_set = set(seed_ids or [])
    for sid in seed_ids or []:
        d = decision_by_id.get(sid)
        if d is not None:
            ordered_decisions.append(d)
    for d in decisions:
        if d.get("id") not in seed_set:
            ordered_decisions.append(d)

    # Serialize decision nodes with their involved entities inline.
    citation_ids: list[str] = []
    if ordered_decisions:
        parts.append("## Decisions\n")
        for i, d in enumerate(ordered_decisions):
            # Only the first MAX_CITATIONS decisions get numbered index
            # markers; later ones are still shown to the LLM but without
            # citation numbers (the model is told it can only cite [1..N]).
            if i < MAX_CITATIONS:
                marker = f"[{i + 1}]"
                citation_ids.append(d.get("id") or "")
            else:
                marker = "-"
            lines = [f"{marker} **{d.get('trigger', 'Unknown trigger')}**"]
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

    return "\n".join(parts), citation_ids


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
    ) -> tuple[list[str], list[str]]:
        """Run fulltext search across decision and entity indexes.

        Returns (decision_ids, entity_ids) ranked by fulltext score. The two
        lists are kept separate so the caller can prioritize decisions for
        seed slots — entity hits make poor seeds because they carry no
        decision text for the LLM to reason over.
        """
        safe_query = escape_lucene(query)
        decision_ids: list[str] = []
        entity_ids: list[str] = []

        result = await session.run(
            f"""
            CALL db.index.fulltext.queryNodes('decision_fulltext', $query)
            YIELD node, score
            WHERE {_user_filter('node')}
            RETURN node.id AS id
            ORDER BY score DESC
            LIMIT $limit
            """,
            parameters={"query": safe_query, "user_id": user_id, "limit": limit},
        )
        async for record in result:
            decision_ids.append(record["id"])

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
            parameters={"query": safe_query, "user_id": user_id, "limit": limit},
        )
        async for record in result:
            entity_ids.append(record["id"])

        return decision_ids, entity_ids

    async def _vector_search(
        self,
        session,
        query: str,
        user_id: str,
        limit: int = 20,
    ) -> tuple[list[str], list[str]]:
        """Run vector search across decision and entity indexes.

        Returns (decision_ids, entity_ids) ranked by vector similarity.
        """
        embedding = await self._embedding_service.embed_text(
            query, input_type="query"
        )

        decision_ids: list[str] = []
        entity_ids: list[str] = []

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
            decision_ids.append(record["id"])

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
            entity_ids.append(record["id"])

        return decision_ids, entity_ids

    async def hybrid_retrieve(
        self,
        query: str,
        user_id: str,
        limit: int = 20,
        session=None,
    ) -> list[str]:
        """Run hybrid retrieval: fulltext + vector search fused with RRF.

        Returns a single fused list with **decision IDs first, then entity IDs**.
        Each modality's decision and entity hits are RRF-fused independently
        within their type so that entity hits can never crowd out decisions
        in the top-K seed budget. Entity seeds still survive (they expand
        usefully through INVOLVES) but stay below the decision seeds.

        Falls back to fulltext-only if vector search fails (e.g. embedding
        service unavailable).
        """
        empty: tuple[list[str], list[str]] = ([], [])

        if session is not None:
            try:
                ft_decisions, ft_entities = await self._fulltext_search(
                    session, query, user_id, limit
                )
            except Exception as e:
                logger.warning(f"Fulltext search failed: {e}")
                ft_decisions, ft_entities = empty

            try:
                vec_decisions, vec_entities = await self._vector_search(
                    session, query, user_id, limit
                )
            except Exception as e:
                logger.warning(
                    f"Vector search failed, falling back to fulltext-only: {e}"
                )
                vec_decisions, vec_entities = empty
        else:
            session_ft = await get_neo4j_session()
            session_vec = await get_neo4j_session()
            try:
                try:
                    (ft_decisions, ft_entities), (vec_decisions, vec_entities) = (
                        await asyncio.gather(
                            self._fulltext_search(session_ft, query, user_id, limit),
                            self._vector_search(session_vec, query, user_id, limit),
                        )
                    )
                except Exception as e:
                    logger.warning(
                        f"Vector search failed, falling back to fulltext-only: {e}"
                    )
                    ft_decisions, ft_entities = await self._fulltext_search(
                        session_ft, query, user_id, limit
                    )
                    vec_decisions, vec_entities = empty
            finally:
                await session_ft.close()
                await session_vec.close()

        decision_fused = rrf_fuse(ft_decisions, vec_decisions)
        entity_fused = rrf_fuse(ft_entities, vec_entities)
        # Decisions before entities; dedupe in case an id somehow appears
        # in both (it shouldn't with separate indexes, but be defensive).
        seen: set[str] = set()
        fused: list[str] = []
        for nid in (*decision_fused, *entity_fused):
            if nid not in seen:
                seen.add(nid)
                fused.append(nid)

        logger.info(
            f"Hybrid retrieve: ft=({len(ft_decisions)}d/{len(ft_entities)}e) "
            f"vec=({len(vec_decisions)}d/{len(vec_entities)}e) "
            f"-> {len(decision_fused)} decisions + {len(entity_fused)} entities"
        )
        return fused

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
            # Subgraph expansion is restricted to INVOLVES only. SIMILAR_TO
            # edges (~2.8k post-densification) otherwise dominate the subgraph
            # with low-signal decision-to-decision pairs, starving the LLM
            # context of actual decision text.
            #
            # When the cap fires (max_nodes), we drop entity nodes first and
            # keep seeds + every other DecisionTrace. This protects the
            # information the LLM actually reasons over (decision text)
            # against being silently truncated for popular hub entities like
            # "PostgreSQL" (46 involved decisions) or "FastAPI".
            result = await session.run(
                """
                UNWIND $seed_ids AS seedId
                MATCH (seed) WHERE seed.id = seedId
                CALL apoc.path.subgraphAll(seed, {
                    maxLevel: $depth,
                    relationshipFilter: 'INVOLVES'
                })
                YIELD nodes, relationships
                WITH COLLECT(DISTINCT nodes) AS nodeLists,
                     COLLECT(DISTINCT relationships) AS allRels,
                     $seed_ids AS seedIds
                UNWIND nodeLists AS nodeList
                UNWIND nodeList AS node
                WITH DISTINCT node, allRels, seedIds
                WITH node, allRels,
                     CASE
                         WHEN node.id IN seedIds THEN 0
                         WHEN HEAD(LABELS(node)) = 'DecisionTrace' THEN 1
                         ELSE 2
                     END AS rank
                ORDER BY rank ASC
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
        prev_query: str | None = None,
        prev_answer: str | None = None,
        session=None,
    ) -> tuple[dict, str, list[str], list[str]]:
        """Full RAG pipeline: retrieve -> expand -> serialize.

        Args:
            query: Current user question.
            user_id: Scoping user ID.
            top_k: Number of seed nodes to expand.
            depth: K-hop traversal depth.
            prev_query: The user's previous turn, if any. Used to enrich
                retrieval so follow-ups like "tell me more about #5" still
                surface relevant nodes.
            prev_answer: The assistant's previous answer text. Truncated and
                folded into the retrieval query so semantically related nodes
                resurface.
            session: Optional Neo4j session.

        Returns:
            Tuple of ``(subgraph_dict, context_string, seed_ids, citation_ids)``
            where ``citation_ids[i]`` is the decision ID that the LLM should
            resolve to when emitting ``[i+1]`` in its answer.
        """
        close_session = False
        if session is None:
            session = await get_neo4j_session()
            close_session = True

        # Build the retrieval query: when there's a prior turn, fold it in so
        # the embedding picks up the topical thread the user is following up
        # on. Cap the prior answer to 800 chars to keep the embedding focused.
        if prev_query or prev_answer:
            parts = []
            if prev_query:
                parts.append(prev_query.strip())
            if prev_answer:
                parts.append(prev_answer.strip()[:800])
            parts.append(query.strip())
            retrieval_query = "\n\n".join(parts)
        else:
            retrieval_query = query

        try:
            # Step 1: Hybrid retrieval
            fused_ids = await self.hybrid_retrieve(
                retrieval_query, user_id, session=session
            )
            seed_ids = fused_ids[:top_k]

            if not seed_ids:
                logger.info("No results from hybrid retrieval")
                return {"nodes": [], "edges": []}, "", [], []

            # Step 2: Subgraph expansion
            subgraph = await self.expand_subgraph(
                seed_ids, depth=depth, session=session
            )

            # Step 3: Serialize for LLM (returns the citation-order list
            # so the router can publish the matching [N] -> decision_id
            # mapping to the frontend via the SSE context event).
            context_str, citation_ids = serialize_context(subgraph, seed_ids)

            return subgraph, context_str, seed_ids, citation_ids
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
