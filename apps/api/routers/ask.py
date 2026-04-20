"""Ask router — SSE streaming endpoint for GraphRAG Q&A.

Provides a GET /api/ask endpoint that:
1. Retrieves relevant context from the knowledge graph via hybrid search
2. Streams an LLM-generated answer as Server-Sent Events (SSE)
"""

import json
from typing import Optional

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import StreamingResponse

from routers.auth import get_current_user_id
from services.graph_rag import get_graph_rag_service
from services.llm import get_llm_client
from utils.logging import get_logger

logger = get_logger(__name__)

router = APIRouter()

SYSTEM_PROMPT = """You are Continuum, a knowledge-graph assistant. Answer the user's question using ONLY the numbered decisions provided in the context below.

CITATION FORMAT — this is the most important rule:
Every factual claim in your answer MUST end with a bracketed citation like [1] or [3], pointing to the numbered decision that supports it. Place the citation at the end of the sentence the claim lives in, before the period.

EXAMPLE — if the context contains:

  [1] **Choosing between Firebase and Supabase for a social app**
      Decision: Supabase
      Rationale: PostgreSQL-backed relational store fits social data naturally.
  [2] **Need a caching layer for the API**
      Decision: Redis

A correct answer looks like:
  "Supabase is preferred for social apps because its PostgreSQL backing fits relational data [1]. For a caching layer, Redis is the canonical choice [2]."

Rules:
- EVERY factual claim in your answer ends with a [N] citation.
- Cite ONLY the numbers present in the context. Never invent numbers.
- Only cite decisions that are actually relevant to the user's question — ignore off-topic numbered decisions in the context.
- You may cite the same number multiple times; you may cite several numbers in one sentence, e.g. [1][3].
- If the context doesn't cover the question, reply exactly: "I don't have enough information in the knowledge graph to answer that."
- Do not invent information beyond the cited decisions.
- Use markdown formatting (bold, bullets) for readability.

## Knowledge Graph Context
{context}"""

SYSTEM_PROMPT_WITH_HISTORY = """You are Continuum, a knowledge-graph assistant. The user is having an ongoing conversation and may refer back ("decision 5", "the second one", "that approach"). Resolve such references using the prior-turn block, then ground your new answer in the numbered decisions in the context.

CITATION FORMAT — this is the most important rule:
Every factual claim in your answer MUST end with a bracketed citation like [1] or [3], pointing to the numbered decision in the context that supports it.

Example:
  "Supabase is preferred because its PostgreSQL backing fits relational data [1]. Redis is the canonical cache [2]."

Rules:
- EVERY factual claim ends with a [N] citation.
- Cite ONLY the numbers present in the context. Never invent numbers.
- Only cite relevant decisions; ignore off-topic numbered decisions.
- If neither the prior turn nor the context covers the question, reply exactly: "I don't have enough information in the knowledge graph to answer that."
- Do not invent information. Use markdown for readability.

## Prior Turn (for resolving "decision N", "that one", etc.)
USER asked: {prev_query}

YOU answered:
{prev_answer}

## Knowledge Graph Context (grounding for the new answer)
{context}"""


