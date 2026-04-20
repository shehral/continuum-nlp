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
- Reference specific decisions, entities, and relationships from the context
- If the context doesn't contain enough information, say "I don't have enough information in the knowledge graph to answer that"
- Do not make up information not present in the context
- Use markdown formatting for readability

## Knowledge Graph Context
{context}"""

SYSTEM_PROMPT_WITH_HISTORY = """You are Continuum, a knowledge graph assistant. The user is having an ongoing conversation with you and may reference earlier turns (e.g. "decision number 5", "the second one", "that approach"). When they do, look up the referent in the prior-turn block below, then ground your new answer in the knowledge graph context.

Rules:
- Base claims strictly on the provided graph context (or the prior turn's content if the user is asking about something they already saw)
- Reference specific decisions, entities, and relationships
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
            subgraph, context_text, seed_ids = await graph_rag.retrieve_context(
                query=q,
                user_id=user_id,
                top_k=top_k,
                depth=depth,
                prev_query=prev_q,
                prev_answer=prev_a,
            )

            # Reshape nodes to match frontend AskSourceNode contract
            seed_id_set = set(seed_ids)
            shaped_nodes = []
            for n in subgraph.get("nodes", []):
                node_id = n.get("id", "")
                label = n.get("label", "")
                node_type = "decision" if label == "DecisionTrace" else "entity"
                shaped_nodes.append({
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
                })

            # Send context event with the reshaped subgraph
            yield _sse_event("context", {
                "nodes": shaped_nodes,
                "edges": subgraph.get("edges", []),
                "seed_ids": list(seed_id_set),
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
                    # Truncate prev_a in the prompt the same way we truncate
                    # in retrieval — keeps the LLM's context budget stable.
                    prev_answer=prev_a[:1500],
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
