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

SYSTEM_PROMPT = """You are Continuum, a knowledge graph assistant. Answer the user's question using ONLY the provided graph context below. Be concise and specific.

Rules:
- Base your answer strictly on the provided context
- When you draw on a specific numbered decision, cite it inline using its bracket marker — for example, "Hasura supports both REST and GraphQL [2]." Place the citation immediately after the claim it supports.
- Only cite decisions that are actually relevant to the user's question. Ignore decisions in the context that are off-topic, even if they are numbered.
- You may cite the same decision multiple times; you may cite several decisions on one sentence like [1][3].
- Do not invent decision numbers that are not in the context block.
- If the context doesn't contain enough information, say "I don't have enough information in the knowledge graph to answer that"
- Do not make up information not present in the context
- Use markdown formatting for readability

## Knowledge Graph Context
{context}"""

SYSTEM_PROMPT_WITH_HISTORY = """You are Continuum, a knowledge graph assistant. The user is having an ongoing conversation with you and may reference earlier turns (e.g. "decision number 5", "the second one", "that approach"). When they do, look up the referent in the prior-turn block below, then ground your new answer in the knowledge graph context.

Rules:
- Base claims strictly on the provided graph context (or the prior turn's content if the user is asking about something they already saw)
- When you draw on a specific numbered decision, cite it inline using its bracket marker — for example, "Hasura supports both REST and GraphQL [2]." Place the citation immediately after the claim it supports.
- Only cite decisions that are actually relevant; ignore off-topic numbered decisions in the context. You may cite the same decision multiple times, and several decisions on one sentence like [1][3].
- Do not invent decision numbers that are not in the context block.
- If neither the prior turn nor the graph context covers what the user is asking, say so
- Do not invent information
- Use markdown formatting for readability

## Prior Turn (for resolving references like "decision N", "that one", etc.)
USER asked: {prev_query}

YOU answered:
{prev_answer}

## Knowledge Graph Context (for grounding the new answer)
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

            async for chunk in llm.generate_stream(
                prompt=q,
                system_prompt=system_prompt,
                temperature=0.3,
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