def _sse_event(event: str, data: dict) -> str:
    """Format a Server-Sent Event."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.get("")
async def ask(
    q: str = Query(..., min_length=3, description="The question to ask"),
    depth: int = Query(default=2, ge=1, le=3, description="Graph traversal depth"),
    top_k: int = Query(default=5, ge=1, le=10, description="Number of seed nodes"),
    prev_q: Optional[str] = Query(default=None, description="Previous user question (for follow-ups)"),
    prev_a: Optional[str] = Query(default=None, max_length=4000, description="Previous assistant answer (for follow-ups)"),
    user_id: str = Depends(get_current_user_id),
):
    """Ask a question and receive a streamed answer grounded in the knowledge graph.

    For follow-up questions, pass the prior turn via `prev_q` and `prev_a`. The
    retrieval query will be enriched with that context so referential queries
    like "tell me more about decision 5" still surface the right subgraph, and
    the LLM will see the prior turn in its system prompt.
    """

    async def event_stream():
        try:
            # Step 1: Retrieve context from the knowledge graph
            graph_rag = get_graph_rag_service()
            subgraph, context_text, seed_ids, citation_ids = await graph_rag.retrieve_context(
                query=q,
                user_id=user_id,
                top_k=top_k,
                depth=depth,
                prev_query=prev_q,
                prev_answer=prev_a,
            )

            # Reshape nodes to match frontend AskSourceNode contract. Place
            # citation-ordered decisions first (matching [1], [2], ... in the
            # LLM context) so the chat-UI source cards line up with the
            # inline markers the model emits. Remaining decisions then
            # entities follow.
            seed_id_set = set(seed_ids)
            citation_id_list = list(citation_ids or [])
            citation_id_set = set(citation_id_list)
            nodes_by_id = {n.get("id", ""): n for n in subgraph.get("nodes", [])}

            def shape(n: dict) -> dict:
                node_id = n.get("id", "")
                label = n.get("label", "")
                node_type = "decision" if label == "DecisionTrace" else "entity"
                return {
                    "id": node_id,
                    "type": node_type,
                    "is_seed": node_id in seed_id_set,
                    "data": {
                        "trigger": n.get("trigger"),
                        "decision": n.get("decision"),
                        "context": n.get("context"),
                        "rationale": n.get("rationale"),
                        "options": n.get("options"),
                        "confidence": n.get("confidence"),
                        "name": n.get("name"),
                        "entity_type": n.get("type"),
                    },
                }

            shaped_nodes: list[dict] = []
            emitted: set[str] = set()
            # Citation-ordered decisions first
            for cid in citation_id_list:
                n = nodes_by_id.get(cid)
                if n is None or cid in emitted:
                    continue
                shaped_nodes.append(shape(n))
                emitted.add(cid)
            # Any remaining decisions (beyond MAX_CITATIONS) and then entities
            for n in subgraph.get("nodes", []):
                nid = n.get("id", "")
                if nid in emitted:
                    continue
                shaped_nodes.append(shape(n))
                emitted.add(nid)

            # Send context event with the reshaped subgraph plus the
            # [N] -> decision_id mapping so the frontend can render inline
            # citations emitted by the LLM.
            yield _sse_event("context", {
                "nodes": shaped_nodes,
                "edges": subgraph.get("edges", []),
                "seed_ids": list(seed_id_set),
                "citation_ids": citation_id_list,
            })

            # Step 2: If no context, send a direct "no info" message
            if not context_text:
                no_info_msg = (
                    "I don't have enough information in the knowledge graph "
                    "to answer that question."
                )
                yield _sse_event("token", {"text": no_info_msg})
                yield _sse_event("done", {"token_count": len(no_info_msg.split())})
                return

            # Step 3: Stream LLM response. Pick the prompt template based on
            # whether the caller passed a prior turn — the conversational
            # template gives the model the previous Q+A to resolve references.
            if prev_q and prev_a:
                system_prompt = SYSTEM_PROMPT_WITH_HISTORY.format(
                    prev_query=prev_q,
                    # Cap at 4000 chars (~1000 tokens). Llama 3.1 8B has 8192
                    # context; this leaves ample room for the graph context
                    # and the new query. Higher cap prevents the model from
                    # losing track of items deeper in a numbered list.
                    prev_answer=prev_a[:4000],
                    context=context_text,
                )
            else:
                system_prompt = SYSTEM_PROMPT.format(context=context_text)
            llm = get_llm_client()
            token_count = 0

            # Temperature tuned low for strict citation-format adherence.
            # Llama 3.1 8B drifts from the [N] format at T>=0.3; 0.1 gives
            # near-deterministic bracketed citations without harming fluency.
            async for chunk in llm.generate_stream(
                prompt=q,
                system_prompt=system_prompt,
                temperature=0.1,
                max_tokens=2048,
                user_id=user_id,
                sanitize_input=False,
            ):
                token_count += 1
                yield _sse_event("token", {"text": chunk})

            yield _sse_event("done", {"token_count": token_count})

        except Exception as e:
            logger.exception(f"Error in /api/ask stream: {e}")
            yield _sse_event("error", {"detail": str(e)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
