# Continuum NLP

A small GraphRAG question-answering app over a knowledge graph of architectural
decisions extracted from 200 synthetic developer–AI conversations. Built for
CS 6120 (NLP, Spring 2026, Northeastern San Jose).

The whole stack — Llama 3.1 8B, `nomic-embed-text` embeddings, Neo4j, FastAPI,
Next.js — runs locally via Docker on a single GPU. No cloud LLM calls at
inference time.

## What you can do

- **`/ask`** — type a question, get a streamed answer grounded in the graph
  with clickable citations.
- **`/graph`** — pan/zoom the full graph (1,233 nodes, 4,111 edges).
- **`/decisions/[id]`** — open the source trace for any cited decision.

That's it for the live demo. No login, no editing — read-only end to end.

## What's in the graph

- 386 `DecisionTrace` nodes (5-field structured: trigger / context / options / decision / rationale)
- 847 `Entity` nodes (technologies, patterns, concepts, systems, persons)
- 1,271 `INVOLVES` edges (decision ↔ entity)
- 2,840 `SIMILAR_TO` edges (k-NN cosine over 768-d nomic-embed-text vectors, K=8)
- Average decision confidence 0.945, top entity by degree is PostgreSQL (46 decisions)

## Run it locally

You'll need Docker + Docker Compose. On macOS, give Docker Desktop ≥ 8 GB of RAM
or `llama3.1:8b` won't load — easier path is to run Ollama on the host and point
the API at it (see "Local Ollama on the host" below).

```bash
git clone https://github.com/shehral/continuum-nlp.git
cd continuum-nlp
cp .env.example .env       # fill in passwords, see notes inside the file
docker compose up -d
docker exec continuum-nlp-ollama ollama pull llama3.1:8b
docker exec continuum-nlp-ollama ollama pull nomic-embed-text
```

Then load the pre-extracted graph (the live app does not re-extract — it serves
a one-time-built graph snapshot):

```bash
docker cp data/snapshots/continuum-nlp-final.cypher continuum-nlp-neo4j:/tmp/
docker exec continuum-nlp-neo4j cypher-shell -u neo4j -p "$NEO4J_PASSWORD" \
    -f /tmp/continuum-nlp-final.cypher
cat data/snapshots/continuum-nlp-postgres.sql | \
    docker exec -i continuum-nlp-postgres psql -U continuum -d continuum
```

Open `http://localhost:3000`.

The snapshots in `data/snapshots/` are not committed to git (too large + need to
be regenerated rather than mirrored). They come out of the migration scripts in
`apps/api/scripts/`.

### Local Ollama on the host (recommended on Mac)

If your Docker Desktop has limited RAM, run Ollama on the host instead:

```bash
brew install ollama
ollama serve &
ollama pull llama3.1:8b
ollama pull nomic-embed-text
# then in .env, set:
#   OLLAMA_HOST=http://host.docker.internal:11434
```

The API container will reach the host's Ollama via Docker's bridge.

## How retrieval works

`/api/ask` runs five stages (`apps/api/services/graph_rag.py`):

1. Embed the query with `nomic-embed-text` → 768-d vector.
2. Hybrid seed retrieval: Neo4j fulltext (BM25) + vector cosine, fused with
   Reciprocal Rank Fusion → top-K seeds (default 5).
3. Subgraph expansion: APOC `subgraphAll` from each seed, depth 2, restricted
   to `INVOLVES` so the context block stays dense in real decision content.
4. Serialize the subgraph to markdown (one block per decision, with
   `Involves: <entity, entity>` attached inline).
5. Stream the answer from Llama 3.1 8B with the serialized subgraph as
   context. Seed node IDs stream separately so the UI can show clickable
   source cards.

The model is told to refuse when no relevant decisions are in the context, so
asking about a topic the corpus doesn't cover (e.g., MongoDB vs Postgres for
some specific use case) returns a polite "no information on that" rather than
a fabrication.

## Where the data came from

200 synthetic developer–AI conversations live in
`apps/api/evaluation/data/synthetic_conversations/`, each as `conv-NNN.json`
plus an `index.json` manifest. They're synthetic because real assistant logs
contain personal info — synthetic gives a controllable corpus that's safe to
distribute. Nine domains: backend, web, ML/AI, DevOps, data engineering,
systems, mobile, security, cloud architecture.

The 7-stage entity resolution cascade (cache → exact → 534-entry canonical
table → alias → fuzzy 85% → embedding cosine ≥ 0.9 → create new) lives in
`apps/api/services/entity_resolver.py`. It's what keeps `pg`, `Postgres`, and
`PostgreSQL` from becoming three separate nodes.

## Tests

```bash
# Backend smoke (live stack required)
pytest apps/api/tests/smoke/ -m smoke -v

# Backend integration
pytest apps/api/tests/integration/ -m integration -v

# Frontend unit
cd apps/web && pnpm test:run __tests__/components/ask

# Frontend end-to-end (Playwright)
cd apps/web && pnpm exec playwright test --project=chromium \
    e2e/demo-critical-path.spec.ts e2e/sidebar-nav.spec.ts \
    e2e/ask-streaming.spec.ts e2e/light-dark-mode.spec.ts
```

The smoke + Playwright suites are designed to run unmodified against a remote
deploy — pass `API_BASE_URL` and `BASE_URL` env vars.

## Layout

```
continuum-nlp/
├── apps/
│   ├── api/          FastAPI backend (4 demo routers + GraphRAG service)
│   │   ├── routers/  ask, graph, decisions, users
│   │   ├── services/ graph_rag, embeddings, llm, extractor, entity_resolver
│   │   ├── scripts/  migrate_graph, reembed_all, densify
│   │   └── tests/    smoke, integration, contract
│   └── web/          Next.js 16 App Router (4 demo pages)
│       ├── app/      ask, graph, decisions/[id], plus auth pages
│       ├── components/ ask, graph, landing, layout, ui
│       └── e2e/      Playwright specs
├── data/snapshots/   Graph dump (not committed)
├── docker-compose.yml
└── .env.example
```

## License

MIT. See [LICENSE](LICENSE).
